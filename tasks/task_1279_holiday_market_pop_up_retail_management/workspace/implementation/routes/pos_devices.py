"""PosDevice endpoints (PRD 3.6)."""
from flask import Blueprint

import db
from errors import ApiError, invalid_state, posture_forbidden
from middleware import auth, require_roles
from response import success
from services import posture
from services.core import (
    arg,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    list_response,
    required,
    serialize,
    touch,
)

bp = Blueprint("pos_devices", __name__)

MO = ("MarketOperator",)
GET_ONE = ("MarketOperator", "VendorRole", "FinanceOfficer")
GET_LIST = ("MarketOperator", "FinanceOfficer")


def _resolve(marketId, posDeviceId):
    get_market(marketId)
    return get_child("pos_devices", posDeviceId, marketId)


@bp.post("/markets/<marketId>/pos_devices")
def create_pos_device(marketId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    data = body()
    assignment_id = as_str(required(data, "assignment_id"), "assignment_id")
    get_child("assignments", assignment_id, marketId)
    device_code = as_str(required(data, "device_code"), "device_code")
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "assignment_id": assignment_id,
            "device_code": device_code,
            "status": "PROVISIONED",
        }
    )
    db.STORES["pos_devices"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/pos_devices/<posDeviceId>")
def get_pos_device(marketId, posDeviceId):
    user = auth()
    require_roles(user, GET_ONE)
    return success(serialize(_resolve(marketId, posDeviceId)))


@bp.get("/markets/<marketId>/pos_devices")
def list_pos_devices(marketId):
    user = auth()
    require_roles(user, GET_LIST)
    get_market(marketId)
    status = arg("status")
    assignment_id = arg("assignment_id")
    records = []
    for d in db.STORES["pos_devices"].values():
        if d["market_id"] != marketId:
            continue
        if status is not None and d["status"] != status:
            continue
        if assignment_id is not None and d["assignment_id"] != assignment_id:
            continue
        records.append(d)
    return list_response(records)


@bp.post("/markets/<marketId>/pos_devices/<posDeviceId>/activate")
def activate_pos_device(marketId, posDeviceId):
    user = auth()
    require_roles(user, MO)
    market = get_market(marketId)
    device = get_child("pos_devices", posDeviceId, marketId)
    if posture.derive_posture(market) != "OPEN":
        raise posture_forbidden("POS device activation requires OPEN posture")
    if device["status"] not in ("PROVISIONED", "SUSPENDED"):
        raise invalid_state("only a PROVISIONED or SUSPENDED device can be activated")
    if device["status"] == "PROVISIONED":
        if not market["shared_pos_enabled"]:
            raise ApiError(
                "ERR_NO_SHARED_POS", "market.shared_pos_enabled is not true", 409
            )
        assignment = db.STORES["assignments"].get(device["assignment_id"])
        if assignment is None or assignment["status"] != "ACTIVE":
            raise invalid_state("linked booth assignment is not ACTIVE")
    device["status"] = "ACTIVE"
    touch(device)
    return success(serialize(device))


@bp.post("/markets/<marketId>/pos_devices/<posDeviceId>/suspend")
def suspend_pos_device(marketId, posDeviceId):
    user = auth()
    require_roles(user, MO)
    device = _resolve(marketId, posDeviceId)
    if device["status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE device can be suspended")
    device["status"] = "SUSPENDED"
    touch(device)
    return success(serialize(device))


@bp.post("/markets/<marketId>/pos_devices/<posDeviceId>/return_device")
def return_pos_device(marketId, posDeviceId):
    user = auth()
    require_roles(user, MO)
    device = _resolve(marketId, posDeviceId)
    if device["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_state("only an ACTIVE or SUSPENDED device can be returned")
    open_settlement = any(
        s["assignment_id"] == device["assignment_id"] and s["status"] in ("DRAFT", "SUBMITTED")
        for s in db.STORES["settlements"].values()
    )
    if open_settlement:
        raise ApiError(
            "ERR_DEVICE_HAS_OPEN_SETTLEMENTS",
            "device cannot be returned while the assignment has DRAFT or SUBMITTED settlements",
            409,
        )
    device["status"] = "RETURNED"
    touch(device)
    return success(serialize(device))
