"""Rider routes."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_RIDER_NOT_FOUND, ERR_DUPLICATE_PHONE, \
    ERR_INVALID_STATE, ERR_ACTIVE_DELIVERIES_EXIST, ERR_VERSION_CONFLICT
from middleware import require_roles
from response import success_response, list_response
from services.calculations import recalculate_cancellation_rate, add_penalty

bp = Blueprint("riders", __name__)


def _get_rider_or_404(rid):
    r = db.riders.get(rid)
    if not r:
        raise_error(ERR_RIDER_NOT_FOUND, "The referenced rider does not exist.")
    return r


def _paginate(request):
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return limit, offset


@bp.route("/platform/riders", methods=["POST"])
def create_rider():
    require_roles("platform_admin")
    body = req.get_json(force=True, silent=True) or {}
    phone = body.get("phone")
    for r in db.riders.values():
        if r["phone"] == phone:
            raise_error(ERR_DUPLICATE_PHONE, "Phone number is already registered among riders.")
    now = db.now_iso()
    r = {
        "id": db.new_id(),
        "name": body.get("name"),
        "phone": phone,
        "vehicle_type": body.get("vehicle_type"),
        "status": "PENDING_APPROVAL",
        "current_latitude": body.get("current_latitude"),
        "current_longitude": body.get("current_longitude"),
        "is_online": False,
        "active_delivery_count": 0,
        "max_concurrent_deliveries": body.get("max_concurrent_deliveries", 3),
        "is_at_capacity": False,
        "rating_average": 0.0,
        "rating_count": 0,
        "total_deliveries_completed": 0,
        "cancellation_count": 0,
        "cancellation_rate": 0.0,
        "earnings_balance_cents": 0,
        "earnings_settled_cents": 0,
        "penalty_points": 0,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.riders[r["id"]] = r
    return success_response(r, 201)


@bp.route("/platform/riders", methods=["GET"])
def list_riders():
    require_roles("platform_admin")
    limit, offset = _paginate(req)
    items = sorted(db.riders.values(), key=lambda x: x["created_at"])
    status_f = req.args.get("status")
    vt_f = req.args.get("vehicle_type")
    online_f = req.args.get("is_online")
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    if vt_f:
        items = [i for i in items if i["vehicle_type"] == vt_f]
    if online_f is not None:
        b = online_f.lower() == "true"
        items = [i for i in items if i["is_online"] == b]
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/riders/<rider_id>", methods=["GET"])
def get_rider(rider_id):
    require_roles("rider", "platform_admin")
    r = _get_rider_or_404(rider_id)
    return success_response(r)


@bp.route("/platform/riders/<rider_id>", methods=["PATCH"])
def update_rider(rider_id):
    require_roles("rider")
    r = _get_rider_or_404(rider_id)
    body = req.get_json(force=True, silent=True) or {}
    if "version" in body and body["version"] is not None:
        if body["version"] != r["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch.")
    for key in ("current_latitude", "current_longitude", "is_online", "max_concurrent_deliveries"):
        if key in body:
            r[key] = body[key]
    r["is_at_capacity"] = r["active_delivery_count"] >= r["max_concurrent_deliveries"]
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    return success_response(r)


@bp.route("/platform/riders/<rider_id>/approve", methods=["POST"])
def approve_rider(rider_id):
    require_roles("platform_admin")
    r = _get_rider_or_404(rider_id)
    if r["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_STATE, "Rider must be PENDING_APPROVAL.")
    r["status"] = "ACTIVE"
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    return success_response(r)


@bp.route("/platform/riders/<rider_id>/suspend", methods=["POST"])
def suspend_rider(rider_id):
    require_roles("platform_admin")
    r = _get_rider_or_404(rider_id)
    if r["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Rider must be ACTIVE to suspend.")
    r["status"] = "SUSPENDED"
    r["is_online"] = False
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    # cascade: cancel ASSIGNED deliveries
    for d in list(db.deliveries.values()):
        if d["rider_id"] == rider_id and d["status"] == "ASSIGNED":
            d["status"] = "CANCELLED_BY_RIDER"
            d["updated_at"] = db.now_iso()
            d["version"] += 1
            r["active_delivery_count"] = max(0, r["active_delivery_count"] - 1)
            r["cancellation_count"] += 1
            add_penalty(r, 15, "CANCELLATION", delivery_id=d["id"])
            # revert corresponding order
            order = db.orders.get(d["order_id"])
            if order and order["status"] in ("CONFIRMED", "PREPARING", "READY_FOR_PICKUP", "PICKED_UP"):
                order["status"] = "READY_FOR_PICKUP"
                order["updated_at"] = db.now_iso()
                order["version"] += 1
    r["is_at_capacity"] = r["active_delivery_count"] >= r["max_concurrent_deliveries"]
    recalculate_cancellation_rate(r)
    return success_response(r)


@bp.route("/platform/riders/<rider_id>/reinstate", methods=["POST"])
def reinstate_rider(rider_id):
    require_roles("platform_admin")
    r = _get_rider_or_404(rider_id)
    if r["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Rider must be SUSPENDED to reinstate.")
    r["status"] = "ACTIVE"
    r["penalty_points"] = 0
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    return success_response(r)


@bp.route("/platform/riders/<rider_id>/deactivate", methods=["POST"])
def deactivate_rider(rider_id):
    require_roles("platform_admin")
    r = _get_rider_or_404(rider_id)
    if r["status"] == "ACTIVE":
        if r["active_delivery_count"] > 0:
            raise_error(ERR_ACTIVE_DELIVERIES_EXIST, "Cannot deactivate rider while active deliveries exist.")
    elif r["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Rider must be ACTIVE or SUSPENDED to deactivate.")
    r["status"] = "DEACTIVATED"
    r["is_online"] = False
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    return success_response(r)
