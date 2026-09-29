"""Pricing depth: the two subscriber-report fee variants, the two audit
recovery rate bases, the two renewal-leverage variants, the MFN benchmark
selection, the six-step net-due waterfall and the two-sided rate clamp.

Every fixture is built from scratch through PRD-declared endpoints.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    agreement_version,
    api_client,
    attach_mfn_clause,
    create_commitment,
    draft_invoice,
    earn_commitment,
    fetch_agreement,
    fetch_commitment,
    fetch_report,
    file_and_accept_report,
    file_report,
    open_engagement,
    record_finding,
    run_renewal_analysis,
    setup_executed_agreement,
    setup_peer_agreement,
    start_fieldwork,
    validate_success,
)

SALES = TEST_USERS["affiliate_sales_exec_headers"]
AUDITOR = TEST_USERS["audit_manager_headers"]
ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]

# --------------------------------------------------------------------------
# Operator / agreement shapes used by the recipes in this module
# --------------------------------------------------------------------------
# "Cliffside Telco": 200,000 subscribers on a flat 40.0000 BASIC agreement.
CLIFFSIDE_DISTRIBUTOR = {
    "legal_name": "Cliffside Telco",
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
    "credit_limit_cents": 100_000_000,
}
CLIFFSIDE_AGREEMENT = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}

# "Vale Satellite Group": DBS peer, 12,000,000 subscribers, 3% escalator.
VALE_AGREEMENT = {
    "escalator_pct": 0.03,
    "penetration_floor_pct": 0.80,
    "committed_tier": "EXPANDED_BASIC",
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
}
# "Streamline Digital": VMVPD peer, 1,500,000 subscribers, flat 38.0000.
STREAMLINE_AGREEMENT = {
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.70,
    "committed_tier": "EXPANDED_BASIC",
    "term_start_date": "2025-06-01T00:00:00Z",
    "term_end_date": "2028-05-31T00:00:00Z",
}


def _reset_mfn_benchmark(clause_id: str, agreement_id: str):
    """Re-run one clause's benchmark against the agreement's live revision."""
    return api_client.reset_mfn_clause(
        clause_id,
        {"action": "RESET", "expected_agreement_version": agreement_version(agreement_id)},
        SALES,
    )


def _setup_two_month_audit_sample(rate_basis: str):
    """Northgate with 2024-03 and 2026-03 accepted, then one engagement over
    that two-year sample in FIELDWORK holding a 100,000-subscriber finding on
    each month.

    Returns (distributor, agreement, engagement, finding_2024_03, finding_2026_03).
    """
    distributor, agreement = setup_executed_agreement()
    report_2024 = file_and_accept_report(
        agreement["id"],
        distributor["id"],
        period_month="2024-03",
        reported_subscribers=3_600_000,
    )
    report_2026 = file_and_accept_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-03",
        reported_subscribers=3_500_000,
    )
    engagement = open_engagement(
        agreement["id"],
        sample_period_start="2024-03",
        sample_period_end="2026-03",
        rate_basis=rate_basis,
    )
    engagement = start_fieldwork(engagement["id"])
    finding_2024 = record_finding(engagement["id"], report_2024["id"], 3_700_000)
    finding_2026 = record_finding(engagement["id"], report_2026["id"], 3_600_000)
    return distributor, agreement, engagement, finding_2024, finding_2026


def _setup_coop_band_fixture():
    """A flat-rate operator whose accepted period grosses 5,200,000 cents —
    200,000 above the middle co-op band's lower bound — against a co-op line
    with 500,000 cents earned and nothing billed.

    Returns (distributor, agreement, commitment, report).
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE_DISTRIBUTOR, CLIFFSIDE_AGREEMENT)
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-12-31T00:00:00Z",
    )
    commitment = earn_commitment(commitment["id"], 500_000, "COOP-Q2-2026-INSERTION-ORDER")
    report = file_and_accept_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    return distributor, agreement, commitment, report


def _setup_three_operator_market():
    """The subject agreement plus a DBS peer and a VMVPD peer, all on
    EXPANDED_BASIC and all current against the clock.

    Returns (subject_distributor, subject_agreement, vale_agreement,
    streamline_agreement).
    """
    _vale_distributor, vale_agreement = setup_peer_agreement(
        40.0000, "DBS", 12_000_000, **VALE_AGREEMENT
    )
    _streamline_distributor, streamline_agreement = setup_peer_agreement(
        38.0000, "VMVPD", 1_500_000, **STREAMLINE_AGREEMENT
    )
    subject_distributor, subject_agreement = setup_executed_agreement()
    return subject_distributor, subject_agreement, vale_agreement, streamline_agreement


def _setup_leverage_agreement():
    """Northgate with one accepted 2026-06 month at 3,500,000 subscribers,
    i.e. 0.8750 penetration against the 0.85 floor."""
    distributor, agreement = setup_executed_agreement()
    report = file_and_accept_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=3_500_000,
    )
    return distributor, fetch_agreement(agreement["id"]), report


