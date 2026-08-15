"""Staff registry endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    CAPABILITIES,
    EMPLOYMENT_STATUSES,
    bump,
    get_staff,
    paginate,
    staff_view,
)
from util import as_int, as_str_list, body, opt_enum, pagination_args, req, req_str

bp = Blueprint("staff", __name__)


def _validate_capabilities(value):
    capabilities = as_str_list(value, "capabilities")
    for cap in capabilities:
        if cap not in CAPABILITIES:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "capabilities must be a subset of INTAKE, INVESTIGATION, OFFICER",
            )
    return capabilities


@bp.post("/hotline/staff-members")
def create_staff():
    auth(["EthicsPlatformAdmin"])
    data = body()
    display_name = req_str(data, "display_name")
    email = req_str(data, "email")
    department = req_str(data, "department")
    capabilities = _validate_capabilities(req(data, "capabilities"))
    max_active_cases = as_int(req(data, "max_active_cases"), "max_active_cases", minimum=1)
    employment_status = opt_enum(data, "employment_status", EMPLOYMENT_STATUSES) or "ACTIVE"
    for s in DB["staff_members"].values():
        if s["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", 400, "email must be unique across staff")
    rec = {
        "id": new_id(),
        "display_name": display_name,
        "email": email,
        "department": department,
        "capabilities": capabilities,
        "employment_status": employment_status,
        "max_active_cases": max_active_cases,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["staff_members"][rec["id"]] = rec
    return ok(staff_view(rec), status=201)


@bp.get("/hotline/staff-members")
def list_staff():
    auth(STAFF_READ_ROLES)
    limit, offset = pagination_args()
    records = list(DB["staff_members"].values())
    employment_status = request.args.get("employment_status")
    if employment_status is not None:
        records = [s for s in records if s["employment_status"] == employment_status]
    capability = request.args.get("capability")
    if capability is not None:
        records = [s for s in records if capability in s["capabilities"]]
    page, total = paginate(records, limit, offset)
    return ok_list([staff_view(s) for s in page], total, limit, offset)


@bp.patch("/hotline/staff-members/<sid>")
def update_staff(sid):
    auth(["EthicsPlatformAdmin"])
    staff = get_staff(sid)
    data = body()
    if "department" in data and data["department"] is not None:
        staff["department"] = req_str(data, "department")
    if "capabilities" in data and data["capabilities"] is not None:
        staff["capabilities"] = _validate_capabilities(data["capabilities"])
    if "max_active_cases" in data and data["max_active_cases"] is not None:
        staff["max_active_cases"] = as_int(
            data["max_active_cases"], "max_active_cases", minimum=1
        )
    if "employment_status" in data and data["employment_status"] is not None:
        staff["employment_status"] = opt_enum(
            data, "employment_status", EMPLOYMENT_STATUSES
        )
    bump(staff)
    return ok(staff_view(staff))
