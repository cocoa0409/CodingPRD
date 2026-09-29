"""State-machine depth: the subscriber report's re-entry into ACCEPTED after an
audit adjustment, the audit engagement's fork out of FIELDWORK, and the two
independent state dimensions carried by one agreement row.

Every fixture is built from scratch through PRD-declared endpoints.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_adjustment,
    advance_clock,
    api_client,
    draft_invoice,
    fetch_agreement,
    fetch_distributor,
    fetch_engagement,
    fetch_report,
    file_and_accept_report,
    issue_findings,
    open_engagement,
    record_finding,
    setup_executed_agreement,
    start_fieldwork,
    start_renewal_analysis,
    suspend_agreement,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["affiliate_sales_exec_headers"]
AUDITOR = TEST_USERS["audit_manager_headers"]
ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]

# "Cliffside Telco": 200,000 subscribers on a flat 40.0000 BASIC agreement, so
# every fee in this module is exact at four decimal places.
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


def _setup_cliffside_accepted_period(period_month: str = "2026-06", reported: int = 130_000):
    """One compliant accepted month on the flat-rate Cliffside agreement.

    Returns (distributor, agreement, report) with the agreement re-read after
    the acceptance cascade.
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE_DISTRIBUTOR, CLIFFSIDE_AGREEMENT)
    report = file_and_accept_report(
        agreement["id"],
        distributor["id"],
        period_month=period_month,
        reported_subscribers=reported,
        reported_tier="BASIC",
    )
    return distributor, fetch_agreement(agreement["id"]), report


def _audit_one_period(agreement_id: str, report, audited_subscribers: int):
    """Open, staff and issue an engagement over one already-accepted month.

    Returns (engagement, finding) with the engagement re-read after issuance.
    """
    period = report["period_month"]
    engagement = open_engagement(
        agreement_id,
        sample_period_start=period,
        sample_period_end=period,
        rate_basis="PERIOD_RATE",
    )
    engagement = start_fieldwork(engagement["id"])
    finding = record_finding(engagement["id"], report["id"], audited_subscribers)
    return issue_findings(engagement["id"]), finding


