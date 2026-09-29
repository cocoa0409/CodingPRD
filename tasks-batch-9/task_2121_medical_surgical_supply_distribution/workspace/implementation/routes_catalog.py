"""Supply rooms, item master, GPO contracts and contract lines."""
from flask import Blueprint, g

from auth import ALL_ROLES, endpoint
from db import (
    by_creation,
    clock_now,
    iso_ms,
    new_entity,
    parse_iso,
    store,
    touch,
)
from errors import ApiError, validation_error
from response import ok, ok_list
from services import (
    activate_contract_lines,
    block_contract_lines,
    check_contract_overlap,
    contract_lines_of,
)
from validation import (
    CONTRACT_STATUSES,
    CONTRACT_TARGET_STATUSES,
    ACTIVATION_STATES,
    HANDLING_CLASSES,
    ITEM_STATUSES,
    LICENSE_STATUSES,
    MEMBER_CLASSES,
    ROOM_TYPES,
    TIERS,
    UOMS,
    get_body,
    opt_bool,
    opt_enum,
    opt_id,
    opt_int,
    opt_str,
    pagination,
    query_enum,
    query_str,
    req_datetime,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# SupplyRoom
# ---------------------------------------------------------------------------
@bp.route("/supply-rooms", methods=["POST"])
@endpoint(["ContractAdmin"])
def create_supply_room():
    body = get_body()
    facility_code = req_str(body, "facility_code")
    room_code = req_str(body, "room_code", min_len=1, max_len=40)
    gpo_member_class = req_enum(body, "gpo_member_class", MEMBER_CLASSES)
    room_type = req_enum(body, "room_type", ROOM_TYPES)
    refrigerated = opt_bool(body, "refrigerated", False)
    controlled_secured = opt_bool(body, "controlled_secured", False)
    controlled_license_status = opt_enum(
        body, "controlled_license_status", LICENSE_STATUSES, "NONE")
    window_open_min = opt_int(body, "window_open_min", 360)
    window_close_min = opt_int(body, "window_close_min", 1080)
    credit_limit_cents = opt_int(body, "credit_limit_cents", 100000000)
    if window_open_min < 0:
        raise validation_error("'window_open_min' must be >= 0.")
    if window_close_min > 1439:
        raise validation_error("'window_close_min' must be <= 1439.")
    if window_open_min >= window_close_min:
        raise validation_error("'window_open_min' must be strictly below 'window_close_min'.")
    if credit_limit_cents < 0:
        raise validation_error("'credit_limit_cents' must be >= 0.")

    for existing in store.supply_rooms.values():
        if existing["room_code"] == room_code:
            raise ApiError("ERR_DUPLICATE_ROOM_CODE",
                           "room_code '%s' already exists." % room_code)

    room = new_entity({
        "facility_code": facility_code,
        "room_code": room_code,
        "gpo_member_class": gpo_member_class,
        "room_type": room_type,
        "refrigerated": refrigerated,
        "controlled_secured": controlled_secured,
        "controlled_license_status": controlled_license_status,
        "window_open_min": window_open_min,
        "window_close_min": window_close_min,
        "credit_limit_cents": credit_limit_cents,
        "open_commitment_cents": 0,
    })
    store.supply_rooms[room["id"]] = room
    return ok(room, 201)


@bp.route("/supply-rooms/<supply_room_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_supply_room(supply_room_id):
    room = store.supply_rooms.get(supply_room_id)
    if room is None:
        raise ApiError("ERR_SUPPLY_ROOM_NOT_FOUND",
                       "Supply room %s does not exist." % supply_room_id)
    return ok(room)


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------
@bp.route("/items", methods=["POST"])
@endpoint(["ContractAdmin"])
def create_item():
    body = get_body()
    sku = req_str(body, "sku")
    description = req_str(body, "description", allow_empty=True)
    manufacturer_code = req_str(body, "manufacturer_code")
    uom = req_enum(body, "uom", UOMS)
    wac_cents = req_int(body, "wac_cents", minimum=1)
    handling_class = req_enum(body, "handling_class", HANDLING_CLASSES)
    units_per_parent = opt_int(body, "units_per_parent", 1, minimum=1)
    lum_parent_item_id = opt_id(body, "lum_parent_item_id", None)
    is_lot_tracked = opt_bool(body, "is_lot_tracked", True)
    status = opt_enum(body, "status", ITEM_STATUSES, "ACTIVE")

    if lum_parent_item_id is not None and lum_parent_item_id not in store.items:
        raise ApiError("ERR_ITEM_NOT_FOUND",
                       "Item %s does not exist." % lum_parent_item_id)

    for existing in store.items.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU", "sku '%s' already exists." % sku)

    item = new_entity({
        "sku": sku,
        "description": description,
        "manufacturer_code": manufacturer_code,
        "uom": uom,
        "units_per_parent": units_per_parent,
        "lum_parent_item_id": lum_parent_item_id,
        "handling_class": handling_class,
        "wac_cents": wac_cents,
        "is_lot_tracked": is_lot_tracked,
        "status": status,
    })
    store.items[item["id"]] = item
    return ok(item, 201)


@bp.route("/items/<item_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_item(item_id):
    item = store.items.get(item_id)
    if item is None:
        raise ApiError("ERR_ITEM_NOT_FOUND", "Item %s does not exist." % item_id)
    return ok(item)


@bp.route("/items", methods=["GET"])
@endpoint(ALL_ROLES)
def list_items():
    limit, offset = pagination()
    lum_parent_item_id = query_str("lum_parent_item_id")
    manufacturer_code = query_str("manufacturer_code")
    handling_class = query_enum("handling_class", HANDLING_CLASSES)
    status = query_enum("status", ITEM_STATUSES)
    rows = []
    for item in store.items.values():
        if lum_parent_item_id is not None and item["lum_parent_item_id"] != lum_parent_item_id:
            continue
        if manufacturer_code is not None and item["manufacturer_code"] != manufacturer_code:
            continue
        if handling_class is not None and item["handling_class"] != handling_class:
            continue
        if status is not None and item["status"] != status:
            continue
        rows.append(item)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


# ---------------------------------------------------------------------------
# GpoContract
# ---------------------------------------------------------------------------
@bp.route("/contracts", methods=["POST"])
@endpoint(["ContractAdmin"])
def create_contract():
    body = get_body()
    manufacturer_code = req_str(body, "manufacturer_code")
    contract_code = req_str(body, "contract_code")
    tier = req_enum(body, "tier", TIERS)
    member_class_scope = req_enum(body, "member_class_scope", MEMBER_CLASSES)
    effective_from_raw, effective_from = req_datetime(body, "effective_from")
    effective_to_raw, effective_to = req_datetime(body, "effective_to")
    committed_volume_units = opt_int(body, "committed_volume_units", 0, minimum=0)
    supersedes_contract_id = opt_id(body, "supersedes_contract_id", None)
    if not (effective_to > effective_from):
        raise validation_error("'effective_to' must be strictly after 'effective_from'.")

    if supersedes_contract_id is not None and supersedes_contract_id not in store.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND",
                       "Contract %s does not exist." % supersedes_contract_id)

    for existing in store.contracts.values():
        if existing["contract_code"] == contract_code:
            raise ApiError("ERR_DUPLICATE_CONTRACT_CODE",
                           "contract_code '%s' already exists." % contract_code)

    contract = new_entity({
        "manufacturer_code": manufacturer_code,
        "contract_code": contract_code,
        "tier": tier,
        "member_class_scope": member_class_scope,
        "committed_volume_units": committed_volume_units,
        "effective_from": effective_from_raw,
        "effective_to": effective_to_raw,
        "supersedes_contract_id": supersedes_contract_id,
        "status": "DRAFT",
        "activated_at": None,
        "chargeback_payable_cents": 0,
    })
    store.contracts[contract["id"]] = contract
    return ok(contract, 201)


@bp.route("/contracts/<contract_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_contract(contract_id):
    contract = store.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND",
                       "Contract %s does not exist." % contract_id)
    return ok(contract)


@bp.route("/contracts", methods=["GET"])
@endpoint(ALL_ROLES)
def list_contracts():
    limit, offset = pagination()
    supersedes_contract_id = query_str("supersedes_contract_id")
    manufacturer_code = query_str("manufacturer_code")
    status = query_enum("status", CONTRACT_STATUSES)
    rows = []
    for contract in store.contracts.values():
        if supersedes_contract_id is not None and contract["supersedes_contract_id"] != supersedes_contract_id:
            continue
        if manufacturer_code is not None and contract["manufacturer_code"] != manufacturer_code:
            continue
        if status is not None and contract["status"] != status:
            continue
        rows.append(contract)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.route("/contracts/<contract_id>/transition", methods=["POST"])
@endpoint(["ContractAdmin"])
def transition_contract(contract_id):
    body = get_body()
    to_status = req_enum(body, "to_status", CONTRACT_TARGET_STATUSES)

    contract = store.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND",
                       "Contract %s does not exist." % contract_id)

    current = contract["status"]
    now = clock_now()

    def invalid(reason):
        return ApiError("ERR_CONTRACT_TRANSITION_INVALID", reason)

    if to_status == "PENDING_ACTIVATION":
        if current != "DRAFT":
            raise invalid("PENDING_ACTIVATION is only reachable from DRAFT.")
        if not contract_lines_of(contract_id):
            raise invalid("A contract needs at least one price line before activation is pending.")
        contract["status"] = "PENDING_ACTIVATION"
        touch(contract)
        return ok(contract)

    if to_status == "ACTIVE":
        if current not in ("PENDING_ACTIVATION", "SUSPENDED"):
            raise invalid("ACTIVE is only reachable from PENDING_ACTIVATION or SUSPENDED.")
        eff_from = parse_iso(contract["effective_from"])
        eff_to = parse_iso(contract["effective_to"])
        if not (eff_from <= now <= eff_to):
            raise invalid("The logical clock lies outside the contract's effective period.")
        check_contract_overlap(contract)
        contract["status"] = "ACTIVE"
        contract["activated_at"] = iso_ms(now)
        touch(contract)
        activate_contract_lines(contract)
        superseded_id = contract.get("supersedes_contract_id")
        if superseded_id:
            superseded = store.contracts.get(superseded_id)
            if superseded is not None and superseded["status"] == "ACTIVE":
                superseded["status"] = "SUPERSEDED"
                touch(superseded)
                block_contract_lines(superseded)
        return ok(contract)

    if to_status == "SUSPENDED":
        if current != "ACTIVE":
            raise invalid("SUSPENDED is only reachable from ACTIVE.")
        contract["status"] = "SUSPENDED"
        touch(contract)
        block_contract_lines(contract)
        return ok(contract)

    if to_status == "EXPIRED":
        if current != "ACTIVE":
            raise invalid("EXPIRED is only reachable from ACTIVE.")
        eff_to = parse_iso(contract["effective_to"])
        if not (now > eff_to):
            raise invalid("The contract cannot expire while the clock is at or before effective_to.")
        contract["status"] = "EXPIRED"
        touch(contract)
        block_contract_lines(contract)
        return ok(contract)

    raise invalid("Unsupported target status.")


# ---------------------------------------------------------------------------
# ContractLine
# ---------------------------------------------------------------------------
@bp.route("/contracts/<contract_id>/lines", methods=["POST"])
@endpoint(["ContractAdmin"])
def create_contract_line(contract_id):
    body = get_body()
    item_id = req_id(body, "item_id")
    tier_price_cents = req_int(body, "tier_price_cents", minimum=1)
    floor_price_cents = req_int(body, "floor_price_cents", minimum=1)
    chargeback_eligible = opt_bool(body, "chargeback_eligible", True)

    contract = store.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND",
                       "Contract %s does not exist." % contract_id)
    if item_id not in store.items:
        raise ApiError("ERR_ITEM_NOT_FOUND", "Item %s does not exist." % item_id)

    for existing in store.contract_lines.values():
        if existing["contract_id"] == contract_id and existing["item_id"] == item_id:
            raise ApiError("ERR_DUPLICATE_CONTRACT_LINE",
                           "This contract already prices item %s." % item_id)

    line = new_entity({
        "contract_id": contract_id,
        "item_id": item_id,
        "tier_price_cents": tier_price_cents,
        "floor_price_cents": floor_price_cents,
        "chargeback_eligible": chargeback_eligible,
        "activation_state": "PENDING",
    })
    store.contract_lines[line["id"]] = line
    return ok(line, 201)


@bp.route("/contract-lines/<contract_line_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_contract_line(contract_line_id):
    line = store.contract_lines.get(contract_line_id)
    if line is None:
        raise ApiError("ERR_CONTRACT_LINE_NOT_FOUND",
                       "Contract line %s does not exist." % contract_line_id)
    return ok(line)


@bp.route("/contract-lines", methods=["GET"])
@endpoint(ALL_ROLES)
def list_contract_lines():
    limit, offset = pagination()
    contract_id = query_str("contract_id")
    item_id = query_str("item_id")
    activation_state = query_enum("activation_state", ACTIVATION_STATES)
    rows = []
    for line in store.contract_lines.values():
        if contract_id is not None and line["contract_id"] != contract_id:
            continue
        if item_id is not None and line["item_id"] != item_id:
            continue
        if activation_state is not None and line["activation_state"] != activation_state:
            continue
        rows.append(line)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))
