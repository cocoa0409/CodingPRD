"""Checkout, payment and hold release (PRD §3.4, §3.5)."""
from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import derive, lookup, pricing, serializers, workflow

bp = Blueprint("orders", __name__)


def _parse_items(payload):
    items = payload.get("items")
    if items is None:
        middleware.bad("items is required.")
    if not isinstance(items, list) or len(items) == 0:
        middleware.bad("items must be a non-empty array.")
    parsed = []
    for raw in items:
        if not isinstance(raw, dict):
            middleware.bad("each entry of items must be an object.")
        entry = {
            "ticket_type_id": middleware.req_string(raw, "ticket_type_id"),
            "quantity": middleware.req_int(raw, "quantity", minimum=1),
            "seat_block_id": middleware.opt_string(raw, "seat_block_id"),
        }
        seat_numbers = raw.get("seat_numbers")
        if seat_numbers is None:
            seat_numbers = []
        if not isinstance(seat_numbers, list):
            middleware.bad("seat_numbers must be an array of integers.")
        for number in seat_numbers:
            if isinstance(number, bool) or not isinstance(number, int):
                middleware.bad("seat_numbers must be an array of integers.")
        entry["seat_numbers"] = list(seat_numbers)
        parsed.append(entry)
    return parsed


@bp.route("/api/orders", methods=["POST"])
def create_order():
    actor = middleware.authenticate(["Buyer"])
    payload = middleware.body()

    # --- step 3: request shape --------------------------------------------
    event_id = middleware.req_string(payload, "event_id")
    buyer_id = middleware.req_string(payload, "buyer_id")
    items = _parse_items(payload)
    promo_code_str = middleware.opt_string(payload, "promo_code")
    expected_event_version = middleware.req_int(payload, "expected_event_version")

    # --- step 4: existence, in the declared internal order -----------------
    buyer = lookup.buyer(buyer_id)
    event = lookup.event(event_id)
    tiers = [lookup.ticket_type(entry["ticket_type_id"]) for entry in items]
    blocks = [
        lookup.seat_block(entry["seat_block_id"]) if entry["seat_block_id"] else None
        for entry in items
    ]
    promo = None
    if promo_code_str is not None:
        candidates = [
            p for p in db.store.promo_codes.values() if p["code"] == promo_code_str
        ]
        if not candidates:
            raise ApiError("ERR_PROMO_CODE_NOT_FOUND", "That promo code does not resolve.")
        scoped = [p for p in candidates if p["event_id"] == event["id"]]
        promo = scoped[0] if scoped else db.ordered(candidates)[0]

    # --- step 5: ownership -------------------------------------------------
    lookup.require_buyer_is(actor, buyer["id"])

    # --- step 6: state -----------------------------------------------------
    if event["status"] != "ONSALE":
        raise ApiError("ERR_EVENT_NOT_ONSALE", "The event is not on sale.")

    # --- step 7: temporal --------------------------------------------------
    now = db.now()
    if promo is not None:
        valid_from = db.parse_iso(promo["valid_from"])
        valid_until = db.parse_iso(promo["valid_until"])
        if not (valid_from <= now < valid_until):
            raise ApiError("ERR_PROMO_WINDOW_CLOSED", "The promo code is outside its window.")

    # --- step 8: referential ----------------------------------------------
    for entry, tier, block in zip(items, tiers, blocks):
        if tier["event_id"] != event["id"]:
            raise ApiError(
                "ERR_PROMO_EVENT_MISMATCH", "A ticket tier does not belong to this event."
            )
        if block is not None and block["ticket_type_id"] != tier["id"]:
            raise ApiError(
                "ERR_PROMO_EVENT_MISMATCH", "A seat block does not belong to the named tier."
            )
    if promo is not None and promo["event_id"] != event["id"]:
        raise ApiError("ERR_PROMO_EVENT_MISMATCH", "The promo code belongs to another event.")

    # --- step 10: structural constraints -----------------------------------
    requested_seats = {}
    for entry, tier, block in zip(items, tiers, blocks):
        if block is None or tier["seating_mode"] != "RESERVED":
            continue
        taken = derive.occupied_seats(block["id"])
        for number in entry["seat_numbers"]:
            if number in taken or number in requested_seats.get(block["id"], set()):
                raise ApiError("ERR_SEAT_UNAVAILABLE", "Seat %s is not available." % number)
            requested_seats.setdefault(block["id"], set()).add(number)

    for entry, tier, block in zip(items, tiers, blocks):
        if tier["seating_mode"] == "RESERVED":
            if block is None:
                raise ApiError(
                    "ERR_SEAT_RANGE_INVALID", "seat_block_id is required on a RESERVED tier."
                )
            if len(entry["seat_numbers"]) != entry["quantity"]:
                raise ApiError(
                    "ERR_SEAT_RANGE_INVALID", "seat_numbers must match the line quantity."
                )
            if len(set(entry["seat_numbers"])) != len(entry["seat_numbers"]):
                raise ApiError("ERR_SEAT_RANGE_INVALID", "seat_numbers must be distinct.")
            for number in entry["seat_numbers"]:
                if number < block["seat_from"] or number > block["seat_to"]:
                    raise ApiError(
                        "ERR_SEAT_RANGE_INVALID", "Seat %s is outside the block range." % number
                    )
        else:
            if block is not None or entry["seat_numbers"]:
                raise ApiError(
                    "ERR_SEAT_RANGE_INVALID",
                    "A GA line must not name a seat block or seat numbers.",
                )

    requested_total = sum(entry["quantity"] for entry in items)
    live = derive.buyer_live_ticket_count(buyer["id"], event["id"])
    if live + requested_total > C.MAX_TICKETS_PER_BUYER_PER_EVENT:
        raise ApiError(
            "ERR_TICKET_LIMIT_EXCEEDED",
            "A buyer may hold at most %d live tickets per event."
            % C.MAX_TICKETS_PER_BUYER_PER_EVENT,
        )

    # --- step 11: fiscal constraints ---------------------------------------
    per_tier = {}
    for entry, tier in zip(items, tiers):
        per_tier[tier["id"]] = per_tier.get(tier["id"], 0) + entry["quantity"]
    for tier in tiers:
        wanted = per_tier[tier["id"]]
        available = derive.tier_available(tier)
        if available == 0:
            raise ApiError("ERR_SOLD_OUT", "The tier is sold out.")
        if available < wanted:
            raise ApiError("ERR_INSUFFICIENT_CAPACITY", "Not enough tickets remain on the tier.")

    lines = []
    for entry, tier, block in zip(items, tiers, blocks):
        line = pricing.line_amounts(tier["price_cents"], entry["quantity"])
        line.update(
            {
                "ticket_type_id": tier["id"],
                "seat_block_id": block["id"] if block is not None else None,
                "quantity": entry["quantity"],
                "seat_numbers": entry["seat_numbers"],
            }
        )
        lines.append(line)
    subtotal = sum(line["line_face_cents"] for line in lines)

    discount = 0
    if promo is not None:
        if subtotal < C.PROMO_MIN_SUBTOTAL_CENTS:
            raise ApiError(
                "ERR_PROMO_NOT_APPLICABLE", "The order subtotal is below the promotional floor."
            )
        if derive.promo_uses(promo["id"]) >= promo["max_uses"]:
            raise ApiError("ERR_PROMO_EXHAUSTED", "The promo code has no redemptions left.")
        discount = pricing.discount_cents(subtotal, promo)

    # --- step 12: optimistic concurrency -----------------------------------
    if expected_event_version != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION")

    order = workflow.create_order(event, buyer, lines, promo=promo, discount=discount)
    return object_response(serializers.order(order), 201)


