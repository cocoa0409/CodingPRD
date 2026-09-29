"""
Derived arithmetic across the transfer desk.

This module pins the computed figures the desk reports rather than the
lifecycles that produce them: which valuation run a portfolio resolves to once a
newer one retires it, how the market curve is selected and how it shifts the
effective discount rate, how the note-rate stratification bands are assigned at
their exact edges, when a statutory borrower notice clears the fifteen-day lead,
how a hedge position is marked against the current curve and what a close
freezes, how the complaint concentration ratio and the capped remediation charge
split a holdback release, and how the reserve price scales pro rata when a tape
line is pulled.
"""

from test_helpers import (
    F,
    U,
    ApiClient,
    ERR_HEDGE_ALREADY_CLOSED,
    ERR_INVALID_REQUEST,
    ERR_NOTICE_LATE,
    ERR_RATE_CURVE_DATE_NOT_ADVANCING,
    JsonDict,
    assert_holdback_split,
    assert_stratum_breakdown,
    build_awarded_trade,
    build_completed_transfer,
    build_published_package,
    build_settled_trade,
    build_stratified_package,
    build_valued_portfolio,
    data_of,
    refresh_agreement,
    refresh_portfolio,
    refresh_transfer,
    rows_of,
    validate_error,
)

# ---------------------------------------------------------------------------
# Local fixture vocabulary
# ---------------------------------------------------------------------------

# A four-loan pool whose note rates sit exactly on the two band edges, at the
# four-decimal resolution the stored note rate keeps. Everything else matches
# the standard pool, so the fair value is unchanged by the rate spread.
_POOL_N = [
    {
        "loan_number": "N-0001", "upb_cents": 10000050,
        "note_rate_pct": 5.9999, "servicing_fee_bps": 25,
        "escrow_balance_cents": 100000, "suspense_balance_cents": 25000,
        "delinquency_bucket": "CURRENT", "loss_mit_status": "NONE",
        "state_code": "CA",
    },
    {
        "loan_number": "N-0002", "upb_cents": 10000050,
        "note_rate_pct": 6.0000, "servicing_fee_bps": 25,
        "escrow_balance_cents": 100000, "suspense_balance_cents": 25000,
        "delinquency_bucket": "CURRENT", "loss_mit_status": "NONE",
        "state_code": "TX",
    },
    {
        "loan_number": "N-0003", "upb_cents": 10000050,
        "note_rate_pct": 6.9999, "servicing_fee_bps": 25,
        "escrow_balance_cents": 100000, "suspense_balance_cents": 25000,
        "delinquency_bucket": "CURRENT", "loss_mit_status": "NONE",
        "state_code": "FL",
    },
    {
        "loan_number": "N-0004", "upb_cents": 10000050,
        "note_rate_pct": 7.0000, "servicing_fee_bps": 25,
        "escrow_balance_cents": 100000, "suspense_balance_cents": 25000,
        "delinquency_bucket": "CURRENT", "loss_mit_status": "NONE",
        "state_code": "NY",
    },
]

_CURVE_4050 = {
    "as_of_date": "2026-08-05",
    "base_rate_bps": 4050,
    "primary_secondary_spread_bps": 90,
}
_CURVE_BACK_TO_4000 = {
    "as_of_date": "2026-08-10",
    "base_rate_bps": 4000,
    "primary_secondary_spread_bps": 85,
}


def _tape_line_for(env: JsonDict, loan_id: str) -> JsonDict:
    """The single tape line the package cut for one loan."""
    matches = [line for line in env["tape_lines"] if line["loan_id"] == loan_id]
    assert len(matches) == 1, (
        f"expected exactly one tape line for loan {loan_id}, "
        f"found {len(matches)}"
    )
    return matches[0]


def _hedges_one_per_instrument(api: ApiClient) -> JsonDict:
    """
    A valued pool carrying three hedges identical in notional, ratio and entry
    rate, differing only by instrument, re-marked against a 4050 bps curve.
    """
    env = build_valued_portfolio(api)
    env["hedges"] = {
        instrument: F.open_hedge(
            api, env["portfolio_id"], instrument=instrument,
            notional_cents=260000, hedge_ratio_pct=60)
        for instrument in ("TBA_LONG", "SWAPTION_RECEIVER",
                           "TREASURY_FUTURE_LONG")
    }
    env["curve_2"] = F.create_rate_curve(api, _CURVE_4050)
    return env


def _release_ready_env(api: ApiClient) -> JsonDict:
    """
    A completed four-loan transfer carrying two complaint cases — one RESOLVED
    with 10000 cents of remediation, one still OPEN — with the clock moved to
    the day the holdback becomes eligible.
    """
    env = build_completed_transfer(api)
    case = F.open_error_case(
        api, env["transfer_id"], env["loan_ids"][0], category="ESCROW",
        description="escrow disbursement missed after the transfer")
    F.acknowledge_case(api, case["id"], env["buyer_id"])
    env["resolved_case"] = F.resolve_case(
        api, case["id"], env["buyer_id"], remediation_cents=10000,
        resolution_note="escrow disbursed and late fee refunded")
    env["open_case"] = F.open_error_case(
        api, env["transfer_id"], env["loan_ids"][1], category="SUSPENSE",
        description="suspense balance not carried over")
    F.set_clock(api, "2026-10-01T00:00:00Z")
    refresh_agreement(api, env)
    return env


