"""Event sales (schedule, drawer open/close-count/reconcile/cancel) and
orders (EVENT_POS + ONLINE creation, fulfillment transitions, refunds)."""
from datetime import timedelta

from flask import Blueprint, request

from core import (AD, SM, TRE, SC, CUST, ApiError, DB,
                  ERR_DESIGN_NOT_LICENSED, ERR_DRAWER_NOT_OPEN, ERR_DROP_NOT_OPEN,
                  ERR_EVENT_NF, ERR_EVENT_WINDOW_PASSED, ERR_INSUFFICIENT_STOCK,
                  ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_LICENSE_REVOKED,
                  ERR_ORDER_NF, ERR_PICKUP_EXPIRED, ERR_PICKUP_NOT_READY,
                  ERR_PROGRAM_NF, ERR_REFUND_EXCEEDS, ERR_REGISTER_CONFLICT,
                  ERR_ROLE, ERR_SEGREGATION, ERR_VARIANT_NF, auth, body, dec,
                  fetch, fetch_scoped, floor_div_dec, gate_active, is_int,
                  is_num, list_response, need_role, new_entity, now_logical,
                  pub, req_dt, req_fields, req_int, rhu, rhu_decimal, success,
                  touch)

bp = Blueprint("sales", __name__)


# --------------------------------------------------------------- EventSale --
@bp.post("/spirit-store/event-sales")
def create_event():
    auth()
    uid, role = auth()
    need_role(role, SM)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    req_fields(data, "program_id", "name", "register_location", "starts_at",
               "ends_at")
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    if not ends_at > starts_at:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "ends_at must be strictly after starts_at")
    gate_active(program)
    # Register buffer rule: windows are closed intervals; a booking conflicts
    # when its gap to another non-CANCELLED event on the same register is
    # strictly less than the buffer ("gap of at least" the buffer passes, so
    # a start exactly at other.ends_at + buffer is conflict-free).
    buffer = timedelta(minutes=program["register_buffer_minutes"])
    for other in DB["events"].values():
        if (other["program_id"] == program["id"]
                and other["register_location"] == data["register_location"]
                and other["status"] != "CANCELLED"):
            if (starts_at < other["ends_at"] + buffer
                    and other["starts_at"] < ends_at + buffer):
                raise ApiError(ERR_REGISTER_CONFLICT, 409,
                               "event booking conflicts with another event on "
                               "the same register")
    event = new_entity({
        "program_id": program["id"],
        "name": data["name"],
        "register_location": data["register_location"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
        "opening_float_cents": None,
        "opened_by_user_id": None,
        "cash_sales_cents": 0,
        "card_sales_cents": 0,
        "cash_refunds_cents": 0,
        "closing_counted_cents": None,
        "counted_by_user_id": None,
        "over_short_cents": None,
        "reconcile_note": None,
    })
    DB["events"][event["id"]] = event
    return success(pub(event), code=201)


@bp.get("/spirit-store/event-sales")
def list_events():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, SC)
    items = list(DB["events"].values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [e for e in items if e["program_id"] == pid]
    return list_response(items, pub)


@bp.get("/spirit-store/event-sales/<eventId>")
def get_event(eventId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, SC)
    return success(pub(fetch("events", eventId, ERR_EVENT_NF)))


@bp.post("/spirit-store/event-sales/<eventId>/open-drawer")
def open_drawer(eventId):
    auth()
    uid, role = auth()
    need_role(role, SC)
    event = fetch("events", eventId, ERR_EVENT_NF)
    data = body()
    float_cents = req_int(data, "opening_float_cents", 0)
    program = DB["programs"].get(event["program_id"])
    gate_active(program)
    if event["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SCHEDULED event's drawer can be opened")
    if now_logical() > event["ends_at"]:
        raise ApiError(ERR_EVENT_WINDOW_PASSED, 409,
                       "the event window has passed")
    event["opening_float_cents"] = float_cents
    event["opened_by_user_id"] = uid
    event["status"] = "OPEN"
    touch(event)
    return success(pub(event))


@bp.post("/spirit-store/event-sales/<eventId>/close-count")
def close_count(eventId):
    auth()
    uid, role = auth()
    need_role(role, TRE)
    event = fetch("events", eventId, ERR_EVENT_NF)
    data = body()
    counted = req_int(data, "closing_counted_cents", 0)
    program = DB["programs"].get(event["program_id"])
    gate_active(program)
    if event["status"] not in ("OPEN", "FLAGGED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an OPEN or FLAGGED event can be counted")
    # Segregation of duties: the counter may not be the opener.
    if uid == event["opened_by_user_id"]:
        raise ApiError(ERR_SEGREGATION, 403,
                       "the drawer counter must differ from the opener")
    expected = (event["opening_float_cents"] + event["cash_sales_cents"]
                - event["cash_refunds_cents"])
    over_short = counted - expected
    event["closing_counted_cents"] = counted
    event["counted_by_user_id"] = uid
    event["over_short_cents"] = over_short
    # Boundary: a discrepancy exactly equal to the tolerance reconciles.
    if abs(over_short) <= program["over_short_tolerance_cents"]:
        event["status"] = "RECONCILED"
    else:
        event["status"] = "FLAGGED"
    touch(event)
    return success(pub(event))


@bp.post("/spirit-store/event-sales/<eventId>/reconcile")
def reconcile_event(eventId):
    auth()
    uid, role = auth()
    need_role(role, AD)
    event = fetch("events", eventId, ERR_EVENT_NF)
    data = body()
    req_fields(data, "note")
    program = DB["programs"].get(event["program_id"])
    gate_active(program)
    if event["status"] != "FLAGGED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a FLAGGED event can be manually reconciled")
    event["reconcile_note"] = data["note"]
    event["status"] = "RECONCILED"
    touch(event)
    return success(pub(event))


