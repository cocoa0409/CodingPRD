"""RegimenProtocol and OrderSetItem endpoints."""
from flask import Blueprint, request

import errors
from db import db
from errors import err
from middleware import get_auth, require_roles
from response import success, list_success
from store_helpers import (
    make_common, touch, public, sort_by_created, get_protocol, get_order_set_item,
)
from validation import (
    get_body, require_str, require_int, require_number, require_enum,
    get_pagination, paginate,
)

bp = Blueprint("protocols", __name__)

ALL_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}
ROLE_VALUES = {"CHEMO", "PREMED"}
DOSING_METHODS = {"BSA", "AUC", "FLAT"}


# ---------- Regimen Protocols ----------

@bp.route("/regimen-protocols", methods=["POST"])
def create_protocol():
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    body = get_body()
    code = require_str(body, "code")
    name = require_str(body, "name")
    cycle_length_days = require_int(body, "cycle_length_days", ge=1)
    total_cycles = require_int(body, "total_cycles", ge=1)

    with db.lock:
        entity = make_common()
        entity.update({
            "code": code,
            "name": name,
            "cycle_length_days": cycle_length_days,
            "total_cycles": total_cycles,
            "status": "DRAFT",
        })
        db.regimen_protocols[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/regimen-protocols", methods=["GET"])
def list_protocols():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    status = request.args.get("status")
    items = [p for p in db.regimen_protocols.values() if status is None or p.get("status") == status]
    items = sort_by_created(items)
    total = len(items)
    window = [public(p) for p in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/regimen-protocols/<pid>", methods=["GET"])
def get_one_protocol(pid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_protocol(pid)
    return success(public(entity), status=200)


@bp.route("/regimen-protocols/<pid>/publish", methods=["POST"])
def publish_protocol(pid):
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    protocol = get_protocol(pid)
    with db.lock:
        items = [i for i in db.order_set_items.values() if i["regimen_protocol_id"] == pid]
        if len(items) == 0:
            raise err(errors.ERR_NO_ORDER_SET_ITEMS, "Protocol has no order set items")
        if not any(i["role"] == "CHEMO" for i in items):
            raise err(errors.ERR_NO_CHEMO_ITEM, "Protocol has no CHEMO order set item")
        protocol["status"] = "PUBLISHED"
        touch(protocol, bump_version=True)
        return success(public(protocol), status=200)


# ---------- Order Set Items ----------

@bp.route("/order-set-items", methods=["POST"])
def create_order_set_item():
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    body = get_body()
    # Existence (FK) before body well-formedness per §2.10 (path before body; this is body FK).
    protocol_id = require_str(body, "regimen_protocol_id")
    protocol = get_protocol(protocol_id)

    drug_name = require_str(body, "drug_name")
    item_role = require_enum(body, "role", ROLE_VALUES)
    dosing_method = require_enum(body, "dosing_method", DOSING_METHODS)

    dose_per_m2 = None
    target_auc = None
    flat_dose_mg = None
    if dosing_method == "BSA":
        dose_per_m2 = require_number(body, "dose_per_m2", gt=0)
    elif dosing_method == "AUC":
        target_auc = require_number(body, "target_auc", gt=0)
    else:  # FLAT
        flat_dose_mg = require_number(body, "flat_dose_mg", gt=0)

    vial_size_mg = require_number(body, "vial_size_mg", gt=0)
    day_offset = require_int(body, "day_offset", ge=1)
    sequence_index = require_int(body, "sequence_index")

    with db.lock:
        # Items attach only while DRAFT; published protocols are immutable templates.
        # No dedicated state error exists for this in the catalog, so the closest
        # applicable rejection is ERR_INVALID_REQUEST (the request targets an
        # immutable template).
        if protocol["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_REQUEST,
                      "Order set items can only attach to a DRAFT protocol")
        entity = make_common()
        entity.update({
            "regimen_protocol_id": protocol_id,
            "drug_name": drug_name,
            "role": item_role,
            "dosing_method": dosing_method,
            "dose_per_m2": dose_per_m2,
            "target_auc": target_auc,
            "flat_dose_mg": flat_dose_mg,
            "vial_size_mg": vial_size_mg,
            "day_offset": day_offset,
            "sequence_index": sequence_index,
        })
        db.order_set_items[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/order-set-items", methods=["GET"])
def list_order_set_items():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    protocol_id = request.args.get("regimen_protocol_id")
    items = [i for i in db.order_set_items.values()
             if protocol_id is None or i["regimen_protocol_id"] == protocol_id]
    items = sort_by_created(items)
    total = len(items)
    window = [public(i) for i in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/order-set-items/<iid>", methods=["GET"])
def get_one_order_set_item(iid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_order_set_item(iid)
    return success(public(entity), status=200)
