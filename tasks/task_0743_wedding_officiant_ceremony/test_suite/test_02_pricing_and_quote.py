"""Booking price quote: tiered travel, conditional rush/interfaith, per-line
gratuity rounding, and immediate visibility of the computed quote (PRD Sections
2.2, 3.2).
"""
from test_helpers import (
    fixtures as fx,
    validate_success,
    create_booking_payload,
    make_couple_headers,
)


def _quote(api, ref, **booking_overrides):
    payload = create_booking_payload(
        ref.officiant["id"], ref.couple["id"], ref.package["id"], ref.venue["id"],
        **booking_overrides,
    )
    resp = api.create_booking(payload, make_couple_headers(ref.couple["id"]))
    return validate_success(resp, 201)


def test_quote_combines_travel_rush_interfaith_and_addon_line_items(api):
    """PRD §3.2: "a distance greater than 75 and up to and including 150 kilometers
    adds 30000 cents"; "The rush surcharge, stored as `quoted_rush_cents`, is 25000
    cents when `days_until_ceremony_at_quote` is strictly fewer than 30 days, and 0
    otherwise."; "The interfaith surcharge, stored as `quoted_interfaith_cents`, is
    20000 cents when `required_style` is exactly `INTERFAITH`, and 0 otherwise."

    Design: Difficulty/combinatorial_formula/price_quote_tiered_travel_rush_interfaith_mode_a
    """
    ref = fx.setup_reference(
        api, officiant_overrides={"styles": ["INTERFAITH"], "denomination": "NONDENOMINATIONAL"}
    )
    data = _quote(
        api, ref,
        ceremony_start="2026-03-21T00:00:00Z", ceremony_end="2026-03-21T01:00:00Z",
        travel_distance_km=100, required_style="INTERFAITH", addon_codes=["HANDFASTING"],
    )
    assert data["quoted_travel_cents"] == 30000
    assert data["quoted_rush_cents"] == 25000
    assert data["quoted_interfaith_cents"] == 20000
    assert data["quoted_addons_cents"] == 8000
    assert data["quoted_subtotal_cents"] == 283000


def test_quote_grand_total_and_deposit_due_from_combined_line_items(api):
    """PRD §3.2: "The grand total, `quoted_total_cents`, is `quoted_subtotal_cents`
    plus `quoted_gratuity_cents`. Finally, `deposit_due_cents` is the grand total
    multiplied by the package's `deposit_pct`, rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/price_quote_tiered_travel_rush_interfaith_mode_a
    """
    ref = fx.setup_reference(
        api, officiant_overrides={"styles": ["INTERFAITH"], "denomination": "NONDENOMINATIONAL"}
    )
    data = _quote(
        api, ref,
        ceremony_start="2026-03-21T00:00:00Z", ceremony_end="2026-03-21T01:00:00Z",
        travel_distance_km=100, required_style="INTERFAITH", addon_codes=["HANDFASTING"],
    )
    assert data["quoted_total_cents"] == 333940
    assert data["deposit_due_cents"] == 100182


def test_gratuity_rounds_per_line_item_then_sums(api):
    """PRD §3.2: "The gratuity applies at a rate of 18 percent to each individual
    line item — the base fee, the travel surcharge, the rush surcharge, the
    interfaith surcharge, and each selected add-on taken separately — with each of
    those per-line amounts rounded half-up to a whole cent, and the rounded amounts
    summed to produce `quoted_gratuity_cents`."

    Design: Difficulty/combinatorial_formula/gratuity_per_line_rounding_order_mode_b
    """
    ref = fx.setup_reference(api)
    data = _quote(
        api, ref,
        travel_distance_km=100, required_style="SECULAR",
        addon_codes=["PREMIUM_SCRIPT", "BILINGUAL_CEREMONY"],
    )
    assert data["quoted_addons_cents"] == 13050
    assert data["quoted_subtotal_cents"] == 243050
    assert data["quoted_gratuity_cents"] == 43750


def test_gratuity_total_and_deposit_use_per_line_rounded_sum(api):
    """PRD §3.2: "it must not be computed by taking 18 percent of the combined
    subtotal, because rounding each line independently can differ from rounding
    the total by a cent."

    Design: Difficulty/combinatorial_formula/gratuity_per_line_rounding_order_mode_b
    """
    ref = fx.setup_reference(api)
    data = _quote(
        api, ref,
        travel_distance_km=100, required_style="SECULAR",
        addon_codes=["PREMIUM_SCRIPT", "BILINGUAL_CEREMONY"],
    )
    assert data["quoted_total_cents"] == 286800
    assert data["deposit_due_cents"] == 86040


def test_rush_fee_zero_at_exactly_30_days_out(api):
    """PRD §3.2: "The rush surcharge, stored as `quoted_rush_cents`, is 25000 cents
    when `days_until_ceremony_at_quote` is strictly fewer than 30 days, and 0
    otherwise."

    Design: Difficulty/boundary_precision_check/rush_fee_threshold_30_days_strict
    """
    ref = fx.setup_reference(api)  # clock defaults to 2026-03-01
    data = _quote(
        api, ref,
        ceremony_start="2026-03-31T00:00:00Z", ceremony_end="2026-03-31T01:00:00Z",
    )
    assert data["quoted_rush_cents"] == 0


def test_rush_fee_applies_at_29_days_out(api):
    """PRD §3.2: "The rush surcharge, stored as `quoted_rush_cents`, is 25000 cents
    when `days_until_ceremony_at_quote` is strictly fewer than 30 days, and 0
    otherwise."

    Design: Difficulty/boundary_precision_check/rush_fee_threshold_30_days_strict
    """
    ref = fx.setup_reference(api)  # clock defaults to 2026-03-01
    data = _quote(
        api, ref,
        ceremony_start="2026-03-30T00:00:00Z", ceremony_end="2026-03-30T01:00:00Z",
    )
    assert data["quoted_rush_cents"] == 25000


def test_travel_tier_boundary_25_vs_26_km(api):
    """PRD §3.2: "a distance of at most 25 kilometers adds nothing; a distance
    greater than 25 and up to and including 75 kilometers adds 15000 cents".

    Design: Corner/calculations/travel_tier_boundary_25_vs_26_km
    """
    ref = fx.setup_reference(api)
    at25 = _quote(api, ref, travel_distance_km=25)
    at26 = _quote(api, ref, travel_distance_km=26,
                  ceremony_start="2026-09-02T15:00:00Z", ceremony_end="2026-09-02T16:00:00Z")
    assert at25["quoted_travel_cents"] == 0
    assert at26["quoted_travel_cents"] == 15000


def test_quote_visible_immediately_in_create_response(api):
    """PRD §3.2: "The grand total, `quoted_total_cents`, is `quoted_subtotal_cents`
    plus `quoted_gratuity_cents`. Finally, `deposit_due_cents` is the grand total
    multiplied by the package's `deposit_pct`, rounded half-up to a whole cent."

    Design: Corner/consistency_model/quote_visible_immediately_in_create_response
    """
    ref = fx.setup_reference(api)
    data = _quote(api, ref, travel_distance_km=100, addon_codes=["UNITY_CANDLE"])
    assert data["quoted_total_cents"] == 277300
    assert data["deposit_due_cents"] == 83190