class TestSubscriberReportFeeVariants:
    """The provisional accrual figure and the final billable figure on one row."""

    def test_provisional_fee_takes_reported_subscribers_verbatim(self):
        """PRD §3.4: "Under the **provisional** variant, stamped at submission into
        `provisional_fee_cents`, the billable count is `reported_subscribers`
        verbatim; the penetration floor is ignored entirely."
        PRD §3.4: "The fee is the billable subscriber count multiplied by
        `rate_applied_cents_per_sub` multiplied by that tier multiplier, rounded
        half up to a whole number of cents."
        PRD §3.3: "The escalated rate is then `base_license_fee_cents_per_sub`
        multiplied by one plus `escalator_pct`, raised to the power of that
        contract-year index, rounded half up to four decimal places of a cent."
        PRD §3.4: "`penetration_pct` is `reported_subscribers` divided by the
        operator's `total_subscribers`, rounded half up to four decimal places."
        PRD §3.4: "A new report opens in `SUBMITTED` with `license_fee_due_cents`
        0, `audit_adjustment_cents` 0, `invoice_id` null, `accepted_at` null and
        `version` 1, and it increments the agreement's `version` by one."

        Design: Difficulty/dual_variant_calc/final_fee_exceeds_provisional_when_reported_below_penetration_floor
        """
        distributor, agreement = setup_executed_agreement()

        report = file_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-06",
            reported_subscribers=3_200_000,
        )

        assert report["status"] == "SUBMITTED", f"a fresh filing opens in SUBMITTED, got {report['status']}"
        assert report["rate_applied_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            "2026-06 falls in contract year index 2, so the rate applied is "
            f"45.4272, got {report['rate_applied_cents_per_sub']}"
        )
        assert report["penetration_pct"] == pytest.approx(0.8000, abs=0.0001), (
            f"3,200,000 of 4,000,000 subscribers is 0.8000 penetration, got {report['penetration_pct']}"
        )
        assert report["provisional_fee_cents"] == 145367040, (
            "the provisional variant prices the reported 3,200,000 subscribers at "
            f"45.4272, i.e. 145367040 cents, got {report['provisional_fee_cents']}"
        )
        assert report["license_fee_due_cents"] == 0, (
            f"a SUBMITTED report carries license_fee_due_cents 0, got {report['license_fee_due_cents']}"
        )
        assert report["accepted_at"] is None, "a SUBMITTED report has accepted_at null"

    def test_final_fee_substitutes_the_penetration_floor_at_acceptance(self):
        """PRD §3.4: "Under the **final** variant, stamped at acceptance into
        `billable_subscribers` and `license_fee_due_cents`, the billable count is
        the greater of `reported_subscribers` and the floor subscriber count."
        PRD §3.4: "Compute the floor subscriber count as the agreement's
        `penetration_floor_pct` multiplied by the operator's `total_subscribers`,
        discarding any fraction."
        PRD §3.4: "Whenever the operator reported fewer subscribers than the floor
        requires, the final fee therefore strictly exceeds the provisional fee for
        identical inputs — the network bills the floor it negotiated, not the
        shortfall the operator delivered."
        PRD §3.4: "A successful acceptance stamps `billable_subscribers`,
        `rate_applied_cents_per_sub` and `license_fee_due_cents` under the final
        variant, sets `accepted_at` to the current logical instant, and moves the
        report `SUBMITTED → ACCEPTED`."
        PRD §3.4: "`tier_placement_breach` is true exactly when the tier actually
        used was narrower than the tier committed: rank the tiers with `BASIC` at
        4, `EXPANDED_BASIC` at 3, `DIGITAL_TIER` at 2 and `PREMIUM` at 1, where a
        higher rank means broader carriage, and set the flag when the rank of
        `reported_tier` is strictly below the rank of the agreement's
        `committed_tier`."

        Design: Difficulty/dual_variant_calc/final_fee_exceeds_provisional_when_reported_below_penetration_floor
        """
        distributor, agreement = setup_executed_agreement()
        report = file_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-06",
            reported_subscribers=3_200_000,
        )

        accepted = validate_success(
            api_client.review_subscriber_report(report["id"], {"action": "ACCEPT"}, ACCOUNTANT)
        )

        assert accepted["status"] == "ACCEPTED", f"acceptance moves the report to ACCEPTED, got {accepted['status']}"
        assert accepted["billable_subscribers"] == 3400000, (
            "the final variant bills the floor count floor(0.85 * 4,000,000) = "
            f"3400000, got {accepted['billable_subscribers']}"
        )
        assert accepted["license_fee_due_cents"] == 154452480, (
            f"3400000 subscribers at 45.4272 is 154452480 cents, got {accepted['license_fee_due_cents']}"
        )
        assert accepted["provisional_fee_cents"] == 145367040, (
            "the accrual figure 145367040 is not overwritten by acceptance, got "
            f"{accepted['provisional_fee_cents']}"
        )
        assert accepted["license_fee_due_cents"] > accepted["provisional_fee_cents"], (
            "an under-penetrating operator owes strictly more than it accrued"
        )
        assert accepted["rate_applied_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            f"the applied rate stays 45.4272, got {accepted['rate_applied_cents_per_sub']}"
        )
        assert accepted["tier_placement_breach"] is False, (
            "EXPANDED_BASIC reported against EXPANDED_BASIC committed is no tier breach"
        )
        assert accepted["accepted_at"] is not None, "acceptance stamps accepted_at"

    def test_final_fee_flows_into_recognised_revenue_and_marks_the_breach(self):
        """PRD §3.4: "First, the agreement's `recognized_revenue_cents` increases
        by the newly stamped `license_fee_due_cents`, and
        `penetration_compliance_status` is re-derived as described in §3.5."
        PRD §3.5: "A non-compliant period does the reverse."
        PRD §3.5: "`consecutive_compliant_periods` drops to 0,
        `penetration_breach_count` increments by one, and
        `penetration_compliance_status` becomes `BREACH`."
        PRD §3.5: "The comparison is **inclusive**: the period is compliant when
        the report's `penetration_pct` is greater than or equal to the agreement's
        `penetration_floor_pct`, with both values rounded to four decimal places
        before being compared, so an operator that lands exactly on its floor is
        compliant."

        Design: Difficulty/dual_variant_calc/final_fee_exceeds_provisional_when_reported_below_penetration_floor
        """
        distributor, agreement = setup_executed_agreement()
        report = file_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-06",
            reported_subscribers=3_200_000,
        )

        validate_success(
            api_client.review_subscriber_report(report["id"], {"action": "ACCEPT"}, ACCOUNTANT)
        )

        after = fetch_agreement(agreement["id"])
        assert after["recognized_revenue_cents"] == 154452480, (
            "recognised revenue takes the final fee 154452480, not the provisional "
            f"145367040, got {after['recognized_revenue_cents']}"
        )
        assert after["penetration_compliance_status"] == "BREACH", (
            f"0.8000 penetration is below the 0.85 floor, got {after['penetration_compliance_status']}"
        )
        assert after["penetration_breach_count"] == 1, (
            f"one non-compliant accepted period is one breach, got {after['penetration_breach_count']}"
        )
        assert after["consecutive_compliant_periods"] == 0, (
            f"a non-compliant period drops the run to 0, got {after['consecutive_compliant_periods']}"
        )