# ---------------------------------------------------------------------------
# Which valuation run a portfolio resolves to
# ---------------------------------------------------------------------------
def test_effective_valuation_prefers_the_higher_sequence_run(api: ApiClient):
    """
    The portfolio resolves to the newest run even when an older run priced the
    pool at exactly the same figure, so the ranking never needs a tie-break.

    PRD: "A portfolio's effective valuation is chosen from the runs on that portfolio whose status is `COMPLETED` or `STALE`, ranked by `sequence_no` descending, taking the single highest — because the counter strictly increases per portfolio the ranking is total and needs no tie-break."

    Design: Corner/calculations/effective_valuation_selection_ignores_the_superseded_run
    """
    env = build_valued_portfolio(api)
    first_run = env["valuation_run"]
    second_run = F.run_valuation(api, env["portfolio_id"],
                                 env["assumption_set_id"],
                                 env["portfolio_version"])

    assert first_run["sequence_no"] == 1
    assert second_run["sequence_no"] == 2
    assert first_run["value_cents"] == 171576
    assert second_run["value_cents"] == 171576

    read = F.hedge_effectiveness(api, env["portfolio_id"])
    assert read["effective_valuation_run_id"] == second_run["id"]
    assert read["msr_value_cents"] == 171576
    assert read["open_hedge_mtm_cents"] == 0
    assert read["net_hedged_position_cents"] == 171576
    assert read["current_base_rate_bps"] == 4000


def test_superseded_run_drops_out_of_the_eligible_valuation_set(api: ApiClient):
    """
    A run retired by a newer one on the same portfolio is excluded from the
    effective-valuation choice and no longer drives the freshness flag.

    PRD: "`SUPERSEDED` runs are excluded from that choice, so a superseded run can never anchor a reserve price or a hedge-effectiveness read."

    Design: Corner/calculations/effective_valuation_selection_ignores_the_superseded_run
    """
    env = build_valued_portfolio(api)
    first_run = env["valuation_run"]
    assert env["portfolio"]["valuation_freshness"] == "CURRENT"

    F.run_valuation(api, env["portfolio_id"], env["assumption_set_id"],
                    env["portfolio_version"])

    retired = F.read_valuation_run(api, first_run["id"])
    assert retired["status"] == "SUPERSEDED"
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["valuation_freshness"] == "CURRENT"

    rows = rows_of(api.list_valuation_runs(
        U.ANALYST,
        {"portfolio_id": env["portfolio_id"], "status": "SUPERSEDED"}))
    assert len(rows) == 1
    assert rows[0]["id"] == first_run["id"]


# ---------------------------------------------------------------------------
# Which rate curve is the market rate
# ---------------------------------------------------------------------------
def test_publishing_a_curve_retires_the_incumbent_snapshot(api: ApiClient):
    """
    The newest snapshot becomes the only ACTIVE one, the outgoing incumbent is
    stamped SUPERSEDED, and the run priced off it goes STALE.

    PRD: "The first link retires the incumbent: the previously `ACTIVE` snapshot moves to `SUPERSEDED`, `superseded_at` is stamped with the current logical clock, and its `version` increments by 1."

    Design: Corner/calculations/active_rate_curve_is_the_newest_snapshot_and_the_date_must_advance
    """
    env = build_valued_portfolio(api)
    newer = F.create_rate_curve(api, _CURVE_4050)
    assert newer["status"] == "ACTIVE"

    incumbent = data_of(api.get_rate_curve(env["curve_id"], U.HEDGE))
    assert incumbent["status"] == "SUPERSEDED"
    assert incumbent["superseded_at"].startswith("2026-08-01T00:00:00")

    run = F.read_valuation_run(api, env["valuation_run_id"])
    assert run["status"] == "STALE"
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["valuation_freshness"] == "STALE"

    active = rows_of(api.list_rate_curves(U.HEDGE, {"status": "ACTIVE"}))
    assert len(active) == 1
    assert active[0]["id"] == newer["id"]


def test_a_new_rate_curve_must_be_dated_after_the_incumbent(api: ApiClient,
                                                            desk: JsonDict):
    """
    A snapshot dated on or before the active snapshot's market date is refused,
    and only a strictly later date is accepted.

    PRD: "The new snapshot must advance the market clock: its `as_of_date` must be strictly greater than the `as_of_date` of the snapshot currently `ACTIVE`, and a date equal to or earlier than the incumbent's is refused with `ERR_RATE_CURVE_DATE_NOT_ADVANCING` (HTTP 422)."

    Design: Corner/calculations/active_rate_curve_is_the_newest_snapshot_and_the_date_must_advance
    """
    incumbent = F.create_rate_curve(api, _CURVE_4050)
    assert incumbent["as_of_date"] == "2026-08-05"

    same_day = api.create_rate_curve(
        {"as_of_date": "2026-08-05", "base_rate_bps": 4075}, U.HEDGE)
    validate_error(same_day, ERR_RATE_CURVE_DATE_NOT_ADVANCING, 422)

    earlier = api.create_rate_curve(
        {"as_of_date": "2026-08-04", "base_rate_bps": 4075}, U.HEDGE)
    validate_error(earlier, ERR_RATE_CURVE_DATE_NOT_ADVANCING, 422)

    unchanged = data_of(api.get_rate_curve(incumbent["id"], U.HEDGE))
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["superseded_at"] is None

    accepted = F.create_rate_curve(
        api, {"as_of_date": "2026-08-06", "base_rate_bps": 4075})
    assert accepted["status"] == "ACTIVE"
    retired = data_of(api.get_rate_curve(incumbent["id"], U.HEDGE))
    assert retired["status"] == "SUPERSEDED"


