"""Transitive cascade propagation across the carriage administration domain.

Each test drives one request and follows the whole chain of consequences it
must produce: report acceptance through the penetration breach ladder into
agreement suspension, window blocking and title coverage; audit findings
through report adjustment, the recovery invoice, the operator's receivable and
engagement collection; and a credit decision fanning out across every carried
agreement of one operator.
"""
import pytest

from test_helpers import (
    accept_report,
    clear_window,
    draft_agreement,
    execute_agreement,
    fetch_agreement,
    fetch_distributor,
    fetch_title,
    fetch_engagement,
    fetch_window,
    file_report,
    issue_invoice,
    plan_window,
    register_cleared_title,
    register_distributor,
    setup_audit_recovery_invoice,
    setup_engagement_with_findings_issued,
    validate_success,
)

CLIFFSIDE_TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
    "launch_fee_cents": 0,
    "marketing_commitment_cents": 0,
}

CLIFFSIDE_OPERATOR = {
    "legal_name": "Cliffside Telco",
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
    "credit_limit_cents": 100_000_000,
}


# --------------------------------------------------------------------------
# Module-private setup chains
# --------------------------------------------------------------------------
def _setup_operator_one_breach_from_suspension():
    """Cliffside Telco carrying the network on a flat 40.0000 BASIC deal with a
    50% penetration floor, one accepted breach period (2026-05 at 90,000 of
    200,000) already on the record, a cleared EXCLUSIVE LINEAR window on an
    OWNED_CLEARED title, and a second breaching period (2026-06 at 92,000)
    filed and awaiting review.

    Returns (distributor, agreement, title, window, june_report).
    """
    distributor = register_distributor(**CLIFFSIDE_OPERATOR)
    agreement = draft_agreement(distributor["id"], **CLIFFSIDE_TERMS)
    agreement = execute_agreement(agreement["id"])

    title = register_cleared_title(
        title="Autumn Classic Bowl",
        home_territory_code="US",
        linear_premiere_at="2026-08-10T00:00:00Z",
    )
    window = plan_window(
        agreement["id"],
        title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-08-20T00:00:00Z",
        window_end="2026-09-20T00:00:00Z",
        exclusivity="EXCLUSIVE",
    )
    window = clear_window(window["id"])
    title = fetch_title(title["id"])

    may = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-05",
        reported_subscribers=90_000,
        reported_tier="BASIC",
    )
    accept_report(may["id"])

    june = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=92_000,
        reported_tier="BASIC",
    )
    return distributor, fetch_agreement(agreement["id"]), title, window, june


