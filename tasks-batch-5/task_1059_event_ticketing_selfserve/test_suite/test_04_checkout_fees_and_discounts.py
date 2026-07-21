"""Composing an order: the platform fee ladder, the discount and the two totals."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_order, assert_order_item,
    setup_draft_event, setup_onsale_event, setup_reserved_onsale_event,
    create_ticket_type, create_promo_code, create_buyer, create_held_order,
    publish_event, place_order, order_item_payload, order_items_of,
    read_order, read_ticket_type, make_buyer_headers,
)


def _two_tier_onsale_event():
    """ONSALE event carrying a 1234-cent tier and a 7777-cent tier."""
    ctx = setup_draft_event(
        event_overrides={"title": "Mixed Tier Night", "starts_at": "2026-08-10T18:00:00Z",
                         "ends_at": "2026-08-10T22:00:00Z"},
        tier_overrides={"name": "Balcony", "tier_rank": 1, "price_cents": 1234,
                        "quantity_total": 10})
    ctx["tier_two"] = create_ticket_type(ctx["organizer"], ctx["event"], name="Floor",
                                         tier_rank=2, price_cents=7777,
                                         quantity_total=10)
    ctx["event"] = publish_event(ctx["organizer"], ctx["event"])
    ctx["event_version"] = ctx["event"]["version"]
    return ctx


# ---------------------------------------------------------------------------
# The pinned rounding order
# ---------------------------------------------------------------------------

def test_order_fee_total_rounds_per_ticket_then_multiplies_then_sums():
    """PRD §3.4: "Multiply the face value by the chosen rate, round that product half
    up to a whole cent, then add a flat component of 179 cents."
    PRD §3.4: "The alternative arrangement — summing face values across the order,
    applying the rate once, rounding once, and adding the flat component afterwards —
    is explicitly not the rule here, and yields a different cent total on any order
    mixing tiers at different prices. Round once per ticket, then multiply, then sum."

    Design: Difficulty/combinatorial_formula/fee_rounded_per_ticket_then_summed_across_mixed_price_lines
    """
    ctx = _two_tier_onsale_event()
    buyer = create_buyer(email="cal@example.com", display_name="Cal")

    order = validate_success(place_order(
        ctx, buyer,
        [order_item_payload(ctx["tt_id"], 3),
         order_item_payload(ctx["tier_two"]["id"], 2)],
        expected_event_version=ctx["event_version"]), 201)

    assert_order(order)
    assert order["subtotal_cents"] == 19256, \
        f"Expected subtotal 1234*3 + 7777*2 = 19256, got {order['subtotal_cents']}"
    assert order["fee_total_cents"] == 1546, (
        "Rounding per ticket then multiplying then summing gives 1546; rounding once "
        f"across the order would give 1545. Got {order['fee_total_cents']}")
    assert order["discount_cents"] == 0
    assert order["buyer_total_cents"] == 20802, \
        f"Expected 19256 - 0 + 1546 = 20802, got {order['buyer_total_cents']}"
    assert order["organizer_gross_cents"] == 19256, \
        f"Expected 19256 - 0 = 19256, got {order['organizer_gross_cents']}"


def test_mixed_price_lines_each_expose_their_own_rounded_fee():
    """PRD §3.4: "The line's `line_face_cents` is `unit_price_cents` multiplied by
    `quantity`; the line's `line_fee_cents` is the **already rounded**
    `per_ticket_fee_cents` multiplied by `quantity`."
    PRD §3.4: "For each line, take the face value snapshotted into `unit_price_cents`
    and choose a rate from a three-rung ladder: a face value of 25 dollars or less —
    that is, at most 2500 cents — uses a rate of 2.0 percent; a face value above that
    but no more than 100 dollars, meaning at most 10000 cents, uses 3.7 percent;
    anything above 10000 cents uses 5.0 percent."

    Design: Difficulty/combinatorial_formula/fee_rounded_per_ticket_then_summed_across_mixed_price_lines
    """
    ctx = _two_tier_onsale_event()
    buyer = create_buyer(email="cal2@example.com", display_name="Cal Two")

    order = validate_success(place_order(
        ctx, buyer,
        [order_item_payload(ctx["tt_id"], 3),
         order_item_payload(ctx["tier_two"]["id"], 2)],
        expected_event_version=ctx["event_version"]), 201)

    lines = order_items_of(order["id"], buyer)
    by_tier = {line["ticket_type_id"]: line for line in lines}
    assert len(lines) == 2, f"Expected one line per items entry, got {len(lines)}"

    balcony = by_tier[ctx["tt_id"]]
    assert_order_item(balcony)
    assert balcony["per_ticket_fee_cents"] == 204, (
        "1234 sits on the 2.0 percent rung: round_half_up(24.68) = 25, plus 179 = 204. "
        f"Got {balcony['per_ticket_fee_cents']}")
    assert balcony["line_fee_cents"] == 612, \
        f"Expected 204 * 3 = 612, got {balcony['line_fee_cents']}"

    floor = by_tier[ctx["tier_two"]["id"]]
    assert_order_item(floor)
    assert floor["per_ticket_fee_cents"] == 467, (
        "7777 sits on the 3.7 percent rung: round_half_up(287.749) = 288, plus 179 = 467. "
        f"Got {floor['per_ticket_fee_cents']}")
    assert floor["line_fee_cents"] == 934, \
        f"Expected 467 * 2 = 934, got {floor['line_fee_cents']}"


def test_fee_tier_three_rate_applies_above_ten_thousand_cents():
    """PRD §3.4: "For each line, take the face value snapshotted into
    `unit_price_cents` and choose a rate from a three-rung ladder: a face value of 25
    dollars or less — that is, at most 2500 cents — uses a rate of 2.0 percent; a
    face value above that but no more than 100 dollars, meaning at most 10000 cents,
    uses 3.7 percent; anything above 10000 cents uses 5.0 percent."

    Design: Corner/calculations/corner_fee_tier_three_rate_applies_above_ten_thousand_cents
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Tier3 Night", "starts_at": "2026-09-29T18:00:00Z",
                         "ends_at": "2026-09-29T22:00:00Z"},
        tier_overrides={"name": "Premium", "tier_rank": 3, "price_cents": 12000,
                        "quantity_total": 10})
    buyer = create_buyer(email="kai@example.com", display_name="Kai")

    order = create_held_order(ctx, buyer, quantity=1,
                              expected_event_version=ctx["event_version"])

    assert order["subtotal_cents"] == 12000
    assert order["fee_total_cents"] == 779, (
        "12000 is above the 10000-cent rung: round_half_up(600.0) = 600, plus 179 = 779. "
        f"Got {order['fee_total_cents']}")
    assert order["buyer_total_cents"] == 12779
    assert order["organizer_gross_cents"] == 12000


