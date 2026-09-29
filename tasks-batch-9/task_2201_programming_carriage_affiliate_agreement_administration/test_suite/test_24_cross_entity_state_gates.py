"""Cross-entity state gates.

Three operations whose own entity sits in a perfectly admissible source state
and which are still refused, because admissibility is a property of a different
record: the parent agreement's lifecycle for subscriber-report acceptance, the
operator's credit standing for licence-fee invoice issuance, and the content
title's rights standing for window clearance.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_report,
    assert_commitment_ledger_identities,
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
    file_report,
    get_success_data,
    plan_window,
    register_title,
    setup_draft_agreement,
    setup_executed_agreement,
    set_title_rights,
    suspend_agreement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["network_admin_headers"]
SALES = TEST_USERS["affiliate_sales_exec_headers"]
ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]
RIGHTS = TEST_USERS["rights_administrator_headers"]

# A 200,000-home telco on a 50% penetration floor: the floor is 100,000 subs,
# the negotiated rate is a flat 40.0000 cents with no escalator, and the
# committed tier is BASIC (multiplier 1.00).
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
CLIFFSIDE_PERIOD = {
    "period_month": "2026-06",
    "reported_subscribers": 130_000,
    "reported_tier": "BASIC",
}


def _setup_cliffside_drafted_invoice():
    """Executed Cliffside agreement carrying a half-earned co-op line, one
    accepted 2026-06 month and a DRAFT licence-fee invoice for that month.

    Returns (distributor, agreement, commitment, report, invoice).
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE_OPERATOR, CLIFFSIDE_TERMS)
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-12-31T00:00:00Z",
    )
    earn_commitment(commitment["id"], 500_000, "COOP-Q2-2026-INSERTION-ORDER")
    report = file_report(agreement["id"], distributor["id"], **CLIFFSIDE_PERIOD)
    report = accept_report(report["id"])
    invoice = draft_invoice(
        distributor["id"], agreement["id"], CLIFFSIDE_PERIOD["period_month"]
    )
    return distributor, agreement, commitment, report, invoice


def _place_hold(api, distributor_id):
    return get_success_data(
        api.credit_review(
            distributor_id,
            {
                "action": "PLACE_HOLD",
                "reason": "Manual review pending confirmation of parent guarantee",
            },
            ACCOUNTANT,
        )
    )


def _release_hold(api, distributor_id):
    return get_success_data(
        api.credit_review(distributor_id, {"action": "RELEASE_HOLD"}, ACCOUNTANT)
    )


