"""Inventory truth, seat occupancy and the guards that gate a checkout."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_availability,
    setup_onsale_event, setup_reserved_onsale_event,
    create_buyer, create_held_order, place_order, order_item_payload,
    setup_paid_order, set_clock, event_version, read_event, read_order,
    read_ticket_type, read_seat_block, attendees_of,
    make_buyer_headers,
)


# ---------------------------------------------------------------------------
# The sibling event's status decides the order
# ---------------------------------------------------------------------------

def test_order_refused_while_the_event_is_paused():
    """PRD §3.4: "Selling is only open while the event is `ONSALE`; an order
    attempted against an event in any other status is rejected with
    `ERR_EVENT_NOT_ONSALE`."

    Design: Difficulty/cross_entity_state_dependency/order_creation_gated_by_event_status_onsale
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Gatekeeper Night", "starts_at": "2026-08-25T18:00:00Z",
                         "ends_at": "2026-08-25T22:00:00Z"})
    paused = validate_success(api_client.pause_event(ctx["event_id"], ctx["org_headers"]), 200)
    buyer = create_buyer(email="pat@example.com", display_name="Pat")

    # Capacity is ample and the version is fresh, so only the sibling state can bite.
    resp = place_order(ctx, buyer, [order_item_payload(ctx["tt_id"], 2)],
                       expected_event_version=paused["version"])
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ONSALE.value, 409)

    assert read_ticket_type(ctx["tt_id"])["held_count"] == 0, \
        "A refused checkout holds no inventory"