@bp.post("/spirit-store/event-sales/<eventId>/cancel")
def cancel_event(eventId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    event = fetch("events", eventId, ERR_EVENT_NF)
    program = DB["programs"].get(event["program_id"])
    gate_active(program)
    if event["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SCHEDULED event can be cancelled")
    event["status"] = "CANCELLED"
    touch(event)
    return success(pub(event))


# -------------------------------------------------------------------- Order --
def validate_lines(data):
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "lines must be a non-empty array")
    out = []
    for line in lines:
        if not isinstance(line, dict) or line.get("variant_id") is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "each line requires a variant_id")
        qty = line.get("qty")
        if not is_int(qty) or qty < 1:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "each line qty must be an integer >= 1")
        discount = line.get("discount_pct", 0)
        if not is_num(discount) or discount < 0 or discount > 1:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "discount_pct must be a fraction between 0 and 1")
        out.append({"variant_id": line["variant_id"], "qty": qty,
                    "discount_pct": discount})
    return out


@bp.post("/spirit-store/orders")
def create_order():
    auth()
    uid, role = auth()
    need_role(role, SC, CUST)
    data = body()
    # Channel-role binding (RBAC): cashier rings EVENT_POS, customer ONLINE.
    channel = data.get("channel")
    if channel == "EVENT_POS" and role != SC:
        raise ApiError(ERR_ROLE, 403,
                       "only a StudentCashier may create EVENT_POS orders")
    if channel == "ONLINE" and role != CUST:
        raise ApiError(ERR_ROLE, 403,
                       "only a Customer may create ONLINE orders")
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    if data.get("event_id") is not None:
        fetch_scoped("events", data["event_id"], ERR_EVENT_NF,
                     data.get("program_id"))
    # Body-FK existence for line variants (pipeline step 4).
    raw_lines = data.get("lines")
    if isinstance(raw_lines, list):
        for line in raw_lines:
            if isinstance(line, dict) and line.get("variant_id") is not None:
                fetch_scoped("variants", line["variant_id"], ERR_VARIANT_NF,
                             data.get("program_id"))
    req_fields(data, "program_id", "channel", "customer_user_id",
               "payment_method", "lines")
    if channel not in ("EVENT_POS", "ONLINE"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "channel must be EVENT_POS or ONLINE")
    if data["payment_method"] not in ("CASH", "CARD"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "payment_method must be CASH or CARD")
    # event_id required iff EVENT_POS, must be null for ONLINE.
    if channel == "EVENT_POS" and data.get("event_id") is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "event_id is required for EVENT_POS orders")
    if channel == "ONLINE" and data.get("event_id") is not None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "event_id must be null for ONLINE orders")
    lines = validate_lines(data)
    gate_active(program)
    event = None
    if channel == "EVENT_POS":
        event = DB["events"][data["event_id"]]
        if event["status"] != "OPEN":
            raise ApiError(ERR_DRAWER_NOT_OPEN, 409,
                           "the event's drawer must be OPEN for POS sales")
    # Licensing gate (pipeline step 8) for every line's design.
    for line in lines:
        variant = DB["variants"][line["variant_id"]]
        design = DB["designs"].get(variant["design_id"])
        if design is not None and design["status"] == "REVOKED":
            raise ApiError(ERR_LICENSE_REVOKED, 409,
                           "design license was revoked")
        if design is None or design["status"] != "APPROVED":
            raise ApiError(ERR_DESIGN_NOT_LICENSED, 409,
                           "design must be APPROVED to sell")
    # Temporal (step 9): online sale of a drop variant needs an OPEN drop.
    if channel == "ONLINE":
        for line in lines:
            variant = DB["variants"][line["variant_id"]]
            if variant["drop_id"]:
                drop = DB["drops"].get(variant["drop_id"])
                if drop is None or drop["status"] != "OPEN":
                    raise ApiError(ERR_DROP_NOT_OPEN, 409,
                                   "the variant's seasonal drop is not OPEN")
    # Constraint (step 10): available_qty must cover every line, atomically.
    for line in lines:
        variant = DB["variants"][line["variant_id"]]
        available = variant["on_hand_qty"] - variant["reserved_online_qty"]
        if available < line["qty"]:
            raise ApiError(ERR_INSUFFICIENT_STOCK, 422,
                           "available stock does not cover the order")
    # Pricing: round per line (half-up), then sum — pinned order (§3.6).
    total = 0
    margin = 0
    stored_lines = []
    for line in lines:
        variant = DB["variants"][line["variant_id"]]
        line_total = rhu_decimal_local(
            variant["unit_price_cents"] * line["qty"]
            * (1 - dec(line["discount_pct"])))
        total += line_total
        margin += line_total - line["qty"] * variant["landed_unit_cost_cents"]
        stored_lines.append({
            "variant_id": line["variant_id"],
            "qty": line["qty"],
            "discount_pct": line["discount_pct"],
            "unit_price_cents": variant["unit_price_cents"],
            "line_total_cents": line_total,
            "_released": 0,
        })
    clock = now_logical()
    order = new_entity({
        "program_id": program["id"],
        "channel": channel,
        "event_id": data.get("event_id"),
        "customer_user_id": data["customer_user_id"],
        "payment_method": data["payment_method"],
        "lines": stored_lines,
        "total_cents": total,
        "margin_cents": margin,
        "payment_status": "PAID",
        "fulfillment_status": ("POS_FULFILLED" if channel == "EVENT_POS"
                               else "PICKUP_PENDING"),
        "refunded_cents": 0,
        "ready_at": None,
        "expires_at": None,
        "picked_up_at": None,
        "_fulfilled_instant": clock if channel == "EVENT_POS" else None,
        "_clawed_cents": 0,
    })
    DB["orders"][order["id"]] = order
    touched = set()
    for line in stored_lines:
        variant = DB["variants"][line["variant_id"]]
        if channel == "EVENT_POS":
            # Stock leaves the shelf immediately.
            variant["on_hand_qty"] -= line["qty"]
            variant["_consumed"] += line["qty"]
        else:
            # Online reserves; nothing leaves the shelf yet.
            variant["reserved_online_qty"] += line["qty"]
        touched.add(variant["id"])
    for vid in touched:
        touch(DB["variants"][vid])
    if event is not None:
        if data["payment_method"] == "CASH":
            event["cash_sales_cents"] += total
        else:
            event["card_sales_cents"] += total
        touch(event)
    program["undistributed_profit_cents"] += margin
    touch(program)
    return success(pub(order), code=201)


