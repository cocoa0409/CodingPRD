"""AggregatorOrder endpoints (PRD §3.5 - §3.8) and the logical clock."""
from datetime import datetime, timezone

from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import new_entity, touch, serialize, paginate, get_or_404
from services import inventory, calculations, routing
from validation import get_body, require_str, require_enum, require_int

bp = Blueprint("orders", __name__)

AGGREGATORS = {"DOORDASH", "UBER_EATS"}


def _resolve_line_items(line_items):
    """Resolve (menu_item, qty) pairs. Raises NOT_FOUND for unknown menu items
    (existence, priority 3) and INVALID_REQUEST for shape problems (priority 12,
    applied by the caller after existence). Returns list of (menu_item, qty)."""
    resolved = []
    for li in line_items:
        menu_item = store.menu_items[li["menu_item_id"]]
        resolved.append((menu_item, li["qty"]))
    return resolved


@bp.route("/orders", methods=["POST"])
def ingest_order():
    user_id, role = get_identity()
    require_role(role, ["AggregatorGateway"])
    body = get_body()
    # Pull raw fields; full field-shape validation (priority 12) is deferred to
    # after existence (3) and idempotency (4) per PRD §3.10.
    brand_id = body.get("brand_id")
    aggregator = body.get("aggregator")
    external_ref = body.get("external_ref")
    line_items = body.get("line_items")

    with store.lock:
        # ---- Priority 3: existence of body FKs (brand + menu items) ----
        # Resolve brand FK if present and a string.
        if isinstance(brand_id, str) and brand_id:
            get_or_404(store.brands, brand_id)
        # Resolve menu_item_id FKs if the line_items array is well-formed enough
        # to read them (existence before field-shape and before idempotency).
        if isinstance(line_items, list):
            for li in line_items:
                if isinstance(li, dict) and isinstance(li.get("menu_item_id"), str):
                    if li["menu_item_id"] not in store.menu_items:
                        raise errors.not_found()

        # ---- Priority 4: idempotency on (aggregator, external_ref) ----
        if (isinstance(aggregator, str) and isinstance(external_ref, str)):
            for o in store.orders.values():
                if o["aggregator"] == aggregator and o["external_ref"] == external_ref:
                    raise errors.duplicate_order()

        # ---- Priority 12: field-shape validation ----
        if not isinstance(brand_id, str) or not brand_id:
            raise errors.invalid_request("brand_id is required.")
        if aggregator not in AGGREGATORS:
            raise errors.invalid_request("aggregator must be one of %s." % sorted(AGGREGATORS))
        if not isinstance(external_ref, str) or not external_ref:
            raise errors.invalid_request("external_ref is required.")
        if not isinstance(line_items, list) or len(line_items) == 0:
            raise errors.invalid_request("line_items must be a non-empty array.")
        normalized = []
        for li in line_items:
            if not isinstance(li, dict):
                raise errors.invalid_request("each line_item must be an object.")
            mid = li.get("menu_item_id")
            qty = li.get("qty")
            if not isinstance(mid, str) or not mid:
                raise errors.invalid_request("line_item.menu_item_id is required.")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
                raise errors.invalid_request("line_item.qty must be an integer >= 1.")
            normalized.append({"menu_item_id": mid, "qty": qty})

        # ---- Create order; snapshot gross revenue at ingestion ----
        resolved = [(store.menu_items[li["menu_item_id"]], li["qty"]) for li in normalized]
        gross = calculations.order_gross_revenue(resolved)
        rec = new_entity("AggregatorOrder", {
            "brand_id": brand_id,
            "aggregator": aggregator,
            "external_ref": external_ref,
            "line_items": normalized,
            "routed_stall_id": None,
            "booking_id": None,
            "gross_revenue_cents": gross,
            "commission_cents": 0,
            "food_cost_cents": 0,
            "status": "INGESTED",
        })
        rec["_consumption"] = []
        rec["_booking_ids"] = []
        rec["_sold_out_flips"] = []
        store.orders[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "BrandOwner", "StallOperator", "AggregatorGateway"])
    with store.lock:
        rec = get_or_404(store.orders, oid)
        return object_response(serialize(rec))


@bp.route("/orders", methods=["GET"])
def list_orders():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "BrandOwner", "StallOperator"])
    with store.lock:
        recs = list(store.orders.values())
        brand_id = request.args.get("brand_id")
        routed_stall_id = request.args.get("routed_stall_id")
        booking_id = request.args.get("booking_id")
        status = request.args.get("status")
        if brand_id is not None:
            recs = [o for o in recs if o["brand_id"] == brand_id]
        if routed_stall_id is not None:
            recs = [o for o in recs if o["routed_stall_id"] == routed_stall_id]
        if booking_id is not None:
            recs = [o for o in recs if o["booking_id"] == booking_id]
        if status is not None:
            recs = [o for o in recs if o["status"] == status]
        items, limit, offset, total = paginate(recs)
        return array_response(items, limit, offset, total)


