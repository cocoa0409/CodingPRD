from flask import Blueprint, request

import db
import clock
import validate
import response
import errors
from errors import err
from middleware import get_user_context, require_role, require_ownership
from services import lookup, serialize, paginate, calc, recompute, seat_ops, order_ops

bp = Blueprint("orders", __name__)

READ_ROLES = ("PlatformAdmin", "Seller", "Buyer", "TrustSafety")


def _split_ok(split_rule, quantity, available):
    if split_rule == "ANY":
        return True
    if split_rule == "PAIRS":
        return quantity % 2 == 0
    if split_rule == "WHOLE":
        return quantity == available
    return False


@bp.post("/orders")
def create_order():
    body = validate.get_json_body()
    listing_id = validate.require_string(body, "listing_id")
    buyer_id = validate.require_string(body, "buyer_id")
    quantity = validate.require_int(body, "quantity", minimum=1)
    expected_listing_version = validate.require_int(body, "expected_listing_version", minimum=0)
    applied_credit_cents = validate.require_int(
        body, "applied_credit_cents", required=False, minimum=0, default=0
    )
    idempotency_key = validate.require_string(body, "idempotency_key", required=False)
    replacement_of_order_id = validate.require_string(body, "replacement_of_order_id", required=False)

    user_id, role = get_user_context()
    require_role(role, ("Buyer",))

    # existence: listing -> buyer
    listing = lookup.get_listing(listing_id)
    buyer = lookup.get_buyer(buyer_id)

    # ownership: order belongs to acting buyer
    require_ownership(role, user_id, buyer_id)

    # referential: replacement_of_order_id (if given) must resolve
    if replacement_of_order_id is not None:
        lookup.get_order(replacement_of_order_id)

    # idempotency replay short-circuit: same key + identical params returns the
    # prior order (a success, not a failure), so it precedes business checks.
    params_sig = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "quantity": quantity,
        "applied_credit_cents": applied_credit_cents,
        "replacement_of_order_id": replacement_of_order_id,
    }
    if idempotency_key is not None:
        existing = db.idempotency_keys.get(idempotency_key)
        if existing is not None and existing["params"] == params_sig:
            prior = db.orders.get(existing["order_id"])
            if prior is not None:
                return response.object_response(serialize.public(prior), 201)

    # state: listing must be ACTIVE/SOLD_OUT and not frozen (priority 5)
    if listing["status"] == "FROZEN":
        raise err(errors.ERR_LISTING_FROZEN, "Listing is frozen")
    if listing["status"] not in ("ACTIVE", "SOLD_OUT"):
        raise err(errors.ERR_INVALID_STATE, "Listing is not available for reservation")

    # inventory/uniqueness (priority 8): seats, split rule, idempotency conflict
    available = listing["available_seat_count"]
    if quantity > available:
        raise err(errors.ERR_INSUFFICIENT_SEATS, "quantity exceeds available seats")
    if not _split_ok(listing["split_rule"], quantity, available):
        raise err(errors.ERR_SPLIT_RULE_VIOLATION, "quantity violates split_rule")
    if idempotency_key is not None:
        existing = db.idempotency_keys.get(idempotency_key)
        if existing is not None and existing["params"] != params_sig:
            raise err(errors.ERR_IDEMPOTENCY_CONFLICT,
                      "idempotency_key reused with different parameters")

    # fiscal: applied credit within wallet (priority 9)
    if applied_credit_cents > buyer["wallet_credit_cents"]:
        raise err(errors.ERR_INSUFFICIENT_WALLET_CREDIT,
                  "applied_credit_cents exceeds wallet balance")

    # OCC: expected_listing_version must match (evaluated last)
    if expected_listing_version != listing["version"]:
        raise err(errors.ERR_STALE_LISTING_VERSION, "Listing version is stale")

    # --- all preconditions passed; commit ---
    # refresh effective price (DYNAMIC depends on current scarcity) before locking
    section = db.sections.get(listing["section_id"])
    event = db.events.get(listing["event_id"])
    locked_unit_price = calc.effective_listing_price(listing, section, event)

    order = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "quantity": quantity,
        "payment_status": "PENDING",
        "delivery_status": "AWAITING",
        "lifecycle_state": "OPEN",
        "locked_unit_price_cents": locked_unit_price,
        "estimated_total_cents": 0,
        "final_total_cents": None,
        "buyer_fee_cents": 0,
        "applied_credit_cents": applied_credit_cents,
        "reservation_expires_at": order_ops.reservation_expiry(),
        "replacement_of_order_id": replacement_of_order_id,
        "_reached_charged": False,
    }
    db.stamp_create(order)

    # estimate variant: wallet AS OF reservation time
    fee, total, _applied = calc.buyer_charge(
        quantity, locked_unit_price, applied_credit_cents, buyer["wallet_credit_cents"]
    )
    order["buyer_fee_cents"] = fee
    order["estimated_total_cents"] = total

    db.orders[order["id"]] = order

    # allocate seats FIFO -> HELD
    seat_ops.allocate_fifo(listing, quantity, order["id"])
    recompute.recompute_listing(listing)
    db.touch(listing)  # explicit Listing.version += 1 on reservation per PRD §3.4
    recompute.recompute_event(event)

    if idempotency_key is not None:
        db.idempotency_keys[idempotency_key] = {"params": params_sig, "order_id": order["id"]}

    return response.object_response(serialize.public(order), 201)


