"""Rental pricing, multi-day discount rounding, delivery fees, and quote parity.

Covers the difficulty instances on dual-variant / combinatorial pricing and the
big-event surcharge boundary, plus corner instances on the free-delivery waiver
boundary, cleaning-fee filtering, and quote/confirm parity.
"""
from test_helpers import (
    validate_success,
    api_client,
    make_customer_headers,
    TEST_USERS,
    create_catalog_item_payload,
    create_customer_payload,
    create_venue_payload,
    create_order_payload,
    add_line_payload,
    get_success_data,
)

AGENT = TEST_USERS["rental_agent_headers"]


def _item(**ov):
    return get_success_data(api_client.create_catalog_item(create_catalog_item_payload(**ov), AGENT))


def _customer():
    return get_success_data(api_client.create_customer(create_customer_payload(), AGENT))


def _will_call_order(customer_id, **ov):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(create_order_payload(customer_id, **ov), h))


def _delivery_order(customer_id, venue_id, **ov):
    h = make_customer_headers(customer_id)
    payload = create_order_payload(customer_id, fulfillment="DELIVERY", venue_id=venue_id, **ov)
    return get_success_data(api_client.create_order(payload, h))


def _venue(customer_id, zone):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_venue(
        create_venue_payload(customer_id, delivery_zone=zone), h))


def _add_line(order_id, item_id, qty, customer_id):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.add_line(order_id, add_line_payload(item_id, qty), h))


def _confirm(order_id, customer_id):
    h = make_customer_headers(customer_id)
    cur = get_success_data(api_client.get_order(order_id, h))
    return api_client.confirm_order(order_id, {"expected_order_version": cur["version"]}, h)


def test_multi_day_full_term_rental_subtotal(api):
    """PRD §3.3: "The per-unit price is then the full first-day rate plus the
    discounted day rate applied to each of the remaining days — that is, the
    discounted day rate multiplied by one fewer than the number of rental days,
    added to the full first-day rate."
    PRD §3.3: "This per-unit price is computed and rounded to whole cents
    **first**, and only then multiplied by the line's `quantity` to give that
    line's `line_rental_cents`."

    CHAIR daily=200, disc=0.20, 3 inclusive days, 100 units:
    disc_day = round_half_up(200*0.80)=160; per_unit = 200 + 2*160 = 520;
    line_rental = 520*100 = 52000.

    Design: Difficulty/dual_variant_calc/line_rental_full_term_vs_weather_prorated
    """
    item = _item(category="CHAIR", total_units=100, daily_rate_cents=200,
                 multi_day_discount_pct=0.20, deposit_per_unit_cents=50,
                 requires_cleaning=False, requires_coi=False)
    cust = _customer()
    order = _will_call_order(cust["id"], event_start="2026-06-01T00:00:00.000Z",
                             event_end="2026-06-03T00:00:00.000Z")
    _add_line(order["id"], item["id"], 100, cust["id"])
    confirmed = validate_success(_confirm(order["id"], cust["id"]), 200)
    assert confirmed["rental_subtotal_cents"] == 52000, confirmed["rental_subtotal_cents"]
    assert confirmed["deposit_total_cents"] == 5000, confirmed["deposit_total_cents"]
    assert confirmed["grand_total_cents"] == 52000, confirmed["grand_total_cents"]


