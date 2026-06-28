"""CycleCount endpoints with OCC (PRD §2.10, §3.10)."""
from flask import Blueprint, request

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import (
    get_client, get_lot, get_cycle_count,
    get_json_body, parse_pagination, paginate,
)
from serializers import serialize_cycle_count

bp = Blueprint("cycle_counts", __name__)

READ_ROLES = {"ReceivingClerk", "BillingClerk"}


@bp.route("/clients/<client_id>/cycle-counts", methods=["POST"])
def apply_cycle_count(client_id):
    _, role = get_auth()
    require_roles(role, {"ReceivingClerk"})
    get_client(client_id)
    body = get_json_body()

    lot_id = body.get("lot_id")
    if not isinstance(lot_id, str) or lot_id == "":
        raise err("ERR_INVALID_REQUEST", "lot_id is required")

    expected_version = body.get("expected_lot_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_lot_version must be an integer")

    counted_qty = body.get("counted_qty")
    if isinstance(counted_qty, bool) or not isinstance(counted_qty, int):
        raise err("ERR_INVALID_REQUEST", "counted_qty must be an integer")
    if counted_qty < 0:
        raise err("ERR_INVALID_REQUEST", "counted_qty must be >= 0")

    # Existence of FK lot.
    lot = get_lot(lot_id)

    # OCC: expected_lot_version must equal the live lot version (runs first, §3.10).
    if expected_version != lot["version"]:
        raise err("ERR_STALE_LOT_VERSION", "Stale InventoryLot version")

    # Cross-ownership: the lot must belong to the path client.
    if lot["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Lot not owned by path client")

    # Apply the correction, conserving reserved units (PRD §3.10).
    on_hand_before = lot["on_hand_qty"]
    variance = counted_qty - on_hand_before

    lot["on_hand_qty"] = counted_qty
    if counted_qty < lot["reserved_qty"]:
        # Silent clamp: reserved down to counted, available floors at 0.
        lot["reserved_qty"] = counted_qty
    # available_qty is derived as on_hand - reserved = max(0, counted - reserved).
    touch(lot)

    # Cascade: owning bin occupied_cc recomputed -> bump bin version.
    bin_rec = store.bins.get(lot["bin_id"])
    if bin_rec is not None:
        touch(bin_rec)

    rec = stamp_create({
        "id": new_id(),
        "lot_id": lot_id,
        "expected_lot_version": expected_version,
        "counted_qty": counted_qty,
        "variance_qty": variance,
        "status": "APPLIED",
    })
    store.cycle_counts[rec["id"]] = rec
    return success(serialize_cycle_count(rec), status=201)


@bp.route("/cycle-counts", methods=["GET"])
def list_cycle_counts():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.cycle_counts.values())
    lot_id = request.args.get("lot_id")
    if lot_id is not None:
        items = [c for c in items if c["lot_id"] == lot_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize_cycle_count(r) for r in page], pagination=meta)


@bp.route("/cycle-counts/<cycle_count_id>", methods=["GET"])
def get_one_cycle_count(cycle_count_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_cycle_count(cycle_count_id)
    return success(serialize_cycle_count(rec))