# ---------------------------------------------------------------------------
# Report acceptance reads the owning agreement's lifecycle
# ---------------------------------------------------------------------------
class TestReportAcceptanceReadsAgreementLifecycle:
    def test_accept_submitted_report_on_draft_agreement_rejected(self, api):
        """PRD §3.4: "After the state check, the server tests the owning
        agreement's lifecycle: acceptance is admissible while `lifecycle_status`
        is `EXECUTED` **or** `SUSPENDED`, and is refused with
        `ERR_AGREEMENT_NOT_EXECUTED` for `DRAFT`, `NEGOTIATING`, `EXPIRED` or
        `TERMINATED`."
        PRD §2.8: "**The first rule that fails decides the response, and no side
        effect of the requested operation fires.**"
        PRD §3.4: "A new report opens in `SUBMITTED` with `license_fee_due_cents`
        0, `audit_adjustment_cents` 0, `invoice_id` null, `accepted_at` null and
        `version` 1, and it increments the agreement's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/report_acceptance_requires_executed_or_suspended_agreement
        """
        distributor, agreement = setup_draft_agreement(CLIFFSIDE_OPERATOR, CLIFFSIDE_TERMS)
        assert agreement["lifecycle_status"] == "DRAFT", (
            "the agreement must still be DRAFT before the acceptance attempt"
        )
        report = file_report(agreement["id"], distributor["id"], **CLIFFSIDE_PERIOD)
        assert report["status"] == "SUBMITTED", (
            f"a fresh filing opens in SUBMITTED, got {report['status']!r}"
        )

        response = api.review_subscriber_report(
            report["id"], {"action": "ACCEPT"}, ACCOUNTANT
        )
        validate_error(response, "ERR_AGREEMENT_NOT_EXECUTED", 409)

        after_report = fetch_report(report["id"])
        assert after_report["status"] == "SUBMITTED", (
            "the refused acceptance must leave the report at SUBMITTED, got "
            f"{after_report['status']!r}"
        )
        assert after_report["license_fee_due_cents"] == 0, (
            "no fee may be stamped by a refused acceptance, got "
            f"{after_report['license_fee_due_cents']}"
        )
        assert after_report["accepted_at"] is None, (
            "accepted_at must stay null when acceptance is refused"
        )

        after_agreement = fetch_agreement(agreement["id"])
        assert after_agreement["recognized_revenue_cents"] == 0, (
            "a refused acceptance recognises no revenue, got "
            f"{after_agreement['recognized_revenue_cents']}"
        )
        assert after_agreement["penetration_compliance_status"] == "UNKNOWN", (
            "the compliance status must be untouched by a refused acceptance, got "
            f"{after_agreement['penetration_compliance_status']!r}"
        )

    def test_accept_submitted_report_on_suspended_agreement_succeeds(self, api):
        """PRD §3.4: "After the state check, the server tests the owning
        agreement's lifecycle: acceptance is admissible while `lifecycle_status`
        is `EXECUTED` **or** `SUSPENDED`, and is refused with
        `ERR_AGREEMENT_NOT_EXECUTED` for `DRAFT`, `NEGOTIATING`, `EXPIRED` or
        `TERMINATED`."
        PRD §3.4: "Under the **final** variant, stamped at acceptance into
        `billable_subscribers` and `license_fee_due_cents`, the billable count is
        the greater of `reported_subscribers` and the floor subscriber count."
        PRD §3.5: "A compliant period increments `consecutive_compliant_periods`
        by one and sets `penetration_compliance_status` to `COMPLIANT`."

        Design: Difficulty/cross_entity_state_dependency/report_acceptance_requires_executed_or_suspended_agreement
        """
        distributor, agreement = setup_executed_agreement(
            CLIFFSIDE_OPERATOR, CLIFFSIDE_TERMS
        )
        report = file_report(agreement["id"], distributor["id"], **CLIFFSIDE_PERIOD)
        suspended = suspend_agreement(agreement["id"])
        assert suspended["lifecycle_status"] == "SUSPENDED", (
            f"the agreement must be SUSPENDED, got {suspended['lifecycle_status']!r}"
        )

        response = api.review_subscriber_report(
            report["id"], {"action": "ACCEPT"}, ACCOUNTANT
        )
        data = validate_success(response, 200)
        assert data["status"] == "ACCEPTED", (
            f"acceptance on a SUSPENDED agreement is admissible, got {data['status']!r}"
        )
        assert data["license_fee_due_cents"] == 5_200_000, (
            "130,000 reported subscribers above the 100,000 floor bill at 40.0000 "
            f"cents on BASIC, expected 5200000, got {data['license_fee_due_cents']}"
        )
        assert data["accepted_at"] is not None, (
            "a successful acceptance stamps accepted_at"
        )

        after_agreement = fetch_agreement(agreement["id"])
        assert after_agreement["lifecycle_status"] == "SUSPENDED", (
            "acceptance never un-suspends an agreement by itself, got "
            f"{after_agreement['lifecycle_status']!r}"
        )
        assert after_agreement["consecutive_compliant_periods"] == 1, (
            "a compliant period increments the run to 1, got "
            f"{after_agreement['consecutive_compliant_periods']}"
        )
        assert after_agreement["penetration_compliance_status"] == "COMPLIANT", (
            "0.6500 penetration clears the 0.5000 floor, got "
            f"{after_agreement['penetration_compliance_status']!r}"
        )
        assert after_agreement["recognized_revenue_cents"] == 5_200_000, (
            "recognised revenue rises by the newly stamped fee, got "
            f"{after_agreement['recognized_revenue_cents']}"
        )


