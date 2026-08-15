"""StockingOrder and StockingDrop endpoints."""
from datetime import date, timedelta
from flask import Blueprint, request
from db import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_ACCOUNT_SUSPENDED, ERR_INVALID_STATE,
    ERR_TAKEOFF_NOT_LOCKED, ERR_PROJECT_NOT_STOCKING_OPEN, ERR_TRUCK_INACTIVE,
    ERR_EMPTY_ORDER, ERR_CAPACITY_EXCEEDED, ERR_WEIGHT_EXCEEDED,
    ERR_SHIFT_DOUBLE_BOOKED, ERR_LEAD_TIME_VIOLATION, ERR_NOT_DISPATCH_DAY,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.helpers import (
    parse_pagination, paginate, body, require_fields, require_int, require_str,
    require_enum, new_common_fields, touch,
)
from services.calc import freight_tier_cents, sheet_weight_lbs, RATED_KINDS

bp = Blueprint("orders", __name__)


def _get_order_or_404(oid):
    o = db.stocking_orders.get(oid)
    if o is None:
        raise ApiError(ERR_NOT_FOUND, "StockingOrder not found", 404)
    return o


def _get_drop_or_404(did):
    d = db.stocking_drops.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, "StockingDrop not found", 404)
    return d


def _order_drops(order_id):
    return [d for d in db.stocking_drops.values() if d["stocking_order_id"] == order_id]


@bp.route("/supply/stocking-orders", methods=["POST"])
def create_order():
    require_roles("DispatcherUser")
    b = body()
    require_fields(b, "project_id", "takeoff_id", "scheduled_date", "shift_window", "boom_truck_id")
    project_id = b["project_id"]
    takeoff_id = b["takeoff_id"]
    boom_truck_id = b["boom_truck_id"]
    if not isinstance(project_id, str):
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    project = db.projects.get(project_id)
    if project is None:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    if not isinstance(takeoff_id, str):
        raise ApiError(ERR_NOT_FOUND, "Takeoff not found", 404)
    takeoff = db.takeoffs.get(takeoff_id)
    if takeoff is None:
        raise ApiError(ERR_NOT_FOUND, "Takeoff not found", 404)
    if not isinstance(boom_truck_id, str):
        raise ApiError(ERR_NOT_FOUND, "BoomTruck not found", 404)
    truck = db.boom_trucks.get(boom_truck_id)
    if truck is None:
        raise ApiError(ERR_NOT_FOUND, "BoomTruck not found", 404)
    scheduled_date = require_str(b, "scheduled_date")
    # Validate YYYY-MM-DD
    try:
        date.fromisoformat(scheduled_date)
    except Exception:
        raise ApiError(ERR_VALIDATION, "scheduled_date must be an ISO 8601 date (YYYY-MM-DD)", 400)
    shift_window = require_enum(b, "shift_window", {"AM", "PM"})
    account = db.contractor_accounts.get(project["account_id"])
    if account is None:
        raise ApiError(ERR_NOT_FOUND, "ContractorAccount not found", 404)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account is not ACTIVE", 409)
    order = new_common_fields()
    order.update({
        "project_id": project_id,
        "takeoff_id": takeoff_id,
        "scheduled_date": scheduled_date,
        "shift_window": shift_window,
        "boom_truck_id": boom_truck_id,
        "freight_charge_cents": 0,
        "status": "DRAFT",
        "stocked_at": None,
    })
    db.stocking_orders[order["id"]] = order
    return success(order, status=201)


@bp.route("/supply/stocking-orders/<oid>", methods=["GET"])
def get_order(oid):
    require_roles("DispatcherUser", "Foreman", "CreditManager", "WarehouseManager", "AccountsReceivableUser")
    return success(_get_order_or_404(oid))


@bp.route("/supply/stocking-orders", methods=["GET"])
def list_orders():
    require_roles("DispatcherUser", "Foreman", "CreditManager", "WarehouseManager", "AccountsReceivableUser")
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    boom_truck_id = request.args.get("boom_truck_id")
    scheduled_date = request.args.get("scheduled_date")
    status = request.args.get("status")
    takeoff_id = request.args.get("takeoff_id")
    items = list(db.stocking_orders.values())
    if project_id is not None:
        items = [o for o in items if o["project_id"] == project_id]
    if boom_truck_id is not None:
        items = [o for o in items if o["boom_truck_id"] == boom_truck_id]
    if scheduled_date is not None:
        items = [o for o in items if o["scheduled_date"] == scheduled_date]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if takeoff_id is not None:
        items = [o for o in items if o["takeoff_id"] == takeoff_id]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/stocking-orders/<oid>/drops", methods=["POST"])
