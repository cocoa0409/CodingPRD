"""Pricing-engine tests: reservation pricing variants, concession totals, rental quotes.

Covers Difficulty queue (combinatorial_formula, dual_variant_calc) and Corner queue
(calculations section) instances that assert computed monetary fields.
"""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    make_patron_headers,
    setup_double_feature_showtime,
    setup_venue_lot_film,
    create_showtime,
    create_season_pass,
    make_reservation,
    create_concession_item,
    create_concession_order,
    standard_concession_lines,
    create_private_rental,
    set_clock,
)


# =====================================================================
# Difficulty: combinatorial_formula / per_car_tiered_extra_person_mode_a
# =====================================================================
def test_per_car_pricing_tiered_extra_person(api):
    """PRD §3.3: "The gross is `base_price_cents`, plus the extra-person count multiplied
    by `per_extra_person_cents`, plus `double_feature_surcharge_cents` when the screening
    is a double feature."

    Design: Difficulty/combinatorial_formula/per_car_tiered_extra_person_mode_a
    """
    venue, lot, f1, f2, st = setup_double_feature_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-15T02:00:00Z",
        pricing_mode="PER_CAR", base_price_cents=2000, included_occupants=2,
        per_extra_person_cents=600, double_feature_surcharge_cents=1500,
    )
    resv = make_reservation(st, "patron-ccc", occupant_count=5)
    # base 2000 + (5-2)*600 + 1500 = 5300
    assert resv["amount_due_cents"] == 5300, f"expected 5300, got {resv['amount_due_cents']}"
    assert resv["stalls_used"] == 1


def test_per_car_extra_person_clamp_at_threshold(api):
    """PRD §3.3: "Compute the extra-person count as the larger of zero and `occupant_count`
    minus `included_occupants` — an `occupant_count` at or below the threshold does not
    reduce the base."

    Design: Difficulty/combinatorial_formula/per_car_tiered_extra_person_mode_a
    """
    venue, lot, f1, f2, st = setup_double_feature_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-15T02:00:00Z",
        pricing_mode="PER_CAR", base_price_cents=2000, included_occupants=2,
        per_extra_person_cents=600, double_feature_surcharge_cents=1500,
    )
    # occupant_count == included_occupants -> max(0, 2-2)=0 extra; gross = 2000 + 0 + 1500
    resv = make_reservation(st, "patron-clamp", occupant_count=2)
    assert resv["amount_due_cents"] == 3500, f"expected 3500, got {resv['amount_due_cents']}"


# =====================================================================
# Difficulty: combinatorial_formula / concession_per_line_tax_rounding_mode_b
# =====================================================================
def test_concession_per_line_tax_rounding(api):
    """PRD §3.8: "each line's tax is the line amount multiplied by that item's `tax_rate`,
    rounded half up to a whole cent per line, and `tax_cents` is the sum of those per-line
    rounded taxes — the rounding happens once per line and the rounded results are summed,
    which can differ from summing exact taxes and rounding once, so the per-line rounding
    order is mandatory."

    Design: Difficulty/combinatorial_formula/concession_per_line_tax_rounding_mode_b
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    a = create_concession_item(venue["id"], name="Nachos A", unit_price_cents=350, tax_rate=0.0725)
    b = create_concession_item(venue["id"], name="Nachos B", unit_price_cents=350, tax_rate=0.0725)
    c = create_concession_item(venue["id"], name="Nachos C", unit_price_cents=350, tax_rate=0.0725)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-16T02:00:00Z")
    resv = make_reservation(st, "patron-ddd", occupant_count=2)
    lines = [
        {"concession_item_id": a["id"], "qty": 1},
        {"concession_item_id": b["id"], "qty": 1},
        {"concession_item_id": c["id"], "qty": 1},
    ]
    order = create_concession_order(resv["id"], "patron-ddd", lines)
    # per line: round_half_up(350*0.0725)=round(25.375)=25; 3 lines -> 75
    assert order["subtotal_cents"] == 1050
    assert order["tax_cents"] == 75, f"expected per-line tax 75, got {order['tax_cents']}"
    assert order["service_fee_cents"] == 53  # round_half_up(1050*0.05)=53
    assert order["total_cents"] == 1178


def test_concession_total_sums_subtotal_tax_fee(api):
    """PRD §3.8: "Finally, `total_cents` is the `subtotal_cents` plus `tax_cents` plus
    `service_fee_cents`."
    PRD §3.8: "The `service_fee_cents` is the `subtotal_cents` multiplied by a five-percent
    service fee, rounded half up once on the subtotal."

    Design: Difficulty/combinatorial_formula/concession_per_line_tax_rounding_mode_b
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    lines, ids = standard_concession_lines(venue["id"])
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-17T02:00:00Z")
    resv = make_reservation(st, "patron-tot", occupant_count=2)
    order = create_concession_order(resv["id"], "patron-tot", lines)
    # subtotal = 350*3 + 1250 + 199*2 = 1050+1250+398 = 2698
    # tax: round(1050*.0725)=76? per line: pop line 1050*.0725=76.125->76; combo 1250*.0725=90.625->91; water 0 => 167
    assert order["subtotal_cents"] == 2698
    assert order["tax_cents"] == 167
    assert order["service_fee_cents"] == 135  # round_half_up(2698*0.05)=round(134.9)=135
    assert order["total_cents"] == 2698 + 167 + 135