# ---------------------------------------------------------------------------
# The reference rate constant and the effective discount rate
# ---------------------------------------------------------------------------
def test_valuation_at_the_reference_rate_leaves_the_discount_unshifted(
        api: ApiClient):
    """
    A curve sitting exactly on the model reference rate produces a zero rate
    delta, so the run's effective discount rate is the assumption set's own.

    PRD: "The rate delta, in percentage points, is the bound snapshot's `base_rate_bps` less the model reference rate of 4,000 basis points, divided by 100."

    Design: Corner/calculations/reference_rate_constant_shifts_the_effective_discount_rate
    """
    env = build_valued_portfolio(api)
    run = F.read_valuation_run(api, env["valuation_run_id"])

    assert run["rate_curve_snapshot_id"] == env["curve_id"]
    assert env["curve"]["base_rate_bps"] == 4000
    assert float(run["effective_discount_rate_pct"]) == 10.0
    assert run["included_loan_count"] == 4
    assert run["value_cents"] == 171576
    assert float(run["value_bps_of_upb"]) == 42.89


def test_a_fifty_basis_point_curve_rise_shifts_the_discount_rate(
        api: ApiClient):
    """
    Publishing a 4050 bps curve lifts the effective discount rate by half a
    percentage point and repriced the pool higher against the same assumptions.

    PRD: "The effective discount rate in percent is the assumption set's `discount_rate_pct` plus that rate delta; the effective float earnings rate in percent is `float_earnings_rate_pct` plus the same rate delta; and the prepayment speed used in the projection is `cpr_pct` divided by 100, that is, expressed as a fraction of the balance retired each year."

    Design: Corner/calculations/reference_rate_constant_shifts_the_effective_discount_rate
    """
    env = build_valued_portfolio(api)
    base_value = env["valuation_run"]["value_cents"]
    assert base_value == 171576

    newer = F.create_rate_curve(api, _CURVE_4050)
    refresh_portfolio(api, env)
    run = F.run_valuation(api, env["portfolio_id"], env["assumption_set_id"],
                          env["portfolio_version"])

    assert run["rate_curve_snapshot_id"] == newer["id"]
    assert float(run["effective_discount_rate_pct"]) == 10.5
    assert run["value_cents"] == 175064
    assert run["value_cents"] - base_value == 3488
    assert float(run["value_bps_of_upb"]) == 43.77


# ---------------------------------------------------------------------------
# Note-rate stratification at the band edges
# ---------------------------------------------------------------------------
def test_note_rate_bands_are_assigned_at_their_exact_edges(api: ApiClient):
    """
    A note rate of 5.9999 falls in the lowest band, 6.0000 and 6.9999 in the
    middle band, and 7.0000 in the highest, with no rounding before comparison.

    PRD: "Each line's `stratum_label` is assigned from the package's scheme — under `BY_STATE` it is the loan's `state_code`; under `BY_DELINQUENCY` it is the loan's `delinquency_bucket`; and under `BY_NOTE_RATE` it is a rate band, namely `LT_600` when the loan's `note_rate_pct` is below 6.00, `600_699` when the note rate is at least 6.00 and below 7.00, and `700_PLUS` when the note rate is 7.00 or above, with the band comparison made against the stored 4-decimal note rate and no rounding first."

    Design: Corner/calculations/note_rate_bands_are_assigned_at_their_exact_edges
    """
    env = build_stratified_package(api, scheme="BY_NOTE_RATE",
                                   loans=_POOL_N, name="Pool-N")

    labels = [
        _tape_line_for(env, loan_id)["stratum_label"]
        for loan_id in env["loan_ids"]
    ]
    assert labels == ["LT_600", "600_699", "600_699", "700_PLUS"]

    middle = F.list_tape_lines(api, env["package_id"],
                              stratum_label="600_699")
    assert len(middle) == 2
    assert sorted(line["loan_id"] for line in middle) == sorted(
        env["loan_ids"][1:3])

    # The note-rate spread does not enter the fair-value model at all.
    assert env["valuation_run"]["value_cents"] == 171576


