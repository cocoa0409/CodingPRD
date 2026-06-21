"""Asset and TransferOrder routes (PRD §3.2, §3.3)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles, get_json_body
from response import object_response, array_response
from services import core

bp = Blueprint("assets", __name__)


# ---------------------------------------------------------------------------
# Asset (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/assets", methods=["POST"])
def mint_asset():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10): body FKs left-to-right.
    core.resolve_body_fk(body, "asset_type_id", db.asset_types)
    core.resolve_body_fk(body, "current_location_id", db.locations)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["asset_type_id", "serial", "in_service_at", "current_location_id"])
    asset_type_id = core.require_str(body, "asset_type_id")
    serial = core.require_str(body, "serial")
    in_service_at = core.require_datetime(body, "in_service_at")
    current_location_id = core.require_str(body, "current_location_id")

    at = db.asset_types[asset_type_id]
    loc = db.locations[current_location_id]

    # DISCONTINUED type blocks new asset (PRD §3.2) -> ERR_ASSET_TYPE_DISCONTINUED.
    if at["status"] == "DISCONTINUED":
        raise err("ERR_ASSET_TYPE_DISCONTINUED",
                  "Cannot mint an asset of a DISCONTINUED asset type")

    # serial unique within asset_type_id (PRD §3.2) -> ERR_DUPLICATE_RESOURCE.
    for a in db.assets.values():
        if a["asset_type_id"] == asset_type_id and a["serial"] == serial:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "Serial already exists for this asset type")

    from db import iso
    asset = core.stamp_new({
        "asset_type_id": asset_type_id,
        "serial": serial,
        "in_service_at": iso(in_service_at),
        "current_location_id": current_location_id,
        "current_hire_id": None,
        "condition": "AVAILABLE",
    })
    db.assets[asset["id"]] = asset
    # Minting increments holding location's physical_balance (recompute) (PRD §3.2).
    core.recompute_location_derived(loc)
    core.touch(loc)
    return object_response(core.public(asset), 201)


@bp.route("/assets/<asset_id>", methods=["GET"])
def get_asset(asset_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    asset = core.require(db.assets, asset_id)
    return object_response(core.public(asset), 200)


@bp.route("/assets", methods=["GET"])
def list_assets():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.assets.values())
    for field in ("asset_type_id", "current_location_id", "current_hire_id", "condition"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


@bp.route("/assets/<asset_id>/report-damage", methods=["POST"])
def report_damage(asset_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    asset = core.require(db.assets, asset_id)
    # Records DAMAGED condition (PRD §3.2/§3.3). Reachable from ON_HIRE/AVAILABLE.
    was_on_hire = asset["condition"] == "ON_HIRE"
    hire_id = asset["current_hire_id"]
    asset["condition"] = "DAMAGED"
    # If on an OPEN hire, remove from hire occupancy and record damage day for
    # chronological replay (PRD §3.2, §3.4).
    if was_on_hire and hire_id is not None:
        hire = db.hires.get(hire_id)
        if hire is not None and hire["lifecycle_status"] == "OPEN":
            hire.setdefault("_damage_at", {})[asset_id] = db.iso_clock()
        asset["current_hire_id"] = None
    core.touch(asset)
    # Recompute owning account outstanding for any affected open hire.
    if hire_id is not None:
        hire = db.hires.get(hire_id)
        if hire is not None:
            acc = db.accounts.get(hire["account_id"])
            if acc is not None:
                core.recompute_account_outstanding(acc)
    return object_response(core.public(asset), 200)


# ---------------------------------------------------------------------------
# TransferOrder (PRD §3.3)
# ---------------------------------------------------------------------------
@bp.route("/transfer-orders", methods=["POST"])
def create_transfer_order():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10): body FKs left-to-right.
    core.resolve_body_fk(body, "from_location_id", db.locations)
    core.resolve_body_fk(body, "to_location_id", db.locations)
    core.resolve_body_fk_list(body, "asset_ids", db.assets)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["from_location_id", "to_location_id", "kind", "asset_ids"])
    from_location_id = core.require_str(body, "from_location_id")
    to_location_id = core.require_str(body, "to_location_id")
    kind = core.require_enum(body, "kind", {"ISSUANCE", "RETURN", "TRANSFER"})
    # transfer-orders permit an empty asset_ids (PRD §2.10).
    asset_ids = core.require_id_list(body, "asset_ids", allow_empty=True)

    order = core.stamp_new({
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "kind": kind,
        "asset_ids": list(asset_ids),
        "quantity": len(asset_ids),
        "dispatched_at": None,
        "received_at": None,
        "status": "DRAFT",
    })
    db.transfer_orders[order["id"]] = order
    return object_response(core.public(order), 201)


@bp.route("/transfer-orders/<transfer_order_id>", methods=["GET"])
def get_transfer_order(transfer_order_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    order = core.require(db.transfer_orders, transfer_order_id)
    return object_response(core.public(order), 200)


@bp.route("/transfer-orders", methods=["GET"])
def list_transfer_orders():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.transfer_orders.values())
    for field in ("from_location_id", "to_location_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [o for o in items if o[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


@bp.route("/transfer-orders/<transfer_order_id>/dispatch", methods=["POST"])
def dispatch_transfer_order(transfer_order_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    order = core.require(db.transfer_orders, transfer_order_id)
    # DRAFT -> DISPATCHED (PRD §3.3).
    if order["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Transfer order is not DRAFT")
    from_loc = db.locations[order["from_location_id"]]
    # Origin must be OPEN (PRD §3.3) -> ERR_LOCATION_CLOSED.
    if from_loc["status"] != "OPEN":
        raise err("ERR_LOCATION_CLOSED", "Origin location is not OPEN")
    # Every manifest asset AVAILABLE at origin (PRD §3.3).
    for aid in order["asset_ids"]:
        a = db.assets[aid]
        if a["condition"] != "AVAILABLE":
            raise err("ERR_ASSET_NOT_AVAILABLE", "Asset %s is not AVAILABLE" % aid)
        if a["current_location_id"] != order["from_location_id"]:
            raise err("ERR_ASSET_WRONG_LOCATION",
                      "Asset %s is not at the origin location" % aid)
    # Commit (atomic — all preconditions passed) (PRD §2.6).
    for aid in order["asset_ids"]:
        a = db.assets[aid]
        a["condition"] = "IN_TRANSIT"
        a["current_location_id"] = None
        core.touch(a)
    order["status"] = "DISPATCHED"
    order["dispatched_at"] = db.iso_clock()
    core.touch(order)
    # Origin physical_balance drops by quantity (recompute) (PRD §3.3).
    core.recompute_location_derived(from_loc)
    core.touch(from_loc)
    return object_response(core.public(order), 200)


@bp.route("/transfer-orders/<transfer_order_id>/receive", methods=["POST"])
def receive_transfer_order(transfer_order_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    order = core.require(db.transfer_orders, transfer_order_id)
    # DISPATCHED -> RECEIVED (PRD §3.3).
    if order["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Transfer order is not DISPATCHED")
    to_loc = db.locations[order["to_location_id"]]
    from_loc = db.locations[order["from_location_id"]]
    # Destination must be OPEN (PRD §3.3) -> ERR_LOCATION_CLOSED.
    if to_loc["status"] != "OPEN":
        raise err("ERR_LOCATION_CLOSED", "Destination location is not OPEN")

    quantity = order["quantity"]
    for aid in order["asset_ids"]:
        a = db.assets[aid]
        a["condition"] = "AVAILABLE"
        a["current_location_id"] = order["to_location_id"]
        core.touch(a)
    order["status"] = "RECEIVED"
    order["received_at"] = db.iso_clock()
    core.touch(order)

    # Equity movement keyed by kind (PRD §3.3).
    kind = order["kind"]
    if kind == "ISSUANCE":
        to_loc["equity_balance"] += quantity
    elif kind == "RETURN":
        from_loc["equity_balance"] -= quantity
    elif kind == "TRANSFER":
        from_loc["equity_balance"] -= quantity
        to_loc["equity_balance"] += quantity

    # Recompute physical_balance and equity_status on every touched location.
    core.recompute_location_derived(to_loc)
    core.touch(to_loc)
    if from_loc["id"] != to_loc["id"]:
        core.recompute_location_derived(from_loc)
        core.touch(from_loc)
    return object_response(core.public(order), 200)


@bp.route("/transfer-orders/<transfer_order_id>/cancel", methods=["POST"])
def cancel_transfer_order(transfer_order_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    order = core.require(db.transfer_orders, transfer_order_id)
    # DRAFT -> CANCELLED (PRD §3.3).
    if order["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT transfer order can be cancelled")
    order["status"] = "CANCELLED"
    core.touch(order)
    return object_response(core.public(order), 200)