def test_platform_fee_is_clamped_to_the_ceiling():
    """PRD §3.4: "Clamp the result upward to a floor of 99 cents and downward to a
    ceiling of 2500 cents — that is, take the larger of the computed amount and 99,
    then take the smaller of that and 2500. The clamped figure is the line's
    `per_ticket_fee_cents`."

    Design: Corner/calculations/corner_platform_fee_cap_clamps_per_ticket_fee
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Cap Night", "starts_at": "2026-09-30T18:00:00Z",
                         "ends_at": "2026-09-30T22:00:00Z"},
        tier_overrides={"name": "Suite", "tier_rank": 4, "price_cents": 100000,
                        "quantity_total": 5})
    buyer = create_buyer(email="lux@example.com", display_name="Lux")

    order = create_held_order(ctx, buyer, quantity=1,
                              expected_event_version=ctx["event_version"])

    assert order["fee_total_cents"] == 2500, (
        "The uncapped figure would be 5000 + 179 = 5179; the ceiling clamps it to 2500. "
        f"Got {order['fee_total_cents']}")
    assert order["buyer_total_cents"] == 102500


def test_absorb_fee_mode_charges_the_organizer_rather_than_the_buyer():
    """PRD §3.4: "Under `ABSORB`, the organiser bears it: `buyer_total_cents` is
    `subtotal_cents` minus `discount_cents`, and `organizer_gross_cents` is
    `subtotal_cents` minus `discount_cents` minus `fee_total_cents`."

    Design: Corner/calculations/corner_absorb_fee_mode_charges_the_organizer_not_the_buyer
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Absorb Night", "starts_at": "2026-10-03T18:00:00Z",
                         "ends_at": "2026-10-03T22:00:00Z", "fee_mode": "ABSORB"})
    buyer = create_buyer(email="ned@example.com", display_name="Ned")

    order = create_held_order(ctx, buyer, quantity=2,
                              expected_event_version=ctx["event_version"])

    assert order["subtotal_cents"] == 10000
    assert order["fee_total_cents"] == 728
    assert order["buyer_total_cents"] == 10000, \
        f"Under ABSORB the buyer pays face only, got {order['buyer_total_cents']}"
    assert order["organizer_gross_cents"] == 9272, \
        f"Expected 10000 - 0 - 728 = 9272, got {order['organizer_gross_cents']}"