def test_identical_order_succeeds_once_the_event_is_resumed():
    """PRD §3.2: "Pausing takes an event from `ONSALE` to `PAUSED` and requires the
    event to be `ONSALE`; resuming takes it from `PAUSED` back to `ONSALE`, requires
    the event to be `PAUSED`, and re-checks that `starts_at` is still strictly in the
    future, rejecting with `ERR_EVENT_START_IN_PAST` if the show has since begun."
    PRD §3.4: "Selling is only open while the event is `ONSALE`; an order attempted
    against an event in any other status is rejected with `ERR_EVENT_NOT_ONSALE`."

    Design: Difficulty/cross_entity_state_dependency/order_creation_gated_by_event_status_onsale
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Gatekeeper Night", "starts_at": "2026-08-25T18:00:00Z",
                         "ends_at": "2026-08-25T22:00:00Z"})
    paused = validate_success(api_client.pause_event(ctx["event_id"], ctx["org_headers"]), 200)
    buyer = create_buyer(email="pat2@example.com", display_name="Pat Two")
    validate_error(
        place_order(ctx, buyer, [order_item_payload(ctx["tt_id"], 2)],
                    expected_event_version=paused["version"]),
        ApiErrorId.ERR_EVENT_NOT_ONSALE.value, 409)

    resumed = validate_success(api_client.resume_event(ctx["event_id"], ctx["org_headers"]), 200)
    assert resumed["status"] == "ONSALE"

    order = validate_success(place_order(
        ctx, buyer, [order_item_payload(ctx["tt_id"], 2)],
        expected_event_version=resumed["version"]), 201)
    assert order["fulfillment_status"] == "HELD"
    assert order["subtotal_cents"] == 10000
    assert order["buyer_total_cents"] == 10728


# ---------------------------------------------------------------------------
# Seat occupancy across the half-open hold interval
# ---------------------------------------------------------------------------

def test_seat_held_by_a_live_hold_is_unavailable():
    """PRD §3.4: "Each requested seat must additionally be free at the current time:
    a seat is occupied when an admission with status `ISSUED`, `CHECKED_IN` or
    `TRANSFERRED` holds it, or when an order line of an order in `HELD` fulfilment
    holds it across the half-open interval running from that order's `created_at` up
    to but not including its `hold_expires_at`. A request landing at exactly the held
    order's `hold_expires_at` therefore finds the seat free. A collision is rejected
    with `ERR_SEAT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/seat_occupancy_frees_exactly_at_hold_expiry_instant
    """
    ctx = setup_reserved_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Holdfast Night", "starts_at": "2026-08-28T18:00:00Z",
                         "ends_at": "2026-08-28T22:00:00Z"})
    first = create_buyer(email="rae@example.com", display_name="Rae")
    second = create_buyer(email="sam@example.com", display_name="Sam")

    held = create_held_order(ctx, first, quantity=1, seat_numbers=[3])
    assert held["hold_expires_at"].startswith("2026-07-05T10:15:00"), (
        "The hold deadline is fifteen minutes after the current time, got "
        f"{held['hold_expires_at']}")

    resp = place_order(ctx, second,
                       [order_item_payload(ctx["tt_id"], 1, ctx["sb_id"], [3])])
    validate_error(resp, ApiErrorId.ERR_SEAT_UNAVAILABLE.value, 409)
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 1


def test_seat_becomes_free_at_exactly_the_hold_expiry_instant():
    """PRD §3.4: "A request landing at exactly the held order's `hold_expires_at`
    therefore finds the seat free."
    PRD §3.4: "The `hold_expires_at` deadline is set to fifteen minutes after the
    current time, and the hold is live for as long as the current time is strictly
    before that instant."

    Design: Difficulty/resource_temporal_overlap/seat_occupancy_frees_exactly_at_hold_expiry_instant
    """
    ctx = setup_reserved_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Holdfast Night", "starts_at": "2026-08-28T18:00:00Z",
                         "ends_at": "2026-08-28T22:00:00Z"})
    first = create_buyer(email="rae2@example.com", display_name="Rae Two")
    second = create_buyer(email="sam2@example.com", display_name="Sam Two")
    create_held_order(ctx, first, quantity=1, seat_numbers=[3])
    observed_version = event_version(ctx["event_id"])

    set_clock("2026-07-05T10:15:00Z")

    order = validate_success(place_order(
        ctx, second, [order_item_payload(ctx["tt_id"], 1, ctx["sb_id"], [3])],
        expected_event_version=observed_version), 201)
    assert order["fulfillment_status"] == "HELD"
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 1, \
        "The lapsed hold no longer occupies the seat; only the new hold does"


# ---------------------------------------------------------------------------
# Conservation of seat occupancy across hold then release
# ---------------------------------------------------------------------------

def test_releasing_a_hold_returns_seats_taken_to_its_pre_hold_value():
    """PRD §3.5: "Releasing gives every reserved seat back, decrementing each
    affected block's `seats_taken` by the number of seat numbers the corresponding
    line held, recomputes the affected tiers' `held_count`, and — when the order
    carried a `promo_code_id` — hands the redemption back by decrementing that code's
    `uses_count` by 1."

    Design: Difficulty/compensating_invariant/seat_occupancy_count_conserved_across_hold_then_release
    """
    ctx = setup_reserved_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Conserve Night", "starts_at": "2026-08-30T18:00:00Z",
                         "ends_at": "2026-08-30T22:00:00Z"})
    buyer = create_buyer(email="tom@example.com", display_name="Tom")
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 0

    order = create_held_order(ctx, buyer, quantity=2, seat_numbers=[3, 4])
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 2

    released = validate_success(
        api_client.release_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert released["fulfillment_status"] == "EXPIRED"
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 0, \
        "Seat occupancy must return to its pre-hold value with no drift"


def test_released_order_leaves_no_admissions_and_frees_the_tier():
    """PRD §2.9: "Voided admissions and expired holds contribute to neither the sold
    nor the held quantity, so releasing a hold or voiding an admission genuinely
    returns capacity to the pool."
    PRD §3.5: "A buyer — or the organiser — may instead abandon the checkout, taking
    fulfilment from `HELD` to `EXPIRED`."

    Design: Difficulty/compensating_invariant/seat_occupancy_count_conserved_across_hold_then_release
    """
    ctx = setup_reserved_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Conserve Night", "starts_at": "2026-08-30T18:00:00Z",
                         "ends_at": "2026-08-30T22:00:00Z"})
    buyer = create_buyer(email="tom2@example.com", display_name="Tom Two")
    order = create_held_order(ctx, buyer, quantity=2, seat_numbers=[3, 4])

    validate_success(api_client.release_order(order["id"], make_buyer_headers(buyer["id"])), 200)

    tier = read_ticket_type(ctx["tt_id"])
    assert tier["held_count"] == 0, f"Expected held_count 0, got {tier['held_count']}"
    assert tier["sold_count"] == 0, f"Expected sold_count 0, got {tier['sold_count']}"
    assert_availability(tier, 10)

    rows, meta = validate_paginated(api_client.list_attendees(
        make_buyer_headers(buyer["id"]), params={"order_id": order["id"]}))
    assert meta["total_count"] == 0, \
        f"An abandoned checkout mints no admissions, got {meta['total_count']}"


# ---------------------------------------------------------------------------
# Capacity and per-buyer ceilings
# ---------------------------------------------------------------------------

def test_order_against_an_exhausted_tier_reports_sold_out():
    """PRD §2.9: "When the available quantity is exactly zero, the tier is sold out
    and the request is rejected with `ERR_SOLD_OUT`; when the available quantity is
    greater than zero but strictly less than the requested number, the request is
    rejected with `ERR_INSUFFICIENT_CAPACITY`."

    Design: Corner/errors/corner_sold_out_error_on_order_create
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Soldout Night", "starts_at": "2026-10-16T18:00:00Z",
                         "ends_at": "2026-10-16T22:00:00Z"},
        tier_overrides={"quantity_total": 1})
    setup_paid_order(ctx, buyer=create_buyer(email="eda@example.com",
                                             display_name="Eda"), quantity=1)
    second = create_buyer(email="fen@example.com", display_name="Fen")

    resp = place_order(ctx, second, [order_item_payload(ctx["tt_id"], 1)])
    validate_error(resp, ApiErrorId.ERR_SOLD_OUT.value, 409)

    tier = read_ticket_type(ctx["tt_id"])
    assert tier["sold_count"] == 1
    assert_availability(tier, 0)


def test_buyer_ticket_ceiling_is_evaluated_across_the_whole_event():
    """PRD §3.4: "No buyer may hold more than ten live tickets for a single event.
    The count sums the `quantity` of every order line across that buyer's orders on
    the event whose fulfilment status is `HELD`, `ISSUED`, `CHECKED_IN_PARTIAL` or
    `CHECKED_IN_FULL`, plus the quantity now being requested; if that total would
    exceed ten, the request is rejected with `ERR_TICKET_LIMIT_EXCEEDED`."

    Design: Corner/validations/corner_buyer_ticket_limit_is_an_aggregate_validation
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Limit Night", "starts_at": "2026-10-08T18:00:00Z",
                         "ends_at": "2026-10-08T22:00:00Z"},
        tier_overrides={"quantity_total": 20})
    buyer = create_buyer(email="ula@example.com", display_name="Ula")

    # Twenty seats remain, so capacity is not the binding constraint.
    resp = place_order(ctx, buyer, [order_item_payload(ctx["tt_id"], 11)],
                       expected_event_version=ctx["event_version"])
    validate_error(resp, ApiErrorId.ERR_TICKET_LIMIT_EXCEEDED.value, 409)
    assert read_ticket_type(ctx["tt_id"])["held_count"] == 0


def test_reserved_line_with_too_few_seat_numbers_is_rejected():
    """PRD §3.4: "For a line on a `RESERVED` tier, `seat_block_id` is required and
    `seat_numbers` must list exactly as many seat numbers as the line's `quantity`;
    for a line on a `GA` tier, `seat_block_id` must be null and `seat_numbers` must be
    empty. Every requested seat number must fall inside the block's inclusive range
    from `seat_from` to `seat_to`. Any of those shape failures is rejected with
    `ERR_SEAT_RANGE_INVALID`."

    Design: Corner/validations/corner_seat_numbers_length_mismatch_returns_seat_range_invalid
    """
    ctx = setup_reserved_onsale_event(
        event_overrides={"title": "Range Night", "starts_at": "2026-10-09T18:00:00Z",
                         "ends_at": "2026-10-09T22:00:00Z"})
    buyer = create_buyer(email="vin@example.com", display_name="Vin")

    resp = place_order(ctx, buyer,
                       [order_item_payload(ctx["tt_id"], 2, ctx["sb_id"], [1])],
                       expected_event_version=ctx["event_version"])
    validate_error(resp, ApiErrorId.ERR_SEAT_RANGE_INVALID.value, 422)
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 0


def test_availability_ignores_a_hold_whose_deadline_has_passed():
    """PRD §2.9: "The held quantity for a tier is the sum of two things: the
    quantities on order lines belonging to orders whose fulfilment status is `HELD`
    and whose hold deadline is still in the future, plus the requested quantities of
    waitlist entries on that tier whose status is `OFFERED` and whose offer deadline
    is still in the future."

    Design: Corner/calculations/corner_availability_excludes_expired_holds
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Expiry Night", "starts_at": "2026-10-04T18:00:00Z",
                         "ends_at": "2026-10-04T22:00:00Z"},
        tier_overrides={"quantity_total": 1})
    first = create_buyer(email="ora@example.com", display_name="Ora")
    second = create_buyer(email="pip@example.com", display_name="Pip")
    create_held_order(ctx, first, quantity=1)
    observed_version = event_version(ctx["event_id"])

    set_clock("2026-07-05T10:16:00Z")

    order = validate_success(place_order(
        ctx, second, [order_item_payload(ctx["tt_id"], 1)],
        expected_event_version=observed_version), 201)
    assert order["fulfillment_status"] == "HELD"
    assert order["subtotal_cents"] == 5000

    tier = read_ticket_type(ctx["tt_id"])
    assert tier["held_count"] == 1, \
        f"Only the live hold counts against the tier, got {tier['held_count']}"
    assert tier["sold_count"] == 0


# ---------------------------------------------------------------------------
# Optimistic concurrency and listing
# ---------------------------------------------------------------------------

def test_stale_expected_event_version_on_order_create_is_rejected():
    """PRD §2.7: "A `POST /api/orders` request must carry `expected_event_version` as
    a required input field, holding the `version` of the target `Event` as the client
    last observed it. If that value does not equal the event's current `version`, the
    create is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/corner_stale_expected_event_version_on_order_create_returns_412
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Occ Night", "starts_at": "2026-10-23T18:00:00Z",
                         "ends_at": "2026-10-23T22:00:00Z"})
    first = create_buyer(email="lyn@example.com", display_name="Lyn")
    second = create_buyer(email="moss@example.com", display_name="Moss")
    published_version = ctx["event_version"]

    # The first checkout consumes that version and advances the event.
    create_held_order(ctx, first, quantity=1, expected_event_version=published_version)

    stale = place_order(ctx, second, [order_item_payload(ctx["tt_id"], 1)],
                        expected_event_version=published_version)
    validate_error(stale, ApiErrorId.ERR_STALE_EVENT_VERSION.value, 412)

    fresh_version = read_event(ctx["event_id"])["version"]
    retried = validate_success(place_order(
        ctx, second, [order_item_payload(ctx["tt_id"], 1)],
        expected_event_version=fresh_version), 201)
    assert retried["fulfillment_status"] == "HELD"

    rows, meta = validate_paginated(api_client.list_orders(
        ctx["org_headers"], params={"event_id": ctx["event_id"]}))
    assert meta["total_count"] == 2, \
        f"Only the two accepted checkouts persist, got {meta['total_count']}"


def test_order_listing_filters_by_buyer_then_paginates():
    """PRD §3.4: "Orders can be read individually and listed with optional
    `event_id`, `buyer_id`, `promo_code_id`, `payment_status` and
    `fulfillment_status` filters; an order that does not resolve yields
    `ERR_ORDER_NOT_FOUND`."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` — the number of records matching the filters before the window is
    applied — and `has_more`, which is true exactly when records remain beyond the
    current window."

    Design: Corner/cross_cutting_layers/corner_orders_list_filters_and_paginates_together
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Filter Night", "starts_at": "2026-10-24T18:00:00Z",
                         "ends_at": "2026-10-24T22:00:00Z"},
        tier_overrides={"quantity_total": 20})
    first = create_buyer(email="opal@example.com", display_name="Opal")
    second = create_buyer(email="pax@example.com", display_name="Pax")
    create_held_order(ctx, first, quantity=1)
    create_held_order(ctx, first, quantity=1)
    create_held_order(ctx, second, quantity=1)

    rows, meta = validate_paginated(api_client.list_orders(
        make_buyer_headers(first["id"]),
        params={"buyer_id": first["id"], "limit": 1, "offset": 0}))

    assert meta["total_count"] == 2, \
        f"The filter counts only the first buyer's orders, got {meta['total_count']}"
    assert meta["has_more"] is True, "A one-row window over two rows leaves more behind"
    assert len(rows) == 1, f"Expected a single-row window, got {len(rows)}"
    assert all(row["buyer_id"] != second["id"] for row in rows), \
        "The other buyer's order must not leak through the filter"