class TestAcceptedReportReEntry:
    """ACCEPTED is reached twice; the second arrival is a settlement
    acknowledgement with a strictly smaller side-effect set."""

    def test_audit_adjustment_leaves_accepted_and_destroys_the_compliant_run(self):
        """PRD §3.5: "A compliant period increments `consecutive_compliant_periods`
        by one and sets `penetration_compliance_status` to `COMPLIANT`."
        PRD §3.7: "Each cited report with positive variance flips `ACCEPTED →
        AUDIT_ADJUSTED`, taking `audit_adjustment_cents` equal to that finding's
        `finding_recovery_cents` and adding that amount to its own
        `license_fee_due_cents`."
        PRD §3.7: "The agreement's `recognized_revenue_cents` increases by the sum
        of the applied adjustments, and its `consecutive_compliant_periods` is
        forced to 0."
        PRD §3.5: "When an audit flips an accepted report to `AUDIT_ADJUSTED`,
        `consecutive_compliant_periods` is forced back to 0 — a period whose numbers
        turned out to be wrong no longer counts toward a compliant run — while
        `penetration_breach_count` is left exactly as it was."

        Design: Difficulty/non_linear_state_machine/accepted_report_reenters_accepted_after_audit_adjustment
        """
        _distributor, agreement, report = _setup_cliffside_accepted_period()
        assert report["license_fee_due_cents"] == 5200000, (
            f"130,000 subscribers at a flat 40.0000 is 5200000 cents, got {report['license_fee_due_cents']}"
        )
        assert agreement["consecutive_compliant_periods"] == 1, (
            "the first arrival at ACCEPTED opens a compliant run of 1, got "
            f"{agreement['consecutive_compliant_periods']}"
        )
        assert agreement["recognized_revenue_cents"] == 5200000, (
            "the first arrival recognises the final fee once, got "
            f"{agreement['recognized_revenue_cents']}"
        )
        assert agreement["penetration_compliance_status"] == "COMPLIANT", (
            f"65.00% clears the 50% floor, got {agreement['penetration_compliance_status']}"
        )

        engagement, _finding = _audit_one_period(agreement["id"], report, 140_000)

        assert engagement["recovery_amount_cents"] == 2943300, (
            f"the priced recovery is 2943300 cents, got {engagement['recovery_amount_cents']}"
        )
        adjusted = fetch_report(report["id"])
        assert adjusted["status"] == "AUDIT_ADJUSTED", (
            f"a positive-variance finding flips the report, got {adjusted['status']}"
        )
        assert adjusted["audit_adjustment_cents"] == 400000, (
            "10,000 subscribers at 40.0000 with a 1.00 tier multiplier is 400000 "
            f"cents, got {adjusted['audit_adjustment_cents']}"
        )
        assert adjusted["license_fee_due_cents"] == 5600000, (
            "the adjustment is added to the report's own fee, 5,200,000 + 400,000, got "
            f"{adjusted['license_fee_due_cents']}"
        )
        after = fetch_agreement(agreement["id"])
        assert after["recognized_revenue_cents"] == 5600000, (
            "recognised revenue rises by the applied adjustment, got "
            f"{after['recognized_revenue_cents']}"
        )
        assert after["consecutive_compliant_periods"] == 0, (
            "an audited period no longer counts toward a compliant run, got "
            f"{after['consecutive_compliant_periods']}"
        )
        assert after["penetration_breach_count"] == 0, (
            f"the breach count is left exactly as it was, got {after['penetration_breach_count']}"
        )

    def test_re_entry_retains_the_adjustment_and_recognises_nothing_twice(self):
        """PRD §3.4: "The second cycle is `ACCEPTED → AUDIT_ADJUSTED → ACCEPTED`,
        and its outbound leg is driven by the audit process of §3.7 rather than by a
        reviewer."
        PRD §3.4: "Accepting the adjustment returns the report `AUDIT_ADJUSTED →
        ACCEPTED`, and it requires that the money has already been billed: the
        owning audit engagement must be in `RECOVERY_INVOICED` or `COLLECTED`."
        PRD §3.4: "The transition retains `audit_adjustment_cents`, leaves
        `license_fee_due_cents` unchanged, and leaves the agreement's
        `recognized_revenue_cents` unchanged, because the adjustment was folded into
        recognised revenue at the moment the report became `AUDIT_ADJUSTED` and must
        not be counted twice."
        PRD §3.7: "When an audit-recovery invoice is drafted naming this engagement,
        the engagement moves `FINDINGS_ISSUED → RECOVERY_INVOICED` and its
        `recovery_invoice_id` is set to the new invoice — permitted only while
        `recovery_invoice_id` is null and `recovery_amount_cents` is strictly
        positive."
        PRD §3.5: "Immediately after a report's final fee is stamped on acceptance,
        the agreement's penetration position is re-derived."

        Design: Difficulty/non_linear_state_machine/accepted_report_reenters_accepted_after_audit_adjustment
        """
        distributor, agreement, report = _setup_cliffside_accepted_period()
        engagement, _finding = _audit_one_period(agreement["id"], report, 140_000)
        # An audit-recovery invoice carries the findings-issuance month.
        draft_invoice(
            distributor["id"],
            agreement["id"],
            "2026-08",
            invoice_kind="AUDIT_RECOVERY",
            audit_engagement_id=engagement["id"],
        )
        assert fetch_engagement(engagement["id"])["status"] == "RECOVERY_INVOICED", (
            "drafting the recovery invoice moves the engagement to RECOVERY_INVOICED, got "
            f"{fetch_engagement(engagement['id'])['status']}"
        )
        adjusted = fetch_report(report["id"])
        revenue_before = fetch_agreement(agreement["id"])["recognized_revenue_cents"]

        settled = accept_adjustment(report["id"])

        assert settled["status"] == "ACCEPTED", (
            f"the report re-enters the state it already visited, got {settled['status']}"
        )
        assert settled["audit_adjustment_cents"] == 400000, (
            f"the adjustment is retained, not cleared, got {settled['audit_adjustment_cents']}"
        )
        assert settled["license_fee_due_cents"] == adjusted["license_fee_due_cents"], (
            "the licence fee is left unchanged by the round trip, got "
            f"{settled['license_fee_due_cents']} against {adjusted['license_fee_due_cents']}"
        )
        assert settled["billable_subscribers"] == 130000, (
            f"the billable count still comes from the reported 130,000, got {settled['billable_subscribers']}"
        )
        after = fetch_agreement(agreement["id"])
        assert after["recognized_revenue_cents"] == revenue_before, (
            "the adjustment must not be counted twice, got "
            f"{after['recognized_revenue_cents']} against {revenue_before}"
        )
        assert after["consecutive_compliant_periods"] == 0, (
            "no final fee is stamped on this leg, so the compliance re-derivation "
            f"does not re-run, got {after['consecutive_compliant_periods']}"
        )
        assert after["penetration_breach_count"] == 0, (
            f"the breach count is still untouched, got {after['penetration_breach_count']}"
        )
        assert after["lifecycle_status"] == "EXECUTED", (
            f"nothing on this leg touches the lifecycle dimension, got {after['lifecycle_status']}"
        )