class TestAuditRecoveryRateBasisVariants:
    """PERIOD_RATE re-prices each audited month; CLOSING_RATE re-prices the
    whole sample at the rate standing when findings issue."""

    def test_period_rate_prices_each_finding_at_its_own_period_rate(self):
        """PRD §3.7: "Under `PERIOD_RATE` — the contractual reading — each audited
        month is re-priced at the agreement's effective rate for that month's own
        `period_month`, escalator and MFN cap included."
        PRD §3.7: "The selected figure is stamped on the finding as its
        `rate_applied_cents_per_sub`."
        PRD §3.7: "Stamp `finding_recovery_cents` as the variance multiplied by the
        selected rate multiplied by that tier multiplier, rounded half up to a
        whole cent."
        PRD §3.7: "This rounding happens per finding, before anything is
        accumulated."
        PRD §3.7: "The engagement's `base_recovery_cents` and `interest_cents` are
        those two accumulated totals, `total_variance_subscribers` is the
        accumulated variance and `total_reported_subscribers` the accumulated
        reported count."

        Design: Difficulty/dual_variant_calc/audit_recovery_period_rate_versus_closing_rate_variants
        """
        _distributor, _agreement, engagement, finding_2024, finding_2026 = (
            _setup_two_month_audit_sample("PERIOD_RATE")
        )

        issued = validate_success(
            api_client.audit_engagement_lifecycle(
                engagement["id"], {"action": "ISSUE_FINDINGS"}, AUDITOR
            )
        )

        assert issued["status"] == "FINDINGS_ISSUED", (
            f"issuing findings moves the engagement to FINDINGS_ISSUED, got {issued['status']}"
        )
        priced_2024 = validate_success(api_client.get_audit_finding(finding_2024["id"], AUDITOR))
        priced_2026 = validate_success(api_client.get_audit_finding(finding_2026["id"], AUDITOR))
        assert priced_2024["rate_applied_cents_per_sub"] == pytest.approx(42.0000, abs=0.0001), (
            "the 2024-03 finding is re-priced at that month's own rate 42.0000, got "
            f"{priced_2024['rate_applied_cents_per_sub']}"
        )
        assert priced_2024["finding_recovery_cents"] == 4200000, (
            f"100,000 subscribers at 42.0000 is 4200000 cents, got {priced_2024['finding_recovery_cents']}"
        )
        assert priced_2026["rate_applied_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            "the 2026-03 finding is re-priced at 45.4272, got "
            f"{priced_2026['rate_applied_cents_per_sub']}"
        )
        assert priced_2026["finding_recovery_cents"] == 4542720, (
            f"100,000 subscribers at 45.4272 is 4542720 cents, got {priced_2026['finding_recovery_cents']}"
        )
        assert issued["base_recovery_cents"] == 8742720, (
            "the base total accumulates the two already-rounded recoveries to "
            f"8742720, got {issued['base_recovery_cents']}"
        )
        assert issued["total_variance_subscribers"] == 200000, (
            f"two findings of 100,000 each is 200000, got {issued['total_variance_subscribers']}"
        )
        assert issued["total_reported_subscribers"] == 7100000, (
            "the snapshotted reported counts 3,600,000 and 3,500,000 total 7100000, got "
            f"{issued['total_reported_subscribers']}"
        )

    def test_period_rate_interest_and_recovery_totals(self):
        """PRD §3.7: "Count the whole calendar months from the **last day of the
        finding's `period_month`** to the current logical instant, treating any
        negative count as zero, and multiply `finding_recovery_cents` by 0.0075 —
        three quarters of one percent per month, simple, not compounding — and by
        that month count, rounding half up to a whole cent."
        PRD §3.7: "`underreporting_pct` is `total_variance_subscribers` divided by
        `total_reported_subscribers`, rounded half up to four decimal places, and
        is exactly 0 when the denominator is 0."
        PRD §3.7: "`penalty_multiplier` is then selected from `underreporting_pct`
        by a ladder with inclusive lower bounds: 1.00 below 0.0500, 1.10 from
        0.0500 up to but not including 0.1000, and 1.25 at 0.1000 and above."
        PRD §3.7: "Separately, `audit_cost_shift_cents` is 2,500,000 cents — the
        network's flat 25,000-dollar cost of audit, shifted onto the operator —
        whenever `underreporting_pct` is at least 0.0500, and 0 otherwise; the
        shift threshold and the first penalty step deliberately coincide."
        PRD §3.7: "Finally, `recovery_amount_cents` is the sum of the base total
        and the interest total, multiplied by `penalty_multiplier` and rounded half
        up to a whole cent, and then the `audit_cost_shift_cents` is added on top —
        the cost shift is never itself penalty-multiplied."

        Design: Difficulty/dual_variant_calc/audit_recovery_period_rate_versus_closing_rate_variants
        """
        _distributor, _agreement, engagement, _f24, _f26 = _setup_two_month_audit_sample(
            "PERIOD_RATE"
        )

        issued = validate_success(
            api_client.audit_engagement_lifecycle(
                engagement["id"], {"action": "ISSUE_FINDINGS"}, AUDITOR
            )
        )

        assert issued["underreporting_pct"] == pytest.approx(0.0282, abs=0.0001), (
            f"200,000 of 7,100,000 is 0.0282 under-reporting, got {issued['underreporting_pct']}"
        )
        assert issued["penalty_multiplier"] == pytest.approx(1.00, abs=0.01), (
            f"0.0282 sits below the 0.0500 step, so the multiplier stays 1.00, got {issued['penalty_multiplier']}"
        )
        assert issued["audit_cost_shift_cents"] == 0, (
            f"no cost is shifted below 0.0500 under-reporting, got {issued['audit_cost_shift_cents']}"
        )
        assert issued["interest_cents"] == 1018282, (
            "interest accrues per finding on its own rounded recovery, totalling "
            f"1018282 cents, got {issued['interest_cents']}"
        )
        assert issued["recovery_amount_cents"] == 9761002, (
            f"base plus interest at multiplier 1.00 is 9761002 cents, got {issued['recovery_amount_cents']}"
        )

    def test_closing_rate_prices_the_whole_sample_at_the_issuance_rate(self):
        """PRD §3.7: "Under `CLOSING_RATE` — the settlement reading — every finding
        in the sample uses one single figure: the agreement's
        `effective_rate_cents_per_sub` as it stands at the findings-issuance
        instant."
        PRD §3.7: "On an escalating agreement the closing-rate reading produces a
        strictly larger recovery than the period-rate reading for the same
        findings, because early periods are re-priced at the later, higher rate."
        PRD §3.7: "Stamp `finding_recovery_cents` as the variance multiplied by the
        selected rate multiplied by that tier multiplier, rounded half up to a
        whole cent."

        Design: Difficulty/dual_variant_calc/audit_recovery_period_rate_versus_closing_rate_variants
        """
        _distributor, _agreement, engagement, finding_2024, finding_2026 = (
            _setup_two_month_audit_sample("CLOSING_RATE")
        )

        issued = validate_success(
            api_client.audit_engagement_lifecycle(
                engagement["id"], {"action": "ISSUE_FINDINGS"}, AUDITOR
            )
        )

        priced_2024 = validate_success(api_client.get_audit_finding(finding_2024["id"], AUDITOR))
        priced_2026 = validate_success(api_client.get_audit_finding(finding_2026["id"], AUDITOR))
        assert priced_2024["rate_applied_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            "under CLOSING_RATE the 2024-03 finding is priced at the closing 45.4272, got "
            f"{priced_2024['rate_applied_cents_per_sub']}"
        )
        assert priced_2026["rate_applied_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            f"both findings share one figure, got {priced_2026['rate_applied_cents_per_sub']}"
        )
        assert issued["base_recovery_cents"] == 9085440, (
            f"two findings at 45.4272 total 9085440 cents of base recovery, got {issued['base_recovery_cents']}"
        )
        assert issued["interest_cents"] == 1090253, (
            f"the larger per-finding recovery carries larger interest, 1090253, got {issued['interest_cents']}"
        )
        assert issued["recovery_amount_cents"] == 10175693, (
            "the closing-rate reading recovers 10175693 cents against the "
            f"period-rate 9761002, got {issued['recovery_amount_cents']}"
        )


