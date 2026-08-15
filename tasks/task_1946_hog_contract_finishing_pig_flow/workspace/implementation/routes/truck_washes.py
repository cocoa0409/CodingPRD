"""Truck washes (PRD §3.5, §2.10): record, verify, reject with recorder/verifier
segregation of duties."""

from flask import Blueprint, request

from db import store
from errors import (
    conflict, segregation_of_duties, ERR_INVALID_STATE_TRANSITION,
)
from middleware import (
    require_roles, ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_TRANSPORT_COORDINATOR,
)
from response import success_object, paginate
from services.core import new_record, touch, ser_truck_wash
from util import get_body, req, as_str, as_datetime, as_enum, load_or_404

bp = Blueprint("truck_washes", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_TRANSPORT_COORDINATOR, ROLE_FIELD_TECH]
WASH_TYPES = {"FULL_DISINFECT", "WASH_ONLY"}


@bp.route("/truck-washes", methods=["POST"])
def create_truck_wash():
    role, user_id = require_roles([ROLE_TRANSPORT_COORDINATOR])
    body = get_body()
    truck_code = as_str(req(body, "truck_code"), "truck_code")
    washed_at = as_datetime(req(body, "washed_at"), "washed_at")
    wash_type = as_enum(req(body, "wash_type"), "wash_type", WASH_TYPES)
    rec = new_record()
    rec.update({
        "truck_code": truck_code, "washed_at": washed_at, "wash_type": wash_type,
        "recorded_by": user_id, "verified_by": None, "wash_status": "RECORDED",
    })
    store.truck_washes[rec["id"]] = rec
    return success_object(ser_truck_wash(rec), 201)


@bp.route("/truck-washes", methods=["GET"])
def list_truck_washes():
    require_roles(ROLES_READ)
    truck_code = request.args.get("truck_code")
    status = request.args.get("wash_status")
    items = list(store.truck_washes.values())
    if truck_code is not None:
        items = [w for w in items if w["truck_code"] == truck_code]
    if status is not None:
        items = [w for w in items if w["wash_status"] == status]
    return paginate(items, request.args, ser_truck_wash)


@bp.route("/truck-washes/<wid>", methods=["GET"])
def get_truck_wash(wid):
    require_roles(ROLES_READ)
    return success_object(ser_truck_wash(load_or_404(store.truck_washes, wid, "TruckWash")))


@bp.route("/truck-washes/<wid>/verify", methods=["POST"])
def verify_truck_wash(wid):
    role, user_id = require_roles([ROLE_INTEGRATOR_ADMIN])
    wash = load_or_404(store.truck_washes, wid, "TruckWash")
    if wash["wash_status"] != "RECORDED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot verify a wash in {wash['wash_status']}")
    # SoD: the verifier must differ from the recorder (§2.11)
    if user_id == wash["recorded_by"]:
        raise segregation_of_duties("Verifier must differ from the wash recorder")
    wash["wash_status"] = "VERIFIED"
    wash["verified_by"] = user_id
    touch(wash)
    return success_object(ser_truck_wash(wash))


@bp.route("/truck-washes/<wid>/reject", methods=["POST"])
def reject_truck_wash(wid):
    role, user_id = require_roles([ROLE_INTEGRATOR_ADMIN])
    wash = load_or_404(store.truck_washes, wid, "TruckWash")
    if wash["wash_status"] != "RECORDED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot reject a wash in {wash['wash_status']}")
    if user_id == wash["recorded_by"]:
        raise segregation_of_duties("Rejecter must differ from the wash recorder")
    wash["wash_status"] = "REJECTED"
    touch(wash)
    return success_object(ser_truck_wash(wash))