# ---------------------------------------------------------------------------
# Licence-fee issuance reads the operator's credit standing
# ---------------------------------------------------------------------------
class TestLicenceFeeIssuanceReadsCreditStanding:
    def test_issue_license_fee_invoice_rejected_while_operator_on_credit_hold(self, api):
        """PRD §3.8: "For a `LICENSE_FEE` invoice the operator must be `ACTIVE`;
        an operator on `CREDIT_HOLD`, `SUSPENDED` or `TERMINATED` cannot be
        handed a new license-fee bill, and the refusal is
        `ERR_DISTRIBUTOR_CREDIT_HOLD`."
        PRD §3.1: "Placing a hold moves an `ACTIVE` operator to `CREDIT_HOLD`
        with `credit_hold_reason` set to `MANUAL_REVIEW`, and then runs the
        operator-level cascade in full: every agreement of that operator whose
        `lifecycle_status` is `EXECUTED` moves to `SUSPENDED` with
        `suspension_reason` of `DISTRIBUTOR_CREDIT_HOLD`, processed in
        `created_at` ascending order; each of those agreements' rights windows in
        `CLEARED` or `ACTIVE` move to `BLOCKED` with `block_reason` of
        `AGREEMENT_SUSPENDED`; and each content title touched by those windows
        re-derives `cleared_window_count` and `distribution_coverage_status`."
        PRD §2.8: "**The first rule that fails decides the response, and no side
        effect of the requested operation fires.**"

        Design: Difficulty/cross_entity_state_dependency/license_fee_issue_blocked_by_distributor_credit_hold
        """
        distributor, agreement, commitment, report, invoice = (
            _setup_cliffside_drafted_invoice()
        )
        assert invoice["status"] == "DRAFT", (
            f"a fresh draft opens in DRAFT, got {invoice['status']!r}"
        )
        assert invoice["net_due_cents"] == 4_784_000, (
            "a 5,200,000-cent gross less a 416,000-cent co-op offset nets "
            f"4784000, got {invoice['net_due_cents']}"
        )

        held = _place_hold(api, distributor["id"])
        assert held["status"] == "CREDIT_HOLD", (
            f"the operator must sit on credit hold, got {held['status']!r}"
        )

        response = api.invoice_lifecycle(invoice["id"], {"action": "ISSUE"}, ACCOUNTANT)
        validate_error(response, "ERR_DISTRIBUTOR_CREDIT_HOLD", 409)

        after_invoice = fetch_invoice(invoice["id"])
        assert after_invoice["status"] == "DRAFT", (
            f"the refused issuance leaves the invoice DRAFT, got {after_invoice['status']!r}"
        )
        assert after_invoice["issued_at"] is None, (
            "issued_at must stay null when issuance is refused"
        )
        assert after_invoice["net_due_cents"] == 4_784_000, (
            f"net_due_cents must be unchanged, got {after_invoice['net_due_cents']}"
        )
        assert after_invoice["coop_offset_cents"] == 416_000, (
            f"coop_offset_cents must be unchanged, got {after_invoice['coop_offset_cents']}"
        )

        assert fetch_distributor(distributor["id"])["receivable_balance_cents"] == 0, (
            "a refused issuance loads nothing onto the receivable"
        )
        ledger = fetch_commitment(commitment["id"])
        assert ledger["billed_cents"] == 0, (
            f"the co-op offset must stay unconsumed, got billed {ledger['billed_cents']}"
        )
        assert ledger["earned_unbilled_cents"] == 500_000, (
            "the earned-but-unbilled pool must stay whole, got "
            f"{ledger['earned_unbilled_cents']}"
        )
        assert_commitment_ledger_identities(ledger)

    def test_issue_license_fee_invoice_succeeds_once_hold_released(self, api):
        """PRD §3.8: "For a `LICENSE_FEE` invoice the operator must be `ACTIVE`;
        an operator on `CREDIT_HOLD`, `SUSPENDED` or `TERMINATED` cannot be
        handed a new license-fee bill, and the refusal is
        `ERR_DISTRIBUTOR_CREDIT_HOLD`."
        PRD §3.1: "Releasing a hold is only permitted when
        `receivable_balance_cents` is at or below `credit_limit_cents` **and**
        `audit_recovery_balance_cents` is exactly zero; the operator returns to
        `ACTIVE` with `credit_hold_reason` back to `NONE`."
        PRD §3.8: "Issuance stamps `issued_at`, consumes the marketing offsets it
        projected, and stamps each folded report's `invoice_id` with this
        invoice's identifier."
        PRD §3.8: "The operator's `receivable_balance_cents` increases by
        `net_due_cents`, and additionally its `audit_recovery_balance_cents`
        increases by the same amount when `invoice_kind` is `AUDIT_RECOVERY`."

        Design: Difficulty/cross_entity_state_dependency/license_fee_issue_blocked_by_distributor_credit_hold
        """
        distributor, agreement, commitment, report, invoice = (
            _setup_cliffside_drafted_invoice()
        )
        _place_hold(api, distributor["id"])
        refused = api.invoice_lifecycle(invoice["id"], {"action": "ISSUE"}, ACCOUNTANT)
        validate_error(refused, "ERR_DISTRIBUTOR_CREDIT_HOLD", 409)

        released = _release_hold(api, distributor["id"])
        assert released["status"] == "ACTIVE", (
            f"release returns the operator to ACTIVE, got {released['status']!r}"
        )
        assert released["credit_hold_reason"] == "NONE", (
            f"release resets credit_hold_reason to NONE, got {released['credit_hold_reason']!r}"
        )

        response = api.invoice_lifecycle(invoice["id"], {"action": "ISSUE"}, ACCOUNTANT)
        data = validate_success(response, 200)
        assert data["status"] == "ISSUED", (
            f"the identical call now issues the invoice, got {data['status']!r}"
        )
        assert data["net_due_cents"] == 4_784_000, (
            f"the invoice row never changed in between, got {data['net_due_cents']}"
        )

        assert (
            fetch_distributor(distributor["id"])["receivable_balance_cents"] == 4_784_000
        ), "issuance loads net_due_cents onto the receivable"
        ledger = fetch_commitment(commitment["id"])
        assert ledger["billed_cents"] == 416_000, (
            f"issuance consumes the projected co-op offset, got {ledger['billed_cents']}"
        )
        assert ledger["earned_unbilled_cents"] == 84_000, (
            "500,000 earned less 416,000 billed leaves 84000, got "
            f"{ledger['earned_unbilled_cents']}"
        )
        assert_commitment_ledger_identities(ledger)
        assert fetch_report(report["id"])["invoice_id"] == invoice["id"], (
            "issuance stamps the folded report's invoice_id"
        )