def test_note_rate_stratification_counts_three_distinct_bands(api: ApiClient):
    """
    Four included lines spread across three bands leave the package with a
    stratum count of three over the whole tape balance.

    PRD: "The package's `tape_loan_count` is then the number of included lines, `tape_upb_cents` the sum of `upb_snapshot_cents` over included lines, and `stratum_count` the number of distinct `stratum_label` values among included lines; the package moves `DRAFT → STRATIFIED` and its `version` increments by 1."

    Design: Corner/calculations/note_rate_bands_are_assigned_at_their_exact_edges
    """
    env = build_stratified_package(api, scheme="BY_NOTE_RATE",
                                  loans=_POOL_N, name="Pool-N")
    package = env["package"]

    assert package["status"] == "STRATIFIED"
    assert package["tape_loan_count"] == 4
    assert package["tape_upb_cents"] == 40000200
    assert package["stratum_count"] == 3
    assert len(env["tape_lines"]) == 4
    assert all(line["upb_snapshot_cents"] == 10000050
               for line in env["tape_lines"])


def test_band_edge_pool_reports_its_weighted_average_note_rate(api: ApiClient):
    """
    The band-edge pool's balance-weighted note rate is carried to four decimals,
    which is the precision the band comparison is made against.

    PRD: "`loan_count` is the number of loans in the portfolio whose status is `ACTIVE`; `total_upb_cents` is the sum of their `upb_cents`; `custodial_funds_total_cents` follows the definition in §2.11; and `weighted_avg_note_rate_pct` is the unpaid-balance-weighted note rate — for the `ACTIVE` loans, the sum of each loan's `upb_cents` multiplied by its `note_rate_pct`, divided by the sum of their `upb_cents`, rounded half up to 4 decimals, and reported as 0.0000 whenever `loan_count` is 0."

    Design: Corner/calculations/note_rate_bands_are_assigned_at_their_exact_edges
    """
    env = build_valued_portfolio(api, loans=_POOL_N, name="Pool-N")
    portfolio = F.read_portfolio(api, env["portfolio_id"])

    assert portfolio["loan_count"] == 4
    assert portfolio["total_upb_cents"] == 40000200
    assert float(portfolio["weighted_avg_note_rate_pct"]) == 6.5


def test_note_rate_strata_are_priced_and_summed_band_by_band(api: ApiClient):
    """
    Pricing each band separately and summing in ascending label order gives a
    purchase price one cent above the single-rounding bid value.

    PRD: "For each distinct `stratum_label` on the awarded tape, visited in ascending lexicographic order of the label, the stratum's unpaid balance is the sum of `upb_snapshot_cents` over that stratum's included lines, and the stratum's price is that balance multiplied by the winning bid's `price_bps`, divided by 10,000, and rounded half up to whole cents."

    Design: Corner/calculations/note_rate_bands_are_assigned_at_their_exact_edges
    """
    env = build_awarded_trade(api, scheme="BY_NOTE_RATE", loans=_POOL_N,
                             name="Pool-N", price_bps=118)
    agreement = env["agreement"]

    assert env["bid"]["bid_value_cents"] == 472002
    assert agreement["purchase_price_cents"] == 472003
    assert_stratum_breakdown(agreement, ["600_699", "700_PLUS", "LT_600"])

    breakdown = agreement["stratum_price_breakdown"]
    assert breakdown["600_699"]["upb_cents"] == 20000100
    assert breakdown["600_699"]["price_cents"] == 236001
    assert breakdown["700_PLUS"]["upb_cents"] == 10000050
    assert breakdown["700_PLUS"]["price_cents"] == 118001
    assert breakdown["LT_600"]["upb_cents"] == 10000050
    assert breakdown["LT_600"]["price_cents"] == 118001


# ---------------------------------------------------------------------------
# Statutory notice lead days
# ---------------------------------------------------------------------------
def test_transferor_notice_is_compliant_at_exactly_fifteen_days_lead(
        api: ApiClient):
    """
    A seller notice sent fifteen calendar days ahead of the transfer date is
    COMPLIANT, and one sent fourteen days ahead is LATE.

    PRD: "For a `TRANSFEROR_15DAY` or a `COMBINED` notice, `lead_days` is the number of calendar days from the date the notice was sent to the effective date — the effective date less the sent date — and `compliance_status` is `COMPLIANT` when `lead_days` is at least 15, and `LATE` otherwise."

    Design: Corner/calculations/transferor_notice_is_compliant_at_exactly_fifteen_days_lead
    """
    env = build_settled_trade(api)
    assert env["transfer_date"] == "2026-09-01"

    F.set_clock(api, "2026-08-17T00:00:00Z")
    on_time = F.send_notice(api, env["transfer_id"], env["loan_ids"][0],
                            env["seller_id"])
    assert on_time["lead_days"] == 15
    assert on_time["compliance_status"] == "COMPLIANT"

    transfer = refresh_transfer(api, env)
    assert transfer["notice_count"] == 1
    assert transfer["late_notice_count"] == 0
    assert transfer["notice_status"] == "NOTICES_IN_PROGRESS"

    F.set_clock(api, "2026-08-18T00:00:00Z")
    late = F.send_notice(api, env["transfer_id"], env["loan_ids"][1],
                         env["seller_id"])
    assert late["lead_days"] == 14
    assert late["compliance_status"] == "LATE"

    transfer = refresh_transfer(api, env)
    assert transfer["notice_count"] == 2
    assert transfer["late_notice_count"] == 1