def add_drop(oid):
    require_roles("DispatcherUser")
    order = _get_order_or_404(oid)
    b = body()
    require_fields(b, "floor_label", "room_label", "product_id", "bundle_count")
    floor_label = require_str(b, "floor_label")
    room_label = require_str(b, "room_label")
    product_id = b["product_id"]
    if not isinstance(product_id, str):
        raise ApiError(ERR_NOT_FOUND, "Product not found", 404)
    product = db.products.get(product_id)
    if product is None:
        raise ApiError(ERR_NOT_FOUND, "Product not found", 404)
    bundle_count = require_int(b, "bundle_count", min_val=1)
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Drops can only be added to a DRAFT stocking order", 409)
    weight = sheet_weight_lbs(bundle_count, product["sheets_per_bundle"], product["thickness_in"])
    drop = new_common_fields()
    drop.update({
        "stocking_order_id": oid,
        "floor_label": floor_label,
        "room_label": room_label,
        "product_id": product_id,
        "bundle_count": bundle_count,
        "sheet_weight_lbs": weight,
    })
    db.stocking_drops[drop["id"]] = drop
    return success(drop, status=201)


@bp.route("/supply/stocking-orders/<oid>/drops", methods=["GET"])
def list_order_drops(oid):
    require_roles("DispatcherUser", "Foreman", "WarehouseManager")
    _get_order_or_404(oid)
    limit, offset = parse_pagination()
    items = _order_drops(oid)
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/stocking-drops", methods=["GET"])
def list_drops():
    require_roles("DispatcherUser", "Foreman", "WarehouseManager")
    limit, offset = parse_pagination()
    order_id = request.args.get("stocking_order_id")
    product_id = request.args.get("product_id")
    items = list(db.stocking_drops.values())
    if order_id is not None:
        items = [d for d in items if d["stocking_order_id"] == order_id]
    if product_id is not None:
        items = [d for d in items if d["product_id"] == product_id]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/stocking-drops/<did>", methods=["GET"])
def get_drop(did):
    require_roles("DispatcherUser", "Foreman", "WarehouseManager")
    return success(_get_drop_or_404(did))


@bp.route("/supply/stocking-orders/<oid>/schedule", methods=["POST"])
def schedule_order(oid):
    require_roles("DispatcherUser")
    order = _get_order_or_404(oid)
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Order must be DRAFT to schedule", 409)

    project = db.projects.get(order["project_id"])
    if project is None:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    if project["status"] != "STOCKING_OPEN":
        raise ApiError(ERR_PROJECT_NOT_STOCKING_OPEN, "Project must be STOCKING_OPEN", 409)

    takeoff = db.takeoffs.get(order["takeoff_id"])
    if takeoff is None:
        raise ApiError(ERR_NOT_FOUND, "Takeoff not found", 404)
    if takeoff["status"] != "LOCKED" or takeoff["project_id"] != order["project_id"]:
        raise ApiError(ERR_TAKEOFF_NOT_LOCKED, "Referenced takeoff must be LOCKED on the same project", 409)

    # Priority per PRD 2.8 on scheduling path:
    # 1) TAKEOFF_NOT_LOCKED (done)
    # 2) LEAD_TIME_VIOLATION
    # 3) SHIFT_DOUBLE_BOOKED
    # 4) CAPACITY_EXCEEDED
    # 5) WEIGHT_EXCEEDED
    # 6) EMPTY_ORDER
    # 7) TRUCK_INACTIVE

    drops = _order_drops(oid)

    # Lead time check (applies across drops' products)
    today = db.clock.today()
    try:
        sched = date.fromisoformat(order["scheduled_date"])
    except Exception:
        raise ApiError(ERR_VALIDATION, "scheduled_date must be YYYY-MM-DD", 400)
    max_lead = 0
    for d in drops:
        p = db.products.get(d["product_id"])
        if p and p["board_kind"] in RATED_KINDS:
            if p["lead_time_days"] > max_lead:
                max_lead = p["lead_time_days"]
    earliest = today + timedelta(days=max_lead)
    if sched < earliest:
        raise ApiError(ERR_LEAD_TIME_VIOLATION, "scheduled_date violates lead-time requirement", 422)

    # Shift double-booked
    for other in db.stocking_orders.values():
        if other["id"] == oid:
            continue
        if other["status"] in ("SCHEDULED", "DISPATCHED"):
            if (
                other["boom_truck_id"] == order["boom_truck_id"]
                and other["scheduled_date"] == order["scheduled_date"]
                and other["shift_window"] == order["shift_window"]
            ):
                raise ApiError(ERR_SHIFT_DOUBLE_BOOKED, "Truck shift slot already reserved", 409)

    # Capacity / weight
    total_bundles = sum(d["bundle_count"] for d in drops)
    total_weight = sum(d["sheet_weight_lbs"] for d in drops)
    truck = db.boom_trucks.get(order["boom_truck_id"])
    if truck is None:
        raise ApiError(ERR_NOT_FOUND, "BoomTruck not found", 404)
    if total_bundles > truck["max_bundle_capacity"]:
        raise ApiError(ERR_CAPACITY_EXCEEDED, "Total bundles exceed boom-truck capacity", 422)
    if total_weight > truck["max_weight_lbs"]:
        raise ApiError(ERR_WEIGHT_EXCEEDED, "Total weight exceeds boom-truck capacity", 422)

    # Empty order
    if not drops:
        raise ApiError(ERR_EMPTY_ORDER, "Order has no drops", 422)

    # Truck active
    if not truck["active"]:
        raise ApiError(ERR_TRUCK_INACTIVE, "BoomTruck is inactive", 422)

    # Provisional freight (no fuel surcharge)
    order["freight_charge_cents"] = freight_tier_cents(project["distance_miles"], final=False)
    order["status"] = "SCHEDULED"
    touch(order)
    return success(order)