# ---------------------------------------------------------------------------
# Window clearance reads the content title's rights standing
# ---------------------------------------------------------------------------
class TestWindowClearanceReadsTitleRights:
    @pytest.mark.parametrize(
        "rights_status", ["PENDING_CLEARANCE", "THIRD_PARTY_LICENSED", "EXPIRED_RIGHTS"]
    )
    def test_clear_window_rejected_while_title_rights_not_cleared(self, api, rights_status):
        """PRD §3.6: "Only `OWNED_CLEARED` permits a window on that title to be
        cleared; `PENDING_CLEARANCE`, `THIRD_PARTY_LICENSED` and `EXPIRED_RIGHTS`
        all block clearance with `ERR_TITLE_RIGHTS_NOT_CLEARED`."
        PRD §3.6: "The new window opens in `PLANNED` with `block_reason` of
        `NONE`, `concurrent_licensee_count` of 0 and `version` 1."
        PRD §3.6: "A newly registered title opens with `rights_status` of
        `PENDING_CLEARANCE`, `cleared_window_count` of 0,
        `distribution_coverage_status` of `UNDISTRIBUTED` and `version` 1."

        Design: Difficulty/cross_entity_state_dependency/window_clear_blocked_by_title_rights_status
        """
        distributor, agreement = setup_executed_agreement()
        title = register_title(
            rights_status=None if rights_status == "PENDING_CLEARANCE" else rights_status,
            linear_premiere_at="2026-08-15T00:00:00Z",
        )
        assert title["rights_status"] == rights_status, (
            f"the title must sit at {rights_status}, got {title['rights_status']!r}"
        )
        window = plan_window(
            agreement["id"],
            title["id"],
            platform="STREAMING",
            territory_code="US",
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-30T00:00:00Z",
            exclusivity="EXCLUSIVE",
        )
        assert window["status"] == "PLANNED", (
            f"the window must be PLANNED, got {window['status']!r}"
        )

        response = api.rights_window_lifecycle(window["id"], {"action": "CLEAR"}, RIGHTS)
        validate_error(response, "ERR_TITLE_RIGHTS_NOT_CLEARED", 409)

        after_window = fetch_window(window["id"])
        assert after_window["status"] == "PLANNED", (
            f"the refused clearance leaves the window PLANNED, got {after_window['status']!r}"
        )
        assert after_window["block_reason"] == "NONE", (
            f"block_reason stays NONE, got {after_window['block_reason']!r}"
        )
        after_title = fetch_title(title["id"])
        assert after_title["cleared_window_count"] == 0, (
            f"no window cleared, got cleared_window_count {after_title['cleared_window_count']}"
        )
        assert after_title["distribution_coverage_status"] == "UNDISTRIBUTED", (
            "an empty occupying set is UNDISTRIBUTED, got "
            f"{after_title['distribution_coverage_status']!r}"
        )

    def test_clear_window_succeeds_once_title_marked_owned_cleared(self, api):
        """PRD §3.6: "Only `OWNED_CLEARED` permits a window on that title to be
        cleared; `PENDING_CLEARANCE`, `THIRD_PARTY_LICENSED` and `EXPIRED_RIGHTS`
        all block clearance with `ERR_TITLE_RIGHTS_NOT_CLEARED`."
        PRD §3.6: "Either way, a window that clears successfully has
        `concurrent_licensee_count` stamped with the number of neighbours found —
        not including itself."
        PRD §3.6: "Its `windowing_holdback_days` is stamped immediately, as the
        whole number of days from the title's `linear_premiere_at` to the window's
        `window_start`, discarding any fraction; a window that opens before the
        linear premiere therefore carries a negative holdback."
        PRD §3.6: "Clearing a window moves it `PLANNED → CLEARED`, increments the
        title's `cleared_window_count` by one and re-derives
        `distribution_coverage_status`."
        PRD §3.6: "`distribution_coverage_status` is derived from the *set of
        distinct platforms* among exactly those windows, by a pinned ladder
        evaluated top to bottom and stopping at the first arm that matches: if the
        set is empty the status is `UNDISTRIBUTED`; otherwise if the set is
        exactly `LINEAR` and nothing else the status is `LINEAR_ONLY`; otherwise
        if the set holds two or more distinct platforms the status is
        `MULTIPLATFORM`; otherwise the set holds exactly one platform which is not
        `LINEAR`, and the status is `EXCLUSIVE_UNCLEARED`, meaning a downstream
        platform is cleared while the linear window that is supposed to precede it
        is not."

        Design: Difficulty/cross_entity_state_dependency/window_clear_blocked_by_title_rights_status
        """
        distributor, agreement = setup_executed_agreement()
        title = register_title(
            rights_status="THIRD_PARTY_LICENSED",
            linear_premiere_at="2026-08-15T00:00:00Z",
        )
        window = plan_window(
            agreement["id"],
            title["id"],
            platform="STREAMING",
            territory_code="US",
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-30T00:00:00Z",
            exclusivity="EXCLUSIVE",
        )
        refused = api.rights_window_lifecycle(window["id"], {"action": "CLEAR"}, RIGHTS)
        validate_error(refused, "ERR_TITLE_RIGHTS_NOT_CLEARED", 409)

        cleared_title = set_title_rights(title["id"], "OWNED_CLEARED")
        assert cleared_title["rights_status"] == "OWNED_CLEARED", (
            f"the title must now be OWNED_CLEARED, got {cleared_title['rights_status']!r}"
        )

        response = api.rights_window_lifecycle(window["id"], {"action": "CLEAR"}, RIGHTS)
        data = validate_success(response, 200)
        assert data["status"] == "CLEARED", (
            f"the identical call now clears the window, got {data['status']!r}"
        )
        assert data["concurrent_licensee_count"] == 0, (
            "the window is the only occupant of its key, so no neighbours are "
            f"counted, got {data['concurrent_licensee_count']}"
        )
        assert data["windowing_holdback_days"] == 17, (
            "2026-08-15 premiere to a 2026-09-01 start is 17 whole days, got "
            f"{data['windowing_holdback_days']}"
        )

        after_title = fetch_title(title["id"])
        assert after_title["cleared_window_count"] == 1, (
            f"clearance increments the count to 1, got {after_title['cleared_window_count']}"
        )
        assert after_title["distribution_coverage_status"] == "EXCLUSIVE_UNCLEARED", (
            "a single non-LINEAR occupying platform reads EXCLUSIVE_UNCLEARED, got "
            f"{after_title['distribution_coverage_status']!r}"
        )
