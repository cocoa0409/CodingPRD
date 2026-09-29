"""PRD 3.8 -- the cyclic plan update lifecycle and the weighted endorsement loop."""

from flask import Blueprint

import calc
import cascades
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_REGIONAL_ADMINISTRATOR, guard
from core import clock
from errors import fail

bp = Blueprint("plan_cycles", __name__)

OPENABLE_ROUND_STATES = ("ENGAGEMENT", "REVISION")


@bp.post("/resilience/plan-cycles")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def create_plan_cycle():
    body = validate.json_body()
    label = validate.string_field(body, "cycle_label", required=True, min_len=1, max_len=80)
    deadline = validate.datetime_field(body, "endorsement_deadline", required=True)
    quorum = validate.int_field(
        body, "quorum_weight_bps", default=6600, minimum=1, maximum=10000
    )
    max_revisions = validate.int_field(
        body, "max_revision_rounds", default=2, minimum=0, maximum=5
    )
    required_sessions = validate.int_field(
        body, "required_session_count", default=2, minimum=0, maximum=10
    )

    record = store.insert(store.plan_cycles, {
        "cycle_label": label,
        "status": "DRAFT",
        "round_number": 0,
        "revision_count": 0,
        "max_revision_rounds": max_revisions,
        "quorum_weight_bps": quorum,
        "required_session_count": required_sessions,
        "achieved_weight_bps": None,
        "endorsement_deadline": deadline,
        "adopted_at": None,
    })
    return envelope.created(serialize.plan_cycle(record))


@bp.get("/resilience/plan-cycles")
@guard()
def list_plan_cycles():
    rows = envelope.match(
        store.ordered(store.plan_cycles),
        status=envelope.str_filter("status"),
    )
    return envelope.listing(rows, serialize.plan_cycle)


@bp.get("/resilience/plan-cycles/<plan_cycle_id>")
@guard()
def get_plan_cycle(plan_cycle_id):
    row = lookup.need("plan_cycle", plan_cycle_id)
    return envelope.ok(serialize.plan_cycle(row))


@bp.post("/resilience/plan-cycles/<plan_cycle_id>/open-engagement")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def open_engagement(plan_cycle_id):
    cycle = lookup.need("plan_cycle", plan_cycle_id)
    if cycle["status"] != "DRAFT":
        fail("ERR_PLAN_CYCLE_STATE_INVALID", "Only a DRAFT cycle may open engagement.")
    cycle["status"] = "ENGAGEMENT"
    store.touch(cycle)
    return envelope.ok(serialize.plan_cycle(cycle))


@bp.post("/resilience/plan-cycles/<plan_cycle_id>/open-endorsement-round")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def open_endorsement_round(plan_cycle_id):
    cycle = lookup.need("plan_cycle", plan_cycle_id)
    if cycle["status"] not in OPENABLE_ROUND_STATES:
        fail(
            "ERR_PLAN_CYCLE_STATE_INVALID",
            "An endorsement round opens only from ENGAGEMENT or REVISION.",
        )
    completed = lookup.sessions_of_cycle(cycle["id"], status="COMPLETED")
    if len(completed) < int(cycle["required_session_count"]):
        fail(
            "ERR_ENGAGEMENT_INCOMPLETE",
            "The cycle has fewer than %d COMPLETED engagement sessions."
            % int(cycle["required_session_count"]),
        )
    screened_in = [
        row for row in lookup.projects_of_cycle(cycle["id"])
        if row["screening_status"] == "SCREENED_IN"
    ]
    if not screened_in:
        fail("ERR_NO_SCREENED_PROJECTS", "The cycle owns no SCREENED_IN project.")

    cycle["round_number"] = int(cycle["round_number"]) + 1
    cycle["status"] = "ENDORSEMENT_ROUND"
    store.touch(cycle)
    return envelope.ok(serialize.plan_cycle(cycle))


def _tally(cycle):
    active_weights = [
        row["endorsement_weight"] for row in store.jurisdictions.values()
        if row["status"] == "ACTIVE"
    ]
    live = [
        row for row in lookup.endorsements_of_cycle(cycle["id"], cycle["round_number"])
        if row["decision"] in cascades.LIVE_DECISIONS
    ]
    return calc.tally(active_weights, live)


@bp.post("/resilience/plan-cycles/<plan_cycle_id>/close-endorsement-round")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def close_endorsement_round(plan_cycle_id):
    cycle = lookup.need("plan_cycle", plan_cycle_id)
    if cycle["status"] != "ENDORSEMENT_ROUND":
        fail("ERR_PLAN_CYCLE_STATE_INVALID", "The cycle is not in an open endorsement round.")

    _total, supporting, veto, achieved = _tally(cycle)
    outcome = calc.tally_outcome(veto, achieved, cycle["quorum_weight_bps"])
    cycle["achieved_weight_bps"] = achieved

    if outcome == "ADOPTED":
        cycle["status"] = "ADOPTED"
        cycle["adopted_at"] = clock.now()
    else:
        cascades.supersede_live_endorsements(cycle)
        if int(cycle["revision_count"]) + 1 <= int(cycle["max_revision_rounds"]):
            cycle["status"] = "REVISION"
            cycle["revision_count"] = int(cycle["revision_count"]) + 1
        else:
            # revision_count is NOT incremented on the FAILED edge
            cycle["status"] = "FAILED"
            cascades.fail_cycle_side_effects(cycle)
    store.touch(cycle)
    return envelope.ok(serialize.plan_cycle(cycle))


@bp.get("/resilience/plan-cycles/<plan_cycle_id>/endorsement-tally")
@guard()
def endorsement_tally(plan_cycle_id):
    cycle = lookup.need("plan_cycle", plan_cycle_id)
    total, supporting, veto, achieved = _tally(cycle)
    return envelope.ok({
        "round_number": cycle["round_number"],
        "total_active_weight": total,
        "supporting_weight": supporting,
        "veto_weight": veto,
        "achieved_weight_bps": achieved,
        "quorum_weight_bps": cycle["quorum_weight_bps"],
        "projected_outcome": calc.tally_outcome(veto, achieved, cycle["quorum_weight_bps"]),
    })
