"""Fee-quote composition, rounding-order pinning, and deposit tier boundaries."""
from test_helpers import (
    validate_success, ApiErrorId,
    create_artist, create_gear_model, create_gear_unit, create_tour, add_stop,
    add_rider_line, source_line,
    create_source_payload, setup_rounding_contrast,
    api_client, TEST_USERS,
)

OPS = TEST_USERS["ops_manager_headers"]
TM = TEST_USERS["tour_manager_headers"]
LC = TEST_USERS["logistics_headers"]


def _zone_setup(topup_cents=110_000):
    """STANDARD artist, model at 100000/day and 300000 replacement, two LAX
    units, one NYC stop."""
    artist = create_artist(legal_name="Zone Act", tier="STANDARD", topup_cents=topup_cents)
    model = create_gear_model(sku="CF-AMP-9", category="AMP", daily_rate_cents=100_000,
                              replacement_value_cents=300_000, weight_class="STANDARD")
    create_gear_unit(model["id"], serial_number="CF-U1", home_city_code="LAX")
    create_gear_unit(model["id"], serial_number="CF-U2", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Zone Tour", insurance_policy_id="POL-Z")
    stop = add_stop(tour["id"], city_code="NYC", venue_date="2026-08-12T00:00:00Z",
                    load_in_ts="2026-08-12T10:00:00Z")
    return artist, model, tour, stop


def test_quote_cross_region_multi_input(api):
    """PRD §3.3: "cartage applies a zone multiplier over the origin–destination
    pair — 1.00 when both cities are the same, which yields zero cartage; 1.10
    when both fall inside one region, the regions being the West Coast set of
    LAX, SFO, SEA, and PDX, the Northeast set of NYC, BOS, PHI, and DC, and the
    Mid-South set of NASH, ATL, and MEM; and 1.25 for any cross-region pair".
    PRD §3.3: "insurance is eight percent of the base, rounded half-up to whole
    cents, charged only when the artist's `risk_score` at quote time is 50 or
    higher, the threshold being inclusive."
    A 5-day window at 100000 cents/day crossing regions (LAX -> NYC) yields
    base 500000 + cartage round_half_up(500000 * 0.25) = 125000 + insurance 0
    (risk below 50) = 625000.

    Design: Difficulty/combinatorial_formula/rental_fee_quote_multi_input_nonlinear
    """
    _, model, _, stop = _zone_setup()
    line = add_rider_line(stop["id"], model["id"])

    reservation = validate_success(api.source_rider_line(
        line["id"], create_source_payload(
            origin_city_code="LAX", dest_city_code="NYC",
            start_date="2026-08-10T00:00:00Z", end_date="2026-08-15T00:00:00Z"), LC))
    # base 500000 + cartage round_half_up(500000 * 0.25) = 125000 + insurance 0
    assert reservation["quoted_fee_cents"] == 625_000


def test_quote_same_city_zero_cartage_and_deposit(api):
    """PRD §3.3: "cartage applies a zone multiplier over the origin–destination
    pair — 1.00 when both cities are the same, which yields zero cartage".
    PRD §3.3: "The deposit hold, stored as `deposit_held_cents`, follows the
    tiered rule of §2.7 against the model's `replacement_value_cents`: twenty
    percent of the first 200,000 cents of replacement value — the first two
    thousand dollars — plus fifteen percent of the next 300,000 cents (the band
    from two thousand to five thousand dollars), plus ten percent of any value
    beyond 500,000 cents."
    The same 5-day window staying within one city (LAX -> LAX) yields zero
    cartage, so the quote is the bare base 500000, and replacement value
    300000 holds 0.20*200000 + 0.15*100000 = 55000.

    Design: Difficulty/combinatorial_formula/rental_fee_quote_multi_input_nonlinear
    """
    _, model, _, stop = _zone_setup()
    line = add_rider_line(stop["id"], model["id"])

    reservation = validate_success(api.source_rider_line(
        line["id"], create_source_payload(
            origin_city_code="LAX", dest_city_code="LAX",
            start_date="2026-08-10T00:00:00Z", end_date="2026-08-15T00:00:00Z"), LC))
    assert reservation["quoted_fee_cents"] == 500_000
    assert reservation["deposit_held_cents"] == 55_000


def test_rounding_contrast_quote_per_component(api):
    """PRD §3.3: "The quote is the sum of base, cartage, and insurance, with
    each component rounded to whole cents before summing — never after."
    Base 33333*5 = 166665; cartage round_half_up(166665*0.25) = 41666;
    insurance round_half_up(166665*0.08) = 13333 (risk 60 >= 50);
    quoted = 221664.

    Design: Difficulty/combinatorial_formula/deposit_vs_fee_rounding_order_contrast
    """
    ctx = setup_rounding_contrast()
    assert ctx["artist"]["risk_score"] == 60
    assert ctx["reservation"]["quoted_fee_cents"] == 221_664


def test_rounding_contrast_deposit_sum_then_round(api):
    """PRD §3.3: "The tiered sum is rounded half-up to whole cents exactly once
    at the end, a deliberate contrast with the quote's per-component rounding."
    Replacement value 250000 -> 0.20*200000 + 0.15*50000 = 47500.

    Design: Difficulty/combinatorial_formula/deposit_vs_fee_rounding_order_contrast
    """
    ctx = setup_rounding_contrast()
    assert ctx["reservation"]["deposit_held_cents"] == 47_500


def test_deposit_tier_boundaries(api):
    """PRD §3.3: "A replacement value of exactly 200,000 cents therefore holds
    40,000 cents, and exactly 500,000 cents holds 85,000 cents."
    PRD §3.3: "The tiered sum is rounded half-up to whole cents exactly once at
    the end, a deliberate contrast with the quote's per-component rounding."
    — 500001 adds 0.10 * 1 = 0.1 cent, rounding the 85000.1 sum to 85000.

    Design: Corner/calculations/deposit_tier_boundaries
    """
    artist = create_artist(legal_name="Tier Act", tier="STANDARD", topup_cents=210_000)
    models = {}
    for sku, rv in (("TR-A", 200_000), ("TR-B", 500_000), ("TR-C", 500_001)):
        models[sku] = create_gear_model(sku=sku, category="AMP", daily_rate_cents=1000,
                                        replacement_value_cents=rv, weight_class="HAND_CARRY")
        create_gear_unit(models[sku]["id"], serial_number=f"{sku}-U", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Tier Tour", insurance_policy_id="POL-T")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
                    load_in_ts="2026-08-10T10:00:00Z")

    held = {}
    for sku in ("TR-A", "TR-B", "TR-C"):
        line = add_rider_line(stop["id"], models[sku]["id"])
        reservation = validate_success(api.source_rider_line(
            line["id"], create_source_payload(
                origin_city_code="LAX", dest_city_code="LAX",
                start_date="2026-08-09T00:00:00Z", end_date="2026-08-11T00:00:00Z"), LC))
        held[sku] = reservation["deposit_held_cents"]

    assert held["TR-A"] == 40_000
    assert held["TR-B"] == 85_000
    assert held["TR-C"] == 85_000
