"""Reversals whose correctness is an identity holding before, during and after.

Two compensations are exercised as before/during/after triples. Voiding an
ISSUED invoice must hand back the marketing pool, the receivable and the reports
it claimed, exactly; reinstating a breach-suspended agreement must undo the
window and title cascade the suspension caused. Both are deliberately partial:
recognized revenue was earned when the operator's subscriber count was accepted,
so neither compensation may reverse a cent of it.
"""
from test_helpers import (
    TEST_USERS,
    accept_report,
    assert_commitment_ledger_identities,
    clear_window,
    create_commitment,
    draft_invoice,
    earn_commitment,
    fetch_agreement,
    fetch_commitment,
    fetch_distributor,
    fetch_invoice,
    fetch_report,
    fetch_title,
    fetch_window,
    file_and_accept_report,
    file_report,
    issue_invoice,
    plan_window,
    record_payment,
    register_cleared_title,
    setup_executed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]
SALES = TEST_USERS["affiliate_sales_exec_headers"]

# Cliffside Telco: 200,000 homes, a 50% floor (so the floor bills 100,000
# subscribers) and a credit limit far above anything billed below.
CLIFFSIDE_OPERATOR = {
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
    "credit_limit_cents": 100_000_000,
}
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


def _setup_issued_license_fee_invoice():
    """Executed Cliffside agreement with a 1,000,000-cent co-op line of which
    500,000 is earned, its 2026-06 month accepted at 130,000 subscribers, and a
    LICENSE_FEE invoice for that month drafted and ISSUED.

    Returns (distributor, agreement, commitment, report, invoice), each read back
    after issuance so the ledger and receivable are current.
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE_OPERATOR, CLIFFSIDE_TERMS)
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-12-31T00:00:00Z",
    )
    earn_commitment(commitment["id"], 500_000, "COOP-Q2-2026-INSERTION-ORDER")
    report = file_and_accept_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    invoice = draft_invoice(distributor["id"], agreement["id"], "2026-06")
    invoice = issue_invoice(invoice["id"])
    return (
        fetch_distributor(distributor["id"]),
        agreement,
        fetch_commitment(commitment["id"]),
        fetch_report(report["id"]),
        invoice,
    )


class TestInvoiceVoidRestoresLedgerReceivableAndReportLink:
    def test_void_from_issued_restores_every_counter_it_consumed(self, api):
        """PRD §2.9: "Each is specified to restore the exact pre-event values of
        the counters it reversed, and the relevant narrative in §3 states the
        invariant it must preserve."
        PRD §3.8: "Voiding an `ISSUED` invoice does the full unwind."
        PRD §3.8: "The operator's `receivable_balance_cents` decreases by
        `net_due_cents`, restoring the pre-issue balance exactly, with
        `audit_recovery_balance_cents` adjusted identically for an audit-recovery
        invoice."
        PRD §3.8: "Every marketing commitment line whose offset this invoice
        consumed has its `billed_cents` and `earned_unbilled_cents` restored, so
        that both ledger identities hold and `earned_unbilled_cents` returns to its
        pre-issue value."
        PRD §3.8: "Every report this invoice billed has its `invoice_id` cleared
        back to null, making those reports billable again."
        PRD §3.8: "`coop_cap_pct` is selected from that gross: 0.05 when the gross
        is below 5,000,000 cents, 0.08 from 5,000,000 cents up to but not including
        25,000,000 cents, and 0.12 at 25,000,000 cents and above."

        Design: Difficulty/compensating_invariant/invoice_void_restores_coop_ledger_receivable_and_report_link
        """
        distributor, agreement = setup_executed_agreement(CLIFFSIDE_OPERATOR, CLIFFSIDE_TERMS)
        commitment = create_commitment(
            agreement["id"],
            commitment_type="COOP_ADVERTISING",
            committed_cents=1_000_000,
            performance_deadline="2026-12-31T00:00:00Z",
        )
        earned = earn_commitment(commitment["id"], 500_000, "COOP-Q2-2026-INSERTION-ORDER")

        # BEFORE
        assert earned["earned_cents"] == 500_000, (
            f"the proof of performance earns 500,000, got {earned['earned_cents']}"
        )
        assert earned["billed_cents"] == 0, (
            f"nothing has been billed against the pool yet, got {earned['billed_cents']}"
        )
        assert earned["earned_unbilled_cents"] == 500_000, (
            f"the whole earned pool is unbilled, got {earned['earned_unbilled_cents']}"
        )
        assert earned["remaining_cents"] == 500_000, (
            f"500,000 of the 1,000,000 commitment is unearned, got {earned['remaining_cents']}"
        )
        assert_commitment_ledger_identities(earned)
        assert fetch_distributor(distributor["id"])["receivable_balance_cents"] == 0, (
            "no invoice has been issued, so the receivable is empty"
        )

        report = file_and_accept_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-06",
            reported_subscribers=130_000,
            reported_tier="BASIC",
        )
        assert report["license_fee_due_cents"] == 5_200_000, (
            f"130,000 subscribers at 40.0000 cents bills 5,200,000, got "
            f"{report['license_fee_due_cents']}"
        )

        invoice = draft_invoice(distributor["id"], agreement["id"], "2026-06")
        assert invoice["gross_license_fee_cents"] == 5_200_000, (
            f"the single accepted 2026-06 report is the gross, got "
            f"{invoice['gross_license_fee_cents']}"
        )
        assert invoice["coop_offset_cents"] == 416_000, (
            "a gross of 5,200,000 selects the 0.08 band, so the ceiling of 416,000 "
            f"is below the 500,000 pool, got {invoice['coop_offset_cents']}"
        )
        assert invoice["net_due_cents"] == 4_784_000, (
            f"5,200,000 less the 416,000 offset is 4,784,000, got {invoice['net_due_cents']}"
        )

        # DURING
        issued = issue_invoice(invoice["id"])
        assert issued["status"] == "ISSUED", (
            f"the invoice is issued inside the credit limit, got {issued['status']!r}"
        )
        mid_commitment = fetch_commitment(commitment["id"])
        assert mid_commitment["billed_cents"] == 416_000, (
            f"issuance consumes 416,000 of the pool, got {mid_commitment['billed_cents']}"
        )
        assert mid_commitment["earned_unbilled_cents"] == 84_000, (
            f"500,000 earned less 416,000 billed is 84,000, got "
            f"{mid_commitment['earned_unbilled_cents']}"
        )
        assert_commitment_ledger_identities(mid_commitment)
        assert fetch_distributor(distributor["id"])["receivable_balance_cents"] == 4_784_000, (
            "issuance loads the net due onto the receivable"
        )
        assert fetch_report(report["id"])["invoice_id"] == invoice["id"], (
            "issuance stamps the billed report with this invoice"
        )

        # AFTER
        response = api.invoice_lifecycle(invoice["id"], {"action": "VOID"}, ACCOUNTANT)
        data = validate_success(response, 200)
        assert data["status"] == "VOID", (
            f"the void succeeds from ISSUED with nothing collected, got {data['status']!r}"
        )
        assert data["paid_cents"] == 0, (
            f"nothing was ever collected, got {data['paid_cents']}"
        )
        assert data["net_due_cents"] == 4_784_000, (
            f"the void does not rewrite the billed amount, got {data['net_due_cents']}"
        )

        after_commitment = fetch_commitment(commitment["id"])
        assert after_commitment["billed_cents"] == 0, (
            f"the consumed offset is handed back, got {after_commitment['billed_cents']}"
        )
        assert after_commitment["earned_unbilled_cents"] == 500_000, (
            "earned_unbilled_cents returns to its pre-issue value, got "
            f"{after_commitment['earned_unbilled_cents']}"
        )
        assert after_commitment["earned_cents"] == 500_000, (
            f"the earned figure was never touched, got {after_commitment['earned_cents']}"
        )
        assert after_commitment["remaining_cents"] == 500_000, (
            f"the unearned remainder was never touched, got {after_commitment['remaining_cents']}"
        )
        assert after_commitment["forfeited_cents"] == 0, (
            f"nothing was forfeited, got {after_commitment['forfeited_cents']}"
        )
        assert after_commitment["status"] == "PARTIALLY_EARNED", (
            f"half the commitment is still unearned, got {after_commitment['status']!r}"
        )
        assert_commitment_ledger_identities(after_commitment)

        after_distributor = fetch_distributor(distributor["id"])
        assert after_distributor["receivable_balance_cents"] == 0, (
            "the receivable returns to its pre-issue balance exactly, got "
            f"{after_distributor['receivable_balance_cents']}"
        )
        assert after_distributor["status"] == "ACTIVE", (
            f"the operator never breached its credit limit, got {after_distributor['status']!r}"
        )
        assert after_distributor["audit_recovery_balance_cents"] == 0, (
            "no audit recovery was ever billed"
        )

        after_report = fetch_report(report["id"])
        assert after_report["invoice_id"] is None, (
            f"the report link is cleared back to null, got {after_report['invoice_id']!r}"
        )
        assert after_report["status"] == "ACCEPTED", (
            f"the void is a billing correction, not a restatement, got {after_report['status']!r}"
        )
        assert after_report["license_fee_due_cents"] == 5_200_000, (
            f"the accepted fee stands, got {after_report['license_fee_due_cents']}"
        )

    def test_void_leaves_recognized_revenue_and_makes_the_month_rebillable(self, api):
        """PRD §3.4: "First, the agreement's `recognized_revenue_cents` increases by
        the newly stamped `license_fee_due_cents`, and `penetration_compliance_status`
        is re-derived as described in §3.5."
        PRD §3.8: "Every report this invoice billed has its `invoice_id` cleared
        back to null, making those reports billable again."
        PRD §3.8: "`invoiced_gross_total_cents`, the sum of
        `gross_license_fee_cents` across that agreement's invoices other than those
        in `VOID`; `open_receivable_cents`, the sum of `net_due_cents` less
        `paid_cents` across that agreement's invoices in `ISSUED` or
        `PARTIALLY_PAID`; and four marketing roll-ups across the agreement's
        commitment lines — `marketing_committed_cents`, `marketing_earned_cents`,
        `marketing_remaining_cents` and `marketing_forfeited_cents`, each the sum of
        the corresponding per-line field."
        PRD §3.8: "It closes with two booleans: `marketing_conserved_identity_holds`,
        true when every one of those lines satisfies committed equals earned plus
        remaining plus forfeited, and `revenue_identity_holds`, true when
        `recognized_revenue_cents` equals `accepted_report_fee_total_cents`."

        Design: Difficulty/compensating_invariant/invoice_void_restores_coop_ledger_receivable_and_report_link
        """
        distributor, agreement, _commitment, _report, invoice = (
            _setup_issued_license_fee_invoice()
        )
        assert fetch_agreement(agreement["id"])["recognized_revenue_cents"] == 5_200_000, (
            "revenue was recognized when the subscriber count was accepted"
        )

        voided = validate_success(
            api.invoice_lifecycle(invoice["id"], {"action": "VOID"}, ACCOUNTANT), 200
        )
        assert voided["status"] == "VOID", f"expected VOID, got {voided['status']!r}"

        after_agreement = fetch_agreement(agreement["id"])
        assert after_agreement["recognized_revenue_cents"] == 5_200_000, (
            "the void is a billing correction, not a revenue reversal, got "
            f"{after_agreement['recognized_revenue_cents']}"
        )

        summary = validate_success(api.get_settlement_summary(agreement["id"], ACCOUNTANT), 200)
        assert summary["marketing_conserved_identity_holds"] is True, (
            "the restored co-op line still satisfies committed == earned + remaining + forfeited"
        )
        assert summary["revenue_identity_holds"] is True, (
            "recognized revenue still equals the accepted report fee total"
        )
        assert summary["open_receivable_cents"] == 0, (
            f"no invoice sits in ISSUED or PARTIALLY_PAID, got {summary['open_receivable_cents']}"
        )
        assert summary["invoiced_gross_total_cents"] == 0, (
            "the only invoice is in VOID and is therefore excluded, got "
            f"{summary['invoiced_gross_total_cents']}"
        )
        assert summary["recognized_revenue_cents"] == 5_200_000, (
            f"expected 5,200,000 recognized, got {summary['recognized_revenue_cents']}"
        )

        # The released report and the restored pool are both reusable.
        fresh = draft_invoice(distributor["id"], agreement["id"], "2026-06")
        assert fresh["gross_license_fee_cents"] == 5_200_000, (
            "the released 2026-06 report is billable again, got "
            f"{fresh['gross_license_fee_cents']}"
        )
        assert fresh["coop_offset_cents"] == 416_000, (
            f"the restored pool offsets the identical 416,000, got {fresh['coop_offset_cents']}"
        )
        assert fresh["net_due_cents"] == 4_784_000, (
            f"the identical net due is reachable, got {fresh['net_due_cents']}"
        )

    def test_void_after_partial_payment_rejected_and_ledger_left_consumed(self, api):
        """PRD §3.8: "Voiding is the compensating path, available from `DRAFT` and
        from `ISSUED`, and from `ISSUED` only while `paid_cents` is exactly zero — a
        partially collected invoice must be written off, never voided, and
        attempting the void is `ERR_INVALID_INVOICE_STATE`."
        PRD §3.8: "A payment that leaves a residue moves the invoice `ISSUED →
        PARTIALLY_PAID`; a payment that closes the balance exactly moves it `ISSUED
        → PAID` or `PARTIALLY_PAID → PAID`."

        Design: Difficulty/compensating_invariant/invoice_void_restores_coop_ledger_receivable_and_report_link
        """
        _distributor, _agreement, commitment, _report, invoice = (
            _setup_issued_license_fee_invoice()
        )
        paid = record_payment(invoice["id"], 1_000_000)
        assert paid["status"] == "PARTIALLY_PAID", (
            f"1,000,000 against 4,784,000 leaves a residue, got {paid['status']!r}"
        )

        response = api.invoice_lifecycle(invoice["id"], {"action": "VOID"}, ACCOUNTANT)
        validate_error(response, "ERR_INVALID_INVOICE_STATE", 409)

        after_invoice = fetch_invoice(invoice["id"])
        assert after_invoice["status"] == "PARTIALLY_PAID", (
            f"the refused void changes nothing, got {after_invoice['status']!r}"
        )
        assert after_invoice["paid_cents"] == 1_000_000, (
            f"the collected cash stands, got {after_invoice['paid_cents']}"
        )

        after_commitment = fetch_commitment(commitment["id"])
        assert after_commitment["billed_cents"] == 416_000, (
            "the co-op offset stays consumed because the void never ran, got "
            f"{after_commitment['billed_cents']}"
        )
        assert after_commitment["earned_unbilled_cents"] == 84_000, (
            f"the unbilled pool stays at 84,000, got {after_commitment['earned_unbilled_cents']}"
        )
        assert_commitment_ledger_identities(after_commitment)


# ---------------------------------------------------------------------------
# Reinstating a breach-suspended agreement
# ---------------------------------------------------------------------------
def _setup_cleared_linear_window():
    """Executed Cliffside agreement with one CLEARED LINEAR/US window over
    October 2026 on a fully cleared title. Returns
    (distributor, agreement, title, window) with the title read back after
    clearance."""
    distributor, agreement = setup_executed_agreement(CLIFFSIDE_OPERATOR, CLIFFSIDE_TERMS)
    title = register_cleared_title(linear_premiere_at="2026-08-15T00:00:00Z")
    window = plan_window(
        agreement["id"],
        title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-31T00:00:00Z",
        exclusivity="EXCLUSIVE",
    )
    window = clear_window(window["id"])
    return distributor, agreement, fetch_title(title["id"]), window


def _accept_period(agreement_id, distributor_id, period_month, reported_subscribers):
    """File and accept one period as the operator's liaison."""
    report = file_report(
        agreement_id,
        distributor_id,
        period_month=period_month,
        reported_subscribers=reported_subscribers,
        reported_tier="BASIC",
    )
    return accept_report(report["id"])


def _drive_breach_suspension(agreement_id, distributor_id):
    """Two accepted periods at 99,000 subscribers — under the 100,000 floor —
    which take the breach counter to the suspension threshold. Returns the two
    accepted reports."""
    first = _accept_period(agreement_id, distributor_id, "2026-03", 99_000)
    second = _accept_period(agreement_id, distributor_id, "2026-04", 99_000)
    return first, second


class TestAgreementReinstateCompensatesSuspensionCascade:
    def test_breach_suspension_cascades_and_reinstate_is_refused_before_the_cure(self, api):
        """PRD §3.5: "A non-compliant period does the reverse. `consecutive_compliant_periods`
        drops to 0, `penetration_breach_count` increments by one, and
        `penetration_compliance_status` becomes `BREACH`. When
        `penetration_breach_count` reaches two while the agreement's
        `lifecycle_status` is `EXECUTED`, the agreement is automatically suspended
        with `suspension_reason` of `PENETRATION_BREACH`, dragging the rights-window
        and content-title cascade behind it."
        PRD §3.3: "Whichever route fires, the same cascade follows: every rights
        window of the agreement in `CLEARED` or `ACTIVE` moves to `BLOCKED` with
        `block_reason` of `AGREEMENT_SUSPENDED`, processed in `window_start`
        ascending then `created_at` ascending order, and every content title those
        windows belonged to re-derives `cleared_window_count` and
        `distribution_coverage_status`."
        PRD §3.3: "When the suspension carried `suspension_reason` of
        `PENETRATION_BREACH`, reinstatement additionally requires that
        `penetration_breach_count` has already been driven back to zero — by three
        consecutive compliant accepted periods, or by a credit review that cleared
        it — and a reinstatement attempted while that counter is still positive is
        refused with `ERR_BREACH_COUNT_NOT_CLEARED`."
        PRD §3.4: "Under the **final** variant, stamped at acceptance into
        `billable_subscribers` and `license_fee_due_cents`, the billable count is
        the greater of `reported_subscribers` and the floor subscriber count."

        Design: Difficulty/compensating_invariant/agreement_reinstate_compensates_suspension_cascade
        """
        distributor, agreement, title, window = _setup_cleared_linear_window()

        # BEFORE
        assert window["status"] == "CLEARED", (
            f"the October window is cleared, got {window['status']!r}"
        )
        assert title["cleared_window_count"] == 1, (
            f"one window occupies the title, got {title['cleared_window_count']}"
        )
        assert title["distribution_coverage_status"] == "LINEAR_ONLY", (
            "the platform set is exactly LINEAR, got "
            f"{title['distribution_coverage_status']!r}"
        )

        first = _accept_period(agreement["id"], distributor["id"], "2026-03", 99_000)
        assert first["license_fee_due_cents"] == 4_000_000, (
            "the 100,000-subscriber floor bills, not the reported 99,000, got "
            f"{first['license_fee_due_cents']}"
        )
        assert fetch_agreement(agreement["id"])["penetration_breach_count"] == 1, (
            "the first under-penetrated period takes the breach counter to 1"
        )

        _accept_period(agreement["id"], distributor["id"], "2026-04", 99_000)
        suspended = fetch_agreement(agreement["id"])
        assert suspended["penetration_breach_count"] == 2, (
            f"the second breach takes the counter to 2, got {suspended['penetration_breach_count']}"
        )
        assert suspended["lifecycle_status"] == "SUSPENDED", (
            f"two breaches auto-suspend the agreement, got {suspended['lifecycle_status']!r}"
        )
        assert suspended["suspension_reason"] == "PENETRATION_BREACH", (
            f"the recorded reason is the breach, got {suspended['suspension_reason']!r}"
        )

        cascaded_window = fetch_window(window["id"])
        assert cascaded_window["status"] == "BLOCKED", (
            f"the suspension blocks the cleared window, got {cascaded_window['status']!r}"
        )
        assert cascaded_window["block_reason"] == "AGREEMENT_SUSPENDED", (
            f"the block reason names the suspension, got {cascaded_window['block_reason']!r}"
        )
        cascaded_title = fetch_title(title["id"])
        assert cascaded_title["cleared_window_count"] == 0, (
            "the blocked window no longer occupies the title, got "
            f"{cascaded_title['cleared_window_count']}"
        )
        assert cascaded_title["distribution_coverage_status"] == "UNDISTRIBUTED", (
            "the platform set is now empty, got "
            f"{cascaded_title['distribution_coverage_status']!r}"
        )

        response = api.agreement_lifecycle(agreement["id"], {"action": "REINSTATE"}, SALES)
        validate_error(response, "ERR_BREACH_COUNT_NOT_CLEARED", 409)
        assert fetch_agreement(agreement["id"])["lifecycle_status"] == "SUSPENDED", (
            "the refused reinstatement leaves the agreement suspended"
        )

    def test_reinstate_still_refused_after_only_two_compliant_periods(self, api):
        """PRD §3.5: "A compliant period increments `consecutive_compliant_periods`
        by one and sets `penetration_compliance_status` to `COMPLIANT`. When that run
        reaches three, the agreement's slate is wiped: `penetration_breach_count` is
        reset to 0 and `consecutive_compliant_periods` is itself reset to 0, so the
        reward pays out once and the operator must build a fresh run of three to earn
        it again."
        PRD §3.3: "When the suspension carried `suspension_reason` of
        `PENETRATION_BREACH`, reinstatement additionally requires that
        `penetration_breach_count` has already been driven back to zero — by three
        consecutive compliant accepted periods, or by a credit review that cleared
        it — and a reinstatement attempted while that counter is still positive is
        refused with `ERR_BREACH_COUNT_NOT_CLEARED`."
        PRD §3.4: "Admitting a suspended agreement here is deliberate: a suspended
        operator keeps settling the periods it reports, and this is the only path by
        which a penetration-breach suspension can ever be cured, since reinstatement
        demands a cleared breach counter and only report acceptance can clear it."

        Design: Difficulty/compensating_invariant/agreement_reinstate_compensates_suspension_cascade
        """
        distributor, agreement, _title, _window = _setup_cleared_linear_window()
        _drive_breach_suspension(agreement["id"], distributor["id"])

        first_cure = _accept_period(agreement["id"], distributor["id"], "2026-05", 130_000)
        assert first_cure["license_fee_due_cents"] == 5_200_000, (
            f"130,000 subscribers bill 5,200,000, got {first_cure['license_fee_due_cents']}"
        )
        after_one = fetch_agreement(agreement["id"])
        assert after_one["consecutive_compliant_periods"] == 1, (
            f"one compliant period so far, got {after_one['consecutive_compliant_periods']}"
        )
        assert after_one["penetration_breach_count"] == 2, (
            f"the breach counter is untouched by a single cure period, got "
            f"{after_one['penetration_breach_count']}"
        )
        validate_error(
            api.agreement_lifecycle(agreement["id"], {"action": "REINSTATE"}, SALES),
            "ERR_BREACH_COUNT_NOT_CLEARED",
            409,
        )

        _accept_period(agreement["id"], distributor["id"], "2026-06", 130_000)
        after_two = fetch_agreement(agreement["id"])
        assert after_two["consecutive_compliant_periods"] == 2, (
            f"two compliant periods so far, got {after_two['consecutive_compliant_periods']}"
        )
        assert after_two["penetration_breach_count"] == 2, (
            "the slate is wiped on the third compliant period, not the second, got "
            f"{after_two['penetration_breach_count']}"
        )
        validate_error(
            api.agreement_lifecycle(agreement["id"], {"action": "REINSTATE"}, SALES),
            "ERR_BREACH_COUNT_NOT_CLEARED",
            409,
        )
        assert fetch_agreement(agreement["id"])["lifecycle_status"] == "SUSPENDED", (
            "the agreement is still suspended after only two compliant periods"
        )

    def test_reinstate_after_three_compliant_periods_restores_window_and_title(self, api):
        """PRD §3.5: "When that run reaches three, the agreement's slate is wiped:
        `penetration_breach_count` is reset to 0 and `consecutive_compliant_periods`
        is itself reset to 0, so the reward pays out once and the operator must build
        a fresh run of three to earn it again."
        PRD §3.3: "On success `suspension_reason` returns to `NONE` and the
        compensation runs: every rights window of this agreement sitting in `BLOCKED`
        with `block_reason` of `AGREEMENT_SUSPENDED` returns to `CLEARED`, provided
        re-clearing still satisfies the occupancy rules of §3.6; a window that would
        now collide stays `BLOCKED`, with its `block_reason` rewritten to
        `BLACKOUT_CONFLICT`."
        PRD §3.3: "Each content title touched by an un-blocked window re-derives
        `cleared_window_count` and `distribution_coverage_status`."
        PRD §3.6: "`distribution_coverage_status` is derived from the *set of
        distinct platforms* among exactly those windows, by a pinned ladder evaluated
        top to bottom and stopping at the first arm that matches: if the set is empty
        the status is `UNDISTRIBUTED`; otherwise if the set is exactly `LINEAR` and
        nothing else the status is `LINEAR_ONLY`; otherwise if the set holds two or
        more distinct platforms the status is `MULTIPLATFORM`; otherwise the set
        holds exactly one platform which is not `LINEAR`, and the status is
        `EXCLUSIVE_UNCLEARED`, meaning a downstream platform is cleared while the
        linear window that is supposed to precede it is not."

        Design: Difficulty/compensating_invariant/agreement_reinstate_compensates_suspension_cascade
        """
        distributor, agreement, title, window = _setup_cleared_linear_window()
        _drive_breach_suspension(agreement["id"], distributor["id"])
        for period_month in ("2026-05", "2026-06", "2026-07"):
            _accept_period(agreement["id"], distributor["id"], period_month, 130_000)

        cured = fetch_agreement(agreement["id"])
        assert cured["penetration_breach_count"] == 0, (
            f"the third compliant period wipes the slate, got {cured['penetration_breach_count']}"
        )
        assert cured["consecutive_compliant_periods"] == 0, (
            "the run resets itself once the reward pays out, got "
            f"{cured['consecutive_compliant_periods']}"
        )

        response = api.agreement_lifecycle(agreement["id"], {"action": "REINSTATE"}, SALES)
        data = validate_success(response, 200)
        assert data["lifecycle_status"] == "EXECUTED", (
            f"the cured agreement is reinstated, got {data['lifecycle_status']!r}"
        )
        assert data["suspension_reason"] == "NONE", (
            f"the suspension reason is cleared, got {data['suspension_reason']!r}"
        )

        restored_window = fetch_window(window["id"])
        assert restored_window["status"] == "CLEARED", (
            "the window blocked by the suspension returns to CLEARED, got "
            f"{restored_window['status']!r}"
        )
        assert restored_window["block_reason"] == "NONE", (
            f"the block reason is cleared, got {restored_window['block_reason']!r}"
        )
        restored_title = fetch_title(title["id"])
        assert restored_title["cleared_window_count"] == 1, (
            "the title returns to its pre-suspension count of 1, got "
            f"{restored_title['cleared_window_count']}"
        )
        assert restored_title["distribution_coverage_status"] == "LINEAR_ONLY", (
            "the platform set is exactly LINEAR again, got "
            f"{restored_title['distribution_coverage_status']!r}"
        )

    def test_reinstatement_restores_rights_but_never_recognized_revenue(self, api):
        """PRD §3.4: "First, the agreement's `recognized_revenue_cents` increases by
        the newly stamped `license_fee_due_cents`, and `penetration_compliance_status`
        is re-derived as described in §3.5."
        PRD §3.3: "On success `suspension_reason` returns to `NONE` and the
        compensation runs: every rights window of this agreement sitting in `BLOCKED`
        with `block_reason` of `AGREEMENT_SUSPENDED` returns to `CLEARED`, provided
        re-clearing still satisfies the occupancy rules of §3.6; a window that would
        now collide stays `BLOCKED`, with its `block_reason` rewritten to
        `BLACKOUT_CONFLICT`."
        PRD §3.4: "Acceptance carries the most conditions, and their evaluation
        order matters because several can fail at once. After the state check, the
        server tests the owning agreement's lifecycle: acceptance is admissible while
        `lifecycle_status` is `EXECUTED` **or** `SUSPENDED`, and is refused with
        `ERR_AGREEMENT_NOT_EXECUTED` for `DRAFT`, `NEGOTIATING`, `EXPIRED` or
        `TERMINATED`."
        PRD §3.8: "It closes with two booleans: `marketing_conserved_identity_holds`,
        true when every one of those lines satisfies committed equals earned plus
        remaining plus forfeited, and `revenue_identity_holds`, true when
        `recognized_revenue_cents` equals `accepted_report_fee_total_cents`."

        Design: Difficulty/compensating_invariant/agreement_reinstate_compensates_suspension_cascade
        """
        distributor, agreement, _title, _window = _setup_cleared_linear_window()
        _drive_breach_suspension(agreement["id"], distributor["id"])
        for period_month in ("2026-05", "2026-06", "2026-07"):
            _accept_period(agreement["id"], distributor["id"], period_month, 130_000)

        before_reinstate = fetch_agreement(agreement["id"])
        assert before_reinstate["recognized_revenue_cents"] == 23_600_000, (
            "two floor-billed periods at 4,000,000 plus three at 5,200,000, got "
            f"{before_reinstate['recognized_revenue_cents']}"
        )

        reinstated = validate_success(
            api.agreement_lifecycle(agreement["id"], {"action": "REINSTATE"}, SALES), 200
        )
        assert reinstated["lifecycle_status"] == "EXECUTED", (
            f"the reinstatement succeeds, got {reinstated['lifecycle_status']!r}"
        )
        assert reinstated["recognized_revenue_cents"] == 23_600_000, (
            "the compensation restores rights, never revenue, got "
            f"{reinstated['recognized_revenue_cents']}"
        )
        assert fetch_agreement(agreement["id"])["recognized_revenue_cents"] == 23_600_000, (
            "recognized revenue is monotone across the whole episode"
        )

        summary = validate_success(api.get_settlement_summary(agreement["id"], ACCOUNTANT), 200)
        assert summary["revenue_identity_holds"] is True, (
            "recognized revenue equals the accepted report fee total"
        )
        assert summary["accepted_report_fee_total_cents"] == 23_600_000, (
            f"the five accepted periods total 23,600,000, got "
            f"{summary['accepted_report_fee_total_cents']}"
        )

        rows, meta = validate_paginated(
            api.list_subscriber_reports(ACCOUNTANT, params={"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 5, (
            f"five periods were filed and accepted, got {meta['total_count']}"
        )
        assert len(rows) == 5, f"expected 5 report rows, got {len(rows)}"
        assert all(row["status"] == "ACCEPTED" for row in rows), (
            "acceptance stayed legal for the three periods filed while suspended, got "
            f"{[row['status'] for row in rows]}"
        )
