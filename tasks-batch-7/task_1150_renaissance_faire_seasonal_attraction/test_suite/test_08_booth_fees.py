"""Booth finance: provisional vs final fee variants, per-day weather-credit
rounding, and the settlement state gates."""
from test_helpers import (
    ApiErrorId,
    get_booth,
    make_booth,
    make_faire_day,
    make_juried_vendor,
    make_open_season,
    make_season,
    set_clock,
    setup_booth_fee_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, OPERATOR, VENDOR_CO
from test_helpers.test_users import make_vendor_headers


def test_booth_provisional_fee_and_accumulated_credits(api):
    """PRD §3.3: "The reservation copies `season_id` from the application and quotes
    a `provisional_fee_cents` that assumes a full season with zero weather days and
    zero surcharges: the `booth_size_sqft` multiplied by the tier rate — 120 cents
    per square foot per week for `PRIME`, 80 for `STANDARD`, 50 for `MEADOW` —
    multiplied by the season's `season_weeks`."
    PRD §3.6: "Fifth, every booth assignment of the season in `RESERVED`,
    `CONFIRMED`, or `SUSPENDED` whose half-open residency interval covers the
    cancelled date — the residency starts on or before the date and ends strictly
    after it — accrues a daily weather credit into `weather_credit_cents`: one
    quarter of the assignment's `provisional_fee_cents` divided by the residency's
    length in whole days, rounded half up to whole cents for that day before being
    added, per the per-day rounding discipline of §2.7."

    Design: Difficulty/dual_variant_calc/booth_fee_provisional_vs_final_settlement
    """
    ctx = setup_booth_fee_scenario()
    booth = validate_success(api.get_booth_assignment(ctx["booth_id"], ANY), 200)
    # Forward-looking variant: 100 sqft * 120 cents * 2 season weeks.
    assert booth["provisional_fee_cents"] == 24000
    # Three in-residency cancellations at round(24000 * 0.25 / 14) = 429 per day.
    assert booth["weather_credit_cents"] == 1287


def test_booth_final_fee_settlement_differs_from_provisional(api, vendor_coordinator_headers):
    """PRD §3.9: "The final fee is evaluated in a pinned order: start from the
    `provisional_fee_cents`, subtract the accumulated `weather_credit_cents` to
    reach the subtotal, and then, only when the application's
    `requested_location_tier` is `PRIME` and that post-credit subtotal is at least
    20,000 cents, add a surcharge of five percent of the subtotal rounded half up to
    whole cents — booths under the threshold or in other tiers pay no surcharge. The
    resulting sum is recorded as `final_fee_cents`, and `settlement_delta_cents`
    records the difference between the final and provisional fees, a negative value
    meaning a refund is due to the vendor. The booth then stands `SETTLED`."

    Design: Difficulty/dual_variant_calc/booth_fee_provisional_vs_final_settlement
    """
    ctx = setup_booth_fee_scenario()
    settled = validate_success(
        api.settle_booth(ctx["booth_id"], vendor_coordinator_headers), 200
    )
    # Settlement variant: subtotal 24000 - 1287 = 22713 (>= 20000, PRIME);
    # surcharge round(22713 * 0.05) = 1136; final 22713 + 1136 = 23849.
    assert settled["status"] == "SETTLED"
    assert settled["weather_credit_cents"] == 1287
    assert settled["final_fee_cents"] == 23849
    assert settled["settlement_delta_cents"] == 23849 - 24000
    assert settled["final_fee_cents"] != settled["provisional_fee_cents"]


def test_weather_credit_rounded_per_day_not_aggregate(api):
    """PRD §2.7: "A booth's daily weather credit is rounded half up to whole cents
    for each cancelled day before being accumulated; rounding the season-long
    aggregate once at the end is a rejected alternative, because the two orders of
    operations yield different cent totals."

    Design: Difficulty/combinatorial_formula/weather_credit_per_day_rounding_order
    """
    set_clock()
    season = make_season(name="Rainy Revel", volunteer_min_hours=0)
    days = [make_faire_day(season["id"], f"2026-06-{d:02d}T00:00:00Z")
            for d in (7, 13, 14)]
    _, application = make_juried_vendor(
        season["id"], business_name="Pewter & Pine", category="ARTISAN",
        booth_size_sqft=100, requested_location_tier="PRIME",
    )
    booth = make_booth(application["id"], "A-01")
    validate_success(api.begin_build(season["id"], OPERATOR), 200)

    # One cancelled day: round_half_up(24000 * 0.25 / 14) = round_half_up(428.571) = 429.
    validate_success(api.open_sales(days[0]["id"], OPERATOR), 200)
    validate_success(api.cancel_weather(days[0]["id"], OPERATOR), 200)
    assert get_booth(booth["id"])["weather_credit_cents"] == 429

    # A second cancelled day adds another per-day-rounded 429.
    validate_success(api.open_sales(days[1]["id"], OPERATOR), 200)
    validate_success(api.cancel_weather(days[1]["id"], OPERATOR), 200)
    assert get_booth(booth["id"])["weather_credit_cents"] == 858


def test_weather_credit_per_day_rounding_order_pinned(api):
    """PRD §2.7: "A booth's daily weather credit is rounded half up to whole cents
    for each cancelled day before being accumulated; rounding the season-long
    aggregate once at the end is a rejected alternative, because the two orders of
    operations yield different cent totals."
    PRD §3.6: "accrues a daily weather credit into `weather_credit_cents`: one
    quarter of the assignment's `provisional_fee_cents` divided by the residency's
    length in whole days, rounded half up to whole cents for that day before being
    added, per the per-day rounding discipline of §2.7."

    Design: Difficulty/combinatorial_formula/weather_credit_per_day_rounding_order
    """
    set_clock()
    season = make_season(name="Rainy Revel", volunteer_min_hours=0)
    days = [make_faire_day(season["id"], f"2026-06-{d:02d}T00:00:00Z")
            for d in (7, 13, 14)]
    _, application = make_juried_vendor(
        season["id"], business_name="Pewter & Pine", category="ARTISAN",
        booth_size_sqft=100, requested_location_tier="PRIME",
    )
    booth = make_booth(application["id"], "A-01")
    validate_success(api.begin_build(season["id"], OPERATOR), 200)
    for day in days:
        validate_success(api.open_sales(day["id"], OPERATOR), 200)
        validate_success(api.cancel_weather(day["id"], OPERATOR), 200)

    credit = get_booth(booth["id"])["weather_credit_cents"]
    # Per-day rounding: 3 * 429 = 1287; aggregate-then-round would give
    # round(24000 * 0.25 * 3 / 14) = 1286 — the pinned order is observable.
    assert credit == 1287
    assert credit != 1286


def test_settle_and_release_state_gates(api, vendor_coordinator_headers):
    """PRD §3.9: "The coordinator settles any booth in `CONFIRMED` or `SUSPENDED` —
    from any other state, `ERR_BOOTH_NOT_SETTLEABLE` — and only while the season is
    in `STRIKE` (else `ERR_SEASON_INVALID_STATE`)."
    PRD §3.3: "Release by the coordinator is available only from `RESERVED` (else
    `ERR_BOOTH_NOT_RELEASEABLE`) and moves the booth to `RELEASED`."

    Design: Corner/endpoints/settle_and_release_state_gates
    """
    set_clock()
    season = make_season(name="Settle Revel", volunteer_min_hours=0)
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    _, app_a = make_juried_vendor(season["id"], business_name="Tack & Tatter")
    _, app_b = make_juried_vendor(season["id"], business_name="Felt & Feather")
    booth_a = make_booth(app_a["id"], "S-01", "2026-06-06T00:00:00Z",
                         "2026-06-21T00:00:00Z")
    booth_b = make_booth(app_b["id"], "S-02", "2026-06-06T00:00:00Z",
                         "2026-06-21T00:00:00Z")
    vendor_a_id = app_a["vendor_id"]
    validate_success(
        api.confirm_booth(booth_a["id"], make_vendor_headers(vendor_a_id)), 200
    )
    validate_success(api.begin_build(season["id"], OPERATOR), 200)
    validate_success(api.open_season(season["id"], OPERATOR), 200)
    validate_success(api.open_sales(day["id"], OPERATOR), 200)

    # Season merely OPEN: the season gate fires first.
    res = api.settle_booth(booth_a["id"], vendor_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_SEASON_INVALID_STATE, expected_status=409)
    # Release requires RESERVED; CONFIRMED fails on the booth gate.
    res = api.release_booth(booth_a["id"], vendor_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_BOOTH_NOT_RELEASEABLE, expected_status=409)

    # Run the day out and move the season to STRIKE.
    set_clock("2026-06-06T07:00:00Z")
    validate_success(api.open_gates(day["id"], OPERATOR), 200)
    validate_success(api.complete_day(day["id"], OPERATOR), 200)
    validate_success(api.begin_strike(season["id"], OPERATOR), 200)

    settled = validate_success(
        api.settle_booth(booth_a["id"], vendor_coordinator_headers), 200
    )
    # MEADOW 64 sqft: 64 * 50 * 2 = 6400; no credits, no surcharge; delta 0.
    assert settled["status"] == "SETTLED"
    assert settled["final_fee_cents"] == 6400
    assert settled["settlement_delta_cents"] == 0

    # RESERVED booth during STRIKE fails on the booth state gate.
    res = api.settle_booth(booth_b["id"], vendor_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_BOOTH_NOT_SETTLEABLE, expected_status=409)
