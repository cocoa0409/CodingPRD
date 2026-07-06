"""Orders: checkout, pay, dispatch, cancel; order-lines list/read."""
from flask import Blueprint, request
from clock import iso_now, parse_iso, get_now
from db import DB
from errors import (
    not_found, invalid_request, invalid_state, stale_version, unauthorized,
    ApiError, ERR_STOCK_UNAVAILABLE, ERR_DELIVERY_OUT_OF_ZONE,
    ERR_INSUFFICIENT_LOYALTY, ERR_DELIVERY_OVERLAP,
)
from middleware import (
    auth_context, require_role, require_customer_owner, require_json,
    parse_pagination, sort_by_created, paginate,
)
from response import ok, created, ok_list
from services.common import stamp_common, bump
from services.validation import require_fields, require_enum, require_int, require_bool
from services.pricing import delivery_fee, order_total
from services.loyalty import (
    compute_accrual_points, compute_reversal_for_line, append_ledger,
)
from services.inventory import select_stock_unit_for_line, recompute_available_count

bp = Blueprint("orders", __name__)

DELIVERY_ZONES = {"ZONE_A", "ZONE_B", "ZONE_C"}


def _validate_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise invalid_request("lines must be a non-empty array")
    out = []
    for l in lines:
        if not isinstance(l, dict):
            raise invalid_request("each line must be an object")
        if "plant_id" not in l or "qty" not in l:
            raise invalid_request("each line requires plant_id and qty")
        if not isinstance(l["qty"], int) or isinstance(l["qty"], bool) or l["qty"] < 1:
            raise invalid_request("qty must be integer >= 1")
        out.append({"plant_id": l["plant_id"], "qty": l["qty"]})
    return out


