"""Paired-variant money and standing calculations that must not be collapsed into one.

Each pair drives the same stored data through both declared variants and pins the two
different answers.
"""

from test_helpers import *  # noqa: F401,F403


def _operation_with_two_accepted_quarters(
    minimum_guarantee_cents: int = 1000000,
    required_advance_cents: int = 250000,
    gross_per_quarter: int = 1500000,
):
    """Two quarters of identical sales, both accepted, on one active jersey agreement."""
    context = setup_licensed_operation(
        minimum_guarantee_cents=minimum_guarantee_cents,
        required_advance_cents=required_advance_cents,
        term_start_date="2026-01-01",
        term_end_date="2027-12-31",
    )
    licensee_id = context["licensee"]["id"]
    reports = []
    for quarter in ("2026Q1", "2026Q2"):
        lines = simple_report_lines(context["authorization"]["id"], gross_per_quarter, units=5000)
        report = create_report(context["agreement"]["id"], quarter, lines, licensee_id)
        file_report(report["id"], licensee_id)
        reports.append(accept_report(report["id"]))
    context["reports"] = reports
    context["agreement"] = get_agreement(context["agreement"]["id"])
    return context


# ---------------------------------------------------------------------------
# Provisional quarterly royalty versus the annual true-up
# ---------------------------------------------------------------------------


def test_provisional_quarters_each_use_a_single_tier_lookup(api):
    """PRD §3.7: "The tier-selection basis is `net_regular_total_cents`, and the
    applicable tier is the single entry of the category's `tier_schedule` whose
    `from_cents` is at or below the basis and whose `to_cents` is either null — the
    unbounded top tier — or strictly above the basis."

    Design: Difficulty/dual_variant_calc/royalty_provisional_quarterly_vs_final_annual_true_up
    """
    context = _operation_with_two_accepted_quarters()

    for report in context["reports"]:
        stored = get_report(report["id"])
        assert stored["net_regular_total_cents"] == 1500000
        # 1 500 000 sits inside the first band, so both quarters are rated at 1200 bps.
        assert stored["applied_tier_rate_bps"] == 1200
        assert stored["royalty_due_cents"] == 180000

    assert context["agreement"]["cumulative_royalty_cents"] == 360000
    assert_advance_ledger_conserved(context["agreement"])


def test_annual_true_up_rates_the_year_marginally_and_yields_a_credit(api, finance_headers):
    """PRD §3.7: "`delta_cents` is `true_up_royalty_cents` minus
    `provisional_total_cents` and may be negative, which represents a credit to the
    licensee; the response also reports the `agreement_id`, the `contract_year` and the
    `included_report_count`."

    Design: Difficulty/dual_variant_calc/royalty_provisional_quarterly_vs_final_annual_true_up
    """
    context = _operation_with_two_accepted_quarters()
    agreement_id = context["agreement"]["id"]
    version_before = context["agreement"]["version"]

    response = api.annual_true_up(agreement_id, annual_true_up_payload(1), finance_headers)
    data = validate_success(response, 200)

    assert data["agreement_id"] == agreement_id
    assert data["contract_year"] == 1
    assert data["included_report_count"] == 2
    assert data["cumulative_net_regular_cents"] == 3000000
    # Marginal rating: 2 000 000 at 1200 bps plus 1 000 000 at 1000 bps.
    assert data["true_up_royalty_cents"] == 340000
    assert data["provisional_total_cents"] == 360000
    assert data["delta_cents"] == -20000

    # A read-only projection never writes to the agreement's ledger.
    after = get_agreement(agreement_id)
    assert after["cumulative_royalty_cents"] == 360000
    assert after["version"] == version_before


# ---------------------------------------------------------------------------
# Rolling-monitor versus strict-assessment risk index
# ---------------------------------------------------------------------------


def _licensee_with_three_dated_risk_factors():
    """One failed sample dated in the as-of quarter plus two return rows two quarters back."""
    context = setup_licensed_operation()
    licensee_id = context["licensee"]["id"]

    lines = simple_report_lines(context["authorization"]["id"], 1000000, units=4000)
    report = create_report(context["agreement"]["id"], "2026Q1", lines, licensee_id)
    for _ in range(2):
        file_report(report["id"], licensee_id)
        return_report(report["id"])

    sample_context = setup_submission_awaiting_sample(context=context)
    record_sample_review(
        sample_context["submission"]["id"], "FAIL", defect_codes=["MARK_PLACEMENT"]
    )
    context["report"] = get_report(report["id"])
    return context