# ---------------------------------------------------------------------------
# The eligibility floor and the discount candidates
# ---------------------------------------------------------------------------

def _promo_boundary_event():
    """ONSALE event with a 5000-cent tier, a 4999-cent tier and a 10 percent code."""
    ctx = setup_draft_event(
        event_overrides={"title": "Edge Night", "starts_at": "2026-08-18T18:00:00Z",
                         "ends_at": "2026-08-18T22:00:00Z"},
        tier_overrides={"name": "Tier A", "tier_rank": 2, "price_cents": 5000,
                        "quantity_total": 10})
    ctx["tier_below"] = create_ticket_type(ctx["organizer"], ctx["event"], name="Tier B",
                                           tier_rank=1, price_cents=4999,
                                           quantity_total=10)
    ctx["promo"] = create_promo_code(ctx["organizer"], ctx["event"], code="SAVE10",
                                     kind="PERCENT", percent_bp=1000, max_uses=5,
                                     valid_from="2026-07-01T00:00:00Z",
                                     valid_until="2026-09-01T00:00:00Z")
    ctx["event"] = publish_event(ctx["organizer"], ctx["event"])
    ctx["event_version"] = ctx["event"]["version"]
    return ctx


def test_promo_applies_at_a_subtotal_of_exactly_the_eligibility_floor():
    """PRD §3.4: "The order's `subtotal_cents` must be at least 50 dollars — 5000
    cents, an inclusive floor, so a subtotal of exactly 5000 cents qualifies —
    otherwise the request is rejected with `ERR_PROMO_NOT_APPLICABLE`."
    PRD §3.4: "The first candidate is the code's raw entitlement: for a `PERCENT`
    code, the order's `subtotal_cents` multiplied by `percent_bp` and divided by
    10000, rounded half up to a whole cent; for a `FIXED` code, simply its
    `amount_cents`."

    Design: Difficulty/boundary_precision_check/promo_min_subtotal_is_inclusive_at_exactly_5000_cents
    """
    ctx = _promo_boundary_event()
    buyer = create_buyer(email="lee@example.com", display_name="Lee")

    order = validate_success(place_order(
        ctx, buyer, [order_item_payload(ctx["tt_id"], 1)],
        expected_event_version=ctx["event_version"], promo_code="SAVE10"), 201)

    assert order["subtotal_cents"] == 5000, \
        f"Expected a subtotal exactly on the floor, got {order['subtotal_cents']}"
    assert order["discount_cents"] == 500, \
        f"Expected round_half_up(5000 * 1000 / 10000) = 500, got {order['discount_cents']}"
    assert order["fee_total_cents"] == 364
    assert order["buyer_total_cents"] == 4864, \
        f"Expected 5000 - 500 + 364 = 4864, got {order['buyer_total_cents']}"
    assert order["organizer_gross_cents"] == 4500

    promo = validate_success(api_client.get_promo_code(
        ctx["promo"]["id"], ctx["org_headers"]), 200)
    assert promo["uses_count"] == 1, \
        f"Applying the code advances uses_count to 1, got {promo['uses_count']}"