def test_notice_lead_days_ignore_the_time_of_day_it_was_sent(api: ApiClient):
    """
    A notice sent one minute before midnight fourteen days out still counts
    fourteen calendar days, so the time of day never rescues it.

    PRD: "Its compliance is then computed on calendar days only, discarding the time of day of `sent_at`."

    Design: Corner/calculations/transferor_notice_is_compliant_at_exactly_fifteen_days_lead
    """
    env = build_settled_trade(api)

    F.set_clock(api, "2026-08-17T23:59:00Z")
    on_time = F.send_notice(api, env["transfer_id"], env["loan_ids"][0],
                            env["seller_id"])
    assert on_time["lead_days"] == 15
    assert on_time["compliance_status"] == "COMPLIANT"

    F.set_clock(api, "2026-08-18T23:59:00Z")
    late = F.send_notice(api, env["transfer_id"], env["loan_ids"][1],
                         env["seller_id"])
    assert late["lead_days"] == 14
    assert late["compliance_status"] == "LATE"


def test_one_late_notice_blocks_attestation_for_the_whole_pool(api: ApiClient):
    """
    With every borrower noticed but one notice fourteen days out, attestation is
    refused on the late count rather than on coverage.

    PRD: "Attestation has two gates, reported in this order: every loan with an included tape line must have at least one `TRANSFEROR_15DAY` or `COMBINED` notice on this transfer, else `ERR_NOTICE_COMPLIANCE_INCOMPLETE` (HTTP 409); and `late_notice_count` must be exactly 0, else `ERR_NOTICE_LATE` (HTTP 409)."

    Design: Corner/calculations/transferor_notice_is_compliant_at_exactly_fifteen_days_lead
    """
    env = build_settled_trade(api)

    F.set_clock(api, "2026-08-17T00:00:00Z")
    for loan_id in env["included_loan_ids"][:3]:
        F.send_notice(api, env["transfer_id"], loan_id, env["seller_id"])

    F.set_clock(api, "2026-08-18T00:00:00Z")
    F.send_notice(api, env["transfer_id"], env["included_loan_ids"][3],
                  env["seller_id"])

    transfer = refresh_transfer(api, env)
    assert transfer["notice_count"] == 4
    assert transfer["late_notice_count"] == 1

    response = api.attest_notices(env["transfer_id"], U.COMPLIANCE)
    validate_error(response, ERR_NOTICE_LATE, 409)