@bp.route("/orders/<oid>/route", methods=["POST"])
def route_order_endpoint(oid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    with store.lock:
        order = get_or_404(store.orders, oid)
        # State (priority 5).
        if order["status"] != "INGESTED":
            raise errors.invalid_state()
        # Brand listed-ness (priority 7).
        brand = store.brands.get(order["brand_id"])
        if brand is None or brand["status"] != "ACTIVE" or brand["availability"] != "LISTED":
            raise errors.brand_not_listed()
        # Resolve line items. Routing raises ERR_NO_ELIGIBLE_STALL (8) then
        # ERR_INSUFFICIENT_INVENTORY (10), and records the SOLD_OUT flips this
        # order caused (for later cancel compensation) on the order itself.
        resolved = [(store.menu_items[li["menu_item_id"]], li["qty"]) for li in order["line_items"]]
        routing.route_order(order, resolved)
        return object_response(serialize(order))


@bp.route("/orders/<oid>/reject", methods=["POST"])
def reject_order(oid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    with store.lock:
        order = get_or_404(store.orders, oid)
        if order["status"] != "INGESTED":
            raise errors.invalid_state()
        order["status"] = "REJECTED"
        touch(order)
        return object_response(serialize(order))


@bp.route("/orders/<oid>/start-prep", methods=["POST"])
def start_prep(oid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        order = get_or_404(store.orders, oid)
        # Ownership: operator of routed_stall_id. Check before state? PRD §2.1
        # ownership is priority 2 (before state priority 5). routed_stall_id may
        # be None if not yet routed; an unrouted order has no owning stall, so a
        # StallOperator cannot own it -> FORBIDDEN.
        if role == "StallOperator" and user_id != order["routed_stall_id"]:
            raise errors.forbidden()
        if order["status"] != "ROUTED":
            raise errors.invalid_state()
        order["status"] = "PREPARING"
        touch(order)
        return object_response(serialize(order))


@bp.route("/orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        order = get_or_404(store.orders, oid)
        if role == "StallOperator" and user_id != order["routed_stall_id"]:
            raise errors.forbidden()
        if order["status"] != "PREPARING":
            raise errors.invalid_state()
        # Finalize food cost from recorded consumption slices (chronological).
        order["food_cost_cents"] = calculations.order_food_cost(order.get("_consumption", []))
        # Credit brand ledger: net payout = gross - commission - food_cost.
        net = order["gross_revenue_cents"] - order["commission_cents"] - order["food_cost_cents"]
        brand = store.brands.get(order["brand_id"])
        if brand is not None:
            brand["ledger_balance_cents"] += net
            touch(brand)
        # Release the order's equipment booking(s) (HELD -> RELEASED).
        for bid in order.get("_booking_ids", []):
            booking = store.bookings.get(bid)
            if booking is not None and booking["status"] == "HELD":
                booking["status"] = "RELEASED"
                touch(booking)
        order["status"] = "FULFILLED"
        touch(order)
        return object_response(serialize(order))


@bp.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    body = get_body()
    with store.lock:
        order = get_or_404(store.orders, oid)
        # State (priority 5): cancel valid only from ROUTED or PREPARING.
        if order["status"] not in ("ROUTED", "PREPARING"):
            raise errors.invalid_state()
        # OCC (priority 11): expected_order_version required and must match.
        expected = body.get("expected_order_version")
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.invalid_request("expected_order_version is required and must be an integer.")
        if expected != order["version"]:
            raise errors.stale_version()
        # Compensation: restore inventory grams (each lot credited exact grams).
        inventory.restore_consumption(order)
        # Flip back SOLD_OUT items this order had flipped, if now makeable.
        stall_id = order["routed_stall_id"]
        for mid in order.get("_sold_out_flips", []):
            mi = store.menu_items.get(mid)
            if mi is None:
                continue
            inventory.reevaluate_availability(mi, stall_id)
        # Release the equipment booking(s) (HELD -> RELEASED).
        for bid in order.get("_booking_ids", []):
            booking = store.bookings.get(bid)
            if booking is not None and booking["status"] == "HELD":
                booking["status"] = "RELEASED"
                touch(booking)
        order["status"] = "CANCELLED"
        touch(order)
        return object_response(serialize(order))


# ---------------------------------------------------------------------------
# Logical clock control (PlatformOps only).
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    parsed = _parse_iso8601(to_iso)
    if parsed is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant.")
    with store.lock:
        store.clock_epoch_seconds = int(parsed.timestamp())
        return object_response(None)


def _parse_iso8601(s):
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