def test_promo_rejected_one_cent_below_the_eligibility_floor():
    """PRD §3.4: "The order's `subtotal_cents` must be at least 50 dollars — 5000
    cents, an inclusive floor, so a subtotal of exactly 5000 cents qualifies —
    otherwise the request is rejected with `ERR_PROMO_NOT_APPLICABLE`."

    Design: Difficulty/boundary_precision_check/promo_min_subtotal_is_inclusive_at_exactly_5000_cents
    """
    ctx = _promo_boundary_event()
    buyer = create_buyer(email="mona@example.com", display_name="Mona")

    resp = place_order(ctx, buyer, [order_item_payload(ctx["tier_below"]["id"], 1)],
                       promo_code="SAVE10")
    validate_error(resp, ApiErrorId.ERR_PROMO_NOT_APPLICABLE.value, 422)

    promo = validate_success(api_client.get_promo_code(
        ctx["promo"]["id"], ctx["org_headers"]), 200)
    assert promo["uses_count"] == 0, \
        f"A rejected order consumes no redemption, got {promo['uses_count']}"


def test_fixed_promo_is_clamped_by_the_thirty_percent_ceiling():
    """PRD §3.4: "The second candidate is a platform-wide ceiling of thirty percent
    of the order's `subtotal_cents`, again rounded half up to a whole cent — no
    promotion, however generous its declaration, may discount an order by more than
    that share."

    Design: Corner/calculations/corner_fixed_promo_clamped_by_thirty_percent_cap
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Bigcut Night", "starts_at": "2026-10-02T18:00:00Z",
                         "ends_at": "2026-10-02T22:00:00Z"})
    promo = create_promo_code(ctx["organizer"], ctx["event"], code="BIGCUT", kind="FIXED",
                              percent_bp=0, amount_cents=5000, max_uses=5,
                              valid_from="2026-07-01T00:00:00Z",
                              valid_until="2026-09-01T00:00:00Z")
    ctx["event"] = publish_event(ctx["organizer"], ctx["event"])
    buyer = create_buyer(email="mel@example.com", display_name="Mel")

    order = create_held_order(ctx, buyer, quantity=2, promo_code="BIGCUT")

    assert order["subtotal_cents"] == 10000
    assert order["discount_cents"] == 3000, (
        "The 5000-cent entitlement is clamped to round_half_up(10000 * 0.30) = 3000. "
        f"Got {order['discount_cents']}")
    assert order["fee_total_cents"] == 728
    assert order["buyer_total_cents"] == 7728, \
        f"Expected 10000 - 3000 + 728 = 7728, got {order['buyer_total_cents']}"
    assert order["organizer_gross_cents"] == 7000
    assert order["promo_code_id"] == promo["id"], \
        "The resolved code's identifier is recorded on the order"


def test_promo_used_outside_its_redemption_window_is_rejected():
    """PRD §3.4: "The current time must fall at or after `valid_from` and strictly
    before `valid_until`, otherwise `ERR_PROMO_WINDOW_CLOSED`."

    Design: Corner/validations/corner_promo_outside_window_returns_promo_window_closed
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Window Night", "starts_at": "2026-10-11T18:00:00Z",
                         "ends_at": "2026-10-11T22:00:00Z"})
    create_promo_code(ctx["organizer"], ctx["event"], code="LATER", kind="PERCENT",
                      percent_bp=1000, max_uses=5,
                      valid_from="2026-08-01T00:00:00Z",
                      valid_until="2026-09-01T00:00:00Z")
    ctx["event"] = publish_event(ctx["organizer"], ctx["event"])
    buyer = create_buyer(email="wyn@example.com", display_name="Wyn")

    # The logical clock still reads its 2026-07-01 default, before valid_from.
    resp = place_order(ctx, buyer, [order_item_payload(ctx["tt_id"], 1)],
                       promo_code="LATER")
    validate_error(resp, ApiErrorId.ERR_PROMO_WINDOW_CLOSED.value, 409)

    rows, meta = validate_paginated(api_client.list_orders(
        ctx["org_headers"], params={"event_id": ctx["event_id"]}))
    assert meta["total_count"] == 0, \
        f"A rejected checkout persists no order, got total_count {meta['total_count']}"


