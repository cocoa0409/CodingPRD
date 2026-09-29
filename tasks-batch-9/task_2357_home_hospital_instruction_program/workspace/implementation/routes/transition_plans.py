"""The coordinated return to the school building (PRD §3.9)."""

from flask import Blueprint

import clock
import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import ABORT_REASONS, PLAN_STATUSES, REINTEGRATION_MODES, listing
from services import logic
from validation import fail, parse_date

bp = Blueprint("transition_plans", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager", "ClassroomTeacher"]

CREATE_BODY = {
    "case_id": {"type": "string", "required": True},
    "target_return_date": {"type": "date", "required": True},
    "reintegration_mode": {"type": "string", "required": True, "enum": REINTEGRATION_MODES},
    "expected_case_version": {"type": "integer", "required": True},
    "ramp_weeks": {"type": "integer", "min": 0, "max": 8},
}

LIST_QUERY = {
    "case_id": {"type": "string"},
    "status": {"type": "string", "enum": PLAN_STATUSES},
}


def load_plan(plan_id):
    row = db.get("transition_plans", plan_id)
    if row is None:
        raise ApiError("ERR_TRANSITION_PLAN_NOT_FOUND")
    return row


@bp.post("/hhi/transition-plans")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_plan():
    body = middleware.body()

    case = db.get("cases", body["case_id"])                      # tier 5
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")

    if body["expected_case_version"] != case["version"]:         # tier 7
        raise ApiError("ERR_STALE_CASE_VERSION")

    if case["service_status"] != "ACTIVE":                       # tier 8
        raise ApiError("ERR_INVALID_CASE_STATE")
    for other in db.by_case("transition_plans", case["id"]):
        if other["status"] in logic.OPEN_PLAN_STATES:
            raise ApiError("ERR_INVALID_CASE_STATE")

    ramp_weeks = body.get("ramp_weeks", 0)
    if body["reintegration_mode"] == "FULL_DAY":                  # tier 11
        if ramp_weeks != 0:
            raise ApiError("ERR_RAMP_WEEKS_INVALID")
    elif ramp_weeks < 1:
        raise ApiError("ERR_RAMP_WEEKS_INVALID")

    if parse_date(body["target_return_date"]) <= clock.get_date():
        fail("target_return_date must be strictly later than the current clock date.")

    syncs = db.by_case("pacing_syncs", case["id"])
    row = db.insert(
        "transition_plans",
        {
            "case_id": case["id"],
            "target_return_date": body["target_return_date"],
            "reintegration_mode": body["reintegration_mode"],
            "ramp_weeks": ramp_weeks,
            "status": "DRAFT",
            "required_ack_count": len(
                [s for s in syncs if s["ack_status"] in ("PENDING", "ACKED", "DISPUTED")]
            ),
            "classroom_ack_count": len([s for s in syncs if s["ack_status"] == "ACKED"]),
            "completed_at": None,
            "abort_reason": None,
        },
    )

    db.set_field(case, "service_status", "TRANSITION_PLANNED")
    db.touch(case)
    return middleware.obj(row)


@bp.get("/hhi/transition-plans/<plan_id>")
@endpoint(READ_ROLES)
def read_plan(plan_id):
    return middleware.obj(load_plan(plan_id))


@bp.get("/hhi/transition-plans")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_plans():
    return listing("transition_plans", LIST_QUERY)


@bp.post("/hhi/transition-plans/<plan_id>/coordinate")
@endpoint(["CaseManager"])
def coordinate_plan(plan_id):
    plan = load_plan(plan_id)
    if plan["status"] != "DRAFT":                                 # tier 8
        raise ApiError("ERR_PLAN_STATE_INVALID")

    case = db.get("cases", plan["case_id"])
    syncs = db.by_case("pacing_syncs", case["id"])
    if not [s for s in syncs if s["ack_status"] in ("PENDING", "ACKED", "DISPUTED")]:
        raise ApiError("ERR_NO_PACING_COORDINATION")              # tier 12
    for log in db.by_case("sped_service_logs", case["id"]):
        if log["continuation_status"] == "SUSPENDED_PENDING_IEP":
            raise ApiError("ERR_SPED_SERVICE_SUSPENDED")

    db.set_field(plan, "status", "CLASSROOM_COORD_PENDING")
    # The readiness guard settles in a single pass and may advance the plan now.
    logic.recompute_ack_counters(case)
    return middleware.obj(plan)


@bp.post("/hhi/transition-plans/<plan_id>/complete")
@endpoint(["ProgramAdministrator"])
def complete_plan(plan_id):
    plan = load_plan(plan_id)
    if plan["status"] != "READY":                                 # tier 8
        raise ApiError("ERR_PLAN_NOT_READY")
    if clock.get_date() < parse_date(plan["target_return_date"]):  # tier 13
        raise ApiError("ERR_RETURN_DATE_NOT_REACHED")

    case = db.get("cases", plan["case_id"])
    db.set_field(plan, "status", "COMPLETED")
    db.set_field(plan, "completed_at", clock.instant_str())

    db.set_field(case, "service_status", "CLOSED")
    db.set_field(case, "close_reason", "RETURNED_TO_CAMPUS")
    logic.release_active_assignments(case)
    logic.cancel_scheduled_sessions(case)
    db.touch(case)
    return middleware.obj(plan)


@bp.post("/hhi/transition-plans/<plan_id>/abort")
@endpoint(
    ["CaseManager"],
    body={"abort_reason": {"type": "string", "required": True, "enum": ABORT_REASONS}},
)
def abort_plan(plan_id):
    plan = load_plan(plan_id)
    if plan["status"] not in logic.OPEN_PLAN_STATES:              # tier 8
        raise ApiError("ERR_PLAN_STATE_INVALID")

    case = db.get("cases", plan["case_id"])
    db.set_field(plan, "status", "ABORTED")
    db.set_field(plan, "abort_reason", middleware.body()["abort_reason"])
    if case["service_status"] == "TRANSITION_PLANNED":
        db.set_field(case, "service_status", "ACTIVE")
    db.touch(case)
    return middleware.obj(plan)
