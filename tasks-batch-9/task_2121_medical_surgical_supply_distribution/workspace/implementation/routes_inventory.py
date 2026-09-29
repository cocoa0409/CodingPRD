"""Formulary mappings, cycle counts, replenishment suggestions and lots."""
import math

from flask import Blueprint, g

from auth import ALL_ROLES, endpoint, scope_check
from db import by_creation, new_entity, store, touch
from errors import ApiError
from response import ok, ok_list
from services import formulary_for
from validation import (
    EXCURSION_ACTIONS,
    FORMULARY_DECISIONS,
    FORMULARY_STATUSES,
    LOT_STATUSES,
    SUGGESTION_VARIANTS,
    get_body,
    opt_bool,
    opt_str,
    pagination,
    query_enum,
    query_required_enum,
    query_str,
    req_datetime,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("inventory", __name__)

_ALLOWED_FORMULARY_TRANSITIONS = {
    ("REQUESTED", "APPROVED"),
    ("REQUESTED", "RESTRICTED"),
    ("APPROVED", "RESTRICTED"),
    ("RESTRICTED", "APPROVED"),
    ("APPROVED", "DELISTED"),
    ("RESTRICTED", "DELISTED"),
}


# ---------------------------------------------------------------------------
# FormularyItem
# ---------------------------------------------------------------------------
@bp.route("/supply-rooms/<supply_room_id>/formulary-items", methods=["POST"])
@endpoint(["MaterialsManager"])
def create_formulary_item(supply_room_id):
    body = get_body()
    item_id = req_id(body, "item_id")
    facility_item_code = req_str(body, "facility_item_code")
    par_qty = req_int(body, "par_qty", minimum=1)
    reorder_point = req_int(body, "reorder_point", minimum=0)
    lum_enabled = opt_bool(body, "lum_enabled", False)
    if reorder_point >= par_qty:
        raise ApiError("ERR_VALIDATION",
                       "'reorder_point' must be strictly below 'par_qty'.")

    room = store.supply_rooms.get(supply_room_id)
    if room is None:
        raise ApiError("ERR_SUPPLY_ROOM_NOT_FOUND",
                       "Supply room %s does not exist." % supply_room_id)
    if item_id not in store.items:
        raise ApiError("ERR_ITEM_NOT_FOUND", "Item %s does not exist." % item_id)

    scope_check(supply_room_id)

    if formulary_for(supply_room_id, item_id) is not None:
        raise ApiError("ERR_DUPLICATE_FORMULARY_ITEM",
                       "This supply room already maps item %s." % item_id)

    mapping = new_entity({
        "supply_room_id": supply_room_id,
        "item_id": item_id,
        "facility_item_code": facility_item_code,
        "formulary_status": "REQUESTED",
        "decided_by_user_id": None,
        "par_qty": par_qty,
        "reorder_point": reorder_point,
        "on_hand_qty": 0,
        "lum_enabled": lum_enabled,
    })
    store.formulary_items[mapping["id"]] = mapping
    return ok(mapping, 201)


@bp.route("/formulary-items/<formulary_item_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_formulary_item(formulary_item_id):
    mapping = store.formulary_items.get(formulary_item_id)
    if mapping is None:
        raise ApiError("ERR_FORMULARY_ITEM_NOT_FOUND",
                       "Formulary item %s does not exist." % formulary_item_id)
    return ok(mapping)


@bp.route("/formulary-items", methods=["GET"])
@endpoint(ALL_ROLES)
def list_formulary_items():
    limit, offset = pagination()
    supply_room_id = query_str("supply_room_id")
    item_id = query_str("item_id")
    formulary_status = query_enum("formulary_status", FORMULARY_STATUSES)
    rows = []
    for mapping in store.formulary_items.values():
        if supply_room_id is not None and mapping["supply_room_id"] != supply_room_id:
            continue
        if item_id is not None and mapping["item_id"] != item_id:
            continue
        if formulary_status is not None and mapping["formulary_status"] != formulary_status:
            continue
        rows.append(mapping)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.route("/formulary-items/<formulary_item_id>/decision", methods=["POST"])
@endpoint(["Clinician"])
def decide_formulary_item(formulary_item_id):
    body = get_body()
    decision = req_enum(body, "decision", FORMULARY_DECISIONS)

    mapping = store.formulary_items.get(formulary_item_id)
    if mapping is None:
        raise ApiError("ERR_FORMULARY_ITEM_NOT_FOUND",
                       "Formulary item %s does not exist." % formulary_item_id)

    current = mapping["formulary_status"]
    if (current, decision) not in _ALLOWED_FORMULARY_TRANSITIONS:
        raise ApiError("ERR_FORMULARY_STATE_INVALID",
                       "A %s mapping does not accept the decision %s." % (current, decision))

    mapping["formulary_status"] = decision
    mapping["decided_by_user_id"] = g.user_id
    touch(mapping)
    return ok(mapping)


@bp.route("/formulary-items/<formulary_item_id>/adjust-on-hand", methods=["POST"])
@endpoint(["MaterialsManager"])
def adjust_on_hand(formulary_item_id):
    body = get_body()
    delta_qty = req_int(body, "delta_qty")
    expected_version = req_int(body, "expected_formulary_item_version")

    mapping = store.formulary_items.get(formulary_item_id)
    if mapping is None:
        raise ApiError("ERR_FORMULARY_ITEM_NOT_FOUND",
                       "Formulary item %s does not exist." % formulary_item_id)

    scope_check(mapping["supply_room_id"])

    if expected_version != mapping["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_formulary_item_version %s does not match the current version %s."
                       % (expected_version, mapping["version"]))

    new_qty = mapping["on_hand_qty"] + delta_qty
    if new_qty < 0:
        new_qty = 0
    mapping["on_hand_qty"] = new_qty
    touch(mapping)
    return ok(mapping)


@bp.route("/formulary-items/<formulary_item_id>/replenishment-suggestion", methods=["GET"])
@endpoint(["MaterialsManager", "ContractAdmin"])
def replenishment_suggestion(formulary_item_id):
    variant = query_required_enum("variant", SUGGESTION_VARIANTS)

    mapping = store.formulary_items.get(formulary_item_id)
    if mapping is None:
        raise ApiError("ERR_FORMULARY_ITEM_NOT_FOUND",
                       "Formulary item %s does not exist." % formulary_item_id)

    scope_check(mapping["supply_room_id"])

    item = store.items.get(mapping["item_id"])
    units_per_parent = item["units_per_parent"] if item is not None else 1
    if units_per_parent < 1:
        units_per_parent = 1

    eligible = (mapping["formulary_status"] == "APPROVED"
                and mapping["on_hand_qty"] <= mapping["reorder_point"])
    if not eligible:
        payload = {
            "eligible": False,
            "deficit_eaches": 0,
            "suggested_case_qty": 0,
            "suggested_each_qty": 0,
            "suggested_total_eaches": 0,
            "variant": variant,
        }
        return ok(payload)

    deficit = mapping["par_qty"] - mapping["on_hand_qty"]
    if variant == "STANDARD_TOPOFF":
        case_qty = int(math.ceil(float(deficit) / float(units_per_parent)))
        each_qty = 0
        total_eaches = case_qty * units_per_parent
    else:
        case_qty = deficit // units_per_parent
        each_qty = deficit - case_qty * units_per_parent
        total_eaches = deficit

    payload = {
        "eligible": True,
        "deficit_eaches": deficit,
        "suggested_case_qty": case_qty,
        "suggested_each_qty": each_qty,
        "suggested_total_eaches": total_eaches,
        "variant": variant,
    }
    return ok(payload)


# ---------------------------------------------------------------------------
# Lot
# ---------------------------------------------------------------------------
@bp.route("/lots", methods=["POST"])
@endpoint(["DistributionOperator"])
def create_lot():
    body = get_body()
    item_id = req_id(body, "item_id")
    lot_code = req_str(body, "lot_code")
    expiry_raw, _expiry = req_datetime(body, "expiry_date")
    received_quantity = req_int(body, "received_quantity", minimum=1)

    if item_id not in store.items:
        raise ApiError("ERR_ITEM_NOT_FOUND", "Item %s does not exist." % item_id)

    lot = new_entity({
        "item_id": item_id,
        "lot_code": lot_code,
        "expiry_date": expiry_raw,
        "received_quantity": received_quantity,
        "quantity_on_hand": received_quantity,
        "status": "AVAILABLE",
        "excursion_flagged_by_user_id": None,
    })
    store.lots[lot["id"]] = lot
    return ok(lot, 201)


@bp.route("/lots/<lot_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_lot(lot_id):
    lot = store.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "Lot %s does not exist." % lot_id)
    return ok(lot)


@bp.route("/lots", methods=["GET"])
@endpoint(ALL_ROLES)
def list_lots():
    limit, offset = pagination()
    item_id = query_str("item_id")
    status = query_enum("status", LOT_STATUSES)
    rows = []
    for lot in store.lots.values():
        if item_id is not None and lot["item_id"] != item_id:
            continue
        if status is not None and lot["status"] != status:
            continue
        rows.append(lot)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.route("/lots/<lot_id>/excursion", methods=["POST"])
@endpoint(["DistributionOperator"])
def lot_excursion(lot_id):
    body = get_body()
    action = req_enum(body, "action", EXCURSION_ACTIONS)
    opt_str(body, "note", None)

    lot = store.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "Lot %s does not exist." % lot_id)

    status = lot["status"]
    if action == "FLAG":
        if status != "AVAILABLE":
            raise ApiError("ERR_LOT_STATE_INVALID",
                           "A lot in %s cannot be flagged." % status)
        lot["status"] = "EXCURSION_HOLD"
        lot["excursion_flagged_by_user_id"] = g.user_id
        touch(lot)
        return ok(lot)

    if action == "RELEASE":
        if status != "EXCURSION_HOLD":
            raise ApiError("ERR_LOT_STATE_INVALID",
                           "A lot in %s cannot be released." % status)
        if lot["excursion_flagged_by_user_id"] is not None and \
                str(lot["excursion_flagged_by_user_id"]) == str(g.user_id):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The operator who flagged the excursion may not release it.")
        lot["status"] = "AVAILABLE"
        lot["excursion_flagged_by_user_id"] = None
        touch(lot)
        return ok(lot)

    # DESTROY
    if status not in ("EXCURSION_HOLD", "QUARANTINED"):
        raise ApiError("ERR_LOT_STATE_INVALID",
                       "A lot in %s cannot be destroyed." % status)
    was_hold = status == "EXCURSION_HOLD"
    lot["status"] = "DESTROYED"
    lot["quantity_on_hand"] = 0
    if was_hold:
        lot["excursion_flagged_by_user_id"] = None
    touch(lot)
    return ok(lot)
