"""Positive-pay settlement, the mismatch fraud chain, sanctions dispositions,
and the suspend/reinstate hold conservation."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_timestamp_equals,
    set_clock,
    create_matrix_rule,
    onboard_vendor_to_active,
    add_verified_primary_bank_account,
    get_vendor,
    create_invoice,
    submit_invoice,
    approve_invoice_fully,
    create_approved_invoice,
    get_invoice,
    create_payment_run,
    get_payment_run,
    get_payment,
    add_invoice_to_run_ok,
    compile_run,
    approve_run,
    release_run,
    create_watchlist_entry,
    list_open_cases_for_vendor,
    suspend_vendor,
    reinstate_vendor,
)

VS1 = TEST_USERS["vendor_specialist_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CLERK = TEST_USERS["ap_clerk_headers"]
SUP1 = TEST_USERS["ap_supervisor_headers"]
TA = TEST_USERS["treasury_analyst_headers"]
TM1 = TEST_USERS["treasury_manager_headers"]
BFP = TEST_USERS["bank_file_processor_headers"]
AUD = TEST_USERS["auditor_headers"]


def _released_run_with_invoices(api, amounts, legal_name, tax_id,
                                invoice_prefix="INV"):
    """Aged payable vendor; one APPROVED invoice per amount; run compiled,
    approved, released. Returns (vendor, account, invoices, run, payments)."""
    set_clock("2026-06-01T00:00:00Z")
    create_matrix_rule()
    vendor = onboard_vendor_to_active(legal_name=legal_name, tax_id=tax_id)
    account = add_verified_primary_bank_account(
        vendor["id"], account_holder_name=legal_name)
    set_clock("2026-08-01T00:00:00Z")
    invoices = []
    for i, amount in enumerate(amounts, start=1):
        invoices.append(create_approved_invoice(
            vendor["id"], amount_cents=amount,
            invoice_number=f"{invoice_prefix}-{i}", received_date="2026-08-01"))
    run = create_payment_run(scheduled_date="2026-08-05")
    payments = [add_invoice_to_run_ok(run["id"], inv["id"]) for inv in invoices]
    compile_run(run["id"])
    approve_run(run["id"])
    release_run(run["id"])
    return get_vendor(vendor["id"]), account, invoices, get_payment_run(run["id"]), payments


class TestConfirmedHitBlockCascade:
    def _cascade_scenario(self, api):
        """Vendor ACTIVE with inv1 IN_PAYMENT_RUN (payment PENDING, run
        APPROVED), inv2 PENDING_APPROVAL, inv3 APPROVED; a REVIEW watchlist
        entry matching the new legal name exists."""
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule()
        vendor = onboard_vendor_to_active(
            legal_name="Cascade Holdings", tax_id="10-0000006")
        add_verified_primary_bank_account(
            vendor["id"], account_holder_name="Cascade Holdings")
        set_clock("2026-08-01T00:00:00Z")

        inv1 = create_approved_invoice(vendor["id"], amount_cents=100000,
                                       invoice_number="INV-8801",
                                       received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-05")
        pay1 = add_invoice_to_run_ok(run["id"], inv1["id"])
        compile_run(run["id"])
        approve_run(run["id"])

        inv2 = create_invoice(vendor["id"], amount_cents=200000,
                              invoice_number="INV-8802", received_date="2026-08-01")
        submit_invoice(inv2["id"])
        inv3 = create_approved_invoice(vendor["id"], amount_cents=50000,
                                       invoice_number="INV-8803",
                                       received_date="2026-08-01")

        create_watchlist_entry("Cascade Holding", severity="REVIEW")
        return vendor, inv1, inv2, inv3, run, pay1

    def test_name_patch_review_suspends_and_holds(self, api):
        """A legal_name edit while ACTIVE re-runs screening; REVIEW suspends the
        vendor, opens a SETUP_SCREENING case, and holds the actionable invoices
        (IN_PAYMENT_RUN untouched by a plain suspend).

        PRD §3.4: "Editing `legal_name` while the vendor is `ACTIVE` or `SUSPENDED` re-runs the setup variant of sanctions screening against the current watchlist: a `CLEAR` leaves the vendor untouched; a `REVIEW` suspends an `ACTIVE` vendor and opens a review case; a `HIT` blocks the vendor outright and fires the ordered block cascade described in §3.2."
        PRD §3.4: "The vendor moves from `ACTIVE` to `SUSPENDED`, and the hold cascade freezes its open approval pipeline: every invoice of this vendor in `PENDING_APPROVAL` or `APPROVED` moves to `ON_HOLD` with its former status recorded in `pre_hold_status`, while an invoice already `ON_HOLD` keeps its original `pre_hold_status`."
        PRD §3.4: "A plain suspension does not touch invoices in `IN_PAYMENT_RUN`."

        Design: Difficulty/transitive_cascade/confirmed_hit_depth4_block_cascade
        """
        vendor, inv1, inv2, inv3, _run, _pay1 = self._cascade_scenario(api)
        patched = validate_success(api.patch_vendor(vendor["id"], {
            "legal_name": "Cascade Holding",
            "expected_vendor_version": get_vendor(vendor["id"])["version"]}, VS1))
        assert patched["status"] == "SUSPENDED"

        cases = list_open_cases_for_vendor(vendor["id"])
        assert len(cases) == 1
        assert cases[0]["opened_reason"] == "SETUP_SCREENING"

        held2 = get_invoice(inv2["id"])
        assert held2["status"] == "ON_HOLD"
        assert held2["pre_hold_status"] == "PENDING_APPROVAL"
        held3 = get_invoice(inv3["id"])
        assert held3["status"] == "ON_HOLD"
        assert held3["pre_hold_status"] == "APPROVED"
        assert get_invoice(inv1["id"])["status"] == "IN_PAYMENT_RUN"

    def test_confirmed_hit_fires_ordered_block_cascade(self, api):
        """CONFIRMED_HIT: vendor BLOCKED -> IN_PAYMENT_RUN invoice held -> its
        PENDING payment voided (VENDOR_BLOCKED) -> run totals recomputed and
        the APPROVED run demoted to COMPILED.

        PRD §3.2: "A `decision` of `CONFIRMED_HIT` closes the case as `CONFIRMED_HIT` and drives the vendor from `SUSPENDED` to `BLOCKED`, firing the ordered block cascade: first, the vendor's invoices in `PENDING_APPROVAL` or `APPROVED`, plus any invoices in `IN_PAYMENT_RUN` whose payment is still `PENDING` because the run has not been released, move to `ON_HOLD` with their prior status recorded in `pre_hold_status` (an invoice already `ON_HOLD` keeps its original `pre_hold_status`); second, every payment whose invoice was just held out of `IN_PAYMENT_RUN` — all of them still `PENDING` by the first step's filter — is voided with `void_reason` `VENDOR_BLOCKED`; third, each affected run recomputes its totals, and a run sitting in `APPROVED` whose contents changed demotes itself to `COMPILED`."

        Design: Difficulty/transitive_cascade/confirmed_hit_depth4_block_cascade
        """
        vendor, inv1, _inv2, _inv3, run, pay1 = self._cascade_scenario(api)
        validate_success(api.patch_vendor(vendor["id"], {
            "legal_name": "Cascade Holding",
            "expected_vendor_version": get_vendor(vendor["id"])["version"]}, VS1))
        case = list_open_cases_for_vendor(vendor["id"])[0]

        dispositioned = validate_success(api.disposition_sanctions_case(
            case["id"], {"decision": "CONFIRMED_HIT",
                         "note": "exact principal match"}, CO))
        assert dispositioned["status"] == "CONFIRMED_HIT"

        assert get_vendor(vendor["id"])["status"] == "BLOCKED", "link 1"
        held1 = get_invoice(inv1["id"])
        assert held1["status"] == "ON_HOLD", "link 2"
        assert held1["pre_hold_status"] == "IN_PAYMENT_RUN"
        voided = get_payment(pay1["id"])
        assert voided["status"] == "VOIDED", "link 3"
        assert voided["void_reason"] == "VENDOR_BLOCKED"
        run_after = get_payment_run(run["id"])
        assert run_after["total_amount_cents"] == 0
        assert run_after["item_count"] == 0
        assert run_after["status"] == "COMPILED", \
            "link 4: content change demoted the APPROVED run"


class TestPositivePayMismatchChain:
    def _mismatch_scenario(self, api):
        """Vendor with two APPROVED invoices in a RELEASED run."""
        return _released_run_with_invoices(
            api, [100000, 150000], "Merkur Supply", "10-0000007",
            invoice_prefix="INV-99")

    def test_mismatch_voids_payment_and_suspends_vendor(self, api):
        """MISMATCH: payment VOIDED (POSITIVE_PAY_MISMATCH), its invoice ends
        ON_HOLD with pre_hold_status APPROVED, vendor SUSPENDED with
        fraud_hold_reason set.

        PRD §3.7: "The payment becomes `VOIDED` with `void_reason` `POSITIVE_PAY_MISMATCH`."
        PRD §3.7: "Second, the vendor moves from `ACTIVE` to `SUSPENDED` with its `fraud_hold_reason` set to `POSITIVE_PAY_MISMATCH`."
        PRD §3.7: "Third, the suspension's hold cascade catches the vendor's invoices in `PENDING_APPROVAL` or `APPROVED` — which now includes the invoice just reverted in the first step, so that invoice ends `ON_HOLD` with `pre_hold_status` recording `APPROVED`."

        Design: Difficulty/transitive_cascade/positive_pay_mismatch_depth3_fraud_chain
        """
        vendor, _account, invoices, run, payments = self._mismatch_scenario(api)
        pay_a, _pay_b = payments
        inv_a, _inv_b = invoices

        validate_success(api.submit_positive_pay_acks(run["id"], {
            "acks": [{"payment_id": pay_a["id"], "ack_result": "MISMATCH"}]}, BFP))

        voided = get_payment(pay_a["id"])
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "POSITIVE_PAY_MISMATCH"
        held = get_invoice(inv_a["id"])
        assert held["status"] == "ON_HOLD", \
            "reverted to APPROVED in step 1, then re-held by the step-3 cascade"
        assert held["pre_hold_status"] == "APPROVED"
        suspended = get_vendor(vendor["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["fraud_hold_reason"] == "POSITIVE_PAY_MISMATCH"
        assert get_payment_run(run["id"])["status"] == "RELEASED", \
            "the second payment is not yet terminal, so the run stays RELEASED"

    def test_match_after_mismatch_clears_and_closes_run(self, api):
        """The surviving payment acks MATCH: CLEARED, its invoice PAID, the run
        bubble-up closes it, and the vendor's dormancy reference is stamped.

        PRD §3.7: "A `MATCH` clears the payment: it moves from `RELEASED` to `CLEARED`, its invoice moves from `IN_PAYMENT_RUN` to `PAID`, the vendor's `last_payment_cleared_at` is stamped with the logical time and the vendor's `version` increments by one — this timestamp is the dormancy reference of §3.4 — and the run checks whether every payment it contains has reached a terminal state, closing itself from `RELEASED` to `CLOSED` when the last one lands."

        Design: Difficulty/transitive_cascade/positive_pay_mismatch_depth3_fraud_chain
        """
        vendor, _account, invoices, run, payments = self._mismatch_scenario(api)
        pay_a, pay_b = payments
        _inv_a, inv_b = invoices
        validate_success(api.submit_positive_pay_acks(run["id"], {
            "acks": [{"payment_id": pay_a["id"], "ack_result": "MISMATCH"}]}, BFP))
        validate_success(api.submit_positive_pay_acks(run["id"], {
            "acks": [{"payment_id": pay_b["id"], "ack_result": "MATCH"}]}, BFP))

        assert get_payment(pay_b["id"])["status"] == "CLEARED"
        assert get_invoice(inv_b["id"])["status"] == "PAID"
        assert get_payment_run(run["id"])["status"] == "CLOSED", \
            "every payment terminal -> run bubble-up closes"
        reloaded = get_vendor(vendor["id"])
        assert_timestamp_equals(reloaded["last_payment_cleared_at"],
                                "2026-08-01T00:00:00Z",
                                "stamped from the logical clock at the ack")


class TestPositivePaySettlement:
    def test_positive_pay_partial_ack_keeps_run_released(self, api):
        """Bubble-up is gated on ALL payments terminal: one of two acked leaves
        the run RELEASED; the second ack closes it.

        PRD §3.7: "A `MATCH` clears the payment: it moves from `RELEASED` to `CLEARED`, its invoice moves from `IN_PAYMENT_RUN` to `PAID`, the vendor's `last_payment_cleared_at` is stamped with the logical time and the vendor's `version` increments by one — this timestamp is the dormancy reference of §3.4 — and the run checks whether every payment it contains has reached a terminal state, closing itself from `RELEASED` to `CLOSED` when the last one lands."

        Design: Corner/endpoints/positive_pay_partial_ack_keeps_run_released
        """
        vendor, _account, invoices, run, payments = _released_run_with_invoices(
            api, [100000, 150000], "Partial Parts", "20-0000048",
            invoice_prefix="INV-90")
        pay1, pay2 = payments
        inv1, inv2 = invoices

        validate_success(api.submit_positive_pay_acks(run["id"], {
            "acks": [{"payment_id": pay1["id"], "ack_result": "MATCH"}]}, BFP))
        assert get_payment_run(run["id"])["status"] == "RELEASED", \
            "pay2 is not yet terminal"
        assert get_invoice(inv1["id"])["status"] == "PAID"
        assert get_invoice(inv2["id"])["status"] == "IN_PAYMENT_RUN"

        validate_success(api.submit_positive_pay_acks(run["id"], {
            "acks": [{"payment_id": pay2["id"], "ack_result": "MATCH"}]}, BFP))
        assert get_payment_run(run["id"])["status"] == "CLOSED"
        assert get_invoice(inv2["id"])["status"] == "PAID"
        reloaded = get_vendor(vendor["id"])
        assert_timestamp_equals(reloaded["last_payment_cleared_at"],
                                "2026-08-01T00:00:00Z")

    def test_double_ack_terminal_rejected(self, api):
        """A second ack for an already-CLEARED payment fails; the run is still
        RELEASED (a sibling payment is outstanding), so only the terminal-payment
        guard can fire, and the first ack's effects are not duplicated.

        PRD §3.7: "The run must be `RELEASED`, and each acked payment must still be `RELEASED`; an ack aimed at a payment already `CLEARED` or `VOIDED` is rejected with `ERR_PAYMENT_ALREADY_TERMINAL`."

        Design: Corner/validations/double_ack_terminal_rejected
        """
        vendor, _account, invoices, run, payments = _released_run_with_invoices(
            api, [100000, 150000], "Ack Ack Co", "20-0000044",
            invoice_prefix="INV-93")
        pay1, pay2 = payments
        inv1, _inv2 = invoices
        validate_success(api.submit_positive_pay_acks(run["id"], {
            "acks": [{"payment_id": pay1["id"], "ack_result": "MATCH"}]}, BFP))
        assert get_payment(pay1["id"])["status"] == "CLEARED"
        assert get_payment_run(run["id"])["status"] == "RELEASED"

        resp = api.submit_positive_pay_acks(run["id"], {
            "acks": [{"payment_id": pay1["id"], "ack_result": "MISMATCH"}]}, BFP)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_TERMINAL.value)
        assert get_payment(pay1["id"])["status"] == "CLEARED"
        assert get_invoice(inv1["id"])["status"] == "PAID"
        assert get_vendor(vendor["id"])["status"] == "ACTIVE", \
            "no phantom fraud cascade from the rejected ack"
        assert get_payment(pay2["id"])["status"] == "RELEASED"

    def test_payment_void_after_release_rejected(self, api):
        """Manual void exists only pre-release: a payment inside a RELEASED run
        is beyond manual void.

        PRD §3.7: "A `TreasuryAnalyst` may void a payment manually while it is still `PENDING` — a payment that is no longer `PENDING`, including one inside a `RELEASED`, `CLOSED`, or `VOIDED` run, yields `ERR_INVALID_STATE_TRANSITION` — which sets `void_reason` `MANUAL_REMOVED`, returns its invoice from `IN_PAYMENT_RUN` to `APPROVED`, recomputes the run totals, and demotes the run from `APPROVED` to `COMPILED` if that is where it sat."
        PRD §3.7: "Once a run is `RELEASED`, its payments are beyond manual void and resolve only through positive-pay acknowledgements."

        Design: Corner/state_machines/payment_void_after_release_rejected
        """
        _vendor, _account, invoices, run, payments = _released_run_with_invoices(
            api, [100000], "Late Lock", "20-0000014", invoice_prefix="INV-98")
        resp = api.void_payment(payments[0]["id"], TA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert get_payment(payments[0]["id"])["status"] == "RELEASED"
        assert get_invoice(invoices[0]["id"])["status"] == "IN_PAYMENT_RUN"


class TestHoldConservationAndSanctionsResolution:
    def _hold_pattern_scenario(self, api):
        """Vendor with inv1 PENDING_APPROVAL, inv2 APPROVED, inv3 RECEIVED."""
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule()
        vendor = onboard_vendor_to_active(
            legal_name="Hold Pattern", tax_id="10-0000015")
        inv1 = create_invoice(vendor["id"], amount_cents=100000,
                              invoice_number="INV-9201", received_date="2026-06-01")
        submit_invoice(inv1["id"])
        inv2 = create_approved_invoice(vendor["id"], amount_cents=200000,
                                       invoice_number="INV-9202",
                                       received_date="2026-06-01")
        inv3 = create_invoice(vendor["id"], amount_cents=300000,
                              invoice_number="INV-9203", received_date="2026-06-01")
        return vendor, inv1, inv2, inv3

    def test_suspend_parks_actionable_invoices(self, api):
        """Suspend parks PENDING_APPROVAL and APPROVED invoices ON_HOLD with
        their former status recorded; RECEIVED is untouched.

        PRD §3.4: "The vendor moves from `ACTIVE` to `SUSPENDED`, and the hold cascade freezes its open approval pipeline: every invoice of this vendor in `PENDING_APPROVAL` or `APPROVED` moves to `ON_HOLD` with its former status recorded in `pre_hold_status`, while an invoice already `ON_HOLD` keeps its original `pre_hold_status`."

        Design: Difficulty/compensating_invariant/vendor_actionable_invoice_set_suspend_reinstate_conserved
        """
        vendor, inv1, inv2, inv3 = self._hold_pattern_scenario(api)
        suspended = suspend_vendor(vendor["id"], reason="audit hold")
        assert suspended["status"] == "SUSPENDED"

        held1 = get_invoice(inv1["id"])
        assert held1["status"] == "ON_HOLD"
        assert held1["pre_hold_status"] == "PENDING_APPROVAL"
        held2 = get_invoice(inv2["id"])
        assert held2["status"] == "ON_HOLD"
        assert held2["pre_hold_status"] == "APPROVED"
        assert get_invoice(inv3["id"])["status"] == "RECEIVED"

    def test_reinstate_restores_actionable_invoice_multiset(self, api):
        """Reinstate restores the exact pre-suspend multiset with pre_hold_status
        cleared and the routing snapshot undisturbed.

        PRD §3.4: "Success fires the resume cascade: each of the vendor's `ON_HOLD` invoices returns to the status recorded in its `pre_hold_status`, and `pre_hold_status` is then cleared; a `STATUS_CHANGE` audit event records the return to `ACTIVE`."

        Design: Difficulty/compensating_invariant/vendor_actionable_invoice_set_suspend_reinstate_conserved
        """
        vendor, inv1, inv2, inv3 = self._hold_pattern_scenario(api)
        before = get_invoice(inv1["id"])
        round_before = before["approval_round"]
        tier_before = before["required_tier"]

        suspend_vendor(vendor["id"], reason="audit hold")
        reinstated = reinstate_vendor(vendor["id"])
        assert reinstated["status"] == "ACTIVE"

        restored1 = get_invoice(inv1["id"])
        assert restored1["status"] == "PENDING_APPROVAL"
        assert restored1["pre_hold_status"] is None
        assert restored1["approval_round"] == round_before
        assert restored1["required_tier"] == tier_before, \
            "the hold round-trip does not disturb the routing snapshot"
        restored2 = get_invoice(inv2["id"])
        assert restored2["status"] == "APPROVED"
        assert restored2["pre_hold_status"] is None
        assert get_invoice(inv3["id"])["status"] == "RECEIVED"

    def test_sanctions_case_cleared_reinstates_vendor_and_resumes_invoices(self, api):
        """Disposition CLEARED compensates the REVIEW suspend: vendor returns to
        ACTIVE and the held invoice resumes its recorded pre_hold_status.

        PRD §3.2: "A `decision` of `CLEARED` closes the case as `CLEARED`, and if the referenced vendor is `SUSPENDED` and has no other `OPEN` case, the vendor returns from `SUSPENDED` to `ACTIVE`, firing the resume cascade of §3.4."
        PRD §3.2: "Disposition belongs to the `ComplianceOfficer`, who supplies a `decision` and may attach an optional `note`, which is recorded on the case as `disposition_note`; the caller is recorded as `dispositioned_by_user_id`, and a `DISPOSITION` audit event is appended."

        Design: Corner/state_machines/sanctions_case_cleared_reinstates_vendor_and_resumes_invoices
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule()
        vendor = onboard_vendor_to_active(
            legal_name="Helion Trading", tax_id="20-0000018")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-9851",
                                 received_date="2026-06-01")
        submit_invoice(invoice["id"])

        create_watchlist_entry("Helion Trade", severity="REVIEW")
        validate_success(api.patch_vendor(vendor["id"], {
            "legal_name": "Helion Trade",
            "expected_vendor_version": get_vendor(vendor["id"])["version"]}, VS1))
        assert get_vendor(vendor["id"])["status"] == "SUSPENDED"
        case = list_open_cases_for_vendor(vendor["id"])[0]
        assert get_invoice(invoice["id"])["status"] == "ON_HOLD"

        dispositioned = validate_success(api.disposition_sanctions_case(
            case["id"], {"decision": "CLEARED", "note": "false positive"}, CO))
        assert dispositioned["status"] == "CLEARED"
        assert dispositioned["dispositioned_by_user_id"] == "u-co-01"
        assert get_vendor(vendor["id"])["status"] == "ACTIVE"
        resumed = get_invoice(invoice["id"])
        assert resumed["status"] == "PENDING_APPROVAL"
        assert resumed["pre_hold_status"] is None

    def test_reinstate_with_open_case_rejected(self, api):
        """Manual reinstate is blocked while the OPEN case that caused the
        suspension exists.

        PRD §3.4: "Reinstatement by a `VendorManager` moves a `SUSPENDED` vendor back to `ACTIVE`, but only while no sanctions review case in `OPEN` status references the vendor; otherwise the reinstatement is rejected with `ERR_VENDOR_HAS_OPEN_CASE`."

        Design: Corner/validations/reinstate_with_open_case_rejected
        """
        vendor = onboard_vendor_to_active(
            legal_name="Helion Trading 2", tax_id="20-0000041")
        create_watchlist_entry("Helion Trade 2", severity="REVIEW",
                               list_source="INTERNAL_FRAUD")
        validate_success(api.patch_vendor(vendor["id"], {
            "legal_name": "Helion Trade 2",
            "expected_vendor_version": get_vendor(vendor["id"])["version"]}, VS1))
        assert get_vendor(vendor["id"])["status"] == "SUSPENDED"

        resp = api.reinstate_vendor(vendor["id"], VM1)
        validate_error(resp, ApiErrorId.ERR_VENDOR_HAS_OPEN_CASE.value)
        assert get_vendor(vendor["id"])["status"] == "SUSPENDED"
