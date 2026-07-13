from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    fetch_or_404, get_json_body, new_common_fields, paginate,
    parse_pagination, require_fields, require_type,
    sorted_by_created, strip_internal,
)
from middleware import require_role
from response import success_array, success_object
from timeutil import current_clock, parse_iso8601

bp = Blueprint("inventory_lots", __name__)

READ_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "MutualAidPartner"]


@bp.route("/inventory-lots", methods=["POST"])
@require_role("LogisticsCoordinator")
def create_inventory_lot():
    body = get_json_body()
    require_fields(body, ["countermeasure_id", "lot_number", "on_hand_quantity", "expiration_date"])
    fetch_or_404(db.countermeasures, body["countermeasure_id"], "Countermeasure")
    pod_id = body.get("pod_id")
    if pod_id is not None:
        fetch_or_404(db.pods, pod_id, "POD")

    require_type(body["on_hand_quantity"], int, "on_hand_quantity")
    require_type(body["expiration_date"], str, "expiration_date")
    try:
        expiration = parse_iso8601(body["expiration_date"])
    except ValueError:
        raise ApiError("ERR_INVALID_EXPIRATION", "expiration_date must be a valid ISO8601 timestamp.", 400)
    if body["on_hand_quantity"] < 0 or expiration <= current_clock():
        raise ApiError("ERR_INVALID_EXPIRATION", "on_hand_quantity must be >= 0 and expiration_date strictly after now.", 400)

    require_type(body["lot_number"], str, "lot_number")

    row = new_common_fields()
    row.update({
        "countermeasure_id": body["countermeasure_id"],
        "pod_id": pod_id,
        "lot_number": body["lot_number"],
        "on_hand_quantity": body["on_hand_quantity"],
        "reserved_quantity": 0,
        "available_quantity": body["on_hand_quantity"],
        "expiration_date": body["expiration_date"],
    })
    db.inventory_lots[row["id"]] = row
    return success_object(strip_internal(row), 201)


@bp.route("/inventory-lots/<lot_id>", methods=["GET"])
@require_role(*READ_ROLES)
def get_inventory_lot(lot_id):
    row = fetch_or_404(db.inventory_lots, lot_id, "InventoryLot")
    return success_object(strip_internal(row))


@bp.route("/inventory-lots", methods=["GET"])
@require_role(*READ_ROLES)
def list_inventory_lots():
    limit, offset = parse_pagination(request.args)
    countermeasure_id = request.args.get("countermeasure_id")
    pod_id = request.args.get("pod_id")
    rows = list(db.inventory_lots.values())
    if countermeasure_id:
        rows = [r for r in rows if r["countermeasure_id"] == countermeasure_id]
    if pod_id:
        rows = [r for r in rows if r["pod_id"] == pod_id]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)
