"""Employee endpoints + test-driving endpoints."""
from flask import Blueprint, request

import db
import response
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_roles
from services import serialize, pagination
from services import validation as V


bp = Blueprint("employees", __name__)


@bp.post("/employees")
@require_roles("HRClerk", "PlatformAdmin")
def create_employee():
    body = V.require_dict(request.get_json(silent=True) or {})
    full_name = V.require_str(body, "full_name")
    work_state = V.require_enum(body, "work_state_code", V.STATE_CODES)
    residence_state = V.require_enum(body, "residence_state_code", V.STATE_CODES)
    locality = V.opt_enum(body, "locality_code", V.LOCALITY_CODES, default="NONE")

    e = {
        "id": db.new_id(),
        "full_name": full_name,
        "work_state_code": work_state,
        "residence_state_code": residence_state,
        "locality_code": locality,
        "status": "ACTIVE",
        "ytd_wages_cents": 0,
        "ytd_fed_withheld_cents": 0,
        "ytd_ss_wages_cents": 0,
        "ytd_medicare_wages_cents": 0,
    }
    db.stamp_common(e)
    db.employees[e["id"]] = e
    return response.success_object(serialize.employee(e), status=201)


@bp.get("/employees/<eid>")
@require_roles("HRClerk", "PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def get_employee(eid):
    e = db.employees.get(eid)
    if not e:
        raise APIError(ERR_NOT_FOUND, 404, "Employee not found")
    return response.success_object(serialize.employee(e))


@bp.get("/employees")
@require_roles("HRClerk", "PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def list_employees():
    limit, offset = pagination.parse_limit_offset()
    status_filter = V.opt_enum(request.args, "status", V.EMPLOYEE_STATUSES)
    state_filter = V.opt_enum(request.args, "work_state_code", V.STATE_CODES)

    items = list(db.employees.values())
    if status_filter:
        items = [e for e in items if e["status"] == status_filter]
    if state_filter:
        items = [e for e in items if e["work_state_code"] == state_filter]

    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.employee(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.patch("/employees/<eid>/status")
@require_roles("HRClerk", "PlatformAdmin")
def patch_status(eid):
    e = db.employees.get(eid)
    if not e:
        raise APIError(ERR_NOT_FOUND, 404, "Employee not found")
    body = V.require_dict(request.get_json(silent=True) or {})
    new_status = V.require_enum(body, "status", V.EMPLOYEE_STATUSES)
    e["status"] = new_status
    db.bump(e)
    return response.success_object(serialize.employee(e))


# -----------------------------------------------------------------------------
# Test-driving endpoints (PlatformAdmin only)
# -----------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    body = V.require_dict(request.get_json(silent=True) or {})
    iso = V.require_str(body, "to_iso8601")
    try:
        db.set_clock(iso)
    except (ValueError, TypeError) as ex:
        raise APIError(ERR_INVALID_REQUEST, 400, f"invalid ISO 8601 timestamp: {ex}")
    return response.success_object({})


@bp.post("/_employees/<eid>/set_ytd")
@require_roles("PlatformAdmin")
def set_ytd(eid):
    e = db.employees.get(eid)
    if not e:
        raise APIError(ERR_NOT_FOUND, 404, "Employee not found")
    body = V.require_dict(request.get_json(silent=True) or {})
    touched = False
    for field in ("ytd_wages_cents", "ytd_fed_withheld_cents",
                  "ytd_ss_wages_cents", "ytd_medicare_wages_cents"):
        if field in body and body[field] is not None:
            v = V.opt_int(body, field, default=0)
            if v < 0:
                raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be non-negative")
            e[field] = v
            touched = True
    if touched:
        db.bump(e)
    return response.success_object(serialize.employee(e))
