"""Advanced state-machine behaviour.

Cyclic guarantee-claim negotiation rounds, parallel payment/delivery axes, and
cross-entity state preconditions on payout release and listing activation
(PRD §3.3, §3.4, §3.5, §3.6, §3.7).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS, make_seller_headers, make_buyer_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


# ==========================================================================
# non_linear_state_machine
# ==========================================================================
def test_guarantee_claim_cyclic_offer_reject_round_increment(api):
    """PRD §3.7: "Rejecting the offer returns the claim from `REPLACEMENT_OFFERED`
    to `INVESTIGATING` and increments the claim's `round_number` by 1 — this is
    the negotiation back-edge, and the cycle may repeat."

    Design: Difficulty/non_linear_state_machine/guarantee_claim_cyclic_offer_reject_round_increment
    """
    ctx = fx.setup_delivery_failed_with_claim(quantity=2, reason="NOT_DELIVERED")
    repl_listing, _ = fx.setup_replacement_listing(ctx, seat_count=2)
    claim_id = ctx["claim"]["id"]
    buyer_h = make_buyer_headers(ctx["buyer_id"])

    # Cycle 1: offer then reject.
    get_success_data(api.offer_replacement(claim_id, {"offered_listing_id": repl_listing["id"]}, TRUST))
    get_success_data(api.reject_offer(claim_id, buyer_h))
    # Cycle 2: offer then reject.
    get_success_data(api.offer_replacement(claim_id, {"offered_listing_id": repl_listing["id"]}, TRUST))
    final = validate_success(api.reject_offer(claim_id, buyer_h))

    assert final["status"] == "INVESTIGATING"
    assert final["round_number"] == 2, \
        f"two reject cycles → round_number 2, got {final['round_number']}"


def test_order_parallel_payment_and_delivery_axes_evolve_independently(api):
    """PRD §3.6: "Delivery runs on the order's `delivery_status` axis, which moves
    independently of the payment axis."
    PRD §3.6: "Sending sets the transfer's `deadline_at` and moves the order's
    `delivery_status` from `AWAITING` or `DELIVERY_FAILED` to `IN_TRANSFER`."
    PRD §3.4: "in every other case the rollup is `OPEN`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_delivery_axes_evolve_independently
    """
    ctx = fx.setup_charged_order(quantity=1, seat_count=1)
    order = ctx["order"]
    seller_h = make_seller_headers(ctx["seller_id"])
    buyer_h = make_buyer_headers(ctx["buyer_id"])
    assert order["payment_status"] == "CHARGED"
    assert order["delivery_status"] == "AWAITING"

    transfer = get_success_data(api.initiate_transfer(order["id"], seller_h))
    get_success_data(api.send_transfer(transfer["id"], seller_h))

    after = validate_success(api.get_order(order["id"], buyer_h))
    assert after["payment_status"] == "CHARGED", "send must not touch the payment axis"
    assert after["delivery_status"] == "IN_TRANSFER"
    assert after["lifecycle_state"] == "OPEN", \
        "lifecycle stays OPEN until both axes resolve"


# ==========================================================================
# cross_entity_state_dependency
# ==========================================================================
def test_payout_release_requires_order_delivered(api):
    """PRD §3.5: "Confirming the delivery window requires that the payout is
    `ESCROWED` and that the order's `delivery_status` is `DELIVERED` — a payout
    cannot be released until the buyer has actually received the seats."

    Design: Difficulty/cross_entity_state_dependency/payout_release_requires_order_delivered
    """
    ctx = fx.setup_charged_order(quantity=1, seat_count=1)
    order = ctx["order"]
    seller_h = make_seller_headers(ctx["seller_id"])
    buyer_h = make_buyer_headers(ctx["buyer_id"])

    transfer = get_success_data(api.initiate_transfer(order["id"], seller_h))
    get_success_data(api.send_transfer(transfer["id"], seller_h))  # delivery IN_TRANSFER

    in_transfer = validate_success(api.get_order(order["id"], buyer_h))
    assert in_transfer["delivery_status"] == "IN_TRANSFER"

    resp = api.confirm_delivery_window(order["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_listing_activate_requires_event_on_sale(api):
    """PRD §3.3: "Activation moves a `DRAFT` listing to `ACTIVE`. The preconditions
    are that the listing is `DRAFT`, that the event is currently `ON_SALE` or
    `LAST_MINUTE` (a non-selling event yields `ERR_EVENT_NOT_SELLING`)."

    Design: Difficulty/cross_entity_state_dependency/listing_activate_requires_event_on_sale
    """
    # Event left SCHEDULED (sales not opened).
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1, open_for_sale=False)
    listing = fx.create_draft_listing(base["event_id"], base["seller_id"], base["section_id"])
    fx.add_seats(listing["id"], base["seller_id"], 1, barcode_prefix="AC")

    event = validate_success(api.get_event(base["event_id"], ADMIN))
    assert event["status"] == "SCHEDULED"

    resp = api.activate_listing(listing["id"], make_seller_headers(base["seller_id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SELLING.value)


# ==========================================================================
# Companion tests (second test per Difficulty instance)
# ==========================================================================
def test_guarantee_claim_single_reject_round_is_one(api):
    """PRD §3.7: "Rejecting the offer returns the claim from `REPLACEMENT_OFFERED`
    to `INVESTIGATING` and increments the claim's `round_number` by 1 — this is
    the negotiation back-edge, and the cycle may repeat."

    Design: Difficulty/non_linear_state_machine/guarantee_claim_cyclic_offer_reject_round_increment
    """
    ctx = fx.setup_delivery_failed_with_claim(quantity=2, reason="NOT_DELIVERED")
    repl_listing, _ = fx.setup_replacement_listing(ctx, seat_count=2)
    claim_id = ctx["claim"]["id"]
    buyer_h = make_buyer_headers(ctx["buyer_id"])
    assert ctx["claim"]["round_number"] == 0, "a new claim starts with round_number 0"

    get_success_data(api.offer_replacement(claim_id, {"offered_listing_id": repl_listing["id"]}, TRUST))
    after = validate_success(api.reject_offer(claim_id, buyer_h))
    assert after["status"] == "INVESTIGATING"
    assert after["round_number"] == 1, \
        f"one reject cycle → round_number 1, got {after['round_number']}"


def test_order_payment_axis_unaffected_by_transfer_initiation(api):
    """PRD §3.6: "Delivery runs on the order's `delivery_status` axis, which moves
    independently of the payment axis."
    PRD §3.4: "in every other case the rollup is `OPEN`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_delivery_axes_evolve_independently
    """
    ctx = fx.setup_charged_order(quantity=1, seat_count=1)
    order = ctx["order"]
    seller_h = make_seller_headers(ctx["seller_id"])
    buyer_h = make_buyer_headers(ctx["buyer_id"])

    # Initiate only (no send) → delivery stays AWAITING, payment stays CHARGED.
    get_success_data(api.initiate_transfer(order["id"], seller_h))
    after = validate_success(api.get_order(order["id"], buyer_h))
    assert after["payment_status"] == "CHARGED"
    assert after["delivery_status"] == "AWAITING", "initiate alone must not advance delivery"
    assert after["lifecycle_state"] == "OPEN"


def test_payout_release_succeeds_once_order_delivered(api):
    """PRD §3.5: "A payout moves from `ESCROWED` to `RELEASABLE` either when an
    admin confirms the delivery window on the order or as the second hop of the
    event-complete cascade. Confirming the delivery window requires that the
    payout is `ESCROWED` and that the order's `delivery_status` is `DELIVERED`."

    Design: Difficulty/cross_entity_state_dependency/payout_release_requires_order_delivered
    """
    ctx = fx.setup_charged_order(quantity=1, seat_count=1)
    order = ctx["order"]
    seller_h = make_seller_headers(ctx["seller_id"])
    buyer_h = make_buyer_headers(ctx["buyer_id"])

    transfer = get_success_data(api.initiate_transfer(order["id"], seller_h))
    get_success_data(api.send_transfer(transfer["id"], seller_h))
    get_success_data(api.accept_transfer(transfer["id"], buyer_h))  # delivery DELIVERED

    delivered = validate_success(api.get_order(order["id"], buyer_h))
    assert delivered["delivery_status"] == "DELIVERED"

    validate_success(api.confirm_delivery_window(order["id"], ADMIN))
    payout = fx.get_payout_for_order(order["id"])
    assert payout["status"] == "RELEASABLE", \
        f"payout releasable once delivered, got {payout['status']}"


def test_listing_activate_succeeds_when_event_on_sale(api):
    """PRD §3.3: "Activation moves a `DRAFT` listing to `ACTIVE`. The preconditions
    are that the listing is `DRAFT`, that the event is currently `ON_SALE` or
    `LAST_MINUTE` (a non-selling event yields `ERR_EVENT_NOT_SELLING`), that the
    listing has at least one seat (its `total_seat_count` is 1 or more), and that
    the seller's `trust_tier` is not `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/listing_activate_requires_event_on_sale
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1, open_for_sale=True)
    listing = fx.create_draft_listing(base["event_id"], base["seller_id"], base["section_id"])
    fx.add_seats(listing["id"], base["seller_id"], 1, barcode_prefix="ACOK")

    activated = validate_success(
        api.activate_listing(listing["id"], make_seller_headers(base["seller_id"])))
    assert activated["status"] == "ACTIVE", \
        "DRAFT listing activates once its event is ON_SALE"