def rhu_decimal_local(value):
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.get("/spirit-store/orders")
def list_orders():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, SC, CUST)
    items = list(DB["orders"].values())
    for param in ("program_id", "event_id", "customer_user_id"):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o[param] == value]
    variant_filter = request.args.get("variant_id")
    if variant_filter is not None:
        items = [o for o in items
                 if any(l["variant_id"] == variant_filter
                        for l in o["lines"])]
    return list_response(items, pub)


@bp.get("/spirit-store/orders/<orderId>")
def get_order(orderId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, SC, CUST)
    return success(pub(fetch("orders", orderId, ERR_ORDER_NF)))


@bp.post("/spirit-store/orders/<orderId>/fulfillment-transition")
def fulfillment_transition(orderId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    order = fetch("orders", orderId, ERR_ORDER_NF)
    data = body()
    req_fields(data, "to_state")
    to_state = data["to_state"]
    if to_state not in ("READY_FOR_PICKUP", "PICKED_UP"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_state must be READY_FOR_PICKUP or PICKED_UP")
    program = DB["programs"].get(order["program_id"])
    gate_active(program)
    clock = now_logical()
    if to_state == "READY_FOR_PICKUP":
        if order["fulfillment_status"] != "PICKUP_PENDING":
            raise ApiError(ERR_PICKUP_NOT_READY, 409,
                           "order is not pending pickup")
        order["fulfillment_status"] = "READY_FOR_PICKUP"
        order["ready_at"] = clock
        order["expires_at"] = clock + timedelta(
            days=program["pickup_window_days"])
    else:  # PICKED_UP
        if order["fulfillment_status"] != "READY_FOR_PICKUP":
            raise ApiError(ERR_PICKUP_NOT_READY, 409,
                           "order is not ready for pickup")
        if clock > order["expires_at"]:
            raise ApiError(ERR_PICKUP_EXPIRED, 409,
                           "the pickup window has expired")
        order["fulfillment_status"] = "PICKED_UP"
        order["picked_up_at"] = clock
        order["_fulfilled_instant"] = clock
        touched = set()
        for line in order["lines"]:
            variant = DB["variants"].get(line["variant_id"])
            if variant is None:
                continue
            variant["on_hand_qty"] -= line["qty"]
            variant["reserved_online_qty"] -= line["qty"]
            variant["_consumed"] += line["qty"]
            touched.add(variant["id"])
        for vid in touched:
            touch(DB["variants"][vid])
    touch(order)
    return success(pub(order))


@bp.post("/spirit-store/orders/<orderId>/refund")
def refund_order(orderId):
    auth()
    uid, role = auth()
    need_role(role, TRE)
    order = fetch("orders", orderId, ERR_ORDER_NF)
    data = body()
    amount = req_int(data, "amount_cents", 1)
    program = DB["programs"].get(order["program_id"])
    gate_active(program)
    # State preconditions (pipeline step 7).
    if order["payment_status"] not in ("PAID", "PARTIALLY_REFUNDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "order is not refundable")
    event = None
    if order["channel"] == "EVENT_POS":
        event = DB["events"].get(order["event_id"])
        if event is None or event["status"] != "OPEN":
            raise ApiError(ERR_DRAWER_NOT_OPEN, 409,
                           "the event's drawer must be OPEN for POS refunds")
    else:
        if order["fulfillment_status"] not in ("PICKUP_PENDING",
                                               "READY_FOR_PICKUP"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "online order is not refundable in its current "
                           "fulfillment state")
    # Fiscal (step 11): refund must stay within what was paid.
    new_refunded = order["refunded_cents"] + amount
    if new_refunded > order["total_cents"]:
        raise ApiError(ERR_REFUND_EXCEEDS, 422,
                       "refund exceeds the amount paid")
    order["refunded_cents"] = new_refunded
    if new_refunded == order["total_cents"]:
        order["payment_status"] = "REFUNDED"
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    # Profit clawback: margin * amount / total, rounded half-up.
    if order["total_cents"] > 0:
        claw = rhu(order["margin_cents"] * amount, order["total_cents"])
    else:
        claw = 0
    order["_clawed_cents"] += claw
    program["undistributed_profit_cents"] -= claw
    touch(program)
    if order["channel"] == "EVENT_POS":
        if order["payment_method"] == "CASH":
            event["cash_refunds_cents"] += amount
            touch(event)
    else:
        # Release the reservation proportionally per refunded whole units.
        full = new_refunded == order["total_cents"]
        touched = set()
        for line in order["lines"]:
            variant = DB["variants"].get(line["variant_id"])
            if variant is None:
                continue
            if full or order["total_cents"] == 0:
                target = line["qty"]
            else:
                target = floor_div_dec(
                    line["qty"] * dec(new_refunded), order["total_cents"])
            delta = target - line.get("_released", 0)
            if delta > 0:
                variant["reserved_online_qty"] -= delta
                line["_released"] = target
                touched.add(variant["id"])
        for vid in touched:
            touch(DB["variants"][vid])
        # A fully refunded online order that has not been picked up moves to
        # EXPIRED_RELEASED, releasing the entire remaining reservation.
        if full:
            order["fulfillment_status"] = "EXPIRED_RELEASED"
    touch(order)
    return success(pub(order))