def test_delivery_fee_combines_zone_base_and_surcharge(api):
    """PRD §3.3: "For a `DELIVERY` order the fee starts from a zone base
    determined by the venue's `delivery_zone`: a local zone contributes a base of
    5000 cents, an extended zone 9000 cents, and a remote zone 15000 cents."
    PRD §3.3: "A big-event surcharge of 4000 cents is added when the order moves a
    lot of gear — specifically when the total reserved units across all lines is
    at least 100 (so 99 units adds nothing and 100 units adds the surcharge)."

    EXTENDED base 9000 + surcharge 4000 (100 units) = 13000; subtotal 52000
    (<200000 so no waiver); grand_total = 52000 + 13000 = 65000.

    Design: Difficulty/combinatorial_formula/delivery_fee_multi_input_nonlinear_mode_a
    """
    item = _item(category="CHAIR", total_units=200, daily_rate_cents=200,
                 multi_day_discount_pct=0.20, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"], "EXTENDED")
    order = _delivery_order(cust["id"], venue["id"],
                            event_start="2026-06-01T00:00:00.000Z",
                            event_end="2026-06-03T00:00:00.000Z")
    _add_line(order["id"], item["id"], 100, cust["id"])
    confirmed = validate_success(_confirm(order["id"], cust["id"]), 200)
    assert confirmed["rental_subtotal_cents"] == 52000, confirmed["rental_subtotal_cents"]
    assert confirmed["delivery_fee_cents"] == 13000, confirmed["delivery_fee_cents"]
    assert confirmed["grand_total_cents"] == 65000, confirmed["grand_total_cents"]


def test_line_rental_rounds_per_unit_before_multiplying(api):
    """PRD §3.3: "Each additional day is billed at a discounted day rate, which is
    the item's `daily_rate_cents` multiplied by one minus the item's
    `multi_day_discount_pct`, rounded half up to a whole number of cents."
    PRD §3.3: "This per-unit price is computed and rounded to whole cents
    **first**, and only then multiplied by the line's `quantity` to give that
    line's `line_rental_cents`. The rounding happens at the per-unit step, before
    multiplying by quantity; the system does not round again afterward."

    daily=10, disc=0.15, 2 days, qty 4: disc_day=round_half_up(10*0.85)=
    round_half_up(8.5)=9; per_unit=10+9=19; line_rental=19*4=76 (NOT 74).

    Design: Difficulty/combinatorial_formula/line_rental_round_then_multiply_order_mode_b
    """
    item = _item(category="TABLE", total_units=50, daily_rate_cents=10,
                 multi_day_discount_pct=0.15, deposit_per_unit_cents=0,
                 requires_cleaning=False, requires_coi=False)
    cust = _customer()
    order = _will_call_order(cust["id"], event_start="2026-09-01T00:00:00.000Z",
                             event_end="2026-09-02T00:00:00.000Z")
    _add_line(order["id"], item["id"], 4, cust["id"])
    confirmed = validate_success(_confirm(order["id"], cust["id"]), 200)
    assert confirmed["rental_subtotal_cents"] == 76, confirmed["rental_subtotal_cents"]


def test_big_event_surcharge_below_threshold_no_surcharge(api):
    """PRD §3.3: "A big-event surcharge of 4000 cents is added when the order moves
    a lot of gear — specifically when the total reserved units across all lines is
    at least 100 (so 99 units adds nothing and 100 units adds the surcharge)."

    99 units (< 100): LOCAL base 5000, no surcharge => delivery_fee 5000;
    subtotal 99*200 = 19800.

    Design: Difficulty/boundary_precision_check/big_event_surcharge_unit_threshold_boundary
    """
    item = _item(category="CHAIR", total_units=200, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"], "LOCAL")
    order = _delivery_order(cust["id"], venue["id"],
                            event_start="2026-06-22T00:00:00.000Z",
                            event_end="2026-06-22T00:00:00.000Z")
    _add_line(order["id"], item["id"], 99, cust["id"])
    confirmed = validate_success(_confirm(order["id"], cust["id"]), 200)
    assert confirmed["delivery_fee_cents"] == 5000, confirmed["delivery_fee_cents"]
    assert confirmed["rental_subtotal_cents"] == 19800, confirmed["rental_subtotal_cents"]


def test_big_event_surcharge_at_threshold_adds_surcharge(api):
    """PRD §3.3: "A big-event surcharge of 4000 cents is added when the order moves
    a lot of gear — specifically when the total reserved units across all lines is
    at least 100 (so 99 units adds nothing and 100 units adds the surcharge)."

    Boundary X+1 of the 99/100 cutover: 100 units => LOCAL base 5000 + surcharge
    4000 = 9000.

    Design: Difficulty/boundary_precision_check/big_event_surcharge_unit_threshold_boundary
    """
    item = _item(category="CHAIR", total_units=200, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"], "LOCAL")
    order = _delivery_order(cust["id"], venue["id"],
                            event_start="2026-06-22T00:00:00.000Z",
                            event_end="2026-06-22T00:00:00.000Z")
    _add_line(order["id"], item["id"], 100, cust["id"])
    confirmed = validate_success(_confirm(order["id"], cust["id"]), 200)
    assert confirmed["delivery_fee_cents"] == 9000, confirmed["delivery_fee_cents"]
    assert confirmed["rental_subtotal_cents"] == 20000, confirmed["rental_subtotal_cents"]


def test_free_delivery_waiver_at_subtotal_boundary(api):
    """PRD §3.3: "A free-delivery waiver then applies: when the order's
    `rental_subtotal_cents` is at least 200000 cents (that is, $2,000.00, with
    199999 cents not qualifying and 200000 cents qualifying), the zone base is
    waived to 0, but the big-event surcharge is **not** waived."

    Subtotal exactly 200000 (1 unit at daily 200000, 1 day), <100 units so no
    surcharge => delivery_fee == 0.

    Design: Corner/calculations/free_delivery_subtotal_waiver_boundary
    """
    item = _item(category="TENT", total_units=10, daily_rate_cents=200000,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"], "LOCAL")
    order = _delivery_order(cust["id"], venue["id"],
                            event_start="2026-06-01T00:00:00.000Z",
                            event_end="2026-06-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    confirmed = validate_success(_confirm(order["id"], cust["id"]), 200)
    assert confirmed["rental_subtotal_cents"] == 200000, confirmed["rental_subtotal_cents"]
    assert confirmed["delivery_fee_cents"] == 0, confirmed["delivery_fee_cents"]


def test_cleaning_fee_only_for_requires_cleaning_items(api):
    """PRD §3.3: "The order's `cleaning_fee_total_cents` is the sum over every line
    whose item requires cleaning of that line's `quantity` times the item's
    `cleaning_fee_cents`."

    LINEN requires_cleaning=true, cleaning_fee=500, qty 40 => cleaning 20000;
    rental 150*40=6000; deposit 100*40=4000; grand_total = 6000 + 0 + 20000 = 26000.

    Design: Corner/calculations/cleaning_fee_applied_only_when_requires_cleaning
    """
    item = _item(category="LINEN", total_units=200, daily_rate_cents=150,
                 multi_day_discount_pct=0, requires_cleaning=True, cleaning_fee_cents=500,
                 deposit_per_unit_cents=100, requires_coi=False)
    cust = _customer()
    order = _will_call_order(cust["id"], event_start="2026-06-01T00:00:00.000Z",
                             event_end="2026-06-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], 40, cust["id"])
    h = make_customer_headers(cust["id"])
    quote = validate_success(api_client.get_quote(order["id"], h), 200)
    assert quote["rental_subtotal_cents"] == 6000, quote["rental_subtotal_cents"]
    assert quote["cleaning_fee_total_cents"] == 20000, quote["cleaning_fee_total_cents"]
    assert quote["deposit_total_cents"] == 4000, quote["deposit_total_cents"]
    assert quote["grand_total_cents"] == 26000, quote["grand_total_cents"]


def test_quote_preview_matches_confirm_totals(api):
    """PRD §3.3: "The same calculations that drive this preview are the ones
    applied at confirmation, so a preview is a faithful forecast of the confirmed
    charges."

    EXTENDED, 100 chairs, 3 days, disc 0.20: subtotal 52000, delivery 9000+4000=
    13000, grand_total 65000 — identical in the quote and on confirm.

    Design: Corner/endpoints/quote_matches_confirm_totals
    """
    item = _item(category="CHAIR", total_units=200, daily_rate_cents=200,
                 multi_day_discount_pct=0.20, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"], "EXTENDED")
    order = _delivery_order(cust["id"], venue["id"],
                            event_start="2026-06-01T00:00:00.000Z",
                            event_end="2026-06-03T00:00:00.000Z")
    _add_line(order["id"], item["id"], 100, cust["id"])
    h = make_customer_headers(cust["id"])
    quote = validate_success(api_client.get_quote(order["id"], h), 200)
    assert quote["rental_subtotal_cents"] == 52000, quote["rental_subtotal_cents"]
    assert quote["delivery_fee_cents"] == 13000, quote["delivery_fee_cents"]
    assert quote["grand_total_cents"] == 65000, quote["grand_total_cents"]

    confirmed = validate_success(_confirm(order["id"], cust["id"]), 200)
    assert confirmed["rental_subtotal_cents"] == quote["rental_subtotal_cents"]
    assert confirmed["delivery_fee_cents"] == quote["delivery_fee_cents"]
    assert confirmed["grand_total_cents"] == quote["grand_total_cents"]