class TestRenewalLeverageVariants:
    """The leverage score is variant-invariant; only the recapture-driven loss
    projections move between BASE_CASE and DOWNSIDE."""

    def test_normalised_inputs_and_leverage_score(self):
        """PRD §3.9: "That report's identifier is recorded as
        `latest_accepted_report_id`."
        PRD §3.9: "`subscriber_share` is the operator's `total_subscribers`
        divided by 90,000,000 — the assumed national addressable universe —
        rounded half up to six decimal places."
        PRD §3.9: "`penetration_ratio` is the selected report's `penetration_pct`
        divided by the agreement's `penetration_floor_pct`, capped at 2.0, rounded
        half up to four decimal places."
        PRD §3.9: "`payment_score` is 1 less the operator's
        `receivable_balance_cents` divided by its `credit_limit_cents`, where that
        ratio is first clamped into the range 0 to 1 inclusive and the divisor is
        treated as at least 1 to keep it defined, rounded half up to four decimal
        places."
        PRD §3.9: "`compliance_score` is 1 less the agreement's
        `penetration_breach_count` divided by 3, that ratio likewise clamped into 0
        to 1 inclusive, rounded half up to four decimal places."
        PRD §3.9: "`leverage_score` is 100 multiplied by the weighted sum of four
        normalised terms — 0.40 times `subscriber_share` divided by 0.15 and capped
        at 1.0, plus 0.25 times `penetration_ratio` divided by 1.5 and capped at
        1.0, plus 0.20 times `payment_score`, plus 0.15 times `compliance_score` —
        rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/renewal_leverage_base_case_versus_downside_variants
        """
        _distributor, agreement, report = _setup_leverage_agreement()

        analysis = run_renewal_analysis(agreement["id"], variant="BASE_CASE")

        assert analysis["latest_accepted_report_id"] == report["id"], (
            "the only ACCEPTED report is the model's evidence, got "
            f"{analysis['latest_accepted_report_id']}"
        )
        assert analysis["subscriber_share"] == pytest.approx(0.044444, abs=1e-6), (
            f"4,000,000 of 90,000,000 is 0.044444, got {analysis['subscriber_share']}"
        )
        assert analysis["penetration_ratio"] == pytest.approx(1.0294, abs=0.0001), (
            f"0.8750 over the 0.85 floor is 1.0294, got {analysis['penetration_ratio']}"
        )
        assert analysis["payment_score"] == pytest.approx(1.0000, abs=0.0001), (
            f"an operator with no receivable scores 1.0000, got {analysis['payment_score']}"
        )
        assert analysis["compliance_score"] == pytest.approx(1.0000, abs=0.0001), (
            f"no breaches on file scores 1.0000, got {analysis['compliance_score']}"
        )
        assert analysis["leverage_score"] == pytest.approx(64.01, abs=0.01), (
            f"the weighted sum of those four terms is 64.01, got {analysis['leverage_score']}"
        )

    def test_leverage_score_is_identical_across_the_two_variants(self):
        """PRD §3.9: "The variant then selects a single behavioural assumption,
        `recapture_rate`: 0.35 under `BASE_CASE` and 0.10 under `DOWNSIDE` — the
        fraction of subscribers assumed to follow the network to a competing
        distributor if this agreement lapses."
        PRD §3.9: "`leverage_score` is computed entirely from the operator's
        structural position and payment history, so it is **identical** for the two
        variants of the same agreement at the same instant; only
        `distribution_loss_subscribers` and `annualized_revenue_at_risk_cents`
        differ, and the `DOWNSIDE` variant — assuming less recapture — always
        yields the larger loss and the larger revenue at risk."
        PRD §3.9: "Both figures are also stamped with the `variant` and
        `recapture_rate` that produced them, so two models of the same agreement
        can be compared directly."

        Design: Difficulty/dual_variant_calc/renewal_leverage_base_case_versus_downside_variants
        """
        _distributor, agreement, _report = _setup_leverage_agreement()

        base_case = run_renewal_analysis(agreement["id"], variant="BASE_CASE")
        downside = run_renewal_analysis(agreement["id"], variant="DOWNSIDE")

        assert base_case["variant"] == "BASE_CASE", (
            f"the requested variant is stamped on the snapshot, got {base_case['variant']}"
        )
        assert downside["variant"] == "DOWNSIDE", (
            f"the requested variant is stamped on the snapshot, got {downside['variant']}"
        )
        assert base_case["recapture_rate"] == pytest.approx(0.35, abs=0.0001), (
            f"BASE_CASE assumes 0.35 recapture, got {base_case['recapture_rate']}"
        )
        assert downside["recapture_rate"] == pytest.approx(0.10, abs=0.0001), (
            f"DOWNSIDE assumes 0.10 recapture, got {downside['recapture_rate']}"
        )
        assert downside["leverage_score"] == pytest.approx(base_case["leverage_score"], abs=0.01), (
            "no weight depends on recapture, so both variants score identically: "
            f"{base_case['leverage_score']} vs {downside['leverage_score']}"
        )
        assert downside["leverage_score"] == pytest.approx(64.01, abs=0.01), (
            f"both rows score 64.01, got {downside['leverage_score']}"
        )
        assert downside["distribution_loss_subscribers"] > base_case["distribution_loss_subscribers"], (
            "assuming less recapture always yields the larger loss, got "
            f"{downside['distribution_loss_subscribers']} vs "
            f"{base_case['distribution_loss_subscribers']}"
        )
        assert (
            downside["annualized_revenue_at_risk_cents"]
            > base_case["annualized_revenue_at_risk_cents"]
        ), (
            "assuming less recapture always yields the larger revenue at risk, got "
            f"{downside['annualized_revenue_at_risk_cents']} vs "
            f"{base_case['annualized_revenue_at_risk_cents']}"
        )

    def test_recapture_rate_drives_the_loss_and_revenue_at_risk_figures(self):
        """PRD §3.9: "`distribution_loss_subscribers` is the operator's
        `total_subscribers` multiplied by the selected report's `penetration_pct`
        multiplied by one less `recapture_rate`, rounded half up to a whole
        subscriber."
        PRD §3.9: "`annualized_revenue_at_risk_cents` is that loss count
        multiplied by the agreement's `effective_rate_cents_per_sub` multiplied by
        12, rounded half up to a whole cent."
        PRD §3.9: "A model is an immutable snapshot: it records what the numbers
        said at one logical instant, carries `id` and `created_at` only, and is
        never updated or deleted."

        Design: Difficulty/dual_variant_calc/renewal_leverage_base_case_versus_downside_variants
        """
        _distributor, agreement, _report = _setup_leverage_agreement()
        assert agreement["effective_rate_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            "the loss is priced at the agreement's live effective rate 45.4272, got "
            f"{agreement['effective_rate_cents_per_sub']}"
        )
        base_case = run_renewal_analysis(agreement["id"], variant="BASE_CASE")

        downside = run_renewal_analysis(agreement["id"], variant="DOWNSIDE")

        assert base_case["distribution_loss_subscribers"] == 2275000, (
            "4,000,000 at 0.8750 penetration retaining 0.65 is 2275000 subscribers, got "
            f"{base_case['distribution_loss_subscribers']}"
        )
        assert base_case["annualized_revenue_at_risk_cents"] == 1240162560, (
            "2,275,000 at 45.4272 over twelve months is 1240162560 cents, got "
            f"{base_case['annualized_revenue_at_risk_cents']}"
        )
        assert downside["distribution_loss_subscribers"] == 3150000, (
            "retaining 0.90 instead leaves 3150000 subscribers at risk, got "
            f"{downside['distribution_loss_subscribers']}"
        )
        assert downside["annualized_revenue_at_risk_cents"] == 1717148160, (
            "3,150,000 at 45.4272 over twelve months is 1717148160 cents, got "
            f"{downside['annualized_revenue_at_risk_cents']}"
        )
        reread_base = validate_success(api_client.get_renewal_analysis(base_case["id"], SALES))
        assert reread_base["distribution_loss_subscribers"] == 2275000, (
            "the earlier snapshot is untouched by the later model, got "
            f"{reread_base['distribution_loss_subscribers']}"
        )
        assert reread_base["annualized_revenue_at_risk_cents"] == 1240162560, (
            f"the earlier snapshot keeps its own figure, got {reread_base['annualized_revenue_at_risk_cents']}"
        )


