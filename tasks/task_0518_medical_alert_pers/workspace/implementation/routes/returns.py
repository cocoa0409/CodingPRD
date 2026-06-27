"""EquipmentReturn endpoints (PRD 3.11)."""
from flask import Blueprint, request

from clock import clock
from db import store
from errors import err
from middleware import get_auth, require_role
from models import touch, serialize_equipment_return
from response import object_response, array_response
from services.lookup import get_equipment_return, get_device, get_contract
from services.calculations import equipment_damage_fee
from util import get_json_body, require_fields, require_enum, parse_pagination, paginate, sort_by_created

bp = Blueprint("returns", __name__)

GRADES = {"A", "B", "C", "UNRETURNED"}


@bp.route("/pers/equipment-returns/<rid>", methods=["GET"])
def get_return_route(rid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    r = get_equipment_return(rid)
    return object_response(serialize_equipment_return(r), 200)


@bp.route("/pers/equipment-returns", methods=["GET"])
def list_returns():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    limit, offset = parse_pagination()
    items = list(store.equipment_returns.values())
    if "contract_id" in request.args:
        items = [r for r in items if r["contract_id"] == request.args.get("contract_id")]
    if "device_id" in request.args:
        items = [r for r in items if r["device_id"] == request.args.get("device_id")]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_equipment_return(r) for r in page], limit, offset, total)


@bp.route("/pers/equipment-returns/<rid>/send-kit", methods=["POST"])
def send_kit(rid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    r = get_equipment_return(rid)
    if r["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", "Return is not INITIATED")
    r["status"] = "KIT_SENT"
    touch(r)
    return object_response(serialize_equipment_return(r), 200)


@bp.route("/pers/equipment-returns/<rid>/mark-received", methods=["POST"])
def mark_received(rid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    r = get_equipment_return(rid)
    if r["status"] != "KIT_SENT":
        raise err("ERR_INVALID_STATE", "Return is not KIT_SENT")
    r["status"] = "RECEIVED"
    r["received_at_dt"] = clock.now()
    touch(r)
    return object_response(serialize_equipment_return(r), 200)


@bp.route("/pers/equipment-returns/<rid>/inspect", methods=["POST"])
def inspect(rid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    r = get_equipment_return(rid)
    body = get_json_body()
    require_fields(body, ["condition_grade"])
    require_enum(body["condition_grade"], GRADES, "condition_grade")
    grade = body["condition_grade"]

    if grade in ("A", "B"):
        # RECEIVED -> INSPECTED_OK
        if r["status"] != "RECEIVED":
            raise err("ERR_INVALID_STATE", "Inspect A/B requires RECEIVED status")
        r["status"] = "INSPECTED_OK"
        r["condition_grade"] = grade
        r["damage_fee_cents"] = 0
        touch(r)
        return object_response(serialize_equipment_return(r), 200)

    if grade == "C":
        if r["status"] != "RECEIVED":
            raise err("ERR_INVALID_STATE", "Inspect C requires RECEIVED status")
        device = get_device(r["device_id"])
        fee = equipment_damage_fee("DAMAGED", device["device_type"])
        r["status"] = "DAMAGED"
        r["condition_grade"] = "C"
        r["damage_fee_cents"] = fee
        # cross-aggregate: add to contract outstanding balance (PRD 3.11)
        contract = store.contracts.get(r["contract_id"])
        if contract is not None:
            contract["outstanding_balance_cents"] = contract.get("outstanding_balance_cents", 0) + fee
            touch(contract)
        touch(r)
        return object_response(serialize_equipment_return(r), 200)

    # UNRETURNED
    if grade == "UNRETURNED":
        if r["status"] not in ("INITIATED", "KIT_SENT"):
            raise err("ERR_INVALID_STATE", "UNRETURNED requires INITIATED or KIT_SENT status")
        due = r.get("due_back_at_dt")
        if due is None or not (clock.now() > due):
            raise err("ERR_TEMPORAL_NOT_DUE", "due_back_at not yet passed")
        device = get_device(r["device_id"])
        fee = equipment_damage_fee("UNRETURNED", device["device_type"])
        r["status"] = "DAMAGED"
        r["condition_grade"] = "UNRETURNED"
        r["damage_fee_cents"] = fee
        contract = store.contracts.get(r["contract_id"])
        if contract is not None:
            contract["outstanding_balance_cents"] = contract.get("outstanding_balance_cents", 0) + fee
            touch(contract)
        touch(r)
        return object_response(serialize_equipment_return(r), 200)

    raise err("ERR_INVALID_REQUEST", "Unknown condition_grade")


@bp.route("/pers/equipment-returns/<rid>/close", methods=["POST"])
def close_return(rid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    r = get_equipment_return(rid)
    if r["status"] not in ("INSPECTED_OK", "DAMAGED"):
        raise err("ERR_INVALID_STATE", "Close requires INSPECTED_OK or DAMAGED status")
    r["status"] = "CLOSED"
    touch(r)
    return object_response(serialize_equipment_return(r), 200)