@bp.post("/orders")
def create_order():
    role, user_id = auth_context()
    require_role(role, {"Customer", "ShopStaff"})
    payload = require_json()
    require_fields(payload, ["customer_id", "delivery_zone", "lines"])
    customer_id = payload["customer_id"]
    delivery_zone = payload["delivery_zone"]
    require_enum(delivery_zone, DELIVERY_ZONES, "delivery_zone")
    gift_flag = require_bool(payload, "gift_flag", False)
    applied_redemption = 0
    if "applied_redemption_cents" in payload:
        applied_redemption = require_int(payload, "applied_redemption_cents", minimum=0)
    lines = _validate_lines(payload["lines"])

    # Existence.
    customer = DB.customers.get(customer_id)
    if not customer:
        raise not_found("Customer")
    # Customer owner check (customer places their own order).
    if role == "Customer" and user_id != customer_id:
        raise unauthorized("Customer may only order for self")

    # Existence of plants.
    plant_map = {}
    for l in lines:
        p = DB.plants.get(l["plant_id"])
        if not p:
            raise not_found("Plant")
        plant_map[l["plant_id"]] = p

    # Business referential — stock availability. Also assign specific units per line.
    # Iterate lines to reserve one FOR_SALE HEALTHY unit per qty.
    reserved_map = []  # list of (plant_id, [stock_unit_id, ...])
    reserved_ids = set()
    # Aggregate qty by plant_id first to ensure per-plant available_count >= qty.
    from collections import defaultdict
    plant_qty = defaultdict(int)
    for l in lines:
        plant_qty[l["plant_id"]] += l["qty"]
    for plant_id, qty in plant_qty.items():
        p = plant_map[plant_id]
        if p["available_count"] < qty:
            raise ApiError(ERR_STOCK_UNAVAILABLE, 409, "stock unavailable")

    # Delivery zone consistency (fiscal, priority 19).
    if delivery_zone != customer["delivery_zone"]:
        raise ApiError(ERR_DELIVERY_OUT_OF_ZONE, 422, "delivery zone mismatch")

    # Fiscal: loyalty redemption caps (priority 17).
    line_subtotals = []
    for l in lines:
        p = plant_map[l["plant_id"]]
        line_subtotals.append(l["qty"] * p["unit_price_cents"])
    subtotal_cents = sum(line_subtotals)
    if applied_redemption > customer.get("points_balance", 0):
        raise ApiError(ERR_INSUFFICIENT_LOYALTY, 402, "not enough points")
    if applied_redemption > subtotal_cents:
        raise ApiError(ERR_INSUFFICIENT_LOYALTY, 402, "redemption exceeds subtotal")

    # Now perform reservations — pick specific stock units per line.
    line_units = []
    for l in lines:
        line_ids = []
        for _ in range(l["qty"]):
            su = select_stock_unit_for_line(l["plant_id"], exclude_ids=reserved_ids)
            if su is None:
                # Cannot fulfill — theoretically caught by available_count check
                # but guard anyway.
                raise ApiError(ERR_STOCK_UNAVAILABLE, 409, "stock unavailable")
            reserved_ids.add(su["id"])
            line_ids.append(su["id"])
        line_units.append(line_ids)

    # Build Order + OrderLines.
    order_common = stamp_common(full=True)
    order = {
        **order_common,
        "customer_id": customer_id,
        "fulfillment_status": "PENDING",
        "payment_status": "UNPAID",
        "delivery_zone": delivery_zone,
        "gift_flag": gift_flag,
        "applied_redemption_cents": applied_redemption,
        "subtotal_cents": subtotal_cents,
        "delivery_fee_cents": 0,
        "total_cents": 0,
        "points_provisional": 0,
        "points_finalized": 0,
    }

    heavy_present = any(
        DB.plants[l["plant_id"]]["weight_class"] == "HEAVY" for l in lines
    )
    order["delivery_fee_cents"] = delivery_fee(delivery_zone, heavy_present, gift_flag, subtotal_cents)
    order["total_cents"] = order_total(subtotal_cents, applied_redemption, order["delivery_fee_cents"])

    # Create lines. OrderLine is reduced-fields (id + created_at).
    order_line_entities = []
    for l, unit_ids in zip(lines, line_units):
        p = plant_map[l["plant_id"]]
        # If qty > 1, produce ONE OrderLine per requested-line-input with the FIRST
        # reserved unit and qty as supplied. The scaffold field stock_unit_id is
        # singular — but we still need qty >= 1 handling. Per PRD each line
        # supplies a plant_id and a qty; each line produces one OrderLine. For
        # qty > 1 we associate the first reserved unit as canonical.
        line_entity = {
            **stamp_common(full=False),
            "order_id": order["id"],
            "plant_id": l["plant_id"],
            "stock_unit_id": unit_ids[0] if len(unit_ids) == 1 else unit_ids[0],
            "qty": l["qty"],
            "unit_price_cents": p["unit_price_cents"],
            "line_subtotal_cents": l["qty"] * p["unit_price_cents"],
            "refund_status": "NONE",
            "refund_amount_cents": 0,
            # Store the full reserved list to preserve cancel/deliver cascade.
            "_reserved_stock_unit_ids": unit_ids,
            # Delivered instant set on deliver (used for warranty window).
            "delivered_at": None,
        }
        DB.order_lines[line_entity["id"]] = line_entity
        order_line_entities.append(line_entity)
        # Flip reserved units to RESERVED.
        for uid in unit_ids:
            su = DB.stock_units[uid]
            su["sale_status"] = "RESERVED"
            bump(su)
        recompute_available_count(l["plant_id"])

    # Loyalty: provisional accrual + redemption ledger row.
    tier_at_checkout = customer["loyalty_tier"]
    provisional = compute_accrual_points(subtotal_cents, tier_at_checkout)
    order["points_provisional"] = provisional
    DB.orders[order["id"]] = order
    append_ledger(customer_id, order["id"], "ACCRUAL_PROVISIONAL", provisional)
    if applied_redemption > 0:
        # 1 cent per point => delta_points = -applied_redemption.
        append_ledger(customer_id, order["id"], "REDEMPTION", -applied_redemption)

    return created(_public_order(order))


def _public_order(order: dict) -> dict:
    """Strip internal fields not part of the public entity."""
    return {k: v for k, v in order.items() if not k.startswith("_")}


def _public_line(line: dict) -> dict:
    return {k: v for k, v in line.items() if not k.startswith("_") and k != "delivered_at"}