class TestAuditFieldworkFork:
    """Which exits out of FIELDWORK are admissible is a property of the findings
    already attached, not of the request."""

    def test_positive_variance_forbids_the_clean_close(self):
        """PRD §3.7: "The **close-with-no-finding** branch moves `FIELDWORK →
        CLOSED_NO_FINDING` and requires the opposite: no finding of the engagement
        may have positive `variance_subscribers`, and attempting it while one does
        is refused with `ERR_FINDINGS_PRESENT_CANNOT_CLOSE`."
        PRD §3.7: "On creation the server snapshots the report's `period_month` and
        its `reported_subscribers` onto the finding, so a later restatement cannot
        rewrite audit history, and computes `variance_subscribers` as the audited
        count less the reported count, floored at zero — an operator that
        over-reported produces a finding of zero variance, never a negative one."
        PRD §2.8: "The first rule that fails decides the response, and no side
        effect of the requested operation fires."

        Design: Difficulty/non_linear_state_machine/audit_fieldwork_forks_on_presence_of_findings
        """
        distributor, agreement = setup_executed_agreement(
            CLIFFSIDE_DISTRIBUTOR, CLIFFSIDE_AGREEMENT
        )
        report = file_and_accept_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-06",
            reported_subscribers=130_000,
            reported_tier="BASIC",
        )
        engagement = open_engagement(
            agreement["id"],
            sample_period_start="2026-06",
            sample_period_end="2026-06",
            rate_basis="PERIOD_RATE",
        )
        engagement = start_fieldwork(engagement["id"])
        finding = record_finding(engagement["id"], report["id"], 140_000)
        assert finding["variance_subscribers"] == 10000, (
            f"140,000 audited against 130,000 reported is a 10000 variance, got {finding['variance_subscribers']}"
        )

        response = api_client.audit_engagement_lifecycle(
            engagement["id"], {"action": "CLOSE_NO_FINDING"}, AUDITOR
        )

        validate_error(response, ApiErrorId.ERR_FINDINGS_PRESENT_CANNOT_CLOSE, 409)
        assert fetch_engagement(engagement["id"])["status"] == "FIELDWORK", (
            "the rejected exit left the machine where it was, got "
            f"{fetch_engagement(engagement['id'])['status']}"
        )

    def test_zero_variance_forbids_issuing_findings(self):
        """PRD §3.7: "The **issue-findings** branch moves `FIELDWORK →
        FINDINGS_ISSUED` and requires at least one finding with a positive
        `variance_subscribers`; attempting it on a sample that turned up no
        shortfall is refused with `ERR_NO_AUDIT_FINDINGS`."
        PRD §3.7: "On creation the server snapshots the report's `period_month` and
        its `reported_subscribers` onto the finding, so a later restatement cannot
        rewrite audit history, and computes `variance_subscribers` as the audited
        count less the reported count, floored at zero — an operator that
        over-reported produces a finding of zero variance, never a negative one."

        Design: Difficulty/non_linear_state_machine/audit_fieldwork_forks_on_presence_of_findings
        """
        distributor, agreement = setup_executed_agreement(
            CLIFFSIDE_DISTRIBUTOR, CLIFFSIDE_AGREEMENT
        )
        report = file_and_accept_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-05",
            reported_subscribers=120_000,
            reported_tier="BASIC",
        )
        engagement = open_engagement(
            agreement["id"],
            sample_period_start="2026-05",
            sample_period_end="2026-05",
            rate_basis="PERIOD_RATE",
        )
        engagement = start_fieldwork(engagement["id"])
        finding = record_finding(engagement["id"], report["id"], 120_000)
        assert finding["variance_subscribers"] == 0, (
            f"a clean month produces a zero variance, got {finding['variance_subscribers']}"
        )

        response = api_client.audit_engagement_lifecycle(
            engagement["id"], {"action": "ISSUE_FINDINGS"}, AUDITOR
        )

        validate_error(response, ApiErrorId.ERR_NO_AUDIT_FINDINGS, 422)
        assert fetch_engagement(engagement["id"])["status"] == "FIELDWORK", (
            "the rejected exit left the machine where it was, got "
            f"{fetch_engagement(engagement['id'])['status']}"
        )
        assert fetch_report(report["id"])["status"] == "ACCEPTED", (
            f"the refused issuance touched no report, got {fetch_report(report['id'])['status']}"
        )

    def test_zero_variance_admits_the_clean_close_with_every_recovery_field_zero(self):
        """PRD §3.7: "Closing with no finding sets `total_variance_subscribers` to
        0, `underreporting_pct` to 0, `penalty_multiplier` to 1.0, and
        `base_recovery_cents`, `interest_cents`, `audit_cost_shift_cents` and
        `recovery_amount_cents` all to 0; it touches no subscriber report and leaves
        the agreement's `recognized_revenue_cents` exactly as it was."
        PRD §3.7: "`CLOSED_NO_FINDING` is terminal."
        PRD §3.7: "The finding's own `engagement_id` records its engagement, while
        its `rate_applied_cents_per_sub` and `finding_recovery_cents` stay at zero
        until the engagement issues findings."

        Design: Difficulty/non_linear_state_machine/audit_fieldwork_forks_on_presence_of_findings
        """
        distributor, agreement = setup_executed_agreement(
            CLIFFSIDE_DISTRIBUTOR, CLIFFSIDE_AGREEMENT
        )
        report = file_and_accept_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-05",
            reported_subscribers=120_000,
            reported_tier="BASIC",
        )
        revenue_before = fetch_agreement(agreement["id"])["recognized_revenue_cents"]
        engagement = open_engagement(
            agreement["id"],
            sample_period_start="2026-05",
            sample_period_end="2026-05",
            rate_basis="PERIOD_RATE",
        )
        engagement = start_fieldwork(engagement["id"])
        finding = record_finding(engagement["id"], report["id"], 120_000)

        closed = validate_success(
            api_client.audit_engagement_lifecycle(
                engagement["id"], {"action": "CLOSE_NO_FINDING"}, AUDITOR
            )
        )

        assert closed["status"] == "CLOSED_NO_FINDING", (
            f"a clean sample admits the dead-end branch, got {closed['status']}"
        )
        assert closed["total_variance_subscribers"] == 0, (
            f"the clean close zeroes the variance total, got {closed['total_variance_subscribers']}"
        )
        assert closed["underreporting_pct"] == pytest.approx(0, abs=0.0001), (
            f"the clean close zeroes the under-reporting share, got {closed['underreporting_pct']}"
        )
        assert closed["penalty_multiplier"] == pytest.approx(1.0, abs=0.01), (
            f"the clean close leaves the multiplier at 1.0, got {closed['penalty_multiplier']}"
        )
        for field in [
            "base_recovery_cents",
            "interest_cents",
            "audit_cost_shift_cents",
            "recovery_amount_cents",
        ]:
            assert closed[field] == 0, f"the clean close zeroes {field}, got {closed[field]}"
        assert closed["recovery_invoice_id"] is None, (
            f"nothing is billed on this branch, got {closed['recovery_invoice_id']}"
        )
        assert validate_success(api_client.get_audit_finding(finding["id"], AUDITOR))[
            "finding_recovery_cents"
        ] == 0, "an unissued finding is never priced"
        assert fetch_report(report["id"])["status"] == "ACCEPTED", (
            f"the clean-close branch touches no report, got {fetch_report(report['id'])['status']}"
        )
        assert fetch_agreement(agreement["id"])["recognized_revenue_cents"] == revenue_before, (
            "the clean close leaves recognised revenue exactly as it was, got "
            f"{fetch_agreement(agreement['id'])['recognized_revenue_cents']}"
        )


