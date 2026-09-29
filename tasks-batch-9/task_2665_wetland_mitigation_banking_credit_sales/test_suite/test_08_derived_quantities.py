"""Derived quantities: attainment scoring, tiered pricing, the demand index,
the credit forecast, the sales-posture ladder and the milestone release
variants.

Every test in this module drives the API through the PRD's own endpoints and
asserts the pinned numeric outcome of one derived quantity. The rounding order
is normative throughout: terms are rounded before they are summed, money is
integer cents, credit quantities carry 2 decimal places and the attainment
score and demand index carry 4.
"""

from test_helpers import (
    FORECAST_HORIZON_QUARTERS,
    TEST_DEFAULTS,
    add_milestone,
    api_client,
    approve_release,
    assert_cents,
    assert_credit_conservation,
    assert_credits,
    assert_ledger_sequence,
    assert_score,
    bank_state,
    cast_votes,
    claim_milestone,
    credit_forecast,
    decide_work_plan,
    draft_prospectus,
    draft_work_plan,
    finalize_prospectus,
    fund_stewardship,
    get_success_data,
    milestone_state,
    open_monitoring_report,
    permittee_state,
    quote_credits,
    record_easement_on_bank,
    release_milestone_fully,
    report_state,
    reserve_sale,
    review_monitoring_report,
    sale_state,
    set_clock,
    setup_draft_bank,
    setup_monitoring_ready_bank,
    setup_sellable_bank,
    submit_monitoring_report,
    submit_prospectus,
    submit_work_plan,
    validate_paginated,
)

CLOCK_START = "2026-08-01T00:00:00Z"
INTERIM_GATE_CENTS = TEST_DEFAULTS["STEWARDSHIP_INTERIM_GATE_CENTS"]
DEED_REFERENCE = "BK4412-PG221"

# The two year-1 standards of the canonical work plan, measured exactly at
# their thresholds.
YEAR1_AT_THRESHOLD = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 120},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
]

# A year-3 sheet that misses the GTE hydroperiod standard by three days and
# overshoots the LTE invasive-cover standard by one percentage point.
YEAR3_NEAR_MISS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 117},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 11.0},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 80.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 400},
]


def _accept_year_one_report():
    """Instrument the canonical bank, then open, submit and accept a year-1
    monitoring report that measures only the two year-1 standards."""
    set_clock(CLOCK_START)
    world = setup_monitoring_ready_bank(
        record_easement=True, stewardship_funded_cents=INTERIM_GATE_CENTS
    )
    set_clock("2027-08-15T00:00:00Z")
    report = open_monitoring_report(
        world,
        monitoring_year=1,
        window_start="2027-08-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        measurements_array=YEAR1_AT_THRESHOLD,
    )
    submit_monitoring_report(world, report["id"])
    accepted = review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)
    return world, accepted


def test_year_one_score_divides_by_only_the_year_one_weights():
    """A year-1 report carries just the two year-1 measurements, so its
    denominator is 0.550 rather than 1.000 and a fully attained sheet scores
    exactly 1.0000 with a PASS compliance status.

    PRD §3.7: "Submission is admissible while the bank is in `INSTRUMENT_EXECUTED`, `MONITORING` or `SUSPENDED` status — a suspended bank must still be able to file, since filing is how it recovers — and requires the measurements array to contain one entry for every performance standard of the bank whose `effective_from_year` is no greater than the report's monitoring year."
    PRD §3.7: "The report's `attainment_score` is the sum of those already-rounded contributions divided by the sum of the effective standards' weights as supplied — the denominator uses the unrounded weights and covers only the standards effective in this year, so a report in an early monitoring year is scored against a denominator smaller than 1.000 — with the quotient rounded half up to 4 decimal places."
    PRD §3.7: "The compliance status then follows from those two outputs in order: it is `PASS` when no standard failed, otherwise `PARTIAL` when the attainment score is at least 0.85 — the boundary is inclusive — and otherwise `FAIL`."
    Design: Corner/calculations/attainment_score_denominator_uses_only_effective_year_standards
    """
    world, accepted = _accept_year_one_report()

    assert_score(accepted["attainment_score"], 1.0000)
    assert accepted["compliance_status"] == "PASS", (
        "a sheet attaining both effective standards scores PASS, got "
        f"{accepted['compliance_status']}"
    )
    assert accepted["failed_standard_codes"] == [], (
        "no standard was missed, so failed_standard_codes must be empty, got "
        f"{accepted['failed_standard_codes']}"
    )

    stored = report_state(accepted["id"], world)
    assert_score(stored["attainment_score"], 1.0000)
    assert stored["review_status"] == "ACCEPTED", (
        f"review status must advance to ACCEPTED, got {stored['review_status']}"
    )