# =====================================================================
# Difficulty: dual_variant_calc / rental_quote_vs_concession_total_distinct_domains
# =====================================================================
def test_rental_quote_ceil_hours(api):
    """PRD §3.7: "take the hold's duration, round it up to a whole number of hours (any
    partial hour bills as a full hour, so a hold of three hours and one minute bills four
    hours), and set `quote_cents` to the `flat_venue_fee_cents` plus the `per_hour_cents`
    multiplied by that rounded-up hour count."

    Design: Difficulty/dual_variant_calc/rental_quote_vs_concession_total_distinct_domains
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    rlot = get_success_data(
        api_client.create_lot(
            {"venue_id": venue["id"], "name": "Rental Lot", "stall_count": 50, "person_capacity": 300},
            make_venue_op(),
        )
    )
    # 3h01m -> ceil 4 hours; quote = 150000 + 20000*4 = 230000
    rental = create_private_rental(
        venue["id"], rlot["id"], "org-1",
        "2026-07-01T18:00:00Z", "2026-07-01T21:01:00Z",
        flat_venue_fee_cents=150000, per_hour_cents=20000,
    )
    assert rental["quote_cents"] == 230000, f"expected 230000, got {rental['quote_cents']}"


def test_concession_three_line_total_distinct_domain(api):
    """PRD §3.8: "Iterating the `lines` in request order, each line's amount is the item's
    `unit_price_cents` multiplied by the line's `qty`; the `subtotal_cents` accumulates
    these line amounts."

    Design: Difficulty/dual_variant_calc/rental_quote_vs_concession_total_distinct_domains
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    lines, ids = standard_concession_lines(venue["id"])
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-12T02:00:00Z")
    resv = make_reservation(st, "patron-bbb", occupant_count=2)
    order = create_concession_order(resv["id"], "patron-bbb", lines)
    assert order["subtotal_cents"] == 2698
    assert order["tax_cents"] == 167
    assert order["service_fee_cents"] == 135
    assert order["total_cents"] == 3000


# =====================================================================
# Corner: calculations / per_person_pricing_variant_selected
# =====================================================================
def test_per_person_pricing_variant(api):
    """PRD §3.3: "Per-person pricing (no `season_pass_id`, and `pricing_mode` is
    `PER_PERSON`): `included_occupants` and `per_extra_person_cents` are ignored entirely;
    every occupant is charged. The gross is `occupant_count` multiplied by `base_price_cents`,
    plus `double_feature_surcharge_cents` when the screening is a double feature."

    Design: Corner/calculations/per_person_pricing_variant_selected
    """
    venue, lot, f1, f2, st = setup_double_feature_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-08-02T02:00:00Z",
        pricing_mode="PER_PERSON", base_price_cents=900,
        double_feature_surcharge_cents=1500, person_capacity=200,
    )
    resv = make_reservation(st, "patron-pp", occupant_count=4)
    # 4*900 + 1500 = 5100
    assert resv["amount_due_cents"] == 5100, f"expected 5100, got {resv['amount_due_cents']}"
    assert resv["stalls_used"] == 0