class TestTwoStateDimensions:
    """One agreement row carries two dimensions; the coupling runs from
    lifecycle to renewal and never the other way."""

    def test_suspension_does_not_disturb_the_renewal_dimension(self):
        """PRD §3.2: "The agreement carries **two independent state dimensions**."
        PRD §3.2: "The renewal dimension is driven by its own action set and never
        writes `lifecycle_status`; the lifecycle dimension writes `renewal_status`
        only in the two forced-lapse cases described below."
        PRD §3.9: "An `AffiliateSalesExec` moves the agreement `NOT_DUE →
        RENEWAL_ANALYSIS`, which requires the `lifecycle_status` to be `EXECUTED` or
        `SUSPENDED` — an operator under suspension is still a renewal candidate —
        and requires the renewal window to be open: `term_end_date` must be no more
        than 270 days beyond the current logical instant."
        PRD §3.9: "The transition stamps `renewal_analysis_started_at` with the
        current logical instant and leaves `negotiation_round` at 0."
        PRD §3.2: "Suspension moves `EXECUTED → SUSPENDED` and arrives by three
        routes: an `AffiliateSalesExec` suspending deliberately, in which case the
        caller may pass a `suspension_reason` and the recorded reason is
        `MANUAL_SUSPENSION`; the compliance engine reaching the breach threshold on
        report acceptance, which records `PENETRATION_BREACH`; and the owning
        operator entering `CREDIT_HOLD`, which records `DISTRIBUTOR_CREDIT_HOLD`."

        Design: Difficulty/non_linear_state_machine/agreement_lifecycle_and_renewal_dimensions_advance_independently
        """
        _distributor, agreement = setup_executed_agreement()
        assert agreement["renewal_status"] == "NOT_DUE", (
            f"a fresh agreement starts at NOT_DUE, got {agreement['renewal_status']}"
        )
        advance_clock("2027-06-01T00:00:00Z")

        opened = start_renewal_analysis(agreement["id"])

        assert opened["renewal_status"] == "RENEWAL_ANALYSIS", (
            f"213 days from term end is inside the 270-day window, got {opened['renewal_status']}"
        )
        assert opened["lifecycle_status"] == "EXECUTED", (
            f"no renewal action ever writes lifecycle_status, got {opened['lifecycle_status']}"
        )
        assert opened["renewal_analysis_started_at"] is not None, (
            f"the transition stamps its instant, got {opened['renewal_analysis_started_at']}"
        )

        suspended = suspend_agreement(agreement["id"], "MANUAL_SUSPENSION")

        assert suspended["lifecycle_status"] == "SUSPENDED", (
            f"the lifecycle dimension advanced, got {suspended['lifecycle_status']}"
        )
        assert suspended["renewal_status"] == "RENEWAL_ANALYSIS", (
            "a deliberate suspension is not one of the two forced-lapse cases, got "
            f"{suspended['renewal_status']}"
        )
        assert suspended["suspension_reason"] == "MANUAL_SUSPENSION", (
            f"a deliberate suspension records MANUAL_SUSPENSION, got {suspended['suspension_reason']}"
        )

    def test_termination_forces_the_renewal_dimension_to_lapsed(self):
        """PRD §3.9: "An offer that is declined or allowed to expire moves the
        agreement `RENEWAL_OFFERED → LAPSED`, and an agreement still under analysis
        lapses too when its `term_end_date` passes on a clock advance or when it is
        terminated outright."
        PRD §3.2: "Terminating from `SUSPENDED` additionally requires that no
        invoice of this agreement sits in `ISSUED` or `PARTIALLY_PAID` — open
        receivables must be resolved first, and the refusal is
        `ERR_OPEN_RECEIVABLE_BLOCKS_TERMINATION` — and it runs the full unwind: every
        rights window in `PLANNED`, `CLEARED`, `ACTIVE` or `BLOCKED` moves to
        `EXPIRED`, every marketing commitment with positive `remaining_cents`
        forfeits that remainder and becomes `FORFEITED`, and the operator's
        `executed_agreement_count` decrements by one."
        PRD §3.9: "Neither `RENEWED` nor `LAPSED` alters `lifecycle_status` by
        itself: an agreement can sit in `EXPIRED` with `renewal_status` of `LAPSED`,
        or in `EXECUTED` with `renewal_status` of `RENEWED`, and every one of the
        resulting pairs is a legal state of the record."

        Design: Difficulty/non_linear_state_machine/agreement_lifecycle_and_renewal_dimensions_advance_independently
        """
        distributor, agreement = setup_executed_agreement()
        advance_clock("2027-06-01T00:00:00Z")
        start_renewal_analysis(agreement["id"])
        suspend_agreement(agreement["id"], "MANUAL_SUSPENSION")

        terminated = validate_success(
            api_client.agreement_lifecycle(agreement["id"], {"action": "TERMINATE"}, SALES)
        )

        assert terminated["lifecycle_status"] == "TERMINATED", (
            f"the lifecycle dimension reaches its terminal state, got {terminated['lifecycle_status']}"
        )
        assert terminated["renewal_status"] == "LAPSED", (
            "an agreement still under analysis lapses when it is terminated outright, got "
            f"{terminated['renewal_status']}"
        )
        assert fetch_distributor(distributor["id"])["executed_agreement_count"] == 0, (
            "the full unwind decrements the operator's executed count, got "
            f"{fetch_distributor(distributor['id'])['executed_agreement_count']}"
        )

    def test_neither_terminal_dimension_can_be_reopened(self):
        """PRD §3.2: "An action that is not a declared transition out of the current
        `lifecycle_status` is rejected with `ERR_INVALID_AGREEMENT_STATE`; an action
        that is not a declared transition out of the current `renewal_status` is
        rejected with `ERR_INVALID_RENEWAL_STATE`. Both are HTTP 409."
        PRD §3.9: "An offer can be pulled back for rework, moving `RENEWAL_OFFERED →
        RENEWAL_ANALYSIS` and incrementing `negotiation_round` by one — the counter
        therefore records how many times the offer was withdrawn and re-tabled, and
        it never decreases."
        PRD §3.9: "`LAPSED` is likewise terminal."
        PRD §3.2: "Reinstatement moves `SUSPENDED → EXECUTED`."

        Design: Difficulty/non_linear_state_machine/agreement_lifecycle_and_renewal_dimensions_advance_independently
        """
        _distributor, agreement = setup_executed_agreement()
        advance_clock("2027-06-01T00:00:00Z")
        start_renewal_analysis(agreement["id"])
        suspend_agreement(agreement["id"], "MANUAL_SUSPENSION")
        validate_success(
            api_client.agreement_lifecycle(agreement["id"], {"action": "TERMINATE"}, SALES)
        )

        reopen = api_client.agreement_renewal(
            agreement["id"], {"action": "REOPEN_ANALYSIS"}, SALES
        )
        reinstate = api_client.agreement_lifecycle(
            agreement["id"], {"action": "REINSTATE"}, SALES
        )

        validate_error(reopen, ApiErrorId.ERR_INVALID_RENEWAL_STATE, 409)
        validate_error(reinstate, ApiErrorId.ERR_INVALID_AGREEMENT_STATE, 409)
        final = fetch_agreement(agreement["id"])
        assert final["lifecycle_status"] == "TERMINATED", (
            f"neither refusal resurrected the lifecycle dimension, got {final['lifecycle_status']}"
        )
        assert final["renewal_status"] == "LAPSED", (
            f"neither refusal resurrected the renewal dimension, got {final['renewal_status']}"
        )