class TestReportAcceptanceCascade:
    """One ACCEPT reaches the agreement, its rights windows and their titles."""

    def test_acceptance_stamps_final_fee_at_the_enforceable_floor(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.4: "`penetration_pct` is `reported_subscribers` divided by the
        operator's `total_subscribers`, rounded half up to four decimal places."
        PRD §3.4: "Compute the floor subscriber count as the agreement's
        `penetration_floor_pct` multiplied by the operator's `total_subscribers`,
        discarding any fraction."
        PRD §3.4: "The fee is the billable subscriber count multiplied by
        `rate_applied_cents_per_sub` multiplied by that tier multiplier, rounded
        half up to a whole number of cents."
        PRD §3.4: "A successful acceptance stamps `billable_subscribers`,
        `rate_applied_cents_per_sub` and `license_fee_due_cents` under the final
        variant, sets `accepted_at` to the current logical instant, and moves the
        report `SUBMITTED → ACCEPTED`."
        PRD §3.6: "Its `windowing_holdback_days` is stamped immediately, as the
        whole number of days from the title's `linear_premiere_at` to the window's
        `window_start`, discarding any fraction; a window that opens before the
        linear premiere therefore carries a negative holdback."

        Design: Difficulty/transitive_cascade/report_acceptance_cascades_to_suspension_window_block_and_title_coverage
        """
        _distributor, agreement, title, window, june = (
            _setup_operator_one_breach_from_suspension()
        )

        assert window["status"] == "CLEARED", (
            f"a window whose start is still in the future stays CLEARED, got {window['status']}"
        )
        assert window["windowing_holdback_days"] == 10, (
            "2026-08-10 premiere to a 2026-08-20 window start is 10 whole days, got "
            f"{window['windowing_holdback_days']}"
        )
        assert title["cleared_window_count"] == 1, (
            f"one cleared window means cleared_window_count 1, got {title['cleared_window_count']}"
        )
        assert title["distribution_coverage_status"] == "LINEAR_ONLY", (
            "a lone LINEAR window is LINEAR_ONLY, got "
            f"{title['distribution_coverage_status']}"
        )
        assert agreement["penetration_breach_count"] == 1, (
            "the accepted 2026-05 breach leaves the counter one short of the threshold, got "
            f"{agreement['penetration_breach_count']}"
        )
        assert agreement["lifecycle_status"] == "EXECUTED", (
            f"the agreement is still carried before the second breach, got {agreement['lifecycle_status']}"
        )

        data = validate_success(
            api.review_subscriber_report(
                june["id"], {"action": "ACCEPT"}, revenue_accountant_headers
            ),
            200,
        )

        assert data["status"] == "ACCEPTED", f"expected ACCEPTED, got {data['status']}"
        assert data["penetration_pct"] == pytest.approx(0.4600, abs=1e-6), (
            f"92,000 of 200,000 is 0.4600, got {data['penetration_pct']}"
        )
        assert data["billable_subscribers"] == 100_000, (
            "the final variant bills the greater of 92,000 and the 100,000 floor, got "
            f"{data['billable_subscribers']}"
        )
        assert data["license_fee_due_cents"] == 4_000_000, (
            f"100,000 * 40.0000 * 1.00 is 4,000,000 cents, got {data['license_fee_due_cents']}"
        )

    def test_second_breach_period_suspends_the_agreement_and_shifts_revenue(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.5: "`consecutive_compliant_periods` drops to 0,
        `penetration_breach_count` increments by one, and
        `penetration_compliance_status` becomes `BREACH`."
        PRD §3.5: "When `penetration_breach_count` reaches two while the
        agreement's `lifecycle_status` is `EXECUTED`, the agreement is
        automatically suspended with `suspension_reason` of `PENETRATION_BREACH`,
        dragging the rights-window and content-title cascade behind it."
        PRD §3.4: "First, the agreement's `recognized_revenue_cents` increases by
        the newly stamped `license_fee_due_cents`, and
        `penetration_compliance_status` is re-derived as described in §3.5."

        Design: Difficulty/transitive_cascade/report_acceptance_cascades_to_suspension_window_block_and_title_coverage
        """
        _distributor, agreement, _title, _window, june = (
            _setup_operator_one_breach_from_suspension()
        )

        validate_success(
            api.review_subscriber_report(
                june["id"], {"action": "ACCEPT"}, revenue_accountant_headers
            ),
            200,
        )

        after = fetch_agreement(agreement["id"])
        assert after["penetration_breach_count"] == 2, (
            f"the second breaching period takes the counter to 2, got {after['penetration_breach_count']}"
        )
        assert after["consecutive_compliant_periods"] == 0, (
            f"a non-compliant period drops the run to 0, got {after['consecutive_compliant_periods']}"
        )
        assert after["penetration_compliance_status"] == "BREACH", (
            f"expected BREACH, got {after['penetration_compliance_status']}"
        )
        assert after["recognized_revenue_cents"] == 8_000_000, (
            "two accepted periods at 4,000,000 cents each recognise 8,000,000, got "
            f"{after['recognized_revenue_cents']}"
        )
        assert after["lifecycle_status"] == "SUSPENDED", (
            f"reaching two breaches auto-suspends the agreement, got {after['lifecycle_status']}"
        )
        assert after["suspension_reason"] == "PENETRATION_BREACH", (
            f"expected PENETRATION_BREACH, got {after['suspension_reason']}"
        )

    def test_breach_suspension_blocks_the_window_and_darkens_the_title(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.4: "Third, because the agreement entered `SUSPENDED`, each of
        its rights windows in `CLEARED` or `ACTIVE` moves to `BLOCKED` with
        `block_reason` of `AGREEMENT_SUSPENDED`, in `window_start` ascending then
        `created_at` ascending order."
        PRD §3.4: "Fourth, each content title touched by those windows re-derives
        `cleared_window_count` and `distribution_coverage_status`."
        PRD §3.6: "`cleared_window_count` is the number of that title's windows
        whose `status` is `CLEARED` or `ACTIVE`."
        PRD §3.1: "`executed_agreement_count` is the number of that operator's
        agreements whose `lifecycle_status` is `EXECUTED` or `SUSPENDED`."

        Design: Difficulty/transitive_cascade/report_acceptance_cascades_to_suspension_window_block_and_title_coverage
        """
        distributor, _agreement, title, window, june = (
            _setup_operator_one_breach_from_suspension()
        )

        validate_success(
            api.review_subscriber_report(
                june["id"], {"action": "ACCEPT"}, revenue_accountant_headers
            ),
            200,
        )

        blocked = fetch_window(window["id"])
        assert blocked["status"] == "BLOCKED", (
            f"the suspension must block the cleared window, got {blocked['status']}"
        )
        assert blocked["block_reason"] == "AGREEMENT_SUSPENDED", (
            f"expected AGREEMENT_SUSPENDED, got {blocked['block_reason']}"
        )

        darkened = fetch_title(title["id"])
        assert darkened["cleared_window_count"] == 0, (
            "the blocked window leaves no occupying window, got "
            f"{darkened['cleared_window_count']}"
        )
        assert darkened["distribution_coverage_status"] == "UNDISTRIBUTED", (
            f"an empty platform set is UNDISTRIBUTED, got {darkened['distribution_coverage_status']}"
        )

        operator = fetch_distributor(distributor["id"])
        assert operator["executed_agreement_count"] == 1, (
            "a SUSPENDED agreement still counts as carried, got "
            f"{operator['executed_agreement_count']}"
        )


JUNE_130K_REPORT = {
    "period_month": "2026-06",
    "reported_subscribers": 130_000,
    "reported_tier": "BASIC",
}


class TestAuditRecoveryCascade:
    """Findings issuance, the recovery invoice, the operator's two balances and
    the engagement's walk to COLLECTED."""

    def test_issuing_findings_prices_the_finding_and_flips_the_cited_report(
        self, api, audit_manager_headers
    ):
        """PRD §3.7: "Stamp `finding_recovery_cents` as the variance multiplied by
        the selected rate multiplied by that tier multiplier, rounded half up to a
        whole cent."
        PRD §3.7: "Finally, `recovery_amount_cents` is the sum of the base total
        and the interest total, multiplied by `penalty_multiplier` and rounded half
        up to a whole cent, and then the `audit_cost_shift_cents` is added on top —
        the cost shift is never itself penalty-multiplied."
        PRD §3.7: "Each cited report with positive variance flips `ACCEPTED →
        AUDIT_ADJUSTED`, taking `audit_adjustment_cents` equal to that finding's
        `finding_recovery_cents` and adding that amount to its own
        `license_fee_due_cents`."

        Design: Difficulty/transitive_cascade/audit_findings_cascade_to_recovery_invoice_and_collection
        """
        _distributor, _agreement, report, engagement, finding = (
            setup_engagement_with_findings_issued(
                140_000,
                distributor_overrides=CLIFFSIDE_OPERATOR,
                agreement_overrides=CLIFFSIDE_TERMS,
                report_overrides=JUNE_130K_REPORT,
            )
        )

        assert engagement["status"] == "FINDINGS_ISSUED", (
            f"issuing findings moves the engagement to FINDINGS_ISSUED, got {engagement['status']}"
        )
        assert engagement["recovery_amount_cents"] == 2_943_300, (
            f"expected a priced recovery of 2,943,300 cents, got {engagement['recovery_amount_cents']}"
        )

        assert report["status"] == "AUDIT_ADJUSTED", (
            f"the cited report must flip to AUDIT_ADJUSTED, got {report['status']}"
        )
        assert report["audit_adjustment_cents"] == 400_000, (
            "the adjustment equals the finding's recovery of 400,000 cents, got "
            f"{report['audit_adjustment_cents']}"
        )

        priced = validate_success(
            api.get_audit_finding(finding["id"], audit_manager_headers), 200
        )
        assert priced["variance_subscribers"] == 10_000, (
            f"140,000 audited less 130,000 reported is 10,000, got {priced['variance_subscribers']}"
        )
        assert priced["rate_applied_cents_per_sub"] == pytest.approx(40.0000, abs=1e-6), (
            f"the flat period rate is 40.0000, got {priced['rate_applied_cents_per_sub']}"
        )
        assert priced["finding_recovery_cents"] == 400_000, (
            f"10,000 * 40.0000 * 1.00 is 400,000 cents, got {priced['finding_recovery_cents']}"
        )

    def test_recovery_invoice_grosses_at_the_engagement_recovery_amount(self):
        """PRD §3.8: "For an `AUDIT_RECOVERY` invoice, the gross is the named
        engagement's `recovery_amount_cents`."
        PRD §3.8: "`coop_cap_pct` is selected from that gross: 0.05 when the gross
        is below 5,000,000 cents, 0.08 from 5,000,000 cents up to but not including
        25,000,000 cents, and 0.12 at 25,000,000 cents and above."
        PRD §3.8: "On an `AUDIT_RECOVERY` invoice it is 0."
        PRD §3.7: "When an audit-recovery invoice is drafted naming this
        engagement, the engagement moves `FINDINGS_ISSUED → RECOVERY_INVOICED` and
        its `recovery_invoice_id` is set to the new invoice — permitted only while
        `recovery_invoice_id` is null and `recovery_amount_cents` is strictly
        positive."

        Design: Difficulty/transitive_cascade/audit_findings_cascade_to_recovery_invoice_and_collection
        """
        distributor, _agreement, _report, engagement, invoice = setup_audit_recovery_invoice(
            140_000,
            distributor_overrides=CLIFFSIDE_OPERATOR,
            agreement_overrides=CLIFFSIDE_TERMS,
            report_overrides=JUNE_130K_REPORT,
        )

        assert invoice["gross_license_fee_cents"] == 2_943_300, (
            "the recovery invoice grosses at the engagement's recovery amount, got "
            f"{invoice['gross_license_fee_cents']}"
        )
        assert invoice["coop_cap_pct"] == pytest.approx(0.05, abs=1e-6), (
            f"a gross below 5,000,000 cents selects the 0.05 band, got {invoice['coop_cap_pct']}"
        )
        assert invoice["coop_offset_cents"] == 0, (
            f"co-op support never offsets an audit recovery, got {invoice['coop_offset_cents']}"
        )
        assert invoice["net_due_cents"] == 2_943_300, (
            f"with no offsets the net due equals the gross, got {invoice['net_due_cents']}"
        )

        assert engagement["status"] == "RECOVERY_INVOICED", (
            f"drafting the recovery invoice moves the engagement on, got {engagement['status']}"
        )
        assert engagement["recovery_invoice_id"] == invoice["id"], (
            "the engagement must back-link the new invoice, got "
            f"{engagement['recovery_invoice_id']}"
        )
        assert distributor["receivable_balance_cents"] == 0, (
            "a DRAFT invoice has not entered the receivable, got "
            f"{distributor['receivable_balance_cents']}"
        )

    def test_full_settlement_unloads_both_balances_and_collects_the_engagement(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.8: "The operator's `receivable_balance_cents` increases by
        `net_due_cents`, and additionally its `audit_recovery_balance_cents`
        increases by the same amount when `invoice_kind` is `AUDIT_RECOVERY`."
        PRD §3.8: "A payment that leaves a residue moves the invoice `ISSUED →
        PARTIALLY_PAID`; a payment that closes the balance exactly moves it `ISSUED
        → PAID` or `PARTIALLY_PAID → PAID`."
        PRD §3.8: "Either way `paid_cents` increases by the amount and the
        operator's `receivable_balance_cents` decreases by the same amount, with
        `audit_recovery_balance_cents` decreasing identically when `invoice_kind` is
        `AUDIT_RECOVERY`."
        PRD §3.8: "On full settlement of an audit-recovery invoice the owning
        engagement moves `RECOVERY_INVOICED → COLLECTED`, and whenever
        `receivable_balance_cents` has fallen to at or below `credit_limit_cents`
        while `audit_recovery_balance_cents` is exactly zero, the operator leaves
        `CREDIT_HOLD` for `ACTIVE` with `credit_hold_reason` of `NONE`."

        Design: Difficulty/transitive_cascade/audit_findings_cascade_to_recovery_invoice_and_collection
        """
        distributor, _agreement, _report, engagement, invoice = setup_audit_recovery_invoice(
            140_000,
            distributor_overrides=CLIFFSIDE_OPERATOR,
            agreement_overrides=CLIFFSIDE_TERMS,
            report_overrides=JUNE_130K_REPORT,
        )
        issue_invoice(invoice["id"])

        loaded = fetch_distributor(distributor["id"])
        assert loaded["receivable_balance_cents"] == 2_943_300, (
            "issuance loads the general receivable, got "
            f"{loaded['receivable_balance_cents']}"
        )
        assert loaded["audit_recovery_balance_cents"] == 2_943_300, (
            "issuance loads the dedicated audit-recovery receivable too, got "
            f"{loaded['audit_recovery_balance_cents']}"
        )

        data = validate_success(
            api.invoice_lifecycle(
                invoice["id"],
                {"action": "RECORD_PAYMENT", "amount_cents": 2_943_300},
                revenue_accountant_headers,
            ),
            200,
        )
        assert data["status"] == "PAID", (
            f"a payment closing the balance exactly moves the invoice to PAID, got {data['status']}"
        )
        assert data["paid_cents"] == 2_943_300, (
            f"expected paid_cents 2,943,300, got {data['paid_cents']}"
        )

        collected = fetch_engagement(engagement["id"])
        assert collected["status"] == "COLLECTED", (
            f"full settlement walks the engagement to COLLECTED, got {collected['status']}"
        )
        assert collected["recovery_invoice_id"] == invoice["id"], (
            "collection keeps the recovery invoice back-link, got "
            f"{collected['recovery_invoice_id']}"
        )

        settled = fetch_distributor(distributor["id"])
        assert settled["receivable_balance_cents"] == 0, (
            f"the receivable must unload to 0, got {settled['receivable_balance_cents']}"
        )
        assert settled["audit_recovery_balance_cents"] == 0, (
            "the audit-recovery balance must unload to 0, got "
            f"{settled['audit_recovery_balance_cents']}"
        )
        assert settled["status"] == "ACTIVE", (
            f"the operator stays ACTIVE throughout, got {settled['status']}"
        )
        assert settled["credit_hold_reason"] == "NONE", (
            f"expected credit_hold_reason NONE, got {settled['credit_hold_reason']}"
        )


def _setup_operator_carrying_two_agreements_with_cleared_windows():
    """Northgate Cable Systems carrying the network under two executed
    agreements, each granting one cleared EXCLUSIVE window on its own
    OWNED_CLEARED title — a STREAMING window on the flagship deal and a LINEAR
    window on the digital-tier deal.

    Returns (distributor, flagship, digital, streaming_title, linear_title,
    streaming_window, linear_window).
    """
    distributor = register_distributor(
        legal_name="Northgate Cable Systems",
        distributor_type="CABLE_MSO",
        rate_card_class="CLASS_A",
        total_subscribers=4_000_000,
        credit_limit_cents=500_000_000,
    )
    flagship = draft_agreement(
        distributor["id"],
        contract_code="NG-2024-01",
        term_start_date="2024-01-01T00:00:00Z",
        term_end_date="2027-12-31T00:00:00Z",
        base_license_fee_cents_per_sub=42.0000,
        escalator_pct=0.04,
        penetration_floor_pct=0.85,
        committed_tier="EXPANDED_BASIC",
        launch_fee_cents=0,
        marketing_commitment_cents=0,
    )
    flagship = execute_agreement(flagship["id"])

    digital = draft_agreement(
        distributor["id"],
        contract_code="NG-2026-02",
        term_start_date="2026-01-01T00:00:00Z",
        term_end_date="2029-12-31T00:00:00Z",
        base_license_fee_cents_per_sub=30.0000,
        escalator_pct=0.00,
        penetration_floor_pct=0.60,
        committed_tier="DIGITAL_TIER",
        launch_fee_cents=0,
        marketing_commitment_cents=0,
    )
    digital = execute_agreement(digital["id"])

    streaming_title = register_cleared_title(
        title="Grand Finale Special",
        home_territory_code="US",
        linear_premiere_at="2026-08-15T00:00:00Z",
    )
    streaming_window = plan_window(
        flagship["id"],
        streaming_title["id"],
        platform="STREAMING",
        territory_code="US",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
        exclusivity="EXCLUSIVE",
    )
    streaming_window = clear_window(streaming_window["id"])

    linear_title = register_cleared_title(
        title="Autumn Classic Bowl",
        home_territory_code="US",
        linear_premiere_at="2026-08-10T00:00:00Z",
    )
    linear_window = plan_window(
        digital["id"],
        linear_title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-08-20T00:00:00Z",
        window_end="2026-09-20T00:00:00Z",
        exclusivity="EXCLUSIVE",
    )
    linear_window = clear_window(linear_window["id"])

    return (
        fetch_distributor(distributor["id"]),
        flagship,
        digital,
        fetch_title(streaming_title["id"]),
        fetch_title(linear_title["id"]),
        streaming_window,
        linear_window,
    )


class TestCreditHoldFanOut:
    """One credit decision on the operator aggregate fans out sideways across
    every carried agreement, every cleared window and every affected title."""

    def test_place_hold_suspends_every_carried_agreement(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.1: "Placing a hold moves an `ACTIVE` operator to `CREDIT_HOLD`
        with `credit_hold_reason` set to `MANUAL_REVIEW`, and then runs the
        operator-level cascade in full: every agreement of that operator whose
        `lifecycle_status` is `EXECUTED` moves to `SUSPENDED` with
        `suspension_reason` of `DISTRIBUTOR_CREDIT_HOLD`, processed in `created_at`
        ascending order; each of those agreements' rights windows in `CLEARED` or
        `ACTIVE` move to `BLOCKED` with `block_reason` of `AGREEMENT_SUSPENDED`; and
        each content title touched by those windows re-derives
        `cleared_window_count` and `distribution_coverage_status`."
        PRD §3.1: "`executed_agreement_count` is the number of that operator's
        agreements whose `lifecycle_status` is `EXECUTED` or `SUSPENDED`."

        Design: Difficulty/transitive_cascade/credit_hold_fans_out_to_agreements_windows_and_titles
        """
        distributor, flagship, digital, _t1, _t2, _w1, _w2 = (
            _setup_operator_carrying_two_agreements_with_cleared_windows()
        )
        assert distributor["executed_agreement_count"] == 2, (
            "two executed agreements are carried before the hold, got "
            f"{distributor['executed_agreement_count']}"
        )

        data = validate_success(
            api.credit_review(
                distributor["id"],
                {
                    "action": "PLACE_HOLD",
                    "reason": "Aged receivable review pending confirmation of Q2 settlement",
                },
                revenue_accountant_headers,
            ),
            200,
        )
        assert data["status"] == "CREDIT_HOLD", (
            f"placing a hold moves the operator to CREDIT_HOLD, got {data['status']}"
        )
        assert data["credit_hold_reason"] == "MANUAL_REVIEW", (
            f"a hold placed by a human records MANUAL_REVIEW, got {data['credit_hold_reason']}"
        )
        assert data["executed_agreement_count"] == 2, (
            "suspended agreements are still carried, got "
            f"{data['executed_agreement_count']}"
        )

        for agreement in (flagship, digital):
            after = fetch_agreement(agreement["id"])
            assert after["lifecycle_status"] == "SUSPENDED", (
                f"agreement {agreement['contract_code']} must suspend, got "
                f"{after['lifecycle_status']}"
            )
            assert after["suspension_reason"] == "DISTRIBUTOR_CREDIT_HOLD", (
                f"agreement {agreement['contract_code']} must record "
                f"DISTRIBUTOR_CREDIT_HOLD, got {after['suspension_reason']}"
            )

    def test_place_hold_blocks_every_cleared_window_and_darkens_each_title(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.2: "Whichever route fires, the same cascade follows: every rights
        window of the agreement in `CLEARED` or `ACTIVE` moves to `BLOCKED` with
        `block_reason` of `AGREEMENT_SUSPENDED`, processed in `window_start`
        ascending then `created_at` ascending order, and every content title those
        windows belonged to re-derives `cleared_window_count` and
        `distribution_coverage_status`."
        PRD §3.6: "if the set is empty the status is `UNDISTRIBUTED`; otherwise if
        the set is exactly `LINEAR` and nothing else the status is `LINEAR_ONLY`;
        otherwise if the set holds two or more distinct platforms the status is
        `MULTIPLATFORM`; otherwise the set holds exactly one platform which is not
        `LINEAR`, and the status is `EXCLUSIVE_UNCLEARED`, meaning a downstream
        platform is cleared while the linear window that is supposed to precede it
        is not."

        Design: Difficulty/transitive_cascade/credit_hold_fans_out_to_agreements_windows_and_titles
        """
        distributor, _flagship, _digital, streaming_title, linear_title, streaming_window, linear_window = (
            _setup_operator_carrying_two_agreements_with_cleared_windows()
        )
        assert streaming_window["windowing_holdback_days"] == 17, (
            "2026-08-15 premiere to a 2026-09-01 window start is 17 whole days, got "
            f"{streaming_window['windowing_holdback_days']}"
        )
        assert streaming_title["distribution_coverage_status"] == "EXCLUSIVE_UNCLEARED", (
            "a lone STREAMING window is EXCLUSIVE_UNCLEARED, got "
            f"{streaming_title['distribution_coverage_status']}"
        )
        assert linear_title["distribution_coverage_status"] == "LINEAR_ONLY", (
            "a lone LINEAR window is LINEAR_ONLY, got "
            f"{linear_title['distribution_coverage_status']}"
        )

        validate_success(
            api.credit_review(
                distributor["id"],
                {
                    "action": "PLACE_HOLD",
                    "reason": "Aged receivable review pending confirmation of Q2 settlement",
                },
                revenue_accountant_headers,
            ),
            200,
        )

        for window in (streaming_window, linear_window):
            after = fetch_window(window["id"])
            assert after["status"] == "BLOCKED", (
                f"the {window['platform']} window must block, got {after['status']}"
            )
            assert after["block_reason"] == "AGREEMENT_SUSPENDED", (
                f"the {window['platform']} window must record AGREEMENT_SUSPENDED, got "
                f"{after['block_reason']}"
            )

        for title in (streaming_title, linear_title):
            after = fetch_title(title["id"])
            assert after["cleared_window_count"] == 0, (
                f"title {title['title']} must re-derive to 0 cleared windows, got "
                f"{after['cleared_window_count']}"
            )
            assert after["distribution_coverage_status"] == "UNDISTRIBUTED", (
                f"title {title['title']} must re-derive to UNDISTRIBUTED, got "
                f"{after['distribution_coverage_status']}"
            )

    def test_release_hold_restores_the_operator_but_not_the_suspensions(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.1: "the operator returns to `ACTIVE` with `credit_hold_reason`
        back to `NONE`."
        PRD §3.1: "Release does not un-suspend anything — agreements suspended for
        `DISTRIBUTOR_CREDIT_HOLD` stay suspended until someone reinstates them
        explicitly."

        Design: Difficulty/transitive_cascade/credit_hold_fans_out_to_agreements_windows_and_titles
        """
        distributor, flagship, digital, _t1, _t2, streaming_window, _w2 = (
            _setup_operator_carrying_two_agreements_with_cleared_windows()
        )
        validate_success(
            api.credit_review(
                distributor["id"],
                {
                    "action": "PLACE_HOLD",
                    "reason": "Aged receivable review pending confirmation of Q2 settlement",
                },
                revenue_accountant_headers,
            ),
            200,
        )

        released = validate_success(
            api.credit_review(
                distributor["id"], {"action": "RELEASE_HOLD"}, revenue_accountant_headers
            ),
            200,
        )
        assert released["status"] == "ACTIVE", (
            f"a clean operator may leave CREDIT_HOLD, got {released['status']}"
        )
        assert released["credit_hold_reason"] == "NONE", (
            f"expected credit_hold_reason NONE after release, got {released['credit_hold_reason']}"
        )

        for agreement in (flagship, digital):
            after = fetch_agreement(agreement["id"])
            assert after["lifecycle_status"] == "SUSPENDED", (
                f"agreement {agreement['contract_code']} must stay SUSPENDED after a "
                f"release, got {after['lifecycle_status']}"
            )

        still_blocked = fetch_window(streaming_window["id"])
        assert still_blocked["status"] == "BLOCKED", (
            f"the window must stay BLOCKED after a release, got {still_blocked['status']}"
        )