@bp.get("/orders/<oid>")
def get_order(oid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "ShopStaff", "Manager", "DeliveryDriver"})
    order = DB.orders.get(oid)
    if not order:
        raise not_found("Order")
    if role == "Customer" and user_id != order["customer_id"]:
        raise unauthorized("not order owner")
    # DeliveryDriver ownership: allowed to read orders they have assignments for.
    if role == "DeliveryDriver":
        # Allowed if there is a delivery for this order assigned to this driver.
        owned = any(
            d["order_id"] == oid and d["driver_id"] == user_id
            for d in DB.deliveries.values()
        )
        if not owned:
            raise unauthorized("driver not assigned to this order")
    return ok(_public_order(order))


@bp.get("/orders")
def list_orders():
    role, user_id = auth_context()
    require_role(role, {"Customer", "ShopStaff", "Manager"})
    limit, offset = parse_pagination(request.args)
    customer_id = request.args.get("customer_id")
    rows = list(DB.orders.values())
    if customer_id:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if role == "Customer":
        rows = [o for o in rows if o["customer_id"] == user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([_public_order(r) for r in page], limit=limit, offset=offset, total_count=total)


@bp.get("/order-lines")
def list_order_lines():
    role, user_id = auth_context()
    require_role(role, {"Customer", "ShopStaff", "Manager"})
    limit, offset = parse_pagination(request.args)
    order_id = request.args.get("order_id")
    plant_id = request.args.get("plant_id")
    stock_unit_id = request.args.get("stock_unit_id")
    rows = list(DB.order_lines.values())
    if order_id:
        rows = [l for l in rows if l["order_id"] == order_id]
    if plant_id:
        rows = [l for l in rows if l["plant_id"] == plant_id]
    if stock_unit_id:
        rows = [l for l in rows if l["stock_unit_id"] == stock_unit_id]
    if role == "Customer":
        rows = [l for l in rows if DB.orders[l["order_id"]]["customer_id"] == user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([_public_line(r) for r in page], limit=limit, offset=offset, total_count=total)


@bp.get("/order-lines/<lid>")
def get_order_line(lid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "ShopStaff", "Manager"})
    line = DB.order_lines.get(lid)
    if not line:
        raise not_found("OrderLine")
    if role == "Customer" and DB.orders[line["order_id"]]["customer_id"] != user_id:
        raise unauthorized("not line owner")
    return ok(_public_line(line))


@bp.get("/orders/<oid>/loyalty-ledger")
def order_loyalty_ledger(oid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "ShopStaff", "Manager"})
    order = DB.orders.get(oid)
    if not order:
        raise not_found("Order")
    if role == "Customer" and user_id != order["customer_id"]:
        raise unauthorized("not order owner")
    limit, offset = parse_pagination(request.args)
    rows = [r for r in DB.loyalty_ledger.values() if r.get("order_id") == oid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)


@bp.post("/orders/<oid>/pay")
def pay_order(oid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "ShopStaff"})
    order = DB.orders.get(oid)
    if not order:
        raise not_found("Order")
    if role == "Customer" and user_id != order["customer_id"]:
        raise unauthorized("not order owner")
    if order["payment_status"] != "UNPAID" or order["fulfillment_status"] != "PENDING":
        raise invalid_state("cannot pay from this state")
    order["payment_status"] = "PAID"
    bump(order)
    return ok(_public_order(order))