@bp.get("/orders/<order_id>")
def get_order(order_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    order = lookup.get_order(order_id)
    return response.object_response(serialize.public(order), 200)


@bp.get("/orders")
def list_orders():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    listing_id = request.args.get("listing_id")
    buyer_id = request.args.get("buyer_id")
    replacement_of = request.args.get("replacement_of_order_id")
    records = list(db.orders.values())
    if listing_id is not None:
        records = [o for o in records if o["listing_id"] == listing_id]
    if buyer_id is not None:
        records = [o for o in records if o["buyer_id"] == buyer_id]
    if replacement_of is not None:
        records = [o for o in records if o.get("replacement_of_order_id") == replacement_of]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)


@bp.post("/orders/<order_id>/charge")
def charge(order_id):
    user_id, role = get_user_context()
    require_role(role, ("Buyer",))
    order = lookup.get_order(order_id)
    require_ownership(role, user_id, order["buyer_id"])
    order_ops.charge(order)
    return response.object_response(serialize.public(order), 200)


@bp.post("/orders/<order_id>/cancel-reservation")
def cancel_reservation(order_id):
    user_id, role = get_user_context()
    require_role(role, ("Buyer",))
    order = lookup.get_order(order_id)
    require_ownership(role, user_id, order["buyer_id"])
    order_ops.cancel_reservation(order)
    return response.object_response(serialize.public(order), 200)


@bp.post("/orders/<order_id>/confirm-delivery-window")
def confirm_delivery_window(order_id):
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin",))
    order = lookup.get_order(order_id)

    # find the order's ESCROWED payout; require delivery_status == DELIVERED
    payouts = [p for p in db.payouts.values() if p["order_id"] == order_id]
    escrowed = [p for p in payouts if p["status"] == "ESCROWED"]
    if not escrowed:
        raise err(errors.ERR_PAYOUT_NOT_RELEASABLE, "No escrowed payout to release")
    if order["delivery_status"] != "DELIVERED":
        raise err(errors.ERR_INVALID_STATE, "Order has not been delivered")

    for payout in escrowed:
        payout["status"] = "RELEASABLE"
        db.touch(payout)
        seller = db.sellers.get(payout["seller_id"])
        if seller is not None:
            recompute.recompute_seller(seller)

    return response.object_response(serialize.public(order), 200)