# =====================================================================
# Corner: calculations / per_person_promo_discount_rounding
# =====================================================================
def test_per_person_promo_discount_rounding(api):
    """PRD §3.3: "the discount is the gross multiplied by `promo_pct`, rounded half up once
    to a whole cent, and `amount_due_cents` is the gross minus that rounded discount. The
    discount is computed on the entire gross and rounded exactly once (sum-then-round), not
    per component."

    Design: Corner/calculations/per_person_promo_discount_rounding
    """
    venue, lot, f1, f2, st = setup_double_feature_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-08-03T02:00:00Z",
        pricing_mode="PER_PERSON", base_price_cents=900,
        double_feature_surcharge_cents=1500, person_capacity=200,
    )
    resv = make_reservation(st, "patron-promo", occupant_count=4, promo_pct=0.10)
    # gross 5100; discount round_half_up(510)=510; due 4590
    assert resv["amount_due_cents"] == 4590, f"expected 4590, got {resv['amount_due_cents']}"


# =====================================================================
# Corner: calculations / season_pass_double_feature_charges_surcharge_only
# =====================================================================
def test_season_pass_double_feature_surcharge_only(api):
    """PRD §3.3: "Season-pass redemption (the reservation supplies a `season_pass_id`):
    regular admission is waived entirely. The gross is just the
    `double_feature_surcharge_cents` when the screening is a double feature, and zero
    otherwise. The `promo_pct` is ignored on a pass redemption, so `amount_due_cents` equals
    that surcharge gross with no discount applied."

    Design: Corner/calculations/season_pass_double_feature_charges_surcharge_only
    """
    venue = _create_venue()
    lot = get_success_data(api_client.create_lot(
        {"venue_id": venue["id"], "name": "L", "stall_count": 10, "person_capacity": 200},
        make_venue_op()))
    f1 = _create_film("F1", 90, "PG")
    f2 = _create_film("F2", 90, "PG")
    set_clock("2026-06-01T00:00:00Z")
    sp = create_season_pass("patron-sp", "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z",
                            tier="GOLD", max_redemptions=5)
    st = create_showtime(
        venue["id"], lot["id"], f1["id"], "2026-08-05T02:00:00Z",
        secondary_film_id=f2["id"], is_double_feature=True, pricing_mode="PER_CAR",
        base_price_cents=2000, included_occupants=2, per_extra_person_cents=600,
        double_feature_surcharge_cents=1500,
    )
    resv = make_reservation(st, "patron-sp", occupant_count=4,
                            season_pass_id=sp["id"], promo_pct=0.20)
    assert resv["amount_due_cents"] == 1500, f"expected 1500, got {resv['amount_due_cents']}"
    pass_after = validate_success(api.get_season_pass(sp["id"], make_venue_op()))
    assert pass_after["redemptions_used"] == 1


# =====================================================================
# Corner: calculations / rental_quote_exact_hours_no_ceil
# =====================================================================
def test_rental_quote_exact_hours_no_ceil(api):
    """PRD §3.7: "take the hold's duration, round it up to a whole number of hours (any
    partial hour bills as a full hour, so a hold of three hours and one minute bills four
    hours), and set `quote_cents` to the `flat_venue_fee_cents` plus the `per_hour_cents`
    multiplied by that rounded-up hour count."

    Design: Corner/calculations/rental_quote_exact_hours_no_ceil
    """
    venue = _create_venue()
    lot = get_success_data(api_client.create_lot(
        {"venue_id": venue["id"], "name": "L", "stall_count": 10, "person_capacity": 100},
        make_venue_op()))
    set_clock("2026-06-01T00:00:00Z")
    # exactly 3h00m -> 3 hours, no ceil bump; 150000 + 3*20000 = 210000
    rental = create_private_rental(
        venue["id"], lot["id"], "org-q",
        "2026-08-07T18:00:00Z", "2026-08-07T21:00:00Z",
        flat_venue_fee_cents=150000, per_hour_cents=20000,
    )
    assert rental["quote_cents"] == 210000, f"expected 210000, got {rental['quote_cents']}"


# ---- small local helpers (avoid importing operator header builders repeatedly) ----
def make_venue_op():
    from test_helpers import TEST_USERS
    return TEST_USERS["venue_operator_headers"]


def _create_venue():
    from test_helpers import create_venue
    return create_venue()


def _create_film(title, runtime, rating):
    from test_helpers import create_film
    return create_film(title=title, runtime_minutes=runtime, rating=rating)
