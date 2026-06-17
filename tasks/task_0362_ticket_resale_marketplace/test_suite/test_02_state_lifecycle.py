"""State-machine transitions, initial/terminal states, side effects, and
inventory/uniqueness errors.

Listing/event/order/transfer/claim lifecycle transitions plus the seat-addable,
open-claim, and idempotency constraint errors (PRD §3.1, §3.3, §3.4, §3.6, §3.7,
§2.10).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS, make_seller_headers, make_buyer_headers,
    assert_listing,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


# ==========================================================================
# state_machines section
# ==========================================================================
def test_charge_already_charged_order_returns_invalid_state(api):
    """PRD §3.4: "Charging commits the purchase, moving `payment_status` from
    `PENDING` to `CHARGED`. The preconditions are that the order is `PENDING`."

    Design: Corner/state_machines/charge_already_charged_order_returns_invalid_state
    """
    ctx = fx.setup_charged_order(quantity=1, seat_count=1)
    resp = api.charge_order(ctx["order"]["id"], make_buyer_headers(ctx["buyer_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_newly_created_listing_starts_in_draft(api):
    """PRD §3.3: "A `Seller` creates a `Listing` in `DRAFT` by supplying the
    `event_id` the tickets are for, their own `seller_id`, the `section_id` the
    seats belong to."
    PRD §2.4: "`version`, an integer that begins at 1 and increments by exactly 1
    on every mutation of that resource."

    Design: Corner/state_machines/newly_created_listing_starts_in_draft
    """
    base = fx.setup_catalog(open_for_sale=False)
    listing = fx.create_draft_listing(base["event_id"], base["seller_id"], base["section_id"])
    assert_listing(listing)
    assert listing["status"] == "DRAFT"
    assert listing["version"] == 1


def test_transfer_recall_returns_order_delivery_to_awaiting(api):
    """PRD §3.6: "the seller may recall a `SENT` credential before the buyer accepts
    it, moving the transfer to the terminal `RECALLED` status and returning the
    order's `delivery_status` to `AWAITING`."

    Design: Corner/state_machines/transfer_recall_returns_order_delivery_to_awaiting
    """
    ctx = fx.setup_charged_order(quantity=1, seat_count=1)
    seller_h = make_seller_headers(ctx["seller_id"])
    buyer_h = make_buyer_headers(ctx["buyer_id"])
    transfer = get_success_data(api.initiate_transfer(ctx["order"]["id"], seller_h))
    get_success_data(api.send_transfer(transfer["id"], seller_h))

    recalled = validate_success(api.recall_transfer(transfer["id"], seller_h))
    assert recalled["status"] == "RECALLED"
    order = validate_success(api.get_order(ctx["order"]["id"], buyer_h))
    assert order["delivery_status"] == "AWAITING"


def test_reservation_expiry_on_clock_advance_releases_seats(api):
    """PRD §2.10: "any reservation whose `reservation_expires_at` has passed is
    auto-refunded (its held seats return to the pool)."
    PRD §3.4: "Either way the order's `HELD` seats return to `AVAILABLE`,
    `available_seat_count` is restored, `Listing.version` increments, a listing
    that had gone `SOLD_OUT` returns to `ACTIVE`."

    Design: Corner/state_machines/reservation_expiry_on_clock_advance_releases_seats_bubble_up
    """
    fx.set_clock("2026-12-01T10:00:00.000Z")
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1,
                            doors_open_at="2027-06-01T19:00:00.000Z")
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="RE",
    )
    order = fx.reserve_order(listing["id"], base["buyer_id"], 1, listing["version"])
    buyer_h = make_buyer_headers(base["buyer_id"])

    fx.advance_clock(100000)  # well past reservation_expires_at

    order_after = validate_success(api.get_order(order["id"], buyer_h))
    listing_after = validate_success(api.get_listing(listing["id"], buyer_h))
    assert order_after["payment_status"] == "REFUNDED"
    assert listing_after["status"] == "ACTIVE"
    assert listing_after["available_seat_count"] == 1


def test_replacement_accept_resolves_claim_and_mints_zero_priced_order(api):
    """PRD §3.7: "a replacement `Order` is minted on the offered listing at a
    `locked_unit_price_cents` of 0 (the replacement is covered by the guarantee),
    already `CHARGED`, with its held seats moved to `SOLD`; the claim records the
    new order in `replacement_order_id`; the original order's `delivery_status`
    moves to `REPLACED` and its `SOLD` or `HELD` seats are voided; and the
    original `ESCROWED` payout is cancelled."

    Design: Corner/state_machines/replacement_accept_resolves_claim_and_mints_zero_priced_order
    """
    ctx = fx.setup_delivery_failed_with_claim(quantity=1, reason="NOT_DELIVERED")
    repl_listing, _ = fx.setup_replacement_listing(ctx, seat_count=1)
    claim_id = ctx["claim"]["id"]
    buyer_h = make_buyer_headers(ctx["buyer_id"])
    orig_seat = ctx["seats"][0]
    orig_payout = ctx["payout"]

    get_success_data(api.offer_replacement(claim_id, {"offered_listing_id": repl_listing["id"]}, TRUST))
    repl_version = fx.get_listing_version(repl_listing["id"], ctx["buyer_id"])

    resolved = validate_success(api.accept_offer(
        claim_id, {"expected_listing_version": repl_version}, buyer_h))
    assert resolved["status"] == "RESOLVED_REPLACED"
    replacement_order_id = resolved["replacement_order_id"]
    assert replacement_order_id

    orig_order = validate_success(api.get_order(ctx["order"]["id"], ADMIN))
    repl_order = validate_success(api.get_order(replacement_order_id, ADMIN))
    seat_after = validate_success(api.get_seat(orig_seat["id"], ADMIN))
    payout_after = validate_success(api.get_payout(orig_payout["id"], ADMIN))

    assert orig_order["delivery_status"] == "REPLACED"
    assert seat_after["status"] == "VOID"
    assert payout_after["status"] == "CANCELLED"
    assert repl_order["locked_unit_price_cents"] == 0, \
        f"replacement minted at locked price 0, got {repl_order['locked_unit_price_cents']}"


# ==========================================================================
# errors section (non-stub)
# ==========================================================================
def test_seat_not_addable_after_listing_active_returns_409(api):
    """PRD §3.3: "Seats are added to a listing one at a time, and only while the
    listing is still `DRAFT` — adding a seat to a listing in any other status is
    rejected with `ERR_SEAT_NOT_ADDABLE`."

    Design: Corner/errors/seat_not_addable_after_listing_active_returns_409
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2)
    seller_h = make_seller_headers(base["seller_id"])
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="SN",
    )
    resp = api.create_seat(
        F.create_seat_payload(listing["id"], row_label="1", seat_number=2, barcode_token="SN-X"),
        seller_h)
    validate_error(resp, ApiErrorId.ERR_SEAT_NOT_ADDABLE.value)


