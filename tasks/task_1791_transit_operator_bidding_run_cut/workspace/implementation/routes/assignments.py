"""Daily assignment endpoints: listing, timekeeping close-out, no-show,
pay finalization and disputes, and pay-record listing."""
from flask import request, Blueprint

from db import db, touch, ser
from errors import (
    ApiError,
    forbidden,
    invalid_state,
    ERR_INVALID_ACTUAL_MINUTES,
)
from helpers import (
    body_json,
    get_assignment_or_404,
    paginated,
    is_int,
)
from middleware import authenticate, require_roles, ALL_ROLES
from response import ok_obj
from services.workflow import create_pay_record

bp = Blueprint("assignments", __name__)


@bp.get("/api/daily-assignments")
def list_assignments():
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    items = list(db.daily_assignments.values())
    for param in ("operator_id", "sign_up_period_id", "service_date", "status", "run_id"):
        raw = request.args.get(param)
        if raw is not None:
            items = [a for a in items if a[param] == raw]
    return paginated(items)


@bp.get("/api/daily-assignments/<aid>")
def get_assignment(aid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    return ok_obj(ser(get_assignment_or_404(aid)))


@bp.post("/api/daily-assignments/<aid>/close-out")
def close_out(aid):
    auth = authenticate()
    require_roles(auth, ["PayrollClerk"])
    assignment = get_assignment_or_404(aid)
    body = body_json(required=False)
    # State gate fires first: only SCHEDULED assignments can be closed out
    if assignment["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED assignment may be closed out")
    # Minutes validation: present, > 0, <= 960
    actual = body.get("actual_platform_minutes")
    if not is_int(actual) or actual <= 0 or actual > 960:
        raise ApiError(
            ERR_INVALID_ACTUAL_MINUTES,
            "actual_platform_minutes must be present, greater than 0, and at most 960",
            422,
        )
    assignment["actual_platform_minutes"] = actual
    assignment["status"] = "WORKED"
    touch(assignment)

    period = db.sign_up_periods.get(assignment["sign_up_period_id"])
    final = create_pay_record(assignment, period, actual, "FINAL")

    op = db.operators.get(assignment["operator_id"])
    if op is not None:
        op["weekly_ot_minutes_accum"] += final["overtime_minutes"]
        touch(op)
    return ok_obj(ser(assignment))


@bp.post("/api/daily-assignments/<aid>/mark-no-show")
def mark_no_show(aid):
    auth = authenticate()
    require_roles(auth, ["SchedulingOfficer"])
    assignment = get_assignment_or_404(aid)
    if assignment["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED assignment may be marked NO_SHOW")
    assignment["status"] = "NO_SHOW"
    touch(assignment)
    return ok_obj(ser(assignment))


@bp.post("/api/daily-assignments/<aid>/finalize-pay")
def finalize_pay(aid):
    auth = authenticate()
    require_roles(auth, ["PayrollClerk"])
    assignment = get_assignment_or_404(aid)
    if assignment["pay_status"] not in ("PROVISIONAL", "DISPUTED"):
        raise invalid_state("Only PROVISIONAL or DISPUTED pay may be finalized")
    has_final = any(
        pr["daily_assignment_id"] == aid and pr["variant"] == "FINAL"
        for pr in db.pay_records.values()
    )
    if assignment["pay_status"] == "PROVISIONAL":
        if assignment["status"] != "WORKED" or not has_final:
            raise invalid_state(
                "Finalization requires the assignment to be WORKED with a FINAL pay record"
            )
    else:  # DISPUTED
        if not has_final:
            raise invalid_state("Finalization requires a FINAL pay record")
    assignment["pay_status"] = "FINALIZED"
    touch(assignment)
    return ok_obj(ser(assignment))


@bp.post("/api/daily-assignments/<aid>/dispute-pay")
def dispute_pay(aid):
    auth = authenticate()
    require_roles(auth, ["Operator"])
    assignment = get_assignment_or_404(aid)
    if assignment["operator_id"] != auth["user_id"]:
        raise forbidden("Only the assigned operator may dispute this pay")
    if assignment["pay_status"] not in ("PROVISIONAL", "FINALIZED"):
        raise invalid_state("Only PROVISIONAL or FINALIZED pay may be disputed")
    assignment["pay_status"] = "DISPUTED"
    touch(assignment)
    return ok_obj(ser(assignment))


@bp.get("/api/daily-assignments/<aid>/pay-records")
def assignment_pay_records(aid):
    auth = authenticate()
    require_roles(auth, ["SchedulingOfficer", "Operator", "PayrollClerk"])
    assignment = get_assignment_or_404(aid)
    if auth["role"] == "Operator" and assignment["operator_id"] != auth["user_id"]:
        raise forbidden("Operators may read pay records of their own assignments only")
    items = [pr for pr in db.pay_records.values() if pr["daily_assignment_id"] == aid]
    return paginated(items)