def test_year_three_standards_exist_but_stay_out_of_the_year_one_denominator():
    """All four standards are materialised on the bank, yet the year-1
    acceptance excludes the two year-3 rows from the score and still carries the
    bank into MONITORING.

    PRD §3.7: "Those standards are the bank's performance standards whose effective-from year is no greater than the report's monitoring year, taken in ascending standard-code order; if there are none, the acceptance is rejected with `ERR_NO_EFFECTIVE_STANDARDS`, and if any of them lacks a matching measurement, it is rejected with `ERR_MEASUREMENT_MISSING`."
    PRD §3.7: "If the bank has never had an accepted report before, this acceptance additionally carries the bank `INSTRUMENT_EXECUTED → MONITORING`."
    Design: Corner/calculations/attainment_score_denominator_uses_only_effective_year_standards
    """
    world, accepted = _accept_year_one_report()

    standards, meta = validate_paginated(
        api_client.list_bank_performance_standards(
            world["bank"]["id"], world["chair_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 4, (
        "all four work-plan standards are materialised on the bank even though "
        f"only two entered the year-1 denominator, got total_count {meta['total_count']}"
    )
    late_years = sorted(
        s["standard_code"] for s in standards if s["effective_from_year"] > 1
    )
    assert late_years == ["NATIVE_COVER_PCT", "STEM_DENSITY_PER_ACRE"], (
        f"expected the two year-3 standards to exist unmeasured, got {late_years}"
    )

    assert accepted["reviewed_by_member_id"] == world["members"][1]["id"], (
        "the accepting member must be recorded onto the report"
    )
    assert accepted["reviewed_at"].startswith("2027-08-15T00:00:00"), (
        f"reviewed_at is stamped from the logical clock, got {accepted['reviewed_at']}"
    )

    bank = bank_state(world)
    assert bank["status"] == "MONITORING", (
        "the bank's first accepted report carries it to MONITORING, got "
        f"{bank['status']}"
    )


def _accept_year_three_near_miss():
    """Accept a year-3 report that misses the hydroperiod standard by three days
    and overshoots the invasive-cover ceiling by one point."""
    set_clock(CLOCK_START)
    world = setup_monitoring_ready_bank(
        record_easement=True, stewardship_funded_cents=INTERIM_GATE_CENTS
    )
    set_clock("2029-08-15T00:00:00Z")
    report = open_monitoring_report(
        world,
        monitoring_year=3,
        window_start="2029-08-01T00:00:00Z",
        window_end="2029-09-01T00:00:00Z",
        measurements_array=YEAR3_NEAR_MISS,
    )
    submit_monitoring_report(world, report["id"])
    accepted = review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)
    return world, accepted


def test_each_standard_contribution_is_rounded_to_four_decimals_before_summing():
    """The four per-standard contributions 0.2925, 0.2250, 0.3000 and 0.1500 are
    each rounded to 4 decimals and only then summed, giving 0.9675 over a
    denominator of 1.000 and a PARTIAL compliance status.

    PRD §3.7: "For a standard whose comparator is `LTE`, the ratio is exactly 1.0 when the measured value is less than or equal to the threshold; when the measured value exceeds the threshold, the ratio is 1.0 minus the excess over the threshold divided by the threshold, floored at 0.0 so a catastrophic overshoot scores zero rather than negative, and the standard is met when the measured value is less than or equal to the threshold — again, equality counts."
    PRD §3.7: "Each standard's contribution is its ratio multiplied by its weight, rounded half up to 4 decimal places; this per-standard rounding is pinned and precedes summation."
    PRD §3.7: "The compliance status then follows from those two outputs in order: it is `PASS` when no standard failed, otherwise `PARTIAL` when the attainment score is at least 0.85 — the boundary is inclusive — and otherwise `FAIL`."
    Design: Corner/calculations/attainment_score_rounds_each_contribution_to_four_decimals
    """
    world, accepted = _accept_year_three_near_miss()

    assert_score(accepted["attainment_score"], 0.9675)
    assert accepted["compliance_status"] == "PARTIAL", (
        "a score of 0.9675 with two missed standards is PARTIAL, got "
        f"{accepted['compliance_status']}"
    )

    stored = report_state(accepted["id"], world)
    assert_score(stored["attainment_score"], 0.9675)
    assert stored["review_status"] == "ACCEPTED", (
        f"review status must advance to ACCEPTED, got {stored['review_status']}"
    )
    assert stored["return_count"] == 0, (
        f"the report was never returned, got return_count {stored['return_count']}"
    )


def test_partial_year_lists_missed_codes_in_order_and_opens_no_remedial_action():
    """The two missed standards are listed in ascending code order, and because
    the compliance status is PARTIAL rather than FAIL no remedial action is
    opened against the report.

    PRD §3.7: "`failed_standard_codes` lists the codes of the standards not met, in ascending code order."
    PRD §3.7: "And if the computed compliance status is `FAIL`, acceptance triggers a four-hop cascade whose order is pinned, because the credit arithmetic at the end depends on it."
    Design: Corner/calculations/attainment_score_rounds_each_contribution_to_four_decimals
    """
    world, accepted = _accept_year_three_near_miss()

    assert accepted["failed_standard_codes"] == [
        "HYDROPERIOD_DAYS",
        "INVASIVE_COVER_PCT",
    ], (
        "the GTE hydroperiod miss and the LTE invasive-cover overshoot are the "
        f"two failures, in ascending code order, got {accepted['failed_standard_codes']}"
    )

    actions, meta = validate_paginated(
        api_client.list_remedial_actions(
            world["chair_headers"],
            params={"monitoring_report_id": accepted["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0, (
        "PARTIAL does not trigger the FAIL cascade, so no remedial action may "
        f"exist, got total_count {meta['total_count']} ({actions})"
    )

    bank = bank_state(world)
    assert bank["status"] == "MONITORING", (
        f"the accepted report still carries the bank to MONITORING, got {bank['status']}"
    )
    assert bank["deferral_count"] == 0, (
        f"no milestone was deferred by a PARTIAL year, got {bank['deferral_count']}"
    )


def _sellable_bank_with_two_quotes():
    """A DEPRESSIONAL bank with 14.82 credits available and its endowment only at
    the interim gate, quoted twice: once at the first tier's ceiling and once one
    credit above it."""
    set_clock(CLOCK_START)
    world = setup_sellable_bank(permittee_required_credits=20.00)
    quote_five = quote_credits(world, 5.00)
    quote_six = quote_credits(world, 6.00)
    return world, quote_five, quote_six


def test_marginal_tier_amounts_are_rounded_before_the_subtotal_is_summed():
    """5.00 credits price wholly inside the first tier at 20520000 cents, while
    6.00 credits split 5.00 at multiplier 1.000 and 1.00 at multiplier 0.950 for
    24418800 cents — not the 24624000 a flat scaling of the smaller quote gives.

    PRD §3.8: "Pricing starts from the bank's hydrogeomorphic class, which fixes a base price per credit: 4,250,000 cents for `RIVERINE`, 3,800,000 cents for `DEPRESSIONAL`, 3,600,000 cents for `SLOPE`, 3,300,000 cents for `FLATS` and 5,100,000 cents for `ESTUARINE`."
    PRD §3.8: "The first tier takes the requested quantity up to a ceiling of 5.00 credits at a multiplier of 1.000."
    PRD §3.8: "The second tier takes whatever remains above 5.00 credits, up to a further 10.00 credits, at a multiplier of 0.950 — so it spans the range from 5.00 to 15.00 credits."
    PRD §3.8: "Each tier carrying a non-zero quantity contributes its quantity multiplied by the base price and by its multiplier, rounded half up to whole cents, and the tiered subtotal is the sum of those already-rounded tier amounts; a tier carrying zero credits contributes nothing and is not rounded at all."
    PRD §3.8: "A bank whose stewardship endowment is funded below its requirement attracts a further 8 percent, and a fully funded bank attracts nothing."
    Design: Corner/calculations/tier_boundary_pricing_at_and_above_five_credits
    """
    world, quote_five, quote_six = _sellable_bank_with_two_quotes()

    assert world["bank"]["hgm_class"] == "DEPRESSIONAL", (
        "the canonical bank is DEPRESSIONAL, which fixes the base price"
    )
    assert world["bank"]["stewardship_funded_cents"] < world["bank"][
        "stewardship_required_cents"
    ], "the endowment sits at the interim gate, so the 8 percent surcharge applies"

    assert_cents(quote_five["quoted_price_cents"], 20520000, "quoted_price_cents at 5.00")
    assert_cents(quote_six["quoted_price_cents"], 24418800, "quoted_price_cents at 6.00")


def test_primary_tier_quote_carries_a_zero_demand_index_on_a_bank_with_no_sales():
    """Quoting into the bank's own site watershed fixes the service-area tier at
    PRIMARY, and with no settled sale anywhere the frozen demand index reads
    0.0000.

    PRD §3.8: "The impact watershed must fall inside the bank's service area, or the quote is rejected with `ERR_OUTSIDE_SERVICE_AREA`: this is the service-area limitation that gives mitigation banking its geographic integrity, and it is also what fixes the sale's `service_area_tier`, which is `PRIMARY` when the impact watershed is the bank's own site watershed and `SECONDARY` when it is any other member of the bank's service-area list."
    PRD §3.8: "For each quarter the server sums the requested credits of the bank's sales standing in `EXECUTED` or `ASSIGNED` status whose `executed_at` falls inside that quarter; sales in `QUOTED`, `RESERVED`, `CANCELLED` or `EXPIRED` status are excluded entirely, which means a reversed sale drops straight out of the measurement."
    Design: Corner/calculations/tier_boundary_pricing_at_and_above_five_credits
    """
    world, quote_five, quote_six = _sellable_bank_with_two_quotes()

    assert quote_five["service_area_tier"] == "PRIMARY", (
        "the impact watershed equals the site watershed, so the tier is PRIMARY, "
        f"got {quote_five['service_area_tier']}"
    )
    assert_score(quote_five["quoted_demand_index"], 0.0000, "quoted_demand_index")
    assert_score(quote_six["quoted_demand_index"], 0.0000, "quoted_demand_index")


def test_quoting_reserves_no_credits_and_raises_the_open_quote_tally():
    """Both quotes stand in QUOTED, the bank's open quote tally reads 2 and not a
    single credit has been placed on hold.

    PRD §3.8: "A quote opens in `QUOTED` status with `hold_start_at`, `hold_expires_at`, `executed_price_cents`, `executed_at`, `assigned_at`, `assignment_reference`, `cancelled_reason` and `cancelled_at` all null, raises the bank's `open_quote_count` by one and increments the bank's `version` by one."
    PRD §3.8: "That counter is a derived tally rather than a hand-maintained number: it is the count of the bank's credit sales standing in either `QUOTED` or `RESERVED`, so a quote that is placed on hold continues to be counted, and a sale leaves the tally only when it settles, is withdrawn or expires."
    Design: Corner/calculations/tier_boundary_pricing_at_and_above_five_credits
    """
    world, quote_five, quote_six = _sellable_bank_with_two_quotes()

    for sale in (quote_five, quote_six):
        stored = sale_state(sale["id"], world)
        assert stored["status"] == "QUOTED", (
            f"a fresh quote stands in QUOTED, got {stored['status']}"
        )
        assert stored["hold_start_at"] is None, "a quote holds nothing yet"
        assert stored["hold_expires_at"] is None, "a quote holds nothing yet"
        assert stored["executed_price_cents"] is None, "a quote has not settled"

    bank = bank_state(world)
    assert bank["open_quote_count"] == 2, (
        f"two quotes stand open on the bank, got {bank['open_quote_count']}"
    )
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold")
    assert_credits(bank["credits_available"], 14.82, "credits_available")
    assert_credit_conservation(bank)


def _bank_with_one_reserved_eight_credit_sale():
    """A sellable bank whose buyer has 40000000 cents in escrow and an 8.00-credit
    sale reserved on the first day of September 2026."""
    set_clock(CLOCK_START)
    world = setup_sellable_bank(
        permittee_required_credits=20.00, permittee_deposit_cents=40_000_000
    )
    set_clock("2026-09-01T00:00:00Z")
    sale = quote_credits(world, 8.00)
    reserve_sale(world, sale["id"])
    return world, sale


def test_a_reserved_sale_contributes_nothing_to_the_demand_measurement():
    """While the 8.00-credit sale is only RESERVED its credits are on hold but
    outside the demand window, so the index, the trailing average and the forward
    horizon all read zero.

    PRD §3.8: "For each quarter the server sums the requested credits of the bank's sales standing in `EXECUTED` or `ASSIGNED` status whose `executed_at` falls inside that quarter; sales in `QUOTED`, `RESERVED`, `CANCELLED` or `EXPIRED` status are excluded entirely, which means a reversed sale drops straight out of the measurement."
    PRD §3.8: "Reservation stamps `hold_start_at` with the current clock and `hold_expires_at` 30 days later, appends a `HOLD_PLACED` entry carrying the requested credits as a negative delta and attributed through a source entity type of `CREDIT_SALE` and the sale's own identifier, recomputes the bank's credits on hold and available credits and its posture, recomputes the bank's `open_quote_count`, and increments the bank's `version` by one."
    Design: Corner/calculations/demand_index_counts_only_executed_sales_in_the_trailing_window
    """
    world, sale = _bank_with_one_reserved_eight_credit_sale()

    assert_score(sale["quoted_demand_index"], 0.0000, "quoted_demand_index")
    assert_cents(sale["quoted_price_cents"], 32216400, "quoted_price_cents at 8.00")

    forecast = credit_forecast(world)
    assert_score(forecast["demand_index"], 0.0000, "demand_index")
    assert_credits(
        forecast["trailing_quarter_average_credits"], 0.00, "trailing_quarter_average_credits"
    )
    assert_credits(forecast["forecast_horizon_credits"], 0.00, "forecast_horizon_credits")
    assert_credits(forecast["credits_available"], 6.82, "credits_available")
    assert_credits(forecast["credits_on_hold"], 8.00, "credits_on_hold")
    assert_credits(forecast["credits_sold"], 0.00, "credits_sold")


def test_settlement_reprices_against_an_unchanged_index_and_debits_escrow():
    """Settled four days into the hold, the executed variant re-derives the same
    32216400 cents because the index is still 0.0000 and the surcharge has not
    cleared, so the 110 percent execution ceiling never binds and escrow falls to
    7783600 cents.

    PRD §3.8: "The settled price is whichever is smaller of the freshly recomputed price and the quoted price multiplied by 1.10 and rounded half up to whole cents."
    PRD §3.8: "The bank's credits on hold, credits sold and available credits are recomputed, the buyer's escrow balance is recomputed as deposits minus settled prices, the posture is recomputed and lands on `SOLD_OUT` when available credits have reached exactly zero, and the bank's `version` increments by one."
    Design: Corner/calculations/demand_index_counts_only_executed_sales_in_the_trailing_window
    """
    world, sale = _bank_with_one_reserved_eight_credit_sale()

    set_clock("2026-09-05T00:00:00Z")
    executed = get_success_data(
        api_client.execute_credit_sale(sale["id"], world["sponsor_headers"])
    )

    assert executed["status"] == "EXECUTED", (
        f"settlement advances the sale to EXECUTED, got {executed['status']}"
    )
    assert_cents(executed["executed_price_cents"], 32216400, "executed_price_cents")
    assert executed["executed_at"].startswith("2026-09-05T00:00:00"), (
        f"executed_at is stamped from the clock, got {executed['executed_at']}"
    )

    buyer = permittee_state(world)
    assert_cents(buyer["escrow_balance_cents"], 7783600, "escrow_balance_cents")
    assert_cents(buyer["deposited_cents"], 40000000, "deposited_cents")


def test_executed_sale_lands_in_the_newest_quarter_at_weight_zero_point_four():
    """Once settled, the 8.00 credits fall in the 90 days immediately preceding
    the clock, so the weighted pressure is 3.20 and the index reads 0.3200, with
    the trailing average at 2.00, the horizon at 8.00 and four quarters to
    sell-out.

    PRD §3.8: "Demand pressure is measured chronologically over the trailing 360 days, divided into four consecutive half-open 90-day quarters ending at the current logical clock, and weighted so that recent activity dominates: the oldest quarter — the one beginning 360 days ago and ending 270 days ago — carries a weight of 0.10, the next 0.20, the next 0.30, and the most recent quarter, the 90 days immediately preceding the clock, carries 0.40."
    PRD §3.8: "Each quarter's sum is multiplied by its weight and rounded half up to 2 decimal places — the per-quarter rounding precedes summation and is pinned — and those four rounded figures are added to give the demand pressure."
    PRD §3.8: "The `demand_index` is that pressure divided by a normaliser of 10.00 credits, capped at a ceiling of 3.0, with the result rounded half up to 4 decimal places."
    PRD §3.9: "`trailing_quarter_average_credits` is the total requested credits of the bank's sales standing in `EXECUTED` or `ASSIGNED` whose settlement instant falls inside the trailing 360-day window measured back from the current clock, divided by 4, rounded half up to 2 decimal places."
    PRD §3.9: "`forecast_horizon_credits` is that quarterly average multiplied by 4 and rounded half up to 2 decimal places, expressing a one-year forward sales expectation at the current rate."
    Design: Corner/calculations/demand_index_counts_only_executed_sales_in_the_trailing_window
    """
    world, sale = _bank_with_one_reserved_eight_credit_sale()

    set_clock("2026-09-05T00:00:00Z")
    get_success_data(api_client.execute_credit_sale(sale["id"], world["sponsor_headers"]))
    set_clock("2026-09-10T00:00:00Z")

    forecast = credit_forecast(world)
    assert_score(forecast["demand_index"], 0.3200, "demand_index")
    assert_credits(
        forecast["trailing_quarter_average_credits"], 2.00, "trailing_quarter_average_credits"
    )
    assert_credits(forecast["forecast_horizon_credits"], 8.00, "forecast_horizon_credits")
    assert forecast["projected_quarters_to_sellout"] == 4, (
        "6.82 available over a 2.00 quarterly average rounds up to 4 quarters, got "
        f"{forecast['projected_quarters_to_sellout']}"
    )
    assert_credits(forecast["credits_released"], 14.82, "credits_released")
    assert_credits(forecast["credits_sold"], 8.00, "credits_sold")
    assert_credits(forecast["credits_on_hold"], 0.00, "credits_on_hold")
    assert_credits(forecast["credits_available"], 6.82, "credits_available")


def test_sellout_projection_is_clamped_to_the_forty_quarter_horizon():
    """A bank with 14.82 available credits and no sales history divides by the
    0.01-credit floor, and the resulting 1482 quarters is clamped to exactly 40 —
    never the raw quotient, never null and never zero.

    PRD §3.9: "`projected_quarters_to_sellout` is 0 whenever the bank has no available credits at all; otherwise it is the available credits divided by the trailing quarterly average, rounded **up** to a whole number of quarters, with the divisor floored at 0.01 credits so that a bank with no sales history yields an enormous rather than an undefined projection, and with the whole result capped at a forecast horizon of 40 quarters."
    Design: Corner/calculations/forecast_sellout_projection_is_capped_at_the_horizon_constant
    """
    set_clock(CLOCK_START)
    world = setup_sellable_bank()

    forecast = credit_forecast(world)
    assert forecast["projected_quarters_to_sellout"] == FORECAST_HORIZON_QUARTERS, (
        "ceil(14.82 / 0.01) = 1482 quarters must be clamped to the forecast "
        f"horizon of {FORECAST_HORIZON_QUARTERS}, got "
        f"{forecast['projected_quarters_to_sellout']}"
    )
    assert_score(forecast["demand_index"], 0.0000, "demand_index")
    assert_credits(
        forecast["trailing_quarter_average_credits"], 0.00, "trailing_quarter_average_credits"
    )
    assert_credits(forecast["forecast_horizon_credits"], 0.00, "forecast_horizon_credits")


def test_forecast_aggregates_reconcile_against_the_append_only_ledger():
    """The forecast's four ledger aggregates match the bank's own projection, and
    the available figure equals the balance carried by the highest-numbered
    ledger entry.

    PRD §2.11: "The invariant no endpoint may ever break is that released credits equal the sum of sold, on-hold and available credits, and that available credits equal the `balance_after` of the bank's highest-numbered ledger entry."
    PRD §3.9: "The read also reports `credits_available`, `credits_released`, `credits_sold` and `credits_on_hold` so that a caller can reconcile the projection against the ledger in one round trip."
    Design: Corner/calculations/forecast_sellout_projection_is_capped_at_the_horizon_constant
    """
    set_clock(CLOCK_START)
    world = setup_sellable_bank()

    forecast = credit_forecast(world)
    assert_credits(forecast["credits_available"], 14.82, "credits_available")
    assert_credits(forecast["credits_released"], 14.82, "credits_released")
    assert_credits(forecast["credits_sold"], 0.00, "credits_sold")
    assert_credits(forecast["credits_on_hold"], 0.00, "credits_on_hold")

    entries, meta = validate_paginated(
        api_client.list_bank_ledger(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2, (
        "instrument execution appended GENERATED and the first release appended "
        f"RELEASED, got total_count {meta['total_count']}"
    )
    assert_ledger_sequence(entries)
    assert_credits(
        entries[-1]["balance_after"],
        forecast["credits_available"],
        "highest-sequence balance_after",
    )
    assert_credit_conservation(bank_state(world))


def _draft_bank_with_prospectus_and_work_plan():
    """A DRAFT bank carrying a drafted prospectus and a drafted work plan."""
    set_clock(CLOCK_START)
    world = setup_draft_bank()
    draft_prospectus(world)
    draft_work_plan(world)
    return world


def test_posture_ladder_reads_frozen_from_both_pre_instrument_statuses():
    """The first branch of the ladder catches DRAFT and PROSPECTUS_REVIEW alike,
    so the bank reads FROZEN before and after the prospectus is submitted even
    though nothing else about it has changed.

    PRD §2.8: "The recomputation is a first-match-wins ladder and the order of its branches is normative."
    PRD §2.8: "If the bank's `status` is `DRAFT`, `PROSPECTUS_REVIEW`, `SUSPENDED` or `CLOSED`, the posture is `FROZEN`."
    PRD §3.2: "A newly registered bank opens in `DRAFT` status with a `sales_posture` of `FROZEN`, and every credit aggregate — `total_authorized_credits`, `credits_released`, `credits_sold`, `credits_on_hold` and `credits_available` — initialised to 0.00."
    PRD §3.3: "Submission by the owning sponsor advances the prospectus `DRAFT → SUBMITTED`, stamps `submitted_at` with the current logical clock, and — this is the side effect that starts the regulatory machine — drags the bank from `DRAFT` to `PROSPECTUS_REVIEW`, recomputing the bank's posture (which remains `FROZEN`, since `PROSPECTUS_REVIEW` is not a sales-eligible status) and incrementing the bank's `version` by one."
    Design: Corner/calculations/posture_recomputation_takes_the_first_matching_branch
    """
    world = _draft_bank_with_prospectus_and_work_plan()

    assert world["bank"]["status"] == "DRAFT", (
        f"a newly registered bank opens in DRAFT, got {world['bank']['status']}"
    )
    assert world["bank"]["sales_posture"] == "FROZEN", (
        f"DRAFT is not a sales-eligible status, got {world['bank']['sales_posture']}"
    )
    assert world["bank"]["easement_recorded"] is False, (
        "the easement branch would also match, but the status branch wins first"
    )

    submit_prospectus(world)
    bank = bank_state(world)
    assert bank["status"] == "PROSPECTUS_REVIEW", (
        f"prospectus submission drags the bank into review, got {bank['status']}"
    )
    assert bank["sales_posture"] == "FROZEN", (
        f"PROSPECTUS_REVIEW is still not sales-eligible, got {bank['sales_posture']}"
    )


def test_posture_ladder_prefers_restricted_then_sold_out_then_open():
    """Once instrumented the ladder walks RESTRICTED (no easement) to SOLD_OUT
    (easement recorded, zero credits available) to OPEN (first tranche released),
    which pins the easement branch ahead of the zero-credit branch.

    PRD §2.8: "Otherwise, if the conservation easement has not been recorded, the posture is `RESTRICTED`."
    PRD §2.8: "Otherwise, if the bank's available credits are exactly zero, the posture is `SOLD_OUT`."
    PRD §2.8: "In every remaining case the posture is `OPEN`."
    PRD §3.5: "The bank's `total_authorized_credits` is set to the approved work plan's planned credit total, and that copy is the only authorised figure the commercial side of the system ever consults."
    PRD §3.5: "The sponsor supplies a single `deed_reference` — the deed book and page reference under which the easement was recorded — and the server sets `easement_recorded` to true, stamps `easement_recorded_at` with the logical clock, stores the supplied reference into `easement_deed_reference`, recomputes the posture, and increments the bank's `version` by one."
    Design: Corner/calculations/posture_recomputation_takes_the_first_matching_branch
    """
    world = _draft_bank_with_prospectus_and_work_plan()
    submit_prospectus(world)
    submit_work_plan(world)
    cast_votes(world)
    finalize_prospectus(world)
    decide_work_plan(world, "APPROVE")

    executed = get_success_data(
        api_client.execute_instrument(world["bank"]["id"], world["chair_headers"])
    )
    world["bank"] = executed
    assert executed["status"] == "INSTRUMENT_EXECUTED", (
        f"execution advances the bank's lifecycle, got {executed['status']}"
    )
    assert_credits(executed["total_authorized_credits"], 98.77, "total_authorized_credits")
    assert executed["sales_posture"] == "RESTRICTED", (
        "with no easement recorded the RESTRICTED branch matches before the "
        f"zero-credit SOLD_OUT branch, got {executed['sales_posture']}"
    )

    with_easement = record_easement_on_bank(world, DEED_REFERENCE)
    assert with_easement["sales_posture"] == "SOLD_OUT", (
        "the easement clears the RESTRICTED branch and zero available credits "
        f"match SOLD_OUT, got {with_easement['sales_posture']}"
    )
    assert with_easement["easement_recorded"] is True, "the easement is now recorded"
    assert with_easement["easement_deed_reference"] == DEED_REFERENCE, (
        f"the supplied deed reference is stored, got {with_easement['easement_deed_reference']}"
    )

    fund_stewardship(world, INTERIM_GATE_CENTS)
    release_milestone_fully(world)

    bank = bank_state(world)
    assert bank["sales_posture"] == "OPEN", (
        "with credits available, an easement recorded and no remedial action "
        f"standing, the posture falls through to OPEN, got {bank['sales_posture']}"
    )
    assert_credits(bank["credits_available"], 14.82, "credits_available")
    assert bank["status"] == "INSTRUMENT_EXECUTED", (
        f"a release never moves the bank's lifecycle status, got {bank['status']}"
    )


def _claimed_construction_milestone():
    """A sellable bank that has filed no monitoring report at all, carrying one
    CLAIMED INSTRUMENT_EXECUTION milestone at a release percentage of 0.150."""
    set_clock(CLOCK_START)
    world = setup_sellable_bank(release_first_milestone=False)
    milestone = add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
    )
    claimed = claim_milestone(world, milestone["id"])
    return world, milestone, claimed


def test_claim_computes_the_provisional_variant_and_leaves_the_factor_null():
    """The provisional quantity is the authorised total times the release
    percentage rounded to 14.82, and the claim records no attainment factor and
    no final quantity because the provisional variant always assumes 1.00.

    PRD §3.6: "Its `provisional_release_credits` is computed straight away, and is recomputed each time the milestone is claimed so that it always reflects the bank's current authorised total."
    PRD §3.6: "That provisional figure is the bank's authorised credit total multiplied by the milestone's release percentage, rounded half up to 2 decimal places."
    PRD §3.6: "A milestone opens in `PENDING` with `claimed_at`, `approved_at` and `deferred_at` null, `attainment_factor_applied` null, and `final_release_credits` at 0.00."
    PRD §3.6: "Claiming is the sponsor's assertion that the milestone has been attained, and it advances the milestone `PENDING → CLAIMED` while stamping `claimed_at` with the logical clock."
    Design: Corner/calculations/milestone_variant_selection_uses_provisional_at_claim_and_final_at_approval
    """
    world, milestone, claimed = _claimed_construction_milestone()

    assert_credits(
        milestone["provisional_release_credits"], 14.82, "provisional_release_credits at add"
    )
    assert milestone["status"] == "PENDING", (
        f"a new milestone opens in PENDING, got {milestone['status']}"
    )

    assert claimed["status"] == "CLAIMED", (
        f"claiming advances the milestone to CLAIMED, got {claimed['status']}"
    )
    assert_credits(
        claimed["provisional_release_credits"], 14.82, "provisional_release_credits at claim"
    )
    assert claimed["attainment_factor_applied"] is None, (
        "the provisional variant records no attainment factor, got "
        f"{claimed['attainment_factor_applied']}"
    )
    assert_credits(claimed["final_release_credits"], 0.00, "final_release_credits at claim")
    assert claimed["claimed_at"].startswith("2026-08-01T00:00:00"), (
        f"claimed_at is stamped from the logical clock, got {claimed['claimed_at']}"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 0.00, "credits_released before approval")


def test_final_variant_for_a_construction_milestone_consults_no_monitoring_report():
    """Approval selects the FINAL variant by milestone code, applies a factor of
    exactly 1.00 without any monitoring report existing, and releases the
    already-rounded 14.82 credits.

    PRD §3.6: "For the two construction milestones, `INSTRUMENT_EXECUTION` and `CONSTRUCTION_COMPLETE`, no monitoring is consulted at all and the attainment factor is exactly 1.00 — earthwork needs no growing season."
    PRD §3.6: "The final release quantity is then the *already-rounded* provisional quantity multiplied by the selected factor, rounded half up to 2 decimal places again."
    PRD §3.6: "Both `attainment_factor_applied` and `final_release_credits` are stamped from the calculation just described."
    PRD §3.6: "What approval does *not* do is move the bank's lifecycle status: only the bank's first accepted monitoring report carries it from `INSTRUMENT_EXECUTED` to `MONITORING`."
    Design: Corner/calculations/milestone_variant_selection_uses_provisional_at_claim_and_final_at_approval
    """
    world, milestone, claimed = _claimed_construction_milestone()

    approved = approve_release(world, milestone["id"], member_index=0)

    assert approved["status"] == "APPROVED", (
        f"approval advances the milestone to APPROVED, got {approved['status']}"
    )
    assert_credits(approved["final_release_credits"], 14.82, "final_release_credits")
    assert approved["attainment_factor_applied"] == 1.00, (
        "a construction milestone applies a factor of exactly 1.00, got "
        f"{approved['attainment_factor_applied']}"
    )
    assert approved["approved_at"].startswith("2026-08-01T00:00:00"), (
        f"approved_at is stamped from the logical clock, got {approved['approved_at']}"
    )

    reports, meta = validate_paginated(
        api_client.list_monitoring_reports(
            world["chair_headers"],
            params={"bank_id": world["bank"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0, (
        "the FINAL variant consulted no monitoring report because none exists, "
        f"got total_count {meta['total_count']}"
    )

    stored = milestone_state(milestone["id"], world)
    assert_credits(stored["final_release_credits"], 14.82, "stored final_release_credits")

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 14.82, "credits_released")
    assert_credits(bank["credits_available"], 14.82, "credits_available")
    assert bank["status"] == "INSTRUMENT_EXECUTED", (
        f"a release never advances the bank to MONITORING, got {bank['status']}"
    )
    assert_credit_conservation(bank)