def test_open_claim_exists_blocks_second_claim_409(api):
    """PRD §3.7: "Only one open claim may exist per order at a time; filing a second
    while one is open is rejected with `ERR_OPEN_CLAIM_EXISTS`."

    Design: Corner/errors/open_claim_exists_blocks_second_claim_409
    """
    ctx = fx.setup_charged_order(quantity=1, seat_count=1)
    seller_h = make_seller_headers(ctx["seller_id"])
    buyer_h = make_buyer_headers(ctx["buyer_id"])
    transfer = get_success_data(api.initiate_transfer(ctx["order"]["id"], seller_h))
    get_success_data(api.fail_transfer(transfer["id"], seller_h))
    get_success_data(api.create_guarantee_claim(
        F.create_guarantee_claim_payload(ctx["order"]["id"], reason="NOT_DELIVERED"), buyer_h))

    resp = api.create_guarantee_claim(
        F.create_guarantee_claim_payload(ctx["order"]["id"], reason="INVALID_BARCODE"), buyer_h)
    validate_error(resp, ApiErrorId.ERR_OPEN_CLAIM_EXISTS.value)


def test_idempotency_conflict_same_key_different_params_409(api):
    """PRD §3.4: "Reusing an `idempotency_key` with different request parameters is
    rejected with `ERR_IDEMPOTENCY_CONFLICT`."

    Design: Corner/errors/idempotency_conflict_same_key_different_params_409
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=3)
    buyer_h = make_buyer_headers(base["buyer_id"])
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=3, barcode_prefix="ID",
    )
    first = F.create_order_payload(listing["id"], base["buyer_id"], listing["version"],
                                   quantity=1, idempotency_key="K1")
    get_success_data(api.create_order(first, buyer_h))
    lv1 = fx.get_listing_version(listing["id"], base["buyer_id"])

    second = F.create_order_payload(listing["id"], base["buyer_id"], lv1,
                                    quantity=2, idempotency_key="K1")
    resp = api.create_order(second, buyer_h)
    validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT.value)
