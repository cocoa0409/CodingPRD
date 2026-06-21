"""Break records and the missed-break premium (PRD §3.4)."""
from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_role
from response import object_response, array_response
from util import as_bool, as_enum, as_int, as_str, body, paginate, pagination, public, public_list
from services.helpers import get_or_404

bp = Blueprint("breaks", __name__)


def _premium_owed(taken, kind, ruleset, employee):
    """premium_owed (SCAFFOLD §1.1): true when not taken AND matching premium
    enabled on the governing rule set AND employee is NON_EXEMPT."""
    if taken:
        return False
    if employee.get("classification") != "NON_EXEMPT":
        return False
    if ruleset is None:
        return False
    if kind == "MEAL":
        return bool(ruleset.get("meal_break_premium_enabled", False))
    if kind == "REST":
        return bool(ruleset.get("rest_break_premium_enabled", False))
    return False


def _governing_ruleset(employee):
    worksite = db.worksites.get(employee.get("home_worksite_id"))
    if worksite is None:
        return None
    for rs in db.wage_rulesets.values():
        if (rs.get("employer_id") == employee.get("employer_id")
                and rs.get("state_code") == worksite.get("state_code")):
            return rs
    return None


@bp.post("/break-records")
def create_break_record():
    require_role("Supervisor", "Employee")
    data = body()
    shift_id = as_str(data, "shift_id", required=True)
    employee_id = as_str(data, "employee_id", required=True)
    kind = as_enum(data, "kind", {"MEAL", "REST"}, required=True)
    taken = as_bool(data, "taken", default=None)
    if taken is None:
        raise err("ERR_INVALID_REQUEST", "taken is required.")
    minutes = as_int(data, "minutes", required=False, default=0)

    # Negative minutes -> ERR_VALIDATION (priority 24).
    if minutes < 0:
        raise err("ERR_VALIDATION", "minutes must be non-negative.")

    # Existence left-to-right (priority 4).
    get_or_404(db.shifts, shift_id)
    employee = get_or_404(db.employees, employee_id)

    # Employee acting on own break records (ownership) (priority 6).
    if g.user_role == "Employee" and g.user_id != employee_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "Acting employee can only record their own break records.")

    ruleset = _governing_ruleset(employee)

    # A missed break flagged as a premium against an EXEMPT employee is not
    # eligible (priority 10). This applies when the matching premium is enabled
    # (the record would otherwise be a premium claim).
    if not taken and employee.get("classification") == "EXEMPT":
        enabled = (
            (kind == "MEAL" and ruleset is not None and ruleset.get("meal_break_premium_enabled", False))
            or (kind == "REST" and ruleset is not None and ruleset.get("rest_break_premium_enabled", False))
        )
        if enabled:
            raise err("ERR_EXEMPT_NOT_ELIGIBLE",
                      "EXEMPT employees are not eligible for break premiums.")

    premium_owed = _premium_owed(taken, kind, ruleset, employee)

    record = db.base_fields()
    record.update({
        "shift_id": shift_id,
        "employee_id": employee_id,
        "kind": kind,
        "taken": taken,
        "minutes": minutes,
        "premium_owed": premium_owed,
    })
    db.break_records[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/break-records")
def list_break_records():
    require_role("PayrollAdmin", "Supervisor", "Employee")
    limit, offset = pagination()
    shift_id = request.args.get("shift_id")
    employee_id = request.args.get("employee_id")
    matches = list(db.break_records.values())
    if shift_id is not None:
        matches = [b for b in matches if b.get("shift_id") == shift_id]
    if employee_id is not None:
        matches = [b for b in matches if b.get("employee_id") == employee_id]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/break-records/<record_id>")
def get_break_record(record_id):
    require_role("PayrollAdmin", "Supervisor", "Employee")
    record = get_or_404(db.break_records, record_id)
    return object_response(public(record))
