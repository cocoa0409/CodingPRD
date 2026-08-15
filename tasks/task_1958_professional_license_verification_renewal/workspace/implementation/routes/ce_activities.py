"""Continuing-education activity endpoints (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, current_date, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import ce_activity_view
from services import refresh_license_derived, touch
from util import (
    as_date, as_num, as_str, body, num_str, pagination_args, required,
    round_half_up_decimal,
)

bp = Blueprint("ce_activities", __name__, url_prefix="/licensing")

CE_ELIGIBLE_STATUSES = ("ACTIVE", "EXPIRED", "LAPSED", "SUSPENDED")


@bp.post("/licenses/<lid>/ce-activities")
def create_ce_activity(lid):
    user_id, role = auth(["Employee", "ComplianceOfficer"])
    lic = DB["licenses"].get(lid)
    if lic is None:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    # Employee actors act only on their own licenses.
    if role == "Employee" and lic["employee_id"] != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403, "Employee does not own the target license"
        )
    data = body()
    provider_name = as_str(required(data, "provider_name"), "provider_name")
    activity_title = as_str(required(data, "activity_title"), "activity_title")
    hours = as_num(required(data, "hours"), "hours")
    if hours < 0.25 or hours > 200:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "hours must be >= 0.25 and <= 200"
        )
    completed = as_date(required(data, "completed_on"), "completed_on")
    if completed > current_date():
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "completed_on must not be in the future"
        )

    # Referential gate: the host license must be CE-eligible (PRD 2.8 step 15).
    if lic["status"] not in CE_ELIGIBLE_STATUSES:
        raise ApiError(
            "ERR_LICENSE_NOT_CE_ELIGIBLE", 409,
            f"License in {lic['status']} cannot accrue CE activities",
        )

    # Per-activity half-hour rounding, applied BEFORE any summation (PRD 3.4).
    rounded = round_half_up_decimal(Decimal(str(hours)) * 2, "1") / 2

    ts = now_iso()
    act = {
        "id": new_id(),
        "license_id": lid,
        "provider_name": provider_name,
        "activity_title": activity_title,
        "hours": hours,
        "rounded_hours": num_str(rounded),
        "completed_on": completed.isoformat(),
        "status": "LOGGED",
        "adjudicated_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["ce_activities"][act["id"]] = act
    return ok(ce_activity_view(act), status=201)


@bp.get("/licenses/<lid>/ce-activities")
def list_ce_activities(lid):
    auth(ALL_ROLES)
    if lid not in DB["licenses"]:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    limit, offset = pagination_args()
    items = sorted(
        (a for a in DB["ce_activities"].values() if a["license_id"] == lid),
        key=lambda x: x["created_at"],
    )
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([ce_activity_view(x) for x in page], total, limit, offset)


def _adjudicate(aid, outcome):
    user_id, role = auth(["ComplianceOfficer"])
    act = DB["ce_activities"].get(aid)
    if act is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CE activity not found")
    if act["status"] != "LOGGED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"CE activity in {act['status']} cannot be adjudicated",
        )
    act["status"] = outcome
    act["adjudicated_by_user_id"] = user_id
    touch(act)
    if outcome == "VALIDATED":
        lic = DB["licenses"][act["license_id"]]
        refresh_license_derived(lic)
        touch(lic)
    return ok(ce_activity_view(act))


@bp.post("/ce-activities/<aid>/validate")
def validate_ce_activity(aid):
    return _adjudicate(aid, "VALIDATED")


@bp.post("/ce-activities/<aid>/reject")
def reject_ce_activity(aid):
    return _adjudicate(aid, "REJECTED")
