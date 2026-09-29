"""Derived-value arithmetic: escalated and applied rates, the two fee variants,
blackout hour accounting, the marketing ledger and the settlement roll-up.

Every expected figure below is the one the PRD's own formulas produce for the
pinned inputs; money is whole cents and rates carry four decimal places, both
rounded half up (PRD §2.6).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_report,
    advance_clock,
    create_invoice_payload,
    dispute_report,
    distributor_version,
    draft_invoice,
    earn_commitment,
    create_commitment,
    fetch_agreement,
    fetch_commitment,
    fetch_report,
    file_report,
    issue_invoice,
    register_cleared_title,
    schedule_blackout,
    setup_executed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
    earn_payload,
)

FLAT_TELCO = {
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
}
FLAT_TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}


def _flat_telco_agreement(**term_overrides):
    """A 200,000-home TELCO operator with one EXECUTED agreement priced at a
    flat 40.0000 cents per subscriber, BASIC tier, 0.50 penetration floor."""
    terms = dict(FLAT_TERMS)
    terms.update(term_overrides)
    return setup_executed_agreement(dict(FLAT_TELCO), terms)


def _accepted_may_and_june(distributor, agreement):
    """2026-05 at 120,000 subscribers and 2026-06 at 130,000, both ACCEPTED."""
    may = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-05",
        reported_subscribers=120_000,
        reported_tier="BASIC",
    )
    may = accept_report(may["id"])
    june = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    june = accept_report(june["id"])
    return may, june


class TestInvoiceGrossInputSet:
    def test_gross_counts_only_accepted_unbilled_reports_of_that_period(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.8: "For a `LICENSE_FEE` invoice, `gross_license_fee_cents` is the
        sum of `license_fee_due_cents` over the subscriber reports of the named
        agreement whose `period_month` equals the invoice's `period_month`, whose
        `status` is `ACCEPTED` or `AUDIT_ADJUSTED`, and whose `invoice_id` is
        still null — each of those figures already rounded per report."
        PRD §3.8: "The raw net is the gross less `coop_offset_cents` less
        `launch_fee_offset_cents` plus `recovery_adjustment_cents`."

        Design: Corner/calculations/invoice_gross_filters_by_period_status_and_prior_billing
        """
        distributor, agreement = _flat_telco_agreement()
        _accepted_may_and_june(distributor, agreement)
        disputed = file_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-06",
            reported_subscribers=140_000,
            reported_tier="BASIC",
        )
        dispute_report(disputed["id"])

        response = api.create_invoice(
            create_invoice_payload(
                distributor["id"],
                agreement["id"],
                "2026-06",
                distributor_version(distributor["id"]),
            ),
            revenue_accountant_headers,
        )
        invoice = validate_success(response, 201)

        assert invoice["gross_license_fee_cents"] == 5_200_000, (
            "the 2026-06 gross is the accepted 130,000-subscriber report alone "
            f"(5,200,000 cents), got {invoice['gross_license_fee_cents']}"
        )
        assert invoice["coop_offset_cents"] == 0, "no commitment line exists to offset"
        assert invoice["launch_fee_offset_cents"] == 0, "no launch-fee line exists to offset"
        assert invoice["net_due_cents"] == 5_200_000, (
            f"net due is the unoffset gross, got {invoice['net_due_cents']}"
        )

    def test_second_invoice_for_an_already_billed_period_is_refused(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.8: "Issuance stamps `issued_at`, consumes the marketing offsets it
        projected, and stamps each folded report's `invoice_id` with this invoice's
        identifier."
        PRD §3.8: "First, none of the subscriber reports a license-fee invoice would
        bill may already carry a non-null `invoice_id`; if one does, the draft is
        refused with `ERR_REPORT_ALREADY_BILLED`."

        Design: Corner/calculations/invoice_gross_filters_by_period_status_and_prior_billing
        """
        distributor, agreement = _flat_telco_agreement()
        may, june = _accepted_may_and_june(distributor, agreement)

        invoice = draft_invoice(distributor["id"], agreement["id"], "2026-06")
        issued = issue_invoice(invoice["id"])
        assert issued["status"] == "ISSUED", f"expected ISSUED, got {issued['status']}"

        assert fetch_report(june["id"])["invoice_id"] == invoice["id"], (
            "issuance stamps the billed 2026-06 report with the invoice id"
        )
        assert fetch_report(may["id"])["invoice_id"] is None, (
            "the 2026-05 report was never billed by this invoice"
        )

        response = api.create_invoice(
            create_invoice_payload(
                distributor["id"],
                agreement["id"],
                "2026-06",
                distributor_version(distributor["id"]),
            ),
            revenue_accountant_headers,
        )
        validate_error(response, ApiErrorId.ERR_REPORT_ALREADY_BILLED)


def test_report_rate_uses_the_contract_year_of_its_own_period(api):
    """PRD §3.3: "The escalated rate is then `base_license_fee_cents_per_sub`
    multiplied by one plus `escalator_pct`, raised to the power of that
    contract-year index, rounded half up to four decimal places of a cent."
    PRD §3.3: "When the rate is being stamped on the agreement itself, the pricing
    month is the month containing the current logical instant; when the rate is
    being applied to a subscriber report, the pricing month is that report's own
    `period_month`, which is why an escalating agreement prices an old period
    differently from a current one."
    PRD §3.4: "The fee is the billable subscriber count multiplied by
    `rate_applied_cents_per_sub` multiplied by that tier multiplier, rounded half
    up to a whole number of cents."

    Design: Corner/calculations/escalator_contract_year_index_derived_from_period_not_today
    """
    distributor, agreement = _flat_telco_agreement(escalator_pct=0.03)
    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )

    accepted = accept_report(report["id"])
    assert accepted["rate_applied_cents_per_sub"] == pytest.approx(41.2000, abs=1e-6), (
        "2026-06 sits in contract year index 1 of a term starting 2025-01-01, so the "
        f"applied rate is 40.0000 * 1.03, got {accepted['rate_applied_cents_per_sub']}"
    )
    assert accepted["billable_subscribers"] == 130_000, (
        "reported 130,000 exceeds the 100,000 floor subscriber count"
    )
    assert accepted["license_fee_due_cents"] == 5_356_000, (
        f"130,000 * 41.2000 * 1.00 is 5,356,000 cents, got {accepted['license_fee_due_cents']}"
    )

    stamped = fetch_agreement(agreement["id"])
    assert stamped["escalated_rate_cents_per_sub"] == pytest.approx(41.2000, abs=1e-6), (
        "the agreement-level stamp prices the month containing the logical instant "
        f"2026-08, also index 1, got {stamped['escalated_rate_cents_per_sub']}"
    )
    assert stamped["effective_rate_cents_per_sub"] == pytest.approx(41.2000, abs=1e-6), (
        "with no MFN clause attached the effective rate equals the escalated rate"
    )
    assert stamped["mfn_capped"] is False, "no clause exists, so nothing capped the rate"
    assert stamped["recognized_revenue_cents"] == 5_356_000, (
        f"recognised revenue is the accepted fee, got {stamped['recognized_revenue_cents']}"
    )


def test_premium_placement_discounts_the_fee_and_raises_the_breach_flag(api):
    """PRD §3.4: "Then select the tier multiplier from the tier actually reported:
    `BASIC` and `EXPANDED_BASIC` both multiply by 1.00, `DIGITAL_TIER` by 0.85, and
    `PREMIUM` by 0.60."
    PRD §3.4: "`tier_placement_breach` is true exactly when the tier actually used
    was narrower than the tier committed: rank the tiers with `BASIC` at 4,
    `EXPANDED_BASIC` at 3, `DIGITAL_TIER` at 2 and `PREMIUM` at 1, where a higher
    rank means broader carriage, and set the flag when the rank of `reported_tier`
    is strictly below the rank of the agreement's `committed_tier`."
    PRD §3.5: "A compliant period increments `consecutive_compliant_periods` by one
    and sets `penetration_compliance_status` to `COMPLIANT`."

    Design: Corner/calculations/premium_tier_multiplier_and_placement_breach_flag
    """
    distributor, agreement = _flat_telco_agreement()
    filed = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="PREMIUM",
    )
    assert filed["provisional_fee_cents"] == 3_120_000, (
        "130,000 * 40.0000 * 0.60 is 3,120,000 cents, got "
        f"{filed['provisional_fee_cents']}"
    )
    assert filed["tier_placement_breach"] is True, (
        "PREMIUM ranks 1, below the BASIC commitment's rank 4"
    )

    accepted = accept_report(filed["id"])
    assert accepted["license_fee_due_cents"] == 3_120_000, (
        f"the final fee applies the same 0.60 multiplier, got {accepted['license_fee_due_cents']}"
    )
    assert accepted["rate_applied_cents_per_sub"] == pytest.approx(40.0000, abs=1e-6), (
        "a zero escalator leaves the applied rate at the base fee"
    )
    assert accepted["billable_subscribers"] == 130_000, "reported count beats the 100,000 floor"
    assert accepted["penetration_pct"] == pytest.approx(0.6500, abs=1e-6), (
        f"130,000 of 200,000 homes is 0.6500, got {accepted['penetration_pct']}"
    )

    stamped = fetch_agreement(agreement["id"])
    assert stamped["penetration_compliance_status"] == "COMPLIANT", (
        "0.6500 clears the 0.50 penetration floor — a tier breach is not a penetration breach"
    )
    assert stamped["recognized_revenue_cents"] == 3_120_000, (
        f"recognised revenue is the discounted fee, got {stamped['recognized_revenue_cents']}"
    )


def test_penetration_pct_rounds_half_up_while_the_fee_uses_raw_subscribers(api):
    """PRD §3.4: "`penetration_pct` is `reported_subscribers` divided by the
    operator's `total_subscribers`, rounded half up to four decimal places."
    PRD §3.4: "Under the **final** variant, stamped at acceptance into
    `billable_subscribers` and `license_fee_due_cents`, the billable count is the
    greater of `reported_subscribers` and the floor subscriber count."

    Design: Corner/calculations/penetration_pct_rounds_half_up_at_four_decimals
    """
    distributor, agreement = _flat_telco_agreement()
    filed = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_010,
        reported_tier="BASIC",
    )

    assert filed["penetration_pct"] == pytest.approx(0.6501, abs=1e-6), (
        "130,010 of 200,000 is exactly 0.65005, which rounds half up to 0.6501, got "
        f"{filed['penetration_pct']}"
    )
    assert filed["provisional_fee_cents"] == 5_200_400, (
        "the provisional fee comes from the raw 130,010 subscribers, got "
        f"{filed['provisional_fee_cents']}"
    )

    accepted = accept_report(filed["id"])
    assert accepted["billable_subscribers"] == 130_010, (
        "130,010 exceeds the 100,000 floor subscriber count"
    )
    assert accepted["license_fee_due_cents"] == 5_200_400, (
        f"130,010 * 40.0000 * 1.00 is 5,200,400 cents, got {accepted['license_fee_due_cents']}"
    )


def test_monthly_blackout_hours_bucket_by_operator_territory_and_month(api):
    """PRD §3.6: "The rule's own `blackout_hours` is the elapsed time from
    `blackout_start` to `blackout_end` expressed in hours and rounded half up to two
    decimal places."
    PRD §3.6: "`monthly_blackout_hours` is that figure plus the `blackout_hours` of
    every other qualifying rule on the same key whose `blackout_start` falls in the
    same UTC calendar month, and if the total exceeds 72 hours — three full days of
    blackout in one operator territory in one month — the rule is refused with
    `ERR_BLACKOUT_MONTHLY_CAP_EXCEEDED`."
    PRD §3.6: "Two aggregate checks run at scheduling time, and both are keyed on
    the *operator* rather than the agreement: rules are compared across every
    agreement of the operator resolved through the naming agreement's
    `distributor_id`, restricted to the same `territory_code` and to rules in
    `SCHEDULED` or `ENFORCED` status."

    Design: Corner/calculations/blackout_hours_aggregate_per_territory_calendar_month
    """
    _distributor, agreement = _flat_telco_agreement()
    substitute = register_cleared_title(linear_premiere_at="2026-08-15T00:00:00Z")

    first_us = schedule_blackout(
        agreement["id"],
        territory_code="US",
        blackout_start="2026-09-05T18:00:00Z",
        blackout_end="2026-09-05T22:00:00Z",
        substitution_required=True,
        substitute_content_title_id=substitute["id"],
    )
    assert first_us["blackout_hours"] == pytest.approx(4.0, abs=0.01), (
        f"18:00Z to 22:00Z is 4 hours, got {first_us['blackout_hours']}"
    )
    assert first_us["monthly_blackout_hours"] == pytest.approx(4.0, abs=0.01), (
        "the first US September rule is alone in its bucket, got "
        f"{first_us['monthly_blackout_hours']}"
    )

    second_us = schedule_blackout(
        agreement["id"],
        territory_code="US",
        blackout_start="2026-09-08T18:00:00Z",
        blackout_end="2026-09-08T21:00:00Z",
        substitution_required=True,
        substitute_content_title_id=substitute["id"],
    )
    assert second_us["blackout_hours"] == pytest.approx(3.0, abs=0.01), (
        f"18:00Z to 21:00Z is 3 hours, got {second_us['blackout_hours']}"
    )
    assert second_us["monthly_blackout_hours"] == pytest.approx(7.0, abs=0.01), (
        "4 hours already scheduled in US September plus this rule's 3 hours, got "
        f"{second_us['monthly_blackout_hours']}"
    )

    canada = schedule_blackout(
        agreement["id"],
        territory_code="CA",
        blackout_start="2026-09-08T18:00:00Z",
        blackout_end="2026-09-08T21:00:00Z",
        substitution_required=True,
        substitute_content_title_id=substitute["id"],
    )
    assert canada["blackout_hours"] == pytest.approx(3.0, abs=0.01)
    assert canada["monthly_blackout_hours"] == pytest.approx(3.0, abs=0.01), (
        "CA is a separate territory bucket, so the US hours do not accumulate here, got "
        f"{canada['monthly_blackout_hours']}"
    )
    assert canada["status"] == "SCHEDULED", (
        "the CA rule occupies the same instants as the second US rule, so both the "
        "separation test and the monthly cap are territory-scoped"
    )

    rows, meta = validate_paginated(
        api.list_blackout_rules(
            TEST_USERS["rights_administrator_headers"],
            params={"agreement_id": agreement["id"], "limit": 10},
        )
    )
    assert meta["total_count"] == 3, f"three rules were scheduled, got {meta['total_count']}"
    assert all(row["status"] == "SCHEDULED" for row in rows), (
        "a new rule opens in SCHEDULED and none of the three was enforced or waived"
    )


class TestMarketingLedgerConservation:
    def test_earn_then_deadline_forfeit_conserves_committed_cents(self, api):
        """PRD §3.8: "Two identities hold after **every** mutation of a commitment
        line, and they are the ledger's correctness condition: `committed_cents`
        always equals `earned_cents` plus `remaining_cents` plus `forfeited_cents`,
        and `earned_unbilled_cents` always equals `earned_cents` less
        `billed_cents`."
        PRD §3.8: "The line's `status` becomes `EARNED` when `remaining_cents`
        reaches 0, and `PARTIALLY_EARNED` while the earned total is above zero but
        still below `committed_cents`."
        PRD §3.8: "And when a clock advance finds the `performance_deadline` passed
        with `remaining_cents` still positive, that remainder is added to
        `forfeited_cents`, `remaining_cents` drops to 0, and `status` becomes
        `FORFEITED` — permanently, since nothing un-forfeits a commitment."

        Design: Corner/calculations/marketing_ledger_conserves_committed_across_earn_and_forfeit
        """
        _distributor, agreement = _flat_telco_agreement()
        line = create_commitment(
            agreement["id"],
            commitment_type="COOP_ADVERTISING",
            committed_cents=1_000_000,
            performance_deadline="2026-10-01T00:00:00Z",
        )
        assert line["status"] == "OPEN", f"a new line opens OPEN, got {line['status']}"
        assert line["earned_cents"] == 0
        assert line["remaining_cents"] == 1_000_000
        assert line["forfeited_cents"] == 0

        earned = earn_commitment(line["id"], 300_000, "IO-2026-09-114")
        assert earned["status"] == "PARTIALLY_EARNED", (
            f"300,000 of 1,000,000 is a partial earn, got {earned['status']}"
        )
        assert earned["earned_cents"] == 300_000
        assert earned["earned_unbilled_cents"] == 300_000, "earned less billed 0"
        assert earned["billed_cents"] == 0
        assert earned["remaining_cents"] == 700_000, (
            f"committed less earned less forfeited, got {earned['remaining_cents']}"
        )

        clock = advance_clock("2026-10-02T00:00:00Z")
        assert clock["set_count"] == 1, f"one advance so far, got {clock['set_count']}"

        forfeited = fetch_commitment(line["id"])
        assert forfeited["status"] == "FORFEITED", (
            f"the deadline passed with a positive remainder, got {forfeited['status']}"
        )
        assert forfeited["earned_cents"] == 300_000, "the earned portion is never clawed back"
        assert forfeited["remaining_cents"] == 0
        assert forfeited["forfeited_cents"] == 700_000, (
            f"the whole remainder forfeits, got {forfeited['forfeited_cents']}"
        )
        assert forfeited["earned_unbilled_cents"] == 300_000, (
            "nothing was billed, so earned_unbilled still equals earned"
        )
        assert (
            forfeited["committed_cents"]
            == forfeited["earned_cents"]
            + forfeited["remaining_cents"]
            + forfeited["forfeited_cents"]
        ), "committed must equal earned plus remaining plus forfeited after the forfeit"

    def test_forfeited_line_refuses_further_earning_and_rolls_up_in_the_summary(
        self, api, affiliate_sales_exec_headers, revenue_accountant_headers
    ):
        """PRD §3.8: "The operation requires the funding agreement to be strictly
        `EXECUTED`, refusing otherwise with `ERR_AGREEMENT_NOT_EXECUTED`; requires
        the line's `performance_deadline` not to have passed at the current logical
        instant, refusing otherwise with `ERR_COMMITMENT_DEADLINE_PASSED`; and
        requires that the already-earned total plus the requested amount does not
        exceed `committed_cents`, refusing otherwise with `ERR_MARKETING_OVEREARN`."
        PRD §3.8: "It closes with two booleans: `marketing_conserved_identity_holds`,
        true when every one of those lines satisfies committed equals earned plus
        remaining plus forfeited, and `revenue_identity_holds`, true when
        `recognized_revenue_cents` equals `accepted_report_fee_total_cents`."

        Design: Corner/calculations/marketing_ledger_conserves_committed_across_earn_and_forfeit
        """
        _distributor, agreement = _flat_telco_agreement()
        line = create_commitment(
            agreement["id"],
            commitment_type="COOP_ADVERTISING",
            committed_cents=1_000_000,
            performance_deadline="2026-10-01T00:00:00Z",
        )
        earn_commitment(line["id"], 300_000, "IO-2026-09-114")
        advance_clock("2026-10-02T00:00:00Z")

        response = api.earn_marketing_commitment(
            line["id"], earn_payload(1, "IO-LATE"), affiliate_sales_exec_headers
        )
        validate_error(response, ApiErrorId.ERR_COMMITMENT_DEADLINE_PASSED)

        summary = validate_success(
            api.get_settlement_summary(agreement["id"], revenue_accountant_headers)
        )
        assert summary["marketing_committed_cents"] == 1_000_000
        assert summary["marketing_earned_cents"] == 300_000
        assert summary["marketing_remaining_cents"] == 0
        assert summary["marketing_forfeited_cents"] == 700_000
        assert summary["marketing_conserved_identity_holds"] is True, (
            "the single line satisfies committed equals earned plus remaining plus forfeited"
        )


def test_settlement_summary_separates_recognition_from_billing(api, revenue_accountant_headers):
    """PRD §3.8: "It reports the `agreement_id`; the agreement's stored
    `recognized_revenue_cents`; `accepted_report_fee_total_cents`, the sum of
    `license_fee_due_cents` across that agreement's reports in `ACCEPTED` or
    `AUDIT_ADJUSTED` status; `invoiced_gross_total_cents`, the sum of
    `gross_license_fee_cents` across that agreement's invoices other than those in
    `VOID`; `open_receivable_cents`, the sum of `net_due_cents` less `paid_cents`
    across that agreement's invoices in `ISSUED` or `PARTIALLY_PAID`; and four
    marketing roll-ups across the agreement's commitment lines —
    `marketing_committed_cents`, `marketing_earned_cents`,
    `marketing_remaining_cents` and `marketing_forfeited_cents`, each the sum of the
    corresponding per-line field."
    PRD §3.8: "It closes with two booleans: `marketing_conserved_identity_holds`,
    true when every one of those lines satisfies committed equals earned plus
    remaining plus forfeited, and `revenue_identity_holds`, true when
    `recognized_revenue_cents` equals `accepted_report_fee_total_cents`."

    Design: Corner/calculations/settlement_summary_rolls_up_accepted_reports_and_open_receivable
    """
    distributor, agreement = _flat_telco_agreement()
    _accepted_may_and_june(distributor, agreement)
    invoice = draft_invoice(distributor["id"], agreement["id"], "2026-06")
    issue_invoice(invoice["id"])

    response = api.get_settlement_summary(agreement["id"], revenue_accountant_headers)
    summary = validate_success(response)

    assert summary["agreement_id"] == agreement["id"]
    assert summary["accepted_report_fee_total_cents"] == 10_000_000, (
        "4,800,000 for 2026-05 plus 5,200,000 for 2026-06, got "
        f"{summary['accepted_report_fee_total_cents']}"
    )
    assert summary["recognized_revenue_cents"] == 10_000_000, (
        f"both acceptances recognised revenue, got {summary['recognized_revenue_cents']}"
    )
    assert summary["invoiced_gross_total_cents"] == 5_200_000, (
        f"only the 2026-06 period was invoiced, got {summary['invoiced_gross_total_cents']}"
    )
    assert summary["open_receivable_cents"] == 5_200_000, (
        f"the issued invoice is unpaid, got {summary['open_receivable_cents']}"
    )
    assert summary["marketing_committed_cents"] == 0
    assert summary["marketing_earned_cents"] == 0
    assert summary["marketing_remaining_cents"] == 0
    assert summary["marketing_forfeited_cents"] == 0
    assert summary["revenue_identity_holds"] is True, (
        "recognized_revenue_cents equals accepted_report_fee_total_cents"
    )
    assert summary["marketing_conserved_identity_holds"] is True, (
        "no commitment line exists, so the conserved identity holds vacuously"
    )
