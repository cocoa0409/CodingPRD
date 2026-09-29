"""The cycle checkpoint and the clock test-driving capability (PRD 3.9, 2.6)."""

from flask import Blueprint

import calc
import services as svc
from db import db, fmt_instant, now, ordered, parse_instant, touch
from middleware import endpoint
from response import ok
from validate import field, parse_input

bp = Blueprint("ops", __name__)


def _earliest_finalized(artwork_id, cycle_year):
    """PRD 3.9: assessed_on ascending, created_at ascending on a tie."""
    rows = [
        a
        for a in db.assessments.values()
        if a["artwork_id"] == artwork_id
        and a["status"] == "FINALIZED"
        and int(a["cycle_year"]) == cycle_year
        and a.get("condition_index") is not None
    ]
    if not rows:
        return None
    rows.sort(key=lambda a: (a["assessed_on"], a.get("created_at") or "", a.get("_seq", 0)))
    return rows[0]


@bp.post("/public-art/ops/run-cycle")
@endpoint(("PublicArtManager",))
def run_cycle():
    body = parse_input({
        "cycle_year": field("int", required=True, minimum=2000, maximum=2100),
    })
    cycle_year = int(body["cycle_year"])

    # pass 1: rescore under the cycle-cohort variant
    rescored = 0
    for artwork in ordered(db.artworks.values()):
        source = _earliest_finalized(artwork["id"], cycle_year)
        if source is None:
            continue
        artwork["treatment_priority_score"] = svc.score_cycle_cohort(artwork, source)
        artwork["priority_basis"] = "CYCLE_COHORT"
        touch(artwork)
        rescored += 1

    # pass 2: overdue consultations lapse
    clock = now()
    lapsed = 0
    for consultation in ordered(db.consultations.values()):
        if consultation["status"] != "PENDING":
            continue
        if parse_instant(consultation["due_at"]) <= clock:
            consultation["status"] = "LAPSED"
            touch(consultation)
            lapsed += 1

    # pass 3: matured notices elapse their statutory wait
    elapsed = 0
    for notice in ordered(db.notices.values()):
        if notice["status"] != "SENT":
            continue
        if parse_instant(notice["earliest_action_at"]) <= clock:
            notice["status"] = "WAIT_ELAPSED"
            touch(notice)
            elapsed += 1

    # pass 4: treated works re-surveyed as healthy rejoin ordinary monitoring
    returned = 0
    for artwork in ordered(db.artworks.values()):
        if artwork["conservation_status"] != "STABILIZED":
            continue
        passing = any(
            a["artwork_id"] == artwork["id"]
            and a["status"] == "FINALIZED"
            and int(a["cycle_year"]) == cycle_year
            and a.get("condition_index") is not None
            and calc.D(a["condition_index"]) >= calc.TREATMENT_TRIGGER_INDEX
            for a in db.assessments.values()
        )
        if passing:
            artwork["conservation_status"] = "MONITORED"
            touch(artwork)
            returned += 1

    svc.recompute_ranks()

    return ok({
        "cycle_year": cycle_year,
        "artworks_rescored": rescored,
        "consultations_lapsed": lapsed,
        "notices_elapsed": elapsed,
        "artworks_returned_to_monitored": returned,
    })


@bp.post("/_clock/set_current_utc")
@endpoint(("PublicArtManager",))
def set_clock():
    body = parse_input({"to_iso8601": field("datetime", required=True)})
    db.clock = parse_instant(body["to_iso8601"])
    return ok({"current_utc": fmt_instant(db.clock)})