class TestMfnBenchmarkPeerSelection:
    """The benchmark is the minimum of a per-peer ADJUSTED rate over a
    scope-filtered candidate set, not the minimum of the raw peer rates."""

    def test_domestic_scope_excludes_the_cheapest_peer_from_the_comparison(self):
        """PRD §3.3: "A peer agreement qualifies when it is not this agreement
        itself, its `lifecycle_status` is `EXECUTED` or `SUSPENDED`, its
        `committed_tier` equals this agreement's `committed_tier` so the comparison
        is like-for-like on packaging, its `term_start_date` is at or before the
        current logical instant while its `term_end_date` is strictly after it, its
        operator is a different operator from this agreement's (so nobody
        benchmarks against themselves), that operator's `total_subscribers` is at
        least the clause's `min_peer_subscribers`, and that operator's
        `distributor_type` is admitted by the clause's scope."
        PRD §3.3: "`DOMESTIC` admits `CABLE_MSO`, `DBS` and `TELCO`; `GLOBAL`
        admits those three plus `VMVPD`."
        PRD §3.3: "Multiply it by a volume-band factor chosen from the peer
        operator's `total_subscribers`: 1.05 for an operator below 2,000,000
        subscribers, 1.00 for one from 2,000,000 up to but not including
        10,000,000, and 0.94 for one at 10,000,000 or above."
        PRD §3.3: "Round each peer's adjusted figure half up to four decimal
        places of a cent **before** any comparison is made."
        PRD §3.3: "`benchmark_rate_cents` is the smallest of those adjusted
        figures, and `benchmark_peer_agreement_id` identifies the peer agreement
        that produced it; where two candidates tie on the adjusted figure, the
        benchmark peer is the one whose agreement has the earlier `created_at`, and
        the record `id` is never used as a tiebreaker."
        PRD §3.3: "`benchmark_status` becomes `BENCHMARKED` and `last_reset_at` is
        stamped with the current logical instant."

        Design: Difficulty/combinatorial_formula/mfn_benchmark_scope_filter_changes_winning_peer
        """
        _subject_distributor, subject, vale, streamline = _setup_three_operator_market()
        assert subject["escalated_rate_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            "the subject escalates to 45.4272 in contract year 2, got "
            f"{subject['escalated_rate_cents_per_sub']}"
        )
        clause = attach_mfn_clause(
            subject["id"],
            mfn_scope="DOMESTIC",
            min_peer_subscribers=1_000_000,
            rate_floor_cents=30.0000,
        )
        assert clause["benchmark_status"] == "NOT_EVALUATED", (
            f"a fresh clause has evaluated nothing, got {clause['benchmark_status']}"
        )

        benchmarked = validate_success(_reset_mfn_benchmark(clause["id"], subject["id"]))

        assert benchmarked["benchmark_status"] == "BENCHMARKED", (
            f"a reset with a non-empty pool benchmarks the clause, got {benchmarked['benchmark_status']}"
        )
        assert benchmarked["benchmark_rate_cents"] == pytest.approx(38.7280, abs=0.0001), (
            "41.2000 in the LARGE band is 38.7280, the smallest adjusted figure a "
            f"DOMESTIC scope can see, got {benchmarked['benchmark_rate_cents']}"
        )
        assert benchmarked["benchmark_peer_agreement_id"] == vale["id"], (
            f"the DBS peer produced the winning figure, got {benchmarked['benchmark_peer_agreement_id']}"
        )
        assert benchmarked["benchmark_peer_agreement_id"] != streamline["id"], (
            "a DOMESTIC scope never admits the VMVPD peer even though its adjusted "
            "36.7080 is the market minimum"
        )
        assert benchmarked["last_reset_at"] is not None, (
            f"a reset always stamps last_reset_at, got {benchmarked['last_reset_at']}"
        )

    def test_domestic_benchmark_caps_the_subject_agreement_only(self):
        """PRD §3.3: "If the agreement has an `ACTIVE` clause whose
        `benchmark_status` is `BENCHMARKED`, take the lesser of the escalated rate
        and the clause's `benchmark_rate_cents`, then take the greater of that
        result and the clause's `rate_floor_cents`, round half up to four decimal
        places, and use it as `effective_rate_cents_per_sub`; `mfn_capped` becomes
        true exactly when that value is strictly less than the escalated rate."
        PRD §3.3: "The owning agreement re-stamps `effective_rate_cents_per_sub`
        and `mfn_capped`."
        PRD §3.3: "The escalated rate is then `base_license_fee_cents_per_sub`
        multiplied by one plus `escalator_pct`, raised to the power of that
        contract-year index, rounded half up to four decimal places of a cent."

        Design: Difficulty/combinatorial_formula/mfn_benchmark_scope_filter_changes_winning_peer
        """
        _subject_distributor, subject, vale, streamline = _setup_three_operator_market()
        clause = attach_mfn_clause(
            subject["id"],
            mfn_scope="DOMESTIC",
            min_peer_subscribers=1_000_000,
            rate_floor_cents=30.0000,
        )

        validate_success(_reset_mfn_benchmark(clause["id"], subject["id"]))

        capped = fetch_agreement(subject["id"])
        assert capped["escalated_rate_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            f"the contractual rate is untouched by the cap, got {capped['escalated_rate_cents_per_sub']}"
        )
        assert capped["effective_rate_cents_per_sub"] == pytest.approx(38.7280, abs=0.0001), (
            "the 30.0000 floor does not bite, so the benchmark binds at 38.7280, got "
            f"{capped['effective_rate_cents_per_sub']}"
        )
        assert capped["mfn_capped"] is True, (
            f"38.7280 is strictly below the escalated 45.4272, got {capped['mfn_capped']}"
        )
        vale_after = fetch_agreement(vale["id"])
        streamline_after = fetch_agreement(streamline["id"])
        assert vale_after["effective_rate_cents_per_sub"] == pytest.approx(41.2000, abs=0.0001), (
            "the reset re-stamps only the owning agreement, so the DBS peer keeps "
            f"41.2000, got {vale_after['effective_rate_cents_per_sub']}"
        )
        assert streamline_after["effective_rate_cents_per_sub"] == pytest.approx(38.0000, abs=0.0001), (
            f"the VMVPD peer keeps its flat 38.0000, got {streamline_after['effective_rate_cents_per_sub']}"
        )

    def test_global_scope_admits_the_vmvpd_peer_and_changes_the_winner(self):
        """PRD §3.3: "`DOMESTIC` admits `CABLE_MSO`, `DBS` and `TELCO`; `GLOBAL`
        admits those three plus `VMVPD`."
        PRD §3.3: "Then, if the peer operator's `distributor_type` is `VMVPD`,
        reduce the result by a further eight percent — that is, multiply by 0.92;
        otherwise leave it unchanged."
        PRD §3.3: "`benchmark_rate_cents` is the smallest of those adjusted
        figures, and `benchmark_peer_agreement_id` identifies the peer agreement
        that produced it; where two candidates tie on the adjusted figure, the
        benchmark peer is the one whose agreement has the earlier `created_at`, and
        the record `id` is never used as a tiebreaker."
        PRD §3.3: "The owning agreement re-stamps `effective_rate_cents_per_sub`
        and `mfn_capped`."

        Design: Difficulty/combinatorial_formula/mfn_benchmark_scope_filter_changes_winning_peer
        """
        _subject_distributor, subject, _vale, streamline = _setup_three_operator_market()
        clause = attach_mfn_clause(
            subject["id"],
            mfn_scope="GLOBAL",
            min_peer_subscribers=1_000_000,
            rate_floor_cents=30.0000,
        )

        benchmarked = validate_success(_reset_mfn_benchmark(clause["id"], subject["id"]))

        assert benchmarked["benchmark_rate_cents"] == pytest.approx(36.7080, abs=0.0001), (
            "38.0000 in the SMALL band then discounted eight percent is 36.7080, got "
            f"{benchmarked['benchmark_rate_cents']}"
        )
        assert benchmarked["benchmark_peer_agreement_id"] == streamline["id"], (
            "widening the scope hands the benchmark to the VMVPD peer, got "
            f"{benchmarked['benchmark_peer_agreement_id']}"
        )
        capped = fetch_agreement(subject["id"])
        assert capped["effective_rate_cents_per_sub"] == pytest.approx(36.7080, abs=0.0001), (
            f"the wider scope bills 36.7080 rather than 38.7280, got {capped['effective_rate_cents_per_sub']}"
        )
        assert capped["mfn_capped"] is True, (
            f"36.7080 is strictly below the escalated 45.4272, got {capped['mfn_capped']}"
        )


