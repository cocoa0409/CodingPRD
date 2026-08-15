"""CustomerOrder and OrderLine endpoints, incl. acknowledge/cancel/reschedule/ship."""

from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, request

import clock
import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    check_buyer_body_ownership,
    fefo_lots_reserved,
    get_json_body,
    get_order_or_404,
    get_order_line_or_404,
    maybe_complete_order,
    maybe_deplete_lot,
    mint_id,
    months_elapsed,
    paginate,
    pagination_params,
    recompute_order_totals,
    recompute_part_availability,
    release_lots_fefo,
    req_date,
    req_int,
    req_str,
    serialize_order,
    serialize_order_line,
    stamp_clock,
    stamp_now,
    touch_order,
    whole_days_between,
)

bp = Blueprint("orders", __name__)

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def _order_lines(order_id):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


def _cancel_line_terms_check(line, now):
    """Cancellation-terms group: NCNR first, then the cancel window (strict <)."""
    if line["ncnr_snapshot"]:
        raise ApiError(E.ERR_LINE_NCNR, 409, "Line is non-cancellable/non-returnable.")
    if now.date() >= line["_cancel_by"]:
        raise ApiError(E.ERR_CANCEL_WINDOW_CLOSED, 409, "Cancel window has closed.")


def _release_line_reservation(line):
    if line["allocated_qty"] > 0:
        release_lots_fefo(line["part_id"], line["allocated_qty"])
        line["allocated_qty"] = 0


def _line_cancel(line, order):
    was_allocated = line["status"] == "ALLOCATED"
    _release_line_reservation(line)
    line["status"] = "CANCELLED"
    line["updated_at"] = stamp_now()
    line["version"] += 1
    recompute_order_totals(order, bump=True)
    recompute_part_availability(line["part_id"])


# ---------------------------------------------------------------------------
# order create / read
# ---------------------------------------------------------------------------

