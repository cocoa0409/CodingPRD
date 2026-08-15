"""SafetyAssessment endpoints with swim_status transitions and recompute cascades."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_VALIDATION, ERR_INVALID_STATE, not_found
from middleware import require_roles
from response import success_object, success_list, paginate
from services.core import replay_result, recompute_ranks
from util import stamp_common, touch, require_fields, require_number, require_bool

bp = Blueprint("safety", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise not_found("event not found")
    return ev


@bp.post("/events/<event_id>/safety-assessments")
def create_assessment(event_id):
    require_roles("RaceDirector", "Referee")
    ev = get_event_or_404(event_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["water_temp_celsius", "lightning_within_10km"])
    temp = require_number(body["water_temp_celsius"], "water_temp_celsius")
    lightning = require_bool(body["lightning_within_10km"], "lightning_within_10km")

    outcome = "SWIM_CANCEL" if (temp < 12.0 or temp > 31.0 or lightning) else "SWIM_OK"

    # Determine target swim_status and validate the transition BEFORE mutating anything.
    if ev["has_swim"]:
        target = "SWIM_ON" if outcome == "SWIM_OK" else "SWIM_CANCELLED"
        if (ev["swim_status"] == "SWIM_CANCELLED" and target == "SWIM_ON"
                and ev["posture"] == "LIVE"):
            raise ApiError(ERR_INVALID_STATE, "swim cannot be reinstated once racing", 409)
    else:
        target = None  # NO_SWIM: no transitions

    # supersede previous RECORDED assessment
    for sa in db.safety_assessments.values():
        if sa["event_id"] == event_id and sa["status"] == "RECORDED":
            sa["status"] = "SUPERSEDED"
            touch(sa)

    sa = stamp_common({
        "event_id": event_id,
        "water_temp_celsius": temp,
        "lightning_within_10km": lightning,
        "outcome": outcome,
        "status": "RECORDED",
    })
    db.safety_assessments[sa["id"]] = sa

    if target is not None and ev["swim_status"] != target:
        ev["swim_status"] = target
        touch(ev)
        # recompute all existing results under the applicable variant
        reg_ids = {r["id"] for r in db.registrations.values() if r["event_id"] == ev["id"]}
        for res in db.results.values():
            if res["registration_id"] in reg_ids:
                replay_result(res)
                touch(res)
        recompute_ranks(ev["id"])

    return success_object(sa, status=201)


@bp.get("/events/<event_id>/safety-assessments")
def list_assessments(event_id):
    require_roles(*ALL)
    get_event_or_404(event_id)
    items = [s for s in db.safety_assessments.values() if s["event_id"] == event_id]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/safety-assessments/<sid>")
def get_assessment(sid):
    require_roles(*ALL)
    sa = db.safety_assessments.get(sid)
    if not sa:
        raise not_found("safety assessment not found")
    return success_object(sa)