class TestEffectiveRateTwoSidedClamp:
    """max(min(escalated, benchmark), floor) — the outer floor can undo the
    inner cap without erasing the benchmark that was won."""

    def test_rate_floor_overrides_a_lower_benchmark(self):
        """PRD §3.3: "If the agreement has an `ACTIVE` clause whose
        `benchmark_status` is `BENCHMARKED`, take the lesser of the escalated rate
        and the clause's `benchmark_rate_cents`, then take the greater of that
        result and the clause's `rate_floor_cents`, round half up to four decimal
        places, and use it as `effective_rate_cents_per_sub`; `mfn_capped` becomes
        true exactly when that value is strictly less than the escalated rate."
        PRD §3.3: "An MFN clause is attached by an `AffiliateSalesExec`, naming the
        `agreement_id` it caps, an `mfn_scope` of either `DOMESTIC` or `GLOBAL`, a
        `rate_floor_cents` of at least zero below which the capped rate may never
        fall, and optionally a `min_peer_subscribers` threshold (default 0) that
        excludes small peers from the comparison."

        Design: Difficulty/combinatorial_formula/mfn_rate_floor_overrides_lower_benchmark
        """
        _vale_distributor, vale = setup_peer_agreement(
            40.0000, "DBS", 12_000_000, **VALE_AGREEMENT
        )
        _subject_distributor, subject = setup_executed_agreement()
        clause = attach_mfn_clause(
            subject["id"],
            mfn_scope="DOMESTIC",
            min_peer_subscribers=1_000_000,
            rate_floor_cents=40.0000,
        )

        benchmarked = validate_success(_reset_mfn_benchmark(clause["id"], subject["id"]))

        assert benchmarked["benchmark_status"] == "BENCHMARKED", (
            f"the DBS peer forms a non-empty pool, got {benchmarked['benchmark_status']}"
        )
        assert benchmarked["benchmark_rate_cents"] == pytest.approx(38.7280, abs=0.0001), (
            "the benchmark is recorded as the adjusted peer figure, un-clamped, got "
            f"{benchmarked['benchmark_rate_cents']}"
        )
        assert benchmarked["benchmark_peer_agreement_id"] == vale["id"], (
            f"the DBS peer produced it, got {benchmarked['benchmark_peer_agreement_id']}"
        )
        assert benchmarked["rate_floor_cents"] == pytest.approx(40.0000, abs=0.0001), (
            f"the clause keeps its contractual floor, got {benchmarked['rate_floor_cents']}"
        )
        capped = fetch_agreement(subject["id"])
        assert capped["escalated_rate_cents_per_sub"] == pytest.approx(45.4272, abs=0.0001), (
            f"the escalated rate is still 45.4272, got {capped['escalated_rate_cents_per_sub']}"
        )
        assert capped["effective_rate_cents_per_sub"] == pytest.approx(40.0000, abs=0.0001), (
            "max(min(45.4272, 38.7280), 40.0000) is 40.0000 — neither 38.7280 nor "
            f"45.4272, got {capped['effective_rate_cents_per_sub']}"
        )

    def test_floor_bound_rate_is_still_flagged_as_mfn_capped(self):
        """PRD §3.3: "`mfn_capped` is a boolean flag that is true exactly when the
        effective rate came out strictly below the escalated rate because a peer
        benchmark bound it."
        PRD §3.3: "If the agreement has an `ACTIVE` clause whose `benchmark_status`
        is `BENCHMARKED`, take the lesser of the escalated rate and the clause's
        `benchmark_rate_cents`, then take the greater of that result and the
        clause's `rate_floor_cents`, round half up to four decimal places, and use
        it as `effective_rate_cents_per_sub`; `mfn_capped` becomes true exactly
        when that value is strictly less than the escalated rate."
        PRD §3.3: "`benchmark_rate_cents` is the smallest of those adjusted
        figures, and `benchmark_peer_agreement_id` identifies the peer agreement
        that produced it; where two candidates tie on the adjusted figure, the
        benchmark peer is the one whose agreement has the earlier `created_at`, and
        the record `id` is never used as a tiebreaker."

        Design: Difficulty/combinatorial_formula/mfn_rate_floor_overrides_lower_benchmark
        """
        _vale_distributor, _vale = setup_peer_agreement(
            40.0000, "DBS", 12_000_000, **VALE_AGREEMENT
        )
        _subject_distributor, subject = setup_executed_agreement()
        clause = attach_mfn_clause(
            subject["id"],
            mfn_scope="DOMESTIC",
            min_peer_subscribers=1_000_000,
            rate_floor_cents=40.0000,
        )

        validate_success(_reset_mfn_benchmark(clause["id"], subject["id"]))

        capped = fetch_agreement(subject["id"])
        assert capped["mfn_capped"] is True, (
            "the flag turns on the effective-versus-escalated comparison, and "
            f"40.0000 < 45.4272, got {capped['mfn_capped']}"
        )
        assert capped["effective_rate_cents_per_sub"] < capped["escalated_rate_cents_per_sub"], (
            "the effective rate must sit strictly below the escalated rate, got "
            f"{capped['effective_rate_cents_per_sub']} vs {capped['escalated_rate_cents_per_sub']}"
        )
        reread_clause = validate_success(api_client.get_mfn_clause(clause["id"], SALES))
        assert reread_clause["benchmark_rate_cents"] == pytest.approx(38.7280, abs=0.0001), (
            "the floor does not overwrite the benchmark the clause actually won, got "
            f"{reread_clause['benchmark_rate_cents']}"
        )