@bp.post("/orders")
def create_order():
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep", "CustomerBuyer"})
    body = get_json_body()

    customer_id = req_str(body, "customer_id")
    note = body.get("note", "")
    if not isinstance(note, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid note.")
    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "lines must be a non-empty array.")
    parsed_lines = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Each line must be an object.")
        part_id = raw.get("part_id")
        if not isinstance(part_id, str) or part_id == "":
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Line part_id is required.")
        quantity = raw.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Line quantity must be a positive integer.")
        ship_date = raw.get("ship_date")
        from services.helpers import parse_iso_date

        sd = parse_iso_date(ship_date)
        if sd is None:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Line ship_date must be an ISO date.")
        parsed_lines.append((part_id, quantity, sd))

    # Ownership (priority 2) precedes FK existence (priority 3) for body customer_id.
    check_buyer_body_ownership(user_id, role, customer_id)

    customer = db.customers.get(customer_id)
    if customer is None:
        raise ApiError(E.ERR_CUSTOMER_NOT_FOUND, 404, "Customer not found.")
    for part_id, _, _ in parsed_lines:
        if part_id not in db.parts:
            raise ApiError(E.ERR_PART_NOT_FOUND, 404, "Part not found.")

    if customer["status"] != "GOOD_STANDING":
        raise ApiError(E.ERR_CUSTOMER_CREDIT_HOLD, 409, "Customer is on CREDIT_HOLD.")

    now = stamp_now()
    order = {
        "id": mint_id(),
        "customer_id": customer_id,
        "note": note,
        "status": "SUBMITTED",
        "open_exposure_cents": 0,
        "allocated_value_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.orders[order["id"]] = order

    for part_id, quantity, sd in parsed_lines:
        line = {
            "id": mint_id(),
            "order_id": order["id"],
            "part_id": part_id,
            "quantity": quantity,
            "ship_date": sd.isoformat(),
            "_ship_date": sd,
            "unit_price_cents": 0,
            "ncnr_snapshot": False,
            "cancel_window_days_snapshot": 0,
            "reschedule_window_days_snapshot": 0,
            "cancel_by_date": None,
            "_cancel_by": None,
            "allocated_qty": 0,
            "shipped_qty": 0,
            "returned_qty": 0,
            "last_shipped_at": None,
            "_last_shipped_at": None,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": _next_seq(),
        }
        db.order_lines[line["id"]] = line

    return success(serialize_order(order), status=201)


@bp.get("/orders")
def list_orders():
    require_auth()
    limit, offset = pagination_params()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(db.orders.values())
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_order(o) for o in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/orders/<orderId>")
def get_order(orderId):
    require_auth()
    order = get_order_or_404(orderId)
    return success(serialize_order(order), status=200)


# ---------------------------------------------------------------------------
# order lifecycle actions
# ---------------------------------------------------------------------------

@bp.post("/orders/<orderId>/acknowledge")
def acknowledge_order(orderId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep"})
    order = get_order_or_404(orderId)
    if order["status"] != "SUBMITTED":
        raise ApiError(E.ERR_ORDER_NOT_SUBMITTED, 409, "Order is not in SUBMITTED.")
    customer = db.customers.get(order["customer_id"])
    if customer is not None and customer["status"] != "GOOD_STANDING":
        raise ApiError(E.ERR_CUSTOMER_CREDIT_HOLD, 409, "Customer is on CREDIT_HOLD.")

    now = stamp_now()
    for line in _order_lines(order["id"]):
        part = db.parts.get(line["part_id"])
        mline = db.manufacturer_lines.get(part["manufacturer_line_id"]) if part else None
        line["unit_price_cents"] = part["book_price_cents"] if part else 0
        line["ncnr_snapshot"] = mline["ncnr"] if mline else False
        line["cancel_window_days_snapshot"] = mline["cancel_window_days"] if mline else 0
        line["reschedule_window_days_snapshot"] = mline["reschedule_window_days"] if mline else 0
        cancel_by = line["_ship_date"] - timedelta(days=line["cancel_window_days_snapshot"])
        line["cancel_by_date"] = cancel_by.isoformat()
        line["_cancel_by"] = cancel_by
        line["updated_at"] = now
        line["version"] += 1

    order["status"] = "ACKNOWLEDGED"
    recompute_order_totals(order, bump=True)
    touched_parts = {l["part_id"] for l in _order_lines(order["id"])}
    for pid in touched_parts:
        recompute_part_availability(pid)
    return success(serialize_order(order), status=200)


@bp.post("/orders/<orderId>/release-hold")
def release_hold(orderId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep", "DistributorAdmin"})
    order = get_order_or_404(orderId)
    if order["status"] != "ON_HOLD":
        raise ApiError(
            E.ERR_ORDER_NOT_ACKNOWLEDGED, 409, "Order is not ON_HOLD."
        )
    order["status"] = "ACKNOWLEDGED"
    touch_order(order)
    return success(serialize_order(order), status=200)


@bp.post("/orders/<orderId>/cancel")
def cancel_order(orderId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep", "CustomerBuyer"})
    order = get_order_or_404(orderId)
    check_buyer_body_ownership(user_id, role, order["customer_id"])
    if order["status"] != "ACKNOWLEDGED":
        raise ApiError(
            E.ERR_ORDER_NOT_ACKNOWLEDGED, 409, "Order is not ACKNOWLEDGED."
        )
    lines = _order_lines(order["id"])
    if any(l["shipped_qty"] > 0 for l in lines):
        raise ApiError(
            E.ERR_ORDER_HAS_SHIPPED_LINES, 409, "Order has shipped lines."
        )
    now = clock.now()
    open_lines = [l for l in lines if l["status"] in ("OPEN", "ALLOCATED")]
    # Atomic: validate the cancellation-terms group on every line first.
    for line in open_lines:
        _cancel_line_terms_check(line, now)
    for line in open_lines:
        _release_line_reservation(line)
        line["status"] = "CANCELLED"
        line["updated_at"] = stamp_now()
        line["version"] += 1
    order["open_exposure_cents"] = 0
    order["allocated_value_cents"] = 0
    order["status"] = "CANCELLED"
    touch_order(order)
    for pid in {l["part_id"] for l in open_lines}:
        recompute_part_availability(pid)
    return success(serialize_order(order), status=200)


# ---------------------------------------------------------------------------
# order line actions
# ---------------------------------------------------------------------------

@bp.post("/orders/<orderId>/lines/<lineId>/reschedule")
def reschedule_line(orderId, lineId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep", "CustomerBuyer"})
    body = get_json_body()
    if "expected_order_version" not in body or body["expected_order_version"] is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "expected_order_version is required.")
    expected = body["expected_order_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "expected_order_version must be an integer.")
    if "new_ship_date" not in body:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "new_ship_date is required.")
    from services.helpers import parse_iso_date

    new_sd = parse_iso_date(body.get("new_ship_date"))
    if new_sd is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "new_ship_date must be an ISO date.")

    order = get_order_or_404(orderId)
    line = db.order_lines.get(lineId)
    if line is None or line["order_id"] != orderId:
        raise ApiError(E.ERR_ORDER_LINE_NOT_FOUND, 404, "Order line not found.")

    check_buyer_body_ownership(user_id, role, order["customer_id"])

    if order["status"] != "ACKNOWLEDGED":
        raise ApiError(E.ERR_ORDER_NOT_ACKNOWLEDGED, 409, "Order is not ACKNOWLEDGED.")
    if expected != order["version"]:
        raise ApiError(E.ERR_STALE_ORDER_VERSION, 412, "Stale order version.")

    now = clock.now()
    reschedule_cutoff = line["_ship_date"] - timedelta(days=line["reschedule_window_days_snapshot"])
    if now.date() >= reschedule_cutoff:
        raise ApiError(E.ERR_RESCHEDULE_WINDOW_CLOSED, 409, "Reschedule window has closed.")
    if new_sd <= now.date():
        raise ApiError(E.ERR_SHIP_DATE_IN_PAST, 409, "new_ship_date must be after today.")
    if line["ncnr_snapshot"] and new_sd <= line["_ship_date"]:
        raise ApiError(
            E.ERR_SHIP_DATE_IN_PAST, 409, "NCNR line reschedule may only push the date out."
        )

    line["ship_date"] = new_sd.isoformat()
    line["_ship_date"] = new_sd
    cancel_by = new_sd - timedelta(days=line["cancel_window_days_snapshot"])
    line["cancel_by_date"] = cancel_by.isoformat()
    line["_cancel_by"] = cancel_by
    line["updated_at"] = stamp_now()
    line["version"] += 1
    touch_order(order)
    return success(serialize_order_line(line), status=200)


@bp.post("/orders/<orderId>/lines/<lineId>/cancel")
def cancel_line(orderId, lineId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep", "CustomerBuyer"})
    order = get_order_or_404(orderId)
    line = db.order_lines.get(lineId)
    if line is None or line["order_id"] != orderId:
        raise ApiError(E.ERR_ORDER_LINE_NOT_FOUND, 404, "Order line not found.")
    check_buyer_body_ownership(user_id, role, order["customer_id"])

    if order["status"] not in ("ACKNOWLEDGED", "PARTIALLY_SHIPPED"):
        raise ApiError(E.ERR_ORDER_NOT_ACKNOWLEDGED, 409, "Order is not ACKNOWLEDGED or PARTIALLY_SHIPPED.")
    if line["status"] not in ("OPEN", "ALLOCATED"):
        raise ApiError(E.ERR_LINE_NOT_OPEN_OR_ALLOCATED, 409, "Line is not OPEN or ALLOCATED.")
    _cancel_line_terms_check(line, clock.now())

    _line_cancel(line, order)
    maybe_complete_order(order)
    return success(serialize_order_line(line), status=200)


@bp.post("/orders/<orderId>/lines/<lineId>/ship")
def ship_line(orderId, lineId):
    user_id, role = require_auth()
    require_role(user_id, role, {"WarehouseOps"})
    body = get_json_body()
    qty = req_int(body, "qty")
    if qty <= 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "qty must be a positive integer.")
    substitute_part_id = body.get("substitute_part_id")
    if substitute_part_id is not None and not isinstance(substitute_part_id, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid substitute_part_id.")

    order = get_order_or_404(orderId)
    line = db.order_lines.get(lineId)
    if line is None or line["order_id"] != orderId:
        raise ApiError(E.ERR_ORDER_LINE_NOT_FOUND, 404, "Order line not found.")
    if substitute_part_id is not None and substitute_part_id not in db.parts:
        raise ApiError(E.ERR_PART_NOT_FOUND, 404, "Part not found.")

    # state preconditions (priority 4)
    if line["status"] != "ALLOCATED":
        raise ApiError(E.ERR_LINE_NOT_ALLOCATED, 409, "Line is not ALLOCATED.")
    if order["status"] == "ON_HOLD":
        raise ApiError(E.ERR_ORDER_ON_HOLD, 409, "Order is ON_HOLD.")

    now = clock.now()
    part = db.parts.get(line["part_id"])
    shipped_part = db.parts.get(substitute_part_id) if substitute_part_id else part

    # safety: date-code freshness across the FEFO pick (priority 5, beats fiscal)
    pick = []
    if substitute_part_id:
        from services.helpers import fefo_lots_available

        candidates = [
            l for l in fefo_lots_available(substitute_part_id) if l["qty_on_hand"] > 0
        ]
        remaining = qty
        for lot in candidates:
            if remaining <= 0:
                break
            take = min(remaining, lot["qty_on_hand"])
            if take > 0:
                pick.append((lot, take))
                remaining -= take
    else:
        candidates = fefo_lots_reserved(line["part_id"])
        remaining = qty
        for lot in candidates:
            if remaining <= 0:
                break
            take = min(remaining, lot["qty_reserved"])
            if take > 0:
                pick.append((lot, take))
                remaining -= take
    for lot, _take in pick:
        if months_elapsed(lot["date_code"], now) > shipped_part["date_code_limit_months"]:
            raise ApiError(E.ERR_DATE_CODE_TOO_OLD, 409, "A picked lot's date code is too old.")

    # business constraint: quantity sanity (priority 6)
    # PRD §3.6: the line's "allocated_qty" is decremented on every ship, so it
    # already represents the unshipped allocated remainder.
    if qty > line["allocated_qty"]:
        raise ApiError(
            E.ERR_QUANTITY_EXCEEDS_AVAILABLE, 409, "Ship qty exceeds allocated remainder."
        )

    # referential: substitute approval (priority 8)
    if substitute_part_id:
        ok = any(
            a["customer_id"] == order["customer_id"]
            and a["primary_part_id"] == line["part_id"]
            and a["alternate_part_id"] == substitute_part_id
            and a["status"] == "APPROVED"
            for a in db.alternate_approvals.values()
        )
        if not ok:
            raise ApiError(
                E.ERR_ALTERNATE_NOT_APPROVED, 409, "No APPROVED alternate-part approval."
            )

    # fiscal: credit check (priority 9) — on failure the order moves to ON_HOLD
    customer = db.customers.get(order["customer_id"])
    ship_value = qty * line["unit_price_cents"]
    if customer is not None:
        if customer["open_balance_cents"] + ship_value > customer["credit_limit_cents"]:
            if order["status"] in ("ACKNOWLEDGED", "PARTIALLY_SHIPPED"):
                order["status"] = "ON_HOLD"
                touch_order(order)
            raise ApiError(
                E.ERR_CREDIT_LIMIT_EXCEEDED, 402, "Ship would exceed the credit limit."
            )

    # ---- commit ----
    for lot, take in pick:
        if substitute_part_id:
            lot["qty_on_hand"] -= take
        else:
            lot["qty_reserved"] -= take
        lot["qty_shipped"] += take
        lot["updated_at"] = stamp_now()
        lot["version"] += 1
        maybe_deplete_lot(lot)

    line["shipped_qty"] += qty
    line["allocated_qty"] -= qty
    line["last_shipped_at"] = stamp_clock()
    line["_last_shipped_at"] = now
    if line["shipped_qty"] >= line["quantity"]:
        line["status"] = "SHIPPED"
    line["updated_at"] = stamp_now()
    line["version"] += 1

    if customer is not None:
        customer["open_balance_cents"] += ship_value
        customer["updated_at"] = stamp_now()
        customer["version"] += 1

    # ship-and-debit claim genesis
    today = now.date()
    candidates = [
        r
        for r in db.design_registrations.values()
        if r["customer_id"] == order["customer_id"]
        and r["part_id"] == shipped_part["id"]
        and r["status"] == "APPROVED"
        and r["_valid_from"] <= today <= r["_valid_to"]
        and r["registered_qty_remaining"] > 0
    ]
    candidates.sort(key=lambda r: (r["_valid_from"], r["created_at"], r["_seq"]))
    if candidates:
        reg = candidates[0]
        covered = min(qty, reg["registered_qty_remaining"])
        if covered > 0:
            claim_now = stamp_now()
            claim = {
                "id": mint_id(),
                "registration_id": reg["id"],
                "order_line_id": line["id"],
                "qty": covered,
                "standard_cost_cents": shipped_part["standard_cost_cents"],
                "registered_cost_cents": reg["registered_cost_cents"],
                "amount_provisional_cents": covered
                * (shipped_part["standard_cost_cents"] - reg["registered_cost_cents"]),
                "audited_cost_cents": None,
                "amount_final_cents": None,
                "status": "SUBMITTED",
                "created_at": claim_now,
                "updated_at": claim_now,
                "version": 1,
                "_seq": _next_seq(),
            }
            db.claims[claim["id"]] = claim
            reg["registered_qty_remaining"] -= covered
            if reg["registered_qty_remaining"] == 0:
                reg["status"] = "EXHAUSTED"
            reg["updated_at"] = claim_now
            reg["version"] += 1

    # order auto-transitions
    if order["status"] == "ACKNOWLEDGED":
        order["status"] = "PARTIALLY_SHIPPED"
    maybe_complete_order(order)
    recompute_order_totals(order, bump=True)
    recompute_part_availability(line["part_id"])
    if substitute_part_id and substitute_part_id != line["part_id"]:
        recompute_part_availability(substitute_part_id)

    return success(serialize_order_line(line), status=200)


# ---------------------------------------------------------------------------
# order line listing
# ---------------------------------------------------------------------------

@bp.get("/order-lines")
def list_order_lines():
    require_auth()
    limit, offset = pagination_params()
    order_id = request.args.get("order_id")
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    items = list(db.order_lines.values())
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    if part_id is not None:
        items = [l for l in items if l["part_id"] == part_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_order_line(l) for l in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/order-lines/<lineId>")
def get_order_line(lineId):
    require_auth()
    line = get_order_line_or_404(lineId)
    return success(serialize_order_line(line), status=200)