def test_transferee_notice_window_is_inclusive_at_zero_and_fifteen(
        api: ApiClient):
    """
    The buyer's disclosure is COMPLIANT from the transfer date through fifteen
    days after it, and LATE when it precedes the transfer date.

    PRD: "For a `TRANSFEREE_15DAY` notice the subtraction is reversed: `lead_days` is the sent date less the effective date, and `compliance_status` is `COMPLIANT` when `lead_days` is at least 0 and at most 15, and `LATE` otherwise."

    Design: Corner/calculations/transferor_notice_is_compliant_at_exactly_fifteen_days_lead
    """
    env = build_settled_trade(api)

    F.set_clock(api, "2026-08-31T00:00:00Z")
    too_early = F.send_notice(api, env["transfer_id"], env["loan_ids"][0],
                              env["buyer_id"],
                              notice_type="TRANSFEREE_15DAY")
    assert too_early["lead_days"] == -1
    assert too_early["compliance_status"] == "LATE"

    F.set_clock(api, "2026-09-01T00:00:00Z")
    on_the_day = F.send_notice(api, env["transfer_id"], env["loan_ids"][1],
                               env["buyer_id"],
                               notice_type="TRANSFEREE_15DAY")
    assert on_the_day["lead_days"] == 0
    assert on_the_day["compliance_status"] == "COMPLIANT"

    F.set_clock(api, "2026-09-16T00:00:00Z")
    last_day = F.send_notice(api, env["transfer_id"], env["loan_ids"][2],
                             env["buyer_id"],
                             notice_type="TRANSFEREE_15DAY")
    assert last_day["lead_days"] == 15
    assert last_day["compliance_status"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# Hedge marks and the per-instrument duration factor
# ---------------------------------------------------------------------------
def test_hedge_mark_uses_the_per_instrument_option_adjusted_duration(
        api: ApiClient):
    """
    Three positions identical but for their instrument mark to different figures
    because each instrument carries its own duration factor.

    PRD: "Take `notional_cents`, multiply by `hedge_ratio_pct` and divide by 100 to get the applied notional; multiply by the instrument's option-adjusted duration factor, which is 4.5 for `TBA_LONG`, 6.0 for `SWAPTION_RECEIVER` and 5.5 for `TREASURY_FUTURE_LONG`; multiply by the difference between `entry_base_rate_bps` and the current active snapshot's base rate, taking entry less current so that a rate rise produces a negative mark; divide by 10,000; and round half up to whole cents on the magnitude, so a computed −0.5 cent becomes −1 cent."

    Design: Corner/calculations/hedge_mark_uses_the_per_instrument_option_adjusted_duration
    """
    env = _hedges_one_per_instrument(api)
    assert env["curve_2"]["base_rate_bps"] == 4050

    for opened in env["hedges"].values():
        assert opened["entry_base_rate_bps"] == 4000
        assert opened["notional_cents"] == 260000
        assert opened["mark_to_market_cents"] == 0

    tba = F.read_hedge(api, env["hedges"]["TBA_LONG"]["id"])
    swaption = F.read_hedge(api, env["hedges"]["SWAPTION_RECEIVER"]["id"])
    treasury = F.read_hedge(api, env["hedges"]["TREASURY_FUTURE_LONG"]["id"])

    assert tba["mark_to_market_cents"] == -3510
    assert swaption["mark_to_market_cents"] == -4680
    assert treasury["mark_to_market_cents"] == -4290
    assert tba["entry_base_rate_bps"] == 4000
    assert tba["status"] == "OPEN"


def test_hedge_effectiveness_sums_the_open_marks_against_the_msr_value(
        api: ApiClient):
    """
    The effectiveness read adds the three open marks together and nets them
    against the value of the servicing asset.

    PRD: "A hedge-effectiveness read on a portfolio reports the two legs side by side: `effective_valuation_run_id` (the run selected as the portfolio's effective valuation, or null when none is eligible), `msr_value_cents` (that run's `value_cents`, or 0 when there is none), `open_hedge_mtm_cents` (the sum of `mark_to_market_cents` over that portfolio's `OPEN` positions), `net_hedged_position_cents` (the MSR value plus that aggregate mark) and `current_base_rate_bps` (the base rate of the currently active snapshot)."

    Design: Corner/calculations/hedge_mark_uses_the_per_instrument_option_adjusted_duration
    """
    env = _hedges_one_per_instrument(api)

    read = F.hedge_effectiveness(api, env["portfolio_id"])
    assert read["effective_valuation_run_id"] == env["valuation_run_id"]
    assert read["current_base_rate_bps"] == 4050
    assert read["msr_value_cents"] == 171576
    assert read["open_hedge_mtm_cents"] == -12480
    assert read["net_hedged_position_cents"] == 159096


def test_closing_one_hedge_freezes_its_mark_and_leaves_the_aggregate(
        api: ApiClient):
    """
    Closing the TBA leg freezes its realized figure at the mark it carried and
    drops it out of the open aggregate, and a second close is refused.

    PRD: "A close stamps `closed_at`, sets `close_base_rate_bps` to the active snapshot's base rate, freezes `realized_pnl_cents` at the position's `mark_to_market_cents` as of that instant, moves the position `OPEN → CLOSED`, and increments its `version` by 1."

    Design: Corner/calculations/hedge_mark_uses_the_per_instrument_option_adjusted_duration
    """
    env = _hedges_one_per_instrument(api)
    tba_id = env["hedges"]["TBA_LONG"]["id"]

    closed = F.close_hedge(api, tba_id)
    assert closed["status"] == "CLOSED"
    assert closed["close_base_rate_bps"] == 4050
    assert closed["realized_pnl_cents"] == -3510

    read = F.hedge_effectiveness(api, env["portfolio_id"])
    assert read["open_hedge_mtm_cents"] == -8970
    assert read["net_hedged_position_cents"] == 162606

    again = api.close_hedge_position(tba_id, U.HEDGE)
    validate_error(again, ERR_HEDGE_ALREADY_CLOSED, 409)
    still = F.read_hedge(api, tba_id)
    assert still["realized_pnl_cents"] == -3510


# ---------------------------------------------------------------------------
# The hedge mark is path independent
# ---------------------------------------------------------------------------
def test_hedge_mark_returns_to_zero_when_the_curve_returns_to_entry(
        api: ApiClient):
    """
    A curve that rises fifty basis points and comes back leaves the position's
    mark at exactly zero, with no drift from the excursion.

    PRD: "Because the mark depends only on the current curve and not on any accumulated history, it is fully reversible: returning the curve to the entry level restores the mark to 0 with no drift."

    Design: Corner/calculations/hedge_mark_returns_to_zero_when_the_curve_returns_to_entry
    """
    env = build_valued_portfolio(api)
    hedge = F.open_hedge(api, env["portfolio_id"])
    assert hedge["entry_base_rate_bps"] == 4000
    assert hedge["mark_to_market_cents"] == 0

    F.create_rate_curve(api, _CURVE_4050)
    marked = F.read_hedge(api, hedge["id"])
    assert marked["mark_to_market_cents"] == -3510

    F.create_rate_curve(api, _CURVE_BACK_TO_4000)
    restored = F.read_hedge(api, hedge["id"])
    assert restored["mark_to_market_cents"] == 0
    assert restored["entry_base_rate_bps"] == 4000
    assert restored["status"] == "OPEN"
    assert restored["realized_pnl_cents"] is None


def test_hedge_effectiveness_is_flat_after_a_curve_round_trip(api: ApiClient):
    """
    After the round trip the effectiveness read shows the entry rate again, a
    zero open mark, and a net position equal to the servicing value alone.

    PRD: "Any operation that needs a market rate resolves it the same way: among snapshots whose `status` is `ACTIVE`, rank by `as_of_date` descending and break ties by `created_at` descending, and take the single highest-ranked row."

    Design: Corner/calculations/hedge_mark_returns_to_zero_when_the_curve_returns_to_entry
    """
    env = build_valued_portfolio(api)
    F.open_hedge(api, env["portfolio_id"])

    second = F.create_rate_curve(api, _CURVE_4050)
    third = F.create_rate_curve(api, _CURVE_BACK_TO_4000)

    read = F.hedge_effectiveness(api, env["portfolio_id"])
    assert read["current_base_rate_bps"] == 4000
    assert read["open_hedge_mtm_cents"] == 0
    assert read["msr_value_cents"] == 171576
    assert read["net_hedged_position_cents"] == 171576

    assert data_of(api.get_rate_curve(env["curve_id"], U.HEDGE))[
        "status"] == "SUPERSEDED"
    assert data_of(api.get_rate_curve(second["id"], U.HEDGE))[
        "status"] == "SUPERSEDED"
    assert data_of(api.get_rate_curve(third["id"], U.HEDGE))[
        "status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# The complaint concentration tier and the capped remediation charge
# ---------------------------------------------------------------------------
def test_complaint_ratio_counts_the_unresolved_case_too(api: ApiClient):
    """
    Two cases against four transferred loans put the transfer in the second tier
    even though only one of them has been resolved, so only half is released.

    PRD: "Count every error resolution case on the agreement's servicing transfer, in any status whatsoever — `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `REOPENED` or `ESCALATED`."

    Design: Corner/calculations/complaint_ratio_counts_every_case_but_charges_only_resolved_ones
    """
    env = _release_ready_env(api)
    assert env["transfer"]["transferred_loan_count"] == 4
    assert env["resolved_case"]["status"] == "RESOLVED"
    assert env["open_case"]["status"] == "OPEN"

    agreement = env["agreement"]
    assert agreement["status"] == "SETTLED"
    assert agreement["holdback_cents"] == 28320
    assert agreement["holdback_retained_cents"] == 28320
    assert agreement["holdback_release_eligible_at"].startswith("2026-10-01")

    released = F.release_holdback(api, env["agreement_id"],
                                 env["agreement_version"])
    assert released["holdback_retained_cents"] == 14160


def test_remediation_charge_is_capped_at_forty_percent_of_the_gross(
        api: ApiClient):
    """
    Ten thousand cents of remediation on the resolved case is charged only up to
    forty percent of this release's gross amount, and the rest is wired.

    PRD: "The charge is the smaller of the remediation total and the cap."

    Design: Corner/calculations/complaint_ratio_counts_every_case_but_charges_only_resolved_ones
    """
    env = _release_ready_env(api)
    assert env["resolved_case"]["remediation_cents"] == 10000

    released = F.release_holdback(api, env["agreement_id"],
                                 env["agreement_version"])

    # Gross 14160 of the 28320 retained; the cap truncates 40 percent of that
    # gross to 5664, which is below the 10000 of remediation recorded.
    assert released["holdback_applied_cents"] == 5664
    assert released["holdback_released_cents"] == 8496


def test_tier_two_release_leaves_a_residual_and_keeps_the_identity(
        api: ApiClient):
    """
    Half the retained balance stays behind and the three buckets still add back
    to the sized holdback after the release.

    PRD: "A tier-two release deliberately leaves a residual: half the retained balance stays behind, the agreement moves `SETTLED → HOLDBACK_RELEASED`, and a later call releases against the residual while the state remains `HOLDBACK_RELEASED`."

    Design: Corner/calculations/complaint_ratio_counts_every_case_but_charges_only_resolved_ones
    """
    env = _release_ready_env(api)

    released = F.release_holdback(api, env["agreement_id"],
                                 env["agreement_version"])

    assert released["status"] == "HOLDBACK_RELEASED"
    assert released["holdback_cents"] == 28320
    assert_holdback_split(released, retained=14160, released=8496,
                          applied=5664)


# ---------------------------------------------------------------------------
# The reserve price scales with the tape
# ---------------------------------------------------------------------------
def test_reserve_price_scales_pro_rata_when_a_tape_line_is_excluded(
        api: ApiClient):
    """
    Pulling one of four equal lines leaves the reserve at three quarters of the
    full-tape figure, with the single rounding applied only at the end.

    PRD: "The reserve is the bound run's `value_cents`, multiplied by the package's `reserve_price_floor_pct` and divided by 100, multiplied by the package's `tape_upb_cents` and divided by the portfolio's `total_upb_cents` as frozen at tape lock, with a single half-up rounding to whole cents applied only at the very end and no intermediate rounding."

    Design: Corner/calculations/reserve_price_scales_pro_rata_when_a_tape_line_is_excluded
    """
    env = build_stratified_package(api)
    assert env["package"]["stratum_count"] == 4
    assert env["package"]["tape_upb_cents"] == 40000200

    line = _tape_line_for(env, env["loan_ids"][3])
    assert line["stratum_label"] == "NY"
    assert line["upb_snapshot_cents"] == 10000050

    excluded = F.set_tape_line_inclusion(api, line["id"], False,
                                        exclusion_reason="DOCUMENT_DEFECT")
    assert excluded["included"] is False
    assert excluded["exclusion_reason"] == "DOCUMENT_DEFECT"
    assert excluded["upb_snapshot_cents"] == 10000050
    assert excluded["stratum_label"] == "NY"

    package = F.publish(api, env["package_id"])
    assert package["tape_loan_count"] == 3
    assert package["tape_upb_cents"] == 30000150
    assert package["stratum_count"] == 3
    assert package["reserve_price_cents"] == 122248


def test_a_full_tape_reserve_is_the_whole_pro_rata_share(api: ApiClient):
    """
    With every line included the reserve is the floor percentage of the whole
    valuation, which is the figure the pro-rata exclusion scales down from.

    PRD: "The reserve is the bound run's `value_cents`, multiplied by the package's `reserve_price_floor_pct` and divided by 100, multiplied by the package's `tape_upb_cents` and divided by the portfolio's `total_upb_cents` as frozen at tape lock, with a single half-up rounding to whole cents applied only at the very end and no intermediate rounding."

    Design: Corner/calculations/reserve_price_scales_pro_rata_when_a_tape_line_is_excluded
    """
    env = build_published_package(api)
    package = env["package"]

    assert package["status"] == "PUBLISHED"
    assert package["reserve_price_floor_pct"] == 95
    assert package["tape_loan_count"] == 4
    assert package["tape_upb_cents"] == 40000200
    assert package["reserve_price_cents"] == 162997
    assert env["valuation_run"]["value_cents"] == 171576


def test_excluding_a_line_leaves_the_valuation_and_pool_total_untouched(
        api: ApiClient):
    """
    The excluded line shrinks only the tape: the bound run and the frozen pool
    total are exactly as they were.

    PRD: "Excluding a tape line therefore shrinks `tape_upb_cents` while leaving the portfolio total and the valuation untouched, so the reserve scales down pro rata by unpaid balance."

    Design: Corner/calculations/reserve_price_scales_pro_rata_when_a_tape_line_is_excluded
    """
    env = build_stratified_package(api)
    line = _tape_line_for(env, env["loan_ids"][3])
    F.set_tape_line_inclusion(api, line["id"], False,
                              exclusion_reason="LITIGATION")
    F.publish(api, env["package_id"])

    run = F.read_valuation_run(api, env["valuation_run_id"])
    assert run["value_cents"] == 171576
    assert run["included_loan_count"] == 4

    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["total_upb_cents"] == 40000200
    assert portfolio["loan_count"] == 4


def test_reduced_tape_prices_both_the_bid_and_the_agreement(api: ApiClient):
    """
    A bid on the shrunken tape is priced over the reduced balance in one
    rounding, while the agreement rounds each surviving stratum separately.

    PRD: "The bid's own economics are computed as `bid_value_cents`: the package's `tape_upb_cents` multiplied by `price_bps`, divided by 10,000, rounded half up to whole cents — **one** rounding over the whole tape."

    Design: Corner/calculations/reserve_price_scales_pro_rata_when_a_tape_line_is_excluded
    """
    env = build_stratified_package(api)
    line = _tape_line_for(env, env["loan_ids"][3])
    F.set_tape_line_inclusion(api, line["id"], False,
                              exclusion_reason="INVESTOR_RESTRICTION")

    env["package"] = F.publish(api, env["package_id"])
    env["package_version"] = env["package"]["version"]
    assert env["package"]["reserve_price_cents"] == 122248

    bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                       env["package_version"], price_bps=118, holdback_pct=6)
    assert bid["bid_value_cents"] == 354002

    agreement = F.award(api, env["package_id"], bid["id"])
    assert agreement["purchase_price_cents"] == 354003
    assert_stratum_breakdown(agreement, ["CA", "FL", "TX"])


def test_excluding_a_tape_line_requires_an_exclusion_reason(api: ApiClient):
    """
    A line cannot be pulled from the tape without naming why, so the reduced
    reserve always carries its justification.

    PRD: "While the package is `STRATIFIED`, a `ValuationAnalyst` may pull or restore individual lines by setting `included`, supplying `exclusion_reason` — `DOCUMENT_DEFECT`, `LITIGATION` or `INVESTOR_RESTRICTION` — which is required whenever `included` is set to false and must be absent whenever `included` is true."

    Design: Corner/calculations/reserve_price_scales_pro_rata_when_a_tape_line_is_excluded
    """
    env = build_stratified_package(api)
    line = _tape_line_for(env, env["loan_ids"][3])

    response = api.patch_tape_line(line["id"], {"included": False}, U.ANALYST)
    validate_error(response, ERR_INVALID_REQUEST, 422)

    unchanged = _tape_line_for(env, env["loan_ids"][3])
    assert unchanged["included"] is True
    package = F.publish(api, env["package_id"])
    assert package["tape_upb_cents"] == 40000200
    assert package["reserve_price_cents"] == 162997