@bp.route("/api/orders/<order_id>", methods=["GET"])
def read_order(order_id):
    actor = middleware.authenticate(["Buyer", "Organizer", "FinanceOfficer", "PlatformAdmin"])
    record = lookup.order(order_id)
    lookup.require_buyer_is(actor, record["buyer_id"])
    lookup.require_organizer_owns_event(actor, lookup.event(record["event_id"]))
    return object_response(serializers.order(record))


@bp.route("/api/orders", methods=["GET"])
def list_orders():
    middleware.authenticate(["Buyer", "Organizer", "FinanceOfficer", "PlatformAdmin"])
    event_id = request.args.get("event_id")
    buyer_id = request.args.get("buyer_id")
    promo_code_id = request.args.get("promo_code_id")
    payment_status = middleware.query_enum("payment_status", C.PAYMENT_STATUSES)
    fulfillment_status = middleware.query_enum("fulfillment_status", C.FULFILLMENT_STATUSES)

    records = [
        o
        for o in db.store.orders.values()
        if (event_id is None or o["event_id"] == event_id)
        and (buyer_id is None or o["buyer_id"] == buyer_id)
        and (promo_code_id is None or o["promo_code_id"] == promo_code_id)
        and (payment_status is None or o["payment_status"] == payment_status)
        and (fulfillment_status is None or o["fulfillment_status"] == fulfillment_status)
    ]
    return paginate(db.ordered(records), serializers.order)