class TestInvoiceNetDueWaterfall:
    """The co-op ceiling band is selected from the step-1 gross, never from the
    payable the offset itself produces."""

    def test_coop_band_is_selected_from_the_gross(self):
        """PRD §3.8: "**Gross.** For a `LICENSE_FEE` invoice,
        `gross_license_fee_cents` is the sum of `license_fee_due_cents` over the
        subscriber reports of the named agreement whose `period_month` equals the
        invoice's `period_month`, whose `status` is `ACCEPTED` or `AUDIT_ADJUSTED`,
        and whose `invoice_id` is still null — each of those figures already rounded
        per report."
        PRD §3.8: "**Co-op ceiling band.** `coop_cap_pct` is selected from that
        gross: 0.05 when the gross is below 5,000,000 cents, 0.08 from 5,000,000
        cents up to but not including 25,000,000 cents, and 0.12 at 25,000,000 cents
        and above."
        PRD §3.8: "The ceiling itself is the gross multiplied by `coop_cap_pct`,
        rounded half up to a whole cent — the only rounded intermediate in the
        waterfall."
        PRD §3.8: "`coop_offset_cents` is the lesser of that pool and the step-2
        ceiling."
        PRD §3.8: "A draft opens in `DRAFT` with `paid_cents` 0, `issued_at` null
        and `version` 1, and drafting increments the operator's `version` by one."

        Design: Difficulty/combinatorial_formula/coop_band_selected_from_gross_before_offset
        """
        distributor, agreement, commitment, report = _setup_coop_band_fixture()
        assert report["license_fee_due_cents"] == 5200000, (
            f"130,000 subscribers at a flat 40.0000 is 5200000 cents, got {report['license_fee_due_cents']}"
        )
        assert commitment["earned_unbilled_cents"] == 500000, (
            f"500,000 earned and nothing billed leaves 500000 unbilled, got {commitment['earned_unbilled_cents']}"
        )

        invoice = draft_invoice(distributor["id"], agreement["id"], "2026-06")

        assert invoice["status"] == "DRAFT", (
            f"a new invoice opens in DRAFT, got {invoice['status']}"
        )
        assert invoice["gross_license_fee_cents"] == 5200000, (
            f"the single unbilled accepted report grosses 5200000, got {invoice['gross_license_fee_cents']}"
        )
        assert invoice["coop_cap_pct"] == pytest.approx(0.08, abs=0.0001), (
            "5,200,000 sits in the 5,000,000-to-25,000,000 band, so the cap is 0.08, got "
            f"{invoice['coop_cap_pct']}"
        )
        assert invoice["coop_offset_cents"] == 416000, (
            "the 416,000 ceiling binds below the 500,000 pool, got "
            f"{invoice['coop_offset_cents']}"
        )
        assert invoice["paid_cents"] == 0, (
            f"a draft has collected nothing, got {invoice['paid_cents']}"
        )

    def test_net_due_reflects_the_gross_selected_band_not_the_payable(self):
        """PRD §3.8: "It is always the step-1 gross, never the post-offset payable.
        Evaluating it the other way lands in a lower band and yields a strictly
        larger net due for identical inputs."
        PRD §3.8: "`launch_fee_offset_cents` is the lesser of that pool and what
        the co-op offset left of the gross — that is, the gross less
        `coop_offset_cents`, floored at zero."
        PRD §3.8: "**Recovery adjustment.** `recovery_adjustment_cents` is 0."
        PRD §3.8: "The raw net is the gross less `coop_offset_cents` less
        `launch_fee_offset_cents` plus `recovery_adjustment_cents`. `net_due_cents`
        is that raw net floored at zero, and `carryforward_cents` is however much
        the raw net went below zero, expressed as a positive amount — the offset
        value that could not be applied."
        PRD §3.8: "Voiding a `DRAFT` restores nothing, and that is the point: a
        draft only *projects* its offsets, so `billed_cents` and
        `earned_unbilled_cents` were never touched at drafting and are not touched
        at void, and the conserved identity of §3.8 holds unchanged across both
        calls."
        PRD §3.8: "Likewise a draft never claims its source reports — their
        `invoice_id` stays null — which is why two drafts for the same period can
        coexist, why only the first one to issue actually claims the reports, and
        why any later draft naming those now-claimed reports is refused with
        `ERR_REPORT_ALREADY_BILLED`."

        Design: Difficulty/combinatorial_formula/coop_band_selected_from_gross_before_offset
        """
        distributor, agreement, commitment, report = _setup_coop_band_fixture()

        invoice = draft_invoice(distributor["id"], agreement["id"], "2026-06")

        assert invoice["launch_fee_offset_cents"] == 0, (
            f"there is no LAUNCH_FEE line to draw on, got {invoice['launch_fee_offset_cents']}"
        )
        assert invoice["recovery_adjustment_cents"] == 0, (
            f"the recovery adjustment is always 0, got {invoice['recovery_adjustment_cents']}"
        )
        assert invoice["net_due_cents"] == 4784000, (
            f"5,200,000 less the 416,000 co-op offset is 4784000, got {invoice['net_due_cents']}"
        )
        assert invoice["net_due_cents"] != 4960800, (
            "4960800 is what reading the band off the post-offset payable would "
            f"produce, got {invoice['net_due_cents']}"
        )
        assert invoice["carryforward_cents"] == 0, (
            f"the raw net never went below zero, got {invoice['carryforward_cents']}"
        )
        settled_commitment = fetch_commitment(commitment["id"])
        assert settled_commitment["billed_cents"] == 0, (
            f"a draft only projects its offsets, got billed_cents {settled_commitment['billed_cents']}"
        )
        assert settled_commitment["earned_unbilled_cents"] == 500000, (
            "the unbilled pool is untouched at drafting, got "
            f"{settled_commitment['earned_unbilled_cents']}"
        )
        assert fetch_report(report["id"])["invoice_id"] is None, (
            "a draft never claims its source reports, got "
            f"{fetch_report(report['id'])['invoice_id']}"
        )