def test_promo_beyond_its_redemption_budget_is_exhausted():
    """PRD §3.4: "The code's `uses_count` must be strictly less than its `max_uses`,
    otherwise `ERR_PROMO_EXHAUSTED`."
    PRD §3.4: "Applying a code advances that code's `uses_count`, which counts
    precisely the orders naming it whose fulfilment status is `HELD`, `ISSUED`,
    `CHECKED_IN_PARTIAL` or `CHECKED_IN_FULL`."

    Design: Corner/validations/corner_promo_exhausted_when_max_uses_reached
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Onlyone Night", "starts_at": "2026-10-12T18:00:00Z",
                         "ends_at": "2026-10-12T22:00:00Z"})
    promo = create_promo_code(ctx["organizer"], ctx["event"], code="ONLYONE",
                              kind="PERCENT", percent_bp=1000, max_uses=1,
                              valid_from="2026-07-01T00:00:00Z",
                              valid_until="2026-09-01T00:00:00Z")
    ctx["event"] = publish_event(ctx["organizer"], ctx["event"])

    first_buyer = create_buyer(email="xan@example.com", display_name="Xan")
    first_order = create_held_order(ctx, first_buyer, quantity=1, promo_code="ONLYONE")
    assert first_order["discount_cents"] == 500

    second_buyer = create_buyer(email="yuri@example.com", display_name="Yuri")
    resp = place_order(ctx, second_buyer, [order_item_payload(ctx["tt_id"], 1)],
                       promo_code="ONLYONE")
    validate_error(resp, ApiErrorId.ERR_PROMO_EXHAUSTED.value, 409)

    reread = validate_success(api_client.get_promo_code(promo["id"], ctx["org_headers"]), 200)
    assert reread["uses_count"] == 1, \
        f"Only the live order holds the code, got uses_count {reread['uses_count']}"


def test_order_lines_are_discoverable_through_their_filtered_list():
    """PRD §3.4: "Order lines are readable individually and listable with optional
    `order_id`, `ticket_type_id` and `seat_block_id` filters, exposing the `order_id`
    of the owning order alongside the fee breakdown; a line that does not resolve
    yields `ERR_ORDER_ITEM_NOT_FOUND`."

    Design: Corner/entities/corner_order_items_discoverable_only_via_filtered_list
    """
    ctx = setup_reserved_onsale_event(
        event_overrides={"title": "Reverse Night", "starts_at": "2026-09-18T18:00:00Z",
                         "ends_at": "2026-09-18T22:00:00Z"})
    buyer = create_buyer(email="wes@example.com", display_name="Wes")
    order = create_held_order(ctx, buyer, quantity=2, seat_numbers=[5, 6])

    rows, meta = validate_paginated(api_client.list_order_items(
        make_buyer_headers(buyer["id"]), params={"seat_block_id": ctx["sb_id"]}))
    assert meta["total_count"] == 1, \
        f"Expected exactly the one seated line, got total_count {meta['total_count']}"

    line = rows[0]
    assert_order_item(line)
    assert line["order_id"] == order["id"]
    assert line["quantity"] == 2
    assert line["unit_price_cents"] == 5000
    assert line["per_ticket_fee_cents"] == 364, \
        f"Expected round_half_up(185.0) + 179 = 364, got {line['per_ticket_fee_cents']}"
    assert line["line_face_cents"] == 10000
    assert line["line_fee_cents"] == 728
