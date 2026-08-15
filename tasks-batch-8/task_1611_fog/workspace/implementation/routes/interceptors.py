"""Grease interceptor endpoints: propose, list, read, approve, commission."""
import uuid

from flask import Blueprint, request

from db import STORE, now, next_seq
from errors import ApiError, ERR_INVALID_STATE, ERR_INTERCEPTOR_UNDERSIZED
from middleware import (
    auth,
    require_roles,
    forbid_unless,
    get_or_404,
    paginate,
    by_creation,
    filter_enum,
)
from response import success
from services.calculations import provisional_capacity, final_sizing
from services.serializers import ser_interceptor
from validation import body_json, v_str, v_int, v_num

bp = Blueprint("interceptors", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer", "FseContact"]
STATUSES = ("PROPOSED", "APPROVED", "ACTIVE")


@bp.post("/interceptors")
def create_interceptor():
    uid, role = auth()
    body = body_json()
    est_id = v_str(body, "establishment_id")
    nominal = v_int(body, "nominal_capacity_gal", min_val=1)
    gpm = v_num(body, "measured_flow_gpm", required=False, gt=0)
    require_roles(role, ["FseContact", "ProgramAdmin"])
    if role == "FseContact":
        forbid_unless(uid == est_id)
    est = get_or_404("establishments", est_id)
    current = now()
    ic = {
        "id": str(uuid.uuid4()),
        "establishment_id": est_id,
        "nominal_capacity_gal": nominal,
        "measured_flow_gpm": gpm,
        "provisional_required_gal": provisional_capacity(est),
        "required_min_capacity_gal": None,
        "sizing_method": None,
        "status": "PROPOSED",
        "approved_by_user_id": None,
        "commissioned_by_user_id": None,
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["interceptors"][ic["id"]] = ic
    return success(ser_interceptor(ic), 201)


@bp.get("/interceptors")
def list_interceptors():
    uid, role = auth()
    require_roles(role, READERS)
    est_filter = request.args.get("establishment_id")
    status_filter = filter_enum(request.args, "status", STATUSES)
    items = list(STORE["interceptors"].values())
    if role == "FseContact":
        items = [i for i in items if i["establishment_id"] == uid]
    if est_filter is not None:
        items = [i for i in items if i["establishment_id"] == est_filter]
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    page, meta = paginate(by_creation(items))
    return success([ser_interceptor(i) for i in page], 200, "array", meta)


@bp.get("/interceptors/<iid>")
def get_interceptor(iid):
    uid, role = auth()
    require_roles(role, READERS)
    ic = get_or_404("interceptors", iid)
    if role == "FseContact":
        forbid_unless(ic["establishment_id"] == uid)
    return success(ser_interceptor(ic))


@bp.post("/interceptors/<iid>/approve")
def approve_interceptor(iid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    ic = get_or_404("interceptors", iid)
    if ic["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Interceptor is not in PROPOSED status")
    required, method = final_sizing(ic)
    if ic["nominal_capacity_gal"] < required:
        raise ApiError(ERR_INTERCEPTOR_UNDERSIZED, 422, "nominal_capacity_gal is below the required minimum capacity")
    ic["status"] = "APPROVED"
    ic["required_min_capacity_gal"] = required
    ic["sizing_method"] = method
    ic["approved_by_user_id"] = uid
    ic["updated_at"] = now()
    ic["version"] += 1
    return success(ser_interceptor(ic))


@bp.post("/interceptors/<iid>/commission")
def commission_interceptor(iid):
    uid, role = auth()
    require_roles(role, ["Inspector"])
    ic = get_or_404("interceptors", iid)
    if ic["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Interceptor is not in APPROVED status")
    ic["status"] = "ACTIVE"
    ic["commissioned_by_user_id"] = uid
    ic["updated_at"] = now()
    ic["version"] += 1
    return success(ser_interceptor(ic))