def test_rolling_monitor_variant_halves_older_factors_and_is_the_stored_index(api):
    """PRD §3.2: "The rolling-monitor profile, named `ROLLING_MONITOR`, halves a row's
    weight for each elapsed quarter but stops halving after the fourth: the factor is 1
    for a row dated in the as-of quarter, one half after one quarter, one quarter after
    two, one eighth after three, and one sixteenth for four elapsed quarters and for
    every remaining quarter inside the window."

    Design: Difficulty/dual_variant_calc/risk_index_rolling_monitor_vs_strict_assessment
    """
    context = _licensee_with_three_dated_risk_factors()
    licensee_id = context["licensee"]["id"]
    assert context["report"]["return_count"] == 2

    projection = get_risk_index(licensee_id)
    assert_risk_index_projection(projection)
    assert projection["variant"] == "ROLLING_MONITOR"
    assert projection["as_of_quarter"] == "2026Q3"
    assert projection["factor_count"] == 3
    # 8 undecayed plus two return rows of 6 at one quarter each: 8 + 1.5 + 1.5.
    assert projection["raw_weighted_total_milli"] == 11000
    assert projection["index"] == 11
    assert projection["posture_band"] == "CLEAR"

    stored = get_licensee(licensee_id)
    assert stored["compliance_risk_index"] == 11
    assert stored["risk_index_as_of_quarter"] == "2026Q3"


def test_strict_assessment_variant_keeps_every_factor_at_full_weight(api):
    """PRD §3.2: "The strict-assessment profile, named `STRICT_ASSESSMENT`, uses a
    factor of 1 for every kept row, so nothing decays inside the eight-quarter window;
    it is the renewal and underwriting view, it always yields an index at least as large
    as the rolling profile for the same data and strictly larger whenever any factor
    predates the as-of quarter, and it is never stored."

    Design: Difficulty/dual_variant_calc/risk_index_rolling_monitor_vs_strict_assessment
    """
    context = _licensee_with_three_dated_risk_factors()
    licensee_id = context["licensee"]["id"]

    projection = get_risk_index(licensee_id, params={"variant": "STRICT_ASSESSMENT"})
    assert_risk_index_projection(projection)
    assert projection["variant"] == "STRICT_ASSESSMENT"
    assert projection["factor_count"] == 3
    # 8 plus 6 plus 6, with nothing decayed.
    assert projection["raw_weighted_total_milli"] == 20000
    assert projection["index"] == 20
    assert projection["posture_band"] == "WATCH"

    # The strict view is never stored, so the licensee still carries the rolling figure.
    assert get_licensee(licensee_id)["compliance_risk_index"] == 11


# ---------------------------------------------------------------------------
# Interim pro-rata shortfall versus the final at-expiry shortfall
# ---------------------------------------------------------------------------


def test_interim_shortfall_prorates_the_guarantee_over_elapsed_quarters(api):
    """PRD §3.9: "The interim variant, run at quarter close while the term is still
    running, computes a pro-rated guarantee as `minimum_guarantee_cents` multiplied by
    the elapsed quarter count divided by the total quarter count and rounded half up,
    and sets `mg_accrued_shortfall_cents` to that pro-rated guarantee minus earned
    royalty, floored at zero; a licensee behind pace accrues a shortfall mid-term, and
    that figure can shrink again next quarter."

    Design: Difficulty/dual_variant_calc/mg_shortfall_interim_pro_rata_vs_final_at_expiry
    """
    context = _operation_with_two_accepted_quarters(
        minimum_guarantee_cents=4000000, required_advance_cents=1000000
    )

    counters = quarter_close("2026Q3")
    assert counters["as_of_quarter"] == "2026Q3"
    assert counters["agreements_expired"] == 0
    assert counters["shortfalls_assessed"] == 1

    agreement = get_agreement(context["agreement"]["id"])
    # Three of eight quarters elapsed: 4 000 000 * 3 / 8 = 1 500 000, less 360 000 earned.
    assert agreement["mg_accrued_shortfall_cents"] == 1140000
    assert agreement["mg_final_shortfall_cents"] is None


def test_final_shortfall_compares_earned_royalty_against_the_whole_guarantee(api):
    """PRD §3.9: "The final variant, run when the agreement reaches `EXPIRED` or
    `TERMINATED`, compares earned royalty against the full guarantee regardless of
    elapsed time and sets `mg_final_shortfall_cents` to `minimum_guarantee_cents` minus
    earned royalty, floored at zero."

    Design: Difficulty/dual_variant_calc/mg_shortfall_interim_pro_rata_vs_final_at_expiry
    """
    context = _operation_with_two_accepted_quarters(
        minimum_guarantee_cents=4000000, required_advance_cents=1000000
    )
    quarter_close("2026Q3")
    interim = get_agreement(context["agreement"]["id"])["mg_accrued_shortfall_cents"]

    terminated = terminate_agreement(
        context["agreement"]["id"], reason="Licensee exited the category"
    )
    assert terminated["contract_status"] == "TERMINATED"
    # The whole 4 000 000 guarantee less the 360 000 earned, with no pro-rating.
    assert terminated["mg_final_shortfall_cents"] == 3640000
    assert terminated["mg_final_shortfall_cents"] > interim