@bp.post("/orders/<oid>/dispatch")
def dispatch_order(oid):
    role, _ = auth_context()
    require_role(role, {"ShopStaff", "Manager"})
    order = DB.orders.get(oid)
    if not order:
        raise not_found("Order")
    payload = require_json()
    require_fields(payload, ["driver_id", "window_start_at", "window_end_at"])
    driver_id = payload["driver_id"]
    window_start = payload["window_start_at"]
    window_end = payload["window_end_at"]
    ws = parse_iso(window_start)
    we = parse_iso(window_end)
    if ws is None or we is None:
        raise invalid_request("window_start_at / window_end_at must be ISO 8601")
    if we < ws:
        raise invalid_request("window_end_at must be >= window_start_at")

    # Existence
    driver = DB.delivery_drivers.get(driver_id)
    if not driver:
        raise not_found("DeliveryDriver")

    # State precondition.
    if not (order["payment_status"] == "PAID" and order["fulfillment_status"] == "PENDING"):
        raise invalid_state("order not eligible for dispatch")
    # Every OrderLine.stock_unit_id must resolve to a RESERVED unit.
    lines = [l for l in DB.order_lines.values() if l["order_id"] == oid]
    for l in lines:
        for uid in l["_reserved_stock_unit_ids"]:
            su = DB.stock_units.get(uid)
            if not su or su["sale_status"] != "RESERVED":
                raise invalid_state("stock not reserved")

    # Business_temporal: overlap and daily-capacity.
    proposed_minutes = int((we - ws).total_seconds() // 60)
    if proposed_minutes < 0:
        proposed_minutes = 0
    ws_date = ws.date()

    # Closed-interval overlap: endpoints of one within/on endpoints of other.
    total_minutes_day = 0
    for other in DB.deliveries.values():
        if other["driver_id"] != driver_id:
            continue
        if other["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        o_ws = parse_iso(other["window_start_at"])
        o_we = parse_iso(other["window_end_at"])
        # Closed-interval overlap.
        if not (we < o_ws or o_we < ws):
            raise ApiError(ERR_DELIVERY_OVERLAP, 409, "driver window overlap")
        if o_ws.date() == ws_date:
            total_minutes_day += int((o_we - o_ws).total_seconds() // 60)
    if total_minutes_day + proposed_minutes > driver["daily_capacity_minutes"]:
        raise ApiError(ERR_DELIVERY_OVERLAP, 409, "driver daily capacity exceeded")

    # Create assignment.
    delivery = {
        **stamp_common(full=True),
        "order_id": oid,
        "driver_id": driver_id,
        "window_start_at": window_start,
        "window_end_at": window_end,
        "status": "SCHEDULED",
    }
    DB.deliveries[delivery["id"]] = delivery
    order["fulfillment_status"] = "DISPATCHED"
    bump(order)
    return created(delivery)


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    order = DB.orders.get(oid)
    if not order:
        raise not_found("Order")
    if role == "Customer" and user_id != order["customer_id"]:
        raise unauthorized("not order owner")
    payload = require_json()
    require_fields(payload, ["expected_order_version"])
    exp = payload["expected_order_version"]
    if not isinstance(exp, int) or isinstance(exp, bool):
        raise invalid_request("expected_order_version must be integer")

    # State precondition (priority 7).
    # Two paths:
    # A) PENDING+* (any payment) — cancellable by Customer or Manager.
    # B) DISPATCHED+PAID — Manager-only.
    fs = order["fulfillment_status"]
    ps = order["payment_status"]
    if fs == "PENDING":
        pass  # ok
    elif fs == "DISPATCHED" and ps == "PAID":
        if role != "Manager":
            # State machine only allows Manager on the post-dispatch path.
            raise invalid_state("post-dispatch cancel is Manager-only")
    else:
        raise invalid_state("order not cancellable from this state")

    # OCC (priority 8).
    if exp != order["version"]:
        raise stale_version("order version mismatch")

    # Cascade.
    was_paid = ps == "PAID"
    lines = [l for l in DB.order_lines.values() if l["order_id"] == oid]

    if fs == "DISPATCHED":
        # Flip any SCHEDULED delivery to FAILED.
        for d in DB.deliveries.values():
            if d["order_id"] == oid and d["status"] == "SCHEDULED":
                d["status"] = "FAILED"
                bump(d)

    # Reservation release: RESERVED -> FOR_SALE per unit.
    affected_plants = set()
    for l in lines:
        for uid in l["_reserved_stock_unit_ids"]:
            su = DB.stock_units.get(uid)
            if not su:
                continue
            if su["sale_status"] == "RESERVED":
                su["sale_status"] = "FOR_SALE"
                bump(su)
                affected_plants.add(su["plant_id"])
    for pid in affected_plants:
        recompute_available_count(pid)

    order["fulfillment_status"] = "CANCELLED"
    if was_paid:
        order["payment_status"] = "REFUNDED"
        customer = DB.customers[order["customer_id"]]
        customer["wallet_credit_cents"] = customer.get("wallet_credit_cents", 0) + order["total_cents"]

    # Loyalty reversal.
    append_ledger(order["customer_id"], oid, "REVERSAL", -order["points_provisional"])

    bump(order)
    return ok(_public_order(order))