@bp.route("/api/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    actor = middleware.authenticate(["Buyer"])
    middleware.body()
    order = lookup.order(order_id)
    event = lookup.event(order["event_id"])
    buyer = lookup.buyer(order["buyer_id"])
    lookup.require_buyer_is(actor, order["buyer_id"])

    if event["status"] != "ONSALE":
        raise ApiError("ERR_EVENT_NOT_ONSALE", "The event is not on sale.")
    if order["payment_status"] != "PENDING" or order["fulfillment_status"] != "HELD":
        raise ApiError("ERR_ORDER_NOT_HELD", "The order is not a pending held order.")
    if db.now() >= db.parse_iso(order["hold_expires_at"]):
        raise ApiError("ERR_HOLD_EXPIRED", "The checkout hold has expired.")

    order["payment_status"] = "PAID"
    order["fulfillment_status"] = "ISSUED"
    order["paid_at"] = db.now_iso()
    workflow.mint_attendees(order, event, buyer)
    db.touch(order)

    organizer = db.store.organizers.get(event["organizer_id"])
    if organizer is not None:
        organizer["lifetime_gross_cents"] += order["organizer_gross_cents"]
        db.touch(organizer)

    derive.recompute_event_gross(event)
    derive.recompute_event_issued(event)

    return object_response(serializers.order(order))


@bp.route("/api/orders/<order_id>/release", methods=["POST"])
def release_order(order_id):
    actor = middleware.authenticate(["Buyer", "Organizer"])
    middleware.body()
    order = lookup.order(order_id)
    event = lookup.event(order["event_id"])
    lookup.require_buyer_is(actor, order["buyer_id"])
    lookup.require_organizer_owns_event(actor, event)

    if order["fulfillment_status"] != "HELD" or order["payment_status"] != "PENDING":
        raise ApiError("ERR_ORDER_NOT_HELD", "The order is not a pending held order.")

    order["fulfillment_status"] = "EXPIRED"
    db.touch(order)
    return object_response(serializers.order(order))


# ------------------------------------------------------------------ order items
@bp.route("/api/order-items/<order_item_id>", methods=["GET"])
def read_order_item(order_item_id):
    actor = middleware.authenticate(["Buyer", "Organizer", "FinanceOfficer", "PlatformAdmin"])
    record = lookup.order_item(order_item_id)
    order = lookup.order(record["order_id"])
    lookup.require_buyer_is(actor, order["buyer_id"])
    lookup.require_organizer_owns_event(actor, lookup.event(order["event_id"]))
    return object_response(serializers.order_item(record))


@bp.route("/api/order-items", methods=["GET"])
def list_order_items():
    middleware.authenticate(["Buyer", "Organizer", "FinanceOfficer", "PlatformAdmin"])
    order_id = request.args.get("order_id")
    ticket_type_id = request.args.get("ticket_type_id")
    seat_block_id = request.args.get("seat_block_id")
    records = [
        i
        for i in db.store.order_items.values()
        if (order_id is None or i["order_id"] == order_id)
        and (ticket_type_id is None or i["ticket_type_id"] == ticket_type_id)
        and (seat_block_id is None or i["seat_block_id"] == seat_block_id)
    ]
    return paginate(db.ordered(records), serializers.order_item)
