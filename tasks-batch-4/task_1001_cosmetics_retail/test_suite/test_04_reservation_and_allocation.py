"""Reservation gates: store posture, sellability, stock, limited launches, pickup slots and points."""

from test_helpers import (
    ApiErrorId,
    assert_lot_counters,
    line,
    new_customer,
    read_customer,
    read_lot,
    read_order,
    read_variant,
    reserve,
    set_clock,
    setup_catalog,
    setup_draft_order,
    setup_full_bopis_slot,
    setup_limited_launch_catalog,
    validate_error,
    validate_success,
)

SLOT_14 = "2026-06-05T14:00:00Z"
SLOT_15 = "2026-06-05T15:00:00Z"


# ─── Cross-entity gate: the store's posture ───────────

def test_reserve_at_a_paused_store_is_rejected(api, admin_headers, associate_headers):
    """PRD §3.6: "The fulfilling store's `status` must be `ACTIVE`. Reserving at a
    `PAUSED` store fails with `ERR_STORE_NOT_ACTIVE` (HTTP 409)."

    The order's own state is a perfectly legal DRAFT; the reservation becomes illegal
    only because the Store row it points at was flipped to PAUSED after the draft was
    priced.

    Design: Difficulty/cross_entity_state_dependency/reserve_blocked_when_store_is_paused
    """
    ctx = setup_draft_order(quantity=1)
    validate_success(
        api.update_store(ctx["store"]["id"], {"status": "PAUSED"}, admin_headers)
    )

    resp = api.reserve_order(ctx["order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_STORE_NOT_ACTIVE.value)
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "DRAFT"


def test_reserve_at_a_paused_store_draws_no_inventory(
    api, admin_headers, associate_headers
):
    """PRD §3.6: "Before any unit moves, a series of gates is checked, in this order:"
    PRD §3.6: "The fulfilling store's `status` must be `ACTIVE`. Reserving at a
    `PAUSED` store fails with `ERR_STORE_NOT_ACTIVE` (HTTP 409)."

    The gate sits in front of the draw, so not a single unit may move.

    Design: Difficulty/cross_entity_state_dependency/reserve_blocked_when_store_is_paused
    """
    ctx = setup_draft_order(quantity=1)
    validate_success(
        api.update_store(ctx["store"]["id"], {"status": "PAUSED"}, admin_headers)
    )

    validate_error(
        api.reserve_order(ctx["order"]["id"], associate_headers),
        ApiErrorId.ERR_STORE_NOT_ACTIVE.value,
    )

    lot = read_lot(ctx["lot"]["id"])
    assert_lot_counters(lot, on_hand_units=10, reserved_units=0, sold_units=0)


def test_reserve_with_a_discontinued_variant_is_rejected(
    api, admin_headers, associate_headers
):
    """PRD §3.6: "Every sale line's variant `status` must be `ACTIVE`; a
    `DISCONTINUED` variant on the basket fails with `ERR_VARIANT_NOT_SELLABLE` (HTTP
    409)."

    Design: Corner/validations/reserve_with_a_discontinued_variant_returns_variant_not_sellable
    """
    ctx = setup_draft_order(quantity=1)
    validate_success(
        api.update_variant(
            ctx["variant"]["id"], {"status": "DISCONTINUED"}, admin_headers
        )
    )

    resp = api.reserve_order(ctx["order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_VARIANT_NOT_SELLABLE.value)
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "DRAFT"


def test_reserve_without_allow_partial_fails_on_short_stock(api, associate_headers):
    """PRD §3.6: "`allow_partial` defaults to false, and it decides what the system
    does when the shelf cannot cover the basket: with `allow_partial` false, a
    shortfall aborts the whole reservation; with `allow_partial` true, each sale line's
    `quantity` is instead clipped down to the units that can actually be drawn, and the
    reservation proceeds on the smaller basket."
    PRD §3.6: "The same `ERR_INSUFFICIENT_STOCK` applies when the general pool cannot
    cover an ordinary line and `allow_partial` is false."

    Design: Corner/calculations/insufficient_stock_when_allow_partial_is_false
    """
    catalog = setup_catalog(units_received=2)
    ctx = setup_draft_order(catalog=catalog, quantity=3)

    resp = api.reserve_order(ctx["order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "DRAFT"
    assert_lot_counters(read_lot(catalog["lot"]["id"]), on_hand_units=2, reserved_units=0)


# ─── Limited-launch allocation ────────────────────────

def test_launch_draw_exhausts_the_launch_pool_first(api, associate_headers):
    """PRD §3.6: "Gate three is the waterfall draw itself. The launch pool is exhausted
    before the general pool, never the reverse. From the lot at the order's store for
    this variant, the units taken from the launch pool are the smaller of the line's
    `quantity` and the lot's `launch_reserved_units`; whatever quantity remains after
    that must come from the general pool, whose size is the lot's `on_hand_units` less
    its `launch_reserved_units`."
    PRD §3.6: "On success the lot's `launch_reserved_units` is reduced by the units
    taken from the launch pool, `on_hand_units` is reduced by the whole drawn amount,
    and `reserved_units` is increased by the same drawn amount."

    Design: Corner/state_machines/reserve_side_effects_draw_launch_pool_before_general_pool
    """
    catalog = setup_limited_launch_catalog(
        units_received=5, launch_reserved_units=3, clock_to="2026-05-03T00:00:00Z"
    )
    assert catalog["variant"]["launch_status"] == "PUBLIC"

    ctx = setup_draft_order(catalog=catalog, quantity=2)
    validate_success(api.reserve_order(ctx["order"]["id"], associate_headers))

    lot = read_lot(catalog["lot"]["id"])
    assert lot["launch_reserved_units"] == 1, (
        "2 of the 3 earmarked units are drawn before the general pool is touched"
    )
    assert_lot_counters(lot, on_hand_units=3, reserved_units=2)


def test_clock_advance_steps_launch_status_through_every_window(api, admin_headers):
    """PRD §2.4: "The server boots with its logical clock set to exactly
    `2026-05-01T00:00:00Z`, and that instant remains "now" until a
    `MerchandisingAdmin` moves it. Advancing the clock is done by supplying a target
    instant as `to_iso8601`; the response reports the resulting `current_utc` together
    with `advanced_variant_ids`, the list of variant identifiers whose launch gate
    moved as a consequence of the new time."
    PRD §3.6: "when a `MerchandisingAdmin` moves the clock forward, every limited
    variant whose thresholds the new instant has crossed is stepped through its gates
    in sequence — from `SCHEDULED` to `TIER_ROUGE_ONLY` once the clock reaches or
    passes `launch_open_rouge_at`, on to `TIER_VIB_PLUS` once it reaches or passes
    `launch_open_vib_at`, and on to `PUBLIC` once it reaches or passes
    `launch_open_public_at`, always in that order — and each step increments the
    variant's `version`."

    Design: Corner/state_machines/clock_advance_walks_variant_launch_status_through_every_window
    """
    catalog = setup_limited_launch_catalog(units_received=10)
    variant = catalog["variant"]

    assert variant["launch_status"] == "SCHEDULED", (
        "created against the 2026-05-01T00:00:00Z boot clock, before any window opens"
    )

    set_clock("2026-05-01T01:00:00Z")
    assert read_variant(variant["id"])["launch_status"] == "TIER_ROUGE_ONLY", (
        "the gate opens once the clock reaches launch_open_rouge_at"
    )

    set_clock("2026-05-01T02:00:00Z")
    assert read_variant(variant["id"])["launch_status"] == "TIER_VIB_PLUS"

    advanced = set_clock("2026-05-02T00:00:00Z")
    assert read_variant(variant["id"])["launch_status"] == "PUBLIC"
    assert variant["id"] in advanced["advanced_variant_ids"]
    assert advanced["current_utc"].startswith("2026-05-02T00:00:00")


def test_reserve_before_any_launch_window_opens_is_rejected(api, associate_headers):
    """PRD §3.6: "Gate one is the tier window, read off the variant's `launch_status`.
    A variant still in `SCHEDULED` has not opened; a variant whose launch has been shut
    down to `CLOSED` will never open again; in both cases the line fails with
    `ERR_LAUNCH_NOT_OPEN` (HTTP 409)."

    Even a ROUGE customer is turned away while the gate is SCHEDULED — the window
    check precedes the tier check.

    Design: Corner/calculations/launch_reserve_before_any_window_opens_returns_launch_not_open
    """
    catalog = setup_limited_launch_catalog(
        units_received=10,
        variant_overrides={
            "launch_open_rouge_at": "2026-06-01T00:00:00Z",
            "launch_open_vib_at": "2026-06-02T00:00:00Z",
            "launch_open_public_at": "2026-06-03T00:00:00Z",
        },
    )
    customer = new_customer(initial_tier="ROUGE")
    ctx = setup_draft_order(customer=customer, catalog=catalog, quantity=1)

    resp = api.reserve_order(ctx["order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_LAUNCH_NOT_OPEN.value)
    assert read_variant(catalog["variant"]["id"])["launch_status"] == "SCHEDULED"


def test_insider_cannot_draw_a_rouge_only_launch(api, associate_headers):
    """PRD §3.6: "A variant in `TIER_ROUGE_ONLY` may only be drawn by a customer whose
    tier is `ROUGE`. A variant in `TIER_VIB_PLUS` may be drawn by a customer whose tier
    is `VIB` or `ROUGE`. A variant in `PUBLIC` may be drawn by any tier. A customer
    whose tier does not clear the currently open window is turned away with
    `ERR_LAUNCH_TIER_LOCKED` (HTTP 403)."

    Design: Corner/calculations/insider_blocked_from_rouge_only_launch_window
    """
    catalog = setup_limited_launch_catalog(
        units_received=10,
        clock_to="2026-06-01T10:00:00Z",
        variant_overrides={
            "launch_open_rouge_at": "2026-06-01T10:00:00Z",
            "launch_open_vib_at": "2026-06-02T10:00:00Z",
            "launch_open_public_at": "2026-06-03T10:00:00Z",
        },
    )
    assert catalog["variant"]["launch_status"] == "TIER_ROUGE_ONLY"

    ctx = setup_draft_order(catalog=catalog, quantity=1)  # a default INSIDER customer

    resp = api.reserve_order(ctx["order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_LAUNCH_TIER_LOCKED.value)


def test_launch_cap_admits_exactly_the_cap_and_rejects_one_more(api, associate_headers):
    """PRD §3.6: "Gate two is the per-customer cap. The system sums the quantities of
    every order line naming this variant across all of this customer's orders whose
    `fulfillment_status` is anything other than `CANCELLED`, **excluding the order now
    being reserved**. If that held count plus the quantity requested on this line
    exceeds the variant's `per_customer_cap`, the line fails with
    `ERR_LAUNCH_CAP_EXCEEDED` (HTTP 409). The boundary is inclusive in the customer's
    favour: held plus requested landing exactly on the cap is allowed."

    Design: Corner/calculations/launch_cap_allows_exactly_the_cap_and_rejects_one_more
    """
    catalog = setup_limited_launch_catalog(
        units_received=10, clock_to="2026-05-03T00:00:00Z"
    )
    customer = new_customer()

    first = setup_draft_order(customer=customer, catalog=catalog, quantity=1)
    reserve(first["order"]["id"])  # the customer now holds 1 unit of the cap-2 variant

    # 1 held + 1 requested == 2 == per_customer_cap: inclusive, so this is allowed.
    at_cap = setup_draft_order(customer=customer, catalog=catalog, quantity=1)
    ok = validate_success(api.reserve_order(at_cap["order"]["id"], associate_headers))
    assert ok["fulfillment_status"] == "RESERVED", (
        "held plus requested landing exactly on the cap is allowed"
    )

    # 2 held + 1 requested == 3 > per_customer_cap: rejected.
    over = setup_draft_order(customer=customer, catalog=catalog, quantity=1)
    validate_error(
        api.reserve_order(over["order"]["id"], associate_headers),
        ApiErrorId.ERR_LAUNCH_CAP_EXCEEDED.value,
    )


# ─── BOPIS pickup-slot occupancy ──────────────────────

def test_third_bopis_order_in_a_full_slot_is_rejected(api, associate_headers):
    """PRD §3.6: "For a `BOPIS` order, the requested collection slot must have room.
    Occupancy is a simple head-count, not a geometric overlap test: the system counts
    the orders at the same store carrying exactly the same `pickup_slot_start` whose
    `fulfillment_status` is `RESERVED` or `READY_FOR_PICKUP`. When that count has
    already reached the store's `bopis_slot_capacity`, the slot is full and the
    reservation fails with `ERR_PICKUP_SLOT_FULL` (HTTP 409). The boundary is
    inclusive: a store with a capacity of 2 accepts a third order only if one of the
    first two has left the slot."

    Design: Difficulty/resource_temporal_overlap/bopis_pickup_slot_is_an_aggregate_count_bucket_not_an_intersection
    """
    ctx = setup_full_bopis_slot(pickup_slot_start=SLOT_14, capacity=2)

    resp = api.reserve_order(ctx["pending_order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_PICKUP_SLOT_FULL.value)
    assert read_order(ctx["pending_order"]["id"])["fulfillment_status"] == "DRAFT"


def test_the_neighbouring_bopis_hour_is_a_separate_counter(api, associate_headers):
    """PRD §3.6: "Occupancy is a simple head-count, not a geometric overlap test: the
    system counts the orders at the same store carrying exactly the same
    `pickup_slot_start` whose `fulfillment_status` is `RESERVED` or
    `READY_FOR_PICKUP`."

    Two RESERVED orders fill the 14:00 bucket, yet the 15:00 bucket is untouched by
    them: the key is the exact `pickup_slot_start`, so there is no geometric
    intersection between neighbouring hours.

    Design: Difficulty/resource_temporal_overlap/bopis_pickup_slot_is_an_aggregate_count_bucket_not_an_intersection
    """
    ctx = setup_full_bopis_slot(pickup_slot_start=SLOT_14, capacity=2)

    next_hour = setup_draft_order(
        customer=ctx["customer"],
        catalog={k: ctx[k] for k in ("store", "product", "variant", "lot")},
        quantity=1,
        channel="BOPIS",
        pickup_slot_start=SLOT_15,
    )

    reserved = validate_success(
        api.reserve_order(next_hour["order"]["id"], associate_headers)
    )
    assert reserved["fulfillment_status"] == "RESERVED", (
        "the 15:00 bucket is a separate counter, unaffected by the full 14:00 hour"
    )

    validate_error(
        api.reserve_order(ctx["pending_order"]["id"], associate_headers),
        ApiErrorId.ERR_PICKUP_SLOT_FULL.value,
    )


def test_cancelling_a_reserved_order_frees_its_pickup_slot(api, associate_headers):
    """PRD §3.6: "the system counts the orders at the same store carrying exactly the
    same `pickup_slot_start` whose `fulfillment_status` is `RESERVED` or
    `READY_FOR_PICKUP`. When that count has already reached the store's
    `bopis_slot_capacity`, the slot is full and the reservation fails with
    `ERR_PICKUP_SLOT_FULL` (HTTP 409). The boundary is inclusive: a store with a
    capacity of 2 accepts a third order only if one of the first two has left the slot."

    Design: Corner/cross_cutting_layers/bopis_slot_counter_releases_when_a_reserved_order_is_cancelled
    """
    ctx = setup_full_bopis_slot(pickup_slot_start=SLOT_14, capacity=2)
    pending = ctx["pending_order"]

    validate_error(
        api.reserve_order(pending["id"], associate_headers),
        ApiErrorId.ERR_PICKUP_SLOT_FULL.value,
    )

    first = ctx["reserved_orders"][0]
    cancelled = validate_success(api.cancel_order(first["id"], associate_headers))
    assert cancelled["fulfillment_status"] == "CANCELLED"

    reserved = validate_success(api.reserve_order(pending["id"], associate_headers))
    assert reserved["fulfillment_status"] == "RESERVED", (
        "a CANCELLED order no longer occupies the slot, so the count drops to 1"
    )


# ─── Payload shape and the fiscal gates ───────────────

def test_points_redeemed_must_be_a_multiple_of_one_hundred(api, associate_headers):
    """PRD §3.6: "`points_redeemed` is how many of the buyer's points they wish to
    spend; it defaults to 0 and must be an exact multiple of 100 — anything else is
    `ERR_INVALID_REQUEST` at the time it is supplied."

    Design: Corner/validations/points_redeemed_not_a_multiple_of_100_returns_invalid_request
    """
    catalog = setup_catalog(units_received=10)
    customer = new_customer(initial_points=500)

    resp = api.create_order(
        {
            "customer_id": customer["id"], "store_id": catalog["store"]["id"],
            "channel": "SHIP_FROM_STORE", "points_redeemed": 150,
            "lines": [line(catalog["variant"]["id"], 1)],
        },
        associate_headers,
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    listed = api.list_orders(
        associate_headers, params={"customer_id": customer["id"]}
    ).json()
    assert listed["data"] == [], "the rejected order must not have been created"


def test_bopis_pickup_slot_must_land_on_the_hour(api, associate_headers):
    """PRD §3.5: "A `BOPIS` order must also carry a `pickup_slot_start`: the UTC
    instant a sixty-minute collection slot begins, and it must land exactly on the
    hour."
    PRD §2.9: "4. Payload shape — on every write, all required fields are present,
    every enum value is legal, every numeric field is in range, `points_redeemed` is an
    exact multiple of 100, a pickup order carries an on-the-hour `pickup_slot_start`,
    and a booked artist actually holds the skill being booked. Any breach is
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/bopis_order_without_on_the_hour_slot_returns_invalid_request
    """
    catalog = setup_catalog(units_received=10)
    customer = new_customer()

    resp = api.create_order(
        {
            "customer_id": customer["id"], "store_id": catalog["store"]["id"],
            "channel": "BOPIS", "pickup_slot_start": "2026-06-05T14:30:00Z",
            "lines": [line(catalog["variant"]["id"], 1)],
        },
        associate_headers,
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_redeeming_more_points_than_the_balance_is_rejected(api, associate_headers):
    """PRD §3.6: "The buyer must actually own the points they are spending: if
    `points_redeemed` exceeds the customer's `points_balance`, the reservation fails
    with `ERR_INSUFFICIENT_POINTS` (HTTP 422)."

    The check runs at reserve, not at create: the draft quote is accepted.

    Design: Corner/validations/redeeming_more_points_than_the_balance_returns_insufficient_points
    """
    catalog = setup_catalog(units_received=10)
    customer = new_customer(initial_points=500)
    ctx = setup_draft_order(
        customer=customer, catalog=catalog, quantity=4, points_redeemed=600
    )

    resp = api.reserve_order(ctx["order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)
    assert read_customer(customer["id"])["points_balance"] == 500, "unchanged"
    assert_lot_counters(read_lot(catalog["lot"]["id"]), on_hand_units=10, reserved_units=0)


def test_points_worth_more_than_the_basket_is_rejected(api, associate_headers):
    """PRD §3.6: "And points may not buy more than the basket is worth: if
    `points_value_cents` exceeds `discounted_subtotal_cents`, the reservation fails
    with `ERR_POINTS_EXCEED_SUBTOTAL` (HTTP 422)."

    The balance is ample (2000 points) but 400 points are worth 2000 cents against a
    1000-cent basket — a different fiscal gate from ERR_INSUFFICIENT_POINTS.

    Design: Corner/validations/points_value_exceeding_discounted_subtotal_returns_points_exceed_subtotal
    """
    catalog = setup_catalog(
        units_received=10,
        product_overrides={"name": "Mini Balm", "base_price_cents": 1000},
        variant_overrides={"shade_name": "Clear", "shade_code": "MB-01",
                           "finish": "DEWY", "undertone": "NEUTRAL",
                           "depth_index": 6, "price_cents": 1000},
    )
    customer = new_customer(initial_points=2000)
    ctx = setup_draft_order(
        customer=customer, catalog=catalog, quantity=1, points_redeemed=400
    )

    resp = api.reserve_order(ctx["order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_POINTS_EXCEED_SUBTOTAL.value)
    assert read_customer(customer["id"])["points_balance"] == 2000, (
        "no REDEEM entry was appended"
    )


# ─── Immediate consistency of the reserve response ────

def test_new_order_starts_draft_and_unpaid(api, associate_headers):
    """PRD §3.5: "The order is born with `fulfillment_status` of `DRAFT` and
    `payment_status` of `UNPAID`."
    PRD §3.5: "On the draft passes the value is `PROVISIONAL`: quantities are taken
    exactly as requested, stock is not consulted at all, `gwp_eligible` is advisory
    only, and **no** gift or sample line rows are created."

    Design: Corner/state_machines/order_starts_in_draft_and_unpaid
    """
    ctx = setup_draft_order(quantity=2)
    order = ctx["order"]

    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["pricing_variant"] == "PROVISIONAL"
    assert order["subtotal_cents"] == 5000, "2 units at 2500"

    assert_lot_counters(read_lot(ctx["lot"]["id"]), on_hand_units=10, reserved_units=0)


def test_reserve_response_carries_every_cascade_immediately(api, associate_headers):
    """PRD §3.6: "When every gate has passed, the reservation commits its effects."
    PRD §3.6: "Finally, if `points_redeemed` is greater than zero, a ledger entry of
    type `REDEEM` is appended carrying the negative of that number as its
    `delta_points`, and the customer's `points_balance` falls by the same amount. The
    order's `pricing_variant` becomes `FINAL` and its `version` increments."
    PRD §3.5: "Every whole block of 100 redeemed points is worth 500 cents, so
    `points_value_cents` is the number of 100-point blocks in `points_redeemed`
    multiplied by 500. `total_due_cents` is `discounted_subtotal_cents` less
    `points_value_cents`."

    Design: Corner/consistency_model/reserve_response_reflects_every_cascade_in_the_same_request
    """
    catalog = setup_catalog(units_received=10)
    customer = new_customer(initial_points=500)
    ctx = setup_draft_order(
        customer=customer, catalog=catalog, quantity=2, points_redeemed=300
    )

    reserved = validate_success(api.reserve_order(ctx["order"]["id"], associate_headers))

    assert reserved["pricing_variant"] == "FINAL"
    assert reserved["points_value_cents"] == 1500, "3 blocks of 100 points at 500 cents"
    assert reserved["total_due_cents"] == 3500, "5000 less 1500"

    assert read_customer(customer["id"])["points_balance"] == 200, (
        "the REDEEM debit is visible on the very next read"
    )
    lot = read_lot(catalog["lot"]["id"])
    assert_lot_counters(lot, on_hand_units=8, reserved_units=2)