@bp.route("/supply/stocking-orders/<oid>/dispatch", methods=["POST"])
def dispatch_order(oid):
    require_roles("DispatcherUser")
    order = _get_order_or_404(oid)
    if order["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Order must be SCHEDULED to dispatch", 409)
    today = db.clock.today().isoformat()
    if order["scheduled_date"] != today:
        raise ApiError(ERR_NOT_DISPATCH_DAY, "Dispatch is only allowed on the scheduled_date", 409)
    project = db.projects.get(order["project_id"])
    if project is None:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    if project["status"] != "STOCKING_OPEN":
        raise ApiError(ERR_PROJECT_NOT_STOCKING_OPEN, "Project must be STOCKING_OPEN", 409)
    # Final freight with fuel surcharge
    order["freight_charge_cents"] = freight_tier_cents(project["distance_miles"], final=True)
    order["status"] = "DISPATCHED"
    touch(order)
    return success(order)


@bp.route("/supply/stocking-orders/<oid>/mark-stocked", methods=["POST"])
def mark_stocked(oid):
    require_roles("Foreman")
    order = _get_order_or_404(oid)
    if order["status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, "Order must be DISPATCHED to mark stocked", 409)
    project = db.projects.get(order["project_id"])
    if project is None:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    account = db.contractor_accounts.get(project["account_id"])
    if account is None:
        raise ApiError(ERR_NOT_FOUND, "ContractorAccount not found", 404)

    order["status"] = "STOCKED"
    order["stocked_at"] = db.clock.iso()
    touch(order)

    # Auto-issue DrawRequest
    takeoff_id = order["takeoff_id"]
    order_skus = {d["product_id"] for d in _order_drops(oid)}
    material_cents = 0
    for l in db.takeoff_lines.values():
        if (
            l["takeoff_id"] == takeoff_id
            and l["line_status"] == "ACTIVE"
            and l["product_id"] in order_skus
        ):
            material_cents += l.get("final_line_cents") or 0
    requested_cents = material_cents + order["freight_charge_cents"]

    draw = new_common_fields()
    draw.update({
        "project_id": order["project_id"],
        "stocking_order_id": oid,
        "requested_cents": requested_cents,
        "status": "ISSUED",
        "paid_cents": 0,
    })
    db.draw_requests[draw["id"]] = draw

    account["ar_outstanding_cents"] = account["ar_outstanding_cents"] + requested_cents
    touch(account)
    if account["ar_outstanding_cents"] > account["credit_limit_cents"]:
        if account["status"] == "ACTIVE":
            account["status"] = "SUSPENDED"
            touch(account)

    return success(order)


@bp.route("/supply/stocking-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    require_roles("DispatcherUser")
    order = _get_order_or_404(oid)
    if order["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError(ERR_INVALID_STATE, "Order cannot be cancelled from its current state", 409)
    order["status"] = "CANCELLED"
    touch(order)
    return success(order)
