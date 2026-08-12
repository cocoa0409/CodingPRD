"""Reimbursement drawdowns: pinned rounding, funds boundary, SoD, and the correction loop
(PRD §2.10, §3.7, §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_reimbursement_request, assert_invoice, assert_money,
    create_drawdown_payload,
    file_invoice, verify_invoice, award_contract, create_contractor,
    create_drawdown, certify_drawdown, submit_drawdown, approve_drawdown,
    create_submitted_drawdown,
    setup_grant_with_contract, setup_grant_with_verified_invoice, request_closeout,
    make_contractor_headers, make_compliance_officer_headers,
    TEST_USERS, ApiErrorId, FINANCE_USER_ID, COMPLIANCE_USER_ID_2,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


class TestPerLineRounding:
    def _setup_three_equal_invoices(self):
        """ACTIVE grant (SMALL_HUB, 0.90); zero-retainage contract with three VERIFIED
        invoices of gross/net 33,333.33 each."""
        ctx = setup_grant_with_contract(awarded_value=200_000, dbe_goal_pct=12.50,
                                        retainage_pct=0.00)
        con_id = ctx["contract"]["id"]
        ctr_id = ctx["contractor"]["id"]
        invoices = []
        for number in ["INV-1", "INV-2", "INV-3"]:
            inv = file_invoice(con_id, ctr_id, invoice_number=number,
                               gross_amount=33_333.33)
            invoices.append(verify_invoice(inv["id"]))
        return ctx, invoices

    def test_drawdown_per_line_rounding_totals(self):
        """PRD §3.7: "`federal_amount` instead uses a pinned per-line rounding order: for
        each invoice, `net_payable` is multiplied by the grant's `federal_share_pct` and
        rounded half-up to two decimal places, and those rounded line amounts are then summed
        exactly."
        PRD §3.7: "for example, three invoices with a net of 33333.33 each under a
        ninety-percent share yield 90000.00 under the pinned per-line order but 89999.99
        under the rejected sum-first order."

        Design: Difficulty/combinatorial_formula/drawdown_per_line_rounding
        """
        ctx, invoices = self._setup_three_equal_invoices()
        drawdown = validate_success(api_client.create_drawdown(
            create_drawdown_payload(ctx["grant"]["id"], [i["id"] for i in invoices]),
            FINANCE), 201)
        assert_reimbursement_request(drawdown)
        assert_money(drawdown["total_net"], 99_999.99, "total_net")
        assert_money(drawdown["federal_amount"], 90_000.00, "federal_amount")
        # The pinned per-line order is what separates 90,000.00 from 89,999.99.
        assert drawdown["federal_amount"] != pytest.approx(89_999.99, abs=0.005)

    def test_drawdown_per_line_rounding_inclusion(self):
        """PRD §3.7: "On creation, each listed invoice moves from `VERIFIED` to `INCLUDED`
        and has its `drawdown_id` set to the new request's identifier".

        Design: Difficulty/combinatorial_formula/drawdown_per_line_rounding
        """
        ctx, invoices = self._setup_three_equal_invoices()
        drawdown = create_drawdown(ctx["grant"]["id"], [i["id"] for i in invoices])
        for invoice in invoices:
            after = validate_success(api_client.get_invoice(invoice["id"], SPONSOR), 200)
            assert after["status"] == "INCLUDED"
            assert after["drawdown_id"] == drawdown["id"]


class TestFederalFundsBoundary:
    def _setup_grant_with_available_819000(self):
        """ACTIVE grant with one APPROVED drawdown of 81,000.00, leaving
        federal_available exactly 819,000.00."""
        ctx = setup_grant_with_verified_invoice()
        approve_drawdown(
            create_submitted_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]])["id"])
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        assert_money(grant["federal_available"], 819_000.00, "federal_available")
        return ctx

    def test_drawdown_exact_remaining_funds_approved(self):
        """PRD §3.7: "and the request's `federal_amount` must not exceed the grant's
        `federal_available`, with exact equality allowed (otherwise
        `ERR_FEDERAL_FUNDS_INSUFFICIENT`, HTTP 402)."
        PRD §3.7: "On approval the request reaches its terminal `APPROVED` status, the
        grant's `federal_drawn` increases by `federal_amount` with `federal_available`
        recomputed".

        Design: Difficulty/boundary_precision_check/drawdown_exact_remaining_funds
        """
        ctx = self._setup_grant_with_available_819000()
        con2 = award_contract(ctx["grant"]["id"], ctx["project"]["id"],
                              ctx["contractor"]["id"], awarded_value=2_000_000,
                              dbe_goal_pct=0.00, retainage_pct=0.00)
        inv = file_invoice(con2["id"], ctx["contractor"]["id"],
                           invoice_number="INV-EXACT", period="2026-06",
                           gross_amount=910_000.00)
        verify_invoice(inv["id"])
        drawdown = create_drawdown(ctx["grant"]["id"], [inv["id"]])
        assert_money(drawdown["federal_amount"], 819_000.00, "federal_amount")
        certify_drawdown(drawdown["id"])
        submitted = submit_drawdown(drawdown["id"])
        assert submitted["status"] == "SUBMITTED"
        approved = approve_drawdown(drawdown["id"])
        assert approved["status"] == "APPROVED"
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        assert_money(grant["federal_drawn"], 900_000.00, "federal_drawn")
        assert_money(grant["federal_available"], 0.00, "federal_available")

    def test_drawdown_over_remaining_funds_rejected(self):
        """PRD §3.7: "and the request's `federal_amount` must not exceed the grant's
        `federal_available`, with exact equality allowed (otherwise
        `ERR_FEDERAL_FUNDS_INSUFFICIENT`, HTTP 402)."
        819,000.02 exceeds the remaining 819,000.00 by two cents.

        Design: Difficulty/boundary_precision_check/drawdown_exact_remaining_funds
        """
        ctx = self._setup_grant_with_available_819000()
        con2 = award_contract(ctx["grant"]["id"], ctx["project"]["id"],
                              ctx["contractor"]["id"], awarded_value=2_000_000,
                              dbe_goal_pct=0.00, retainage_pct=0.00)
        inv = file_invoice(con2["id"], ctx["contractor"]["id"],
                           invoice_number="INV-OVER", period="2026-06",
                           gross_amount=910_000.02)
        verify_invoice(inv["id"])
        drawdown = create_drawdown(ctx["grant"]["id"], [inv["id"]])
        assert_money(drawdown["federal_amount"], 819_000.02, "federal_amount")
        certify_drawdown(drawdown["id"])
        res = api_client.submit_drawdown(drawdown["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_FEDERAL_FUNDS_INSUFFICIENT, expected_status=402)


class TestDrawdownCorrectionLoop:
    def test_drawdown_return_clears_certifier(self):
        """PRD §3.7: "Alternatively, the `FAAManager` may return a submitted request for
        correction: the request moves back from `SUBMITTED` to `DRAFT`, and its
        `certified_by_user_id` is cleared to null, forcing re-certification before it can be
        submitted again."

        Design: Difficulty/non_linear_state_machine/drawdown_return_correction_cycle
        """
        ctx = setup_grant_with_verified_invoice()
        drawdown = create_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]])
        certify_drawdown(drawdown["id"])
        submit_drawdown(drawdown["id"])
        returned = validate_success(api_client.return_drawdown(drawdown["id"], FAA), 200)
        assert returned["status"] == "DRAFT"
        assert returned["certified_by_user_id"] is None

    def test_drawdown_return_correction_loop_resubmits(self):
        """PRD §3.7: "the request moves back from `SUBMITTED` to `DRAFT`, and its
        `certified_by_user_id` is cleared to null, forcing re-certification before it can be
        submitted again."
        The invoice stays INCLUDED throughout the loop (no rule moves it back).

        Design: Difficulty/non_linear_state_machine/drawdown_return_correction_cycle
        """
        ctx = setup_grant_with_verified_invoice()
        drawdown = create_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]])
        certify_drawdown(drawdown["id"])
        submit_drawdown(drawdown["id"])
        validate_success(api_client.return_drawdown(drawdown["id"], FAA), 200)
        invoice = validate_success(
            api_client.get_invoice(ctx["invoice"]["id"], SPONSOR), 200)
        assert invoice["status"] == "INCLUDED"

        certify_drawdown(drawdown["id"])  # second certification after the return
        resubmitted = submit_drawdown(drawdown["id"])
        assert resubmitted["status"] == "SUBMITTED"
        invoice = validate_success(
            api_client.get_invoice(ctx["invoice"]["id"], SPONSOR), 200)
        assert invoice["status"] == "INCLUDED"


class TestDrawdownGuards:
    def test_drawdown_submit_from_draft_rejected(self):
        """PRD §3.7: "Submission is then the `FinanceOfficer`'s action, moving `CERTIFIED` to
        `SUBMITTED`" — a DRAFT drawdown cannot skip the certification step.
        PRD §2.9: "state preconditions for the requested transition (generic failures carry
        `ERR_INVALID_STATE`, HTTP 409, while specific ones carry their dedicated codes)".

        Design: Corner/state_machines/drawdown_submit_from_draft_rejected
        """
        ctx = setup_grant_with_verified_invoice()
        drawdown = create_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]])
        res = api_client.submit_drawdown(drawdown["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api_client.get_drawdown(drawdown["id"], SPONSOR), 200)
        assert after["status"] == "DRAFT"

    def test_drawdown_over_unverified_invoice_rejected(self):
        """PRD §3.7: "every listed invoice must currently be `VERIFIED` and belong to a
        contract of the named grant, otherwise the creation is rejected with
        `ERR_INVOICE_NOT_VERIFIABLE` (HTTP 422)."

        Design: Corner/validations/drawdown_over_unverified_invoice_rejected
        """
        ctx = setup_grant_with_contract()
        invoice = file_invoice(ctx["contract"]["id"], ctx["contractor"]["id"])  # SUBMITTED
        res = api_client.create_drawdown(
            create_drawdown_payload(ctx["grant"]["id"], [invoice["id"]]), FINANCE)
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_VERIFIABLE, expected_status=422)
        after = validate_success(api_client.get_invoice(invoice["id"], SPONSOR), 200)
        assert after["status"] == "SUBMITTED"

    def test_drawdown_self_certify_rejected(self):
        """PRD §3.7: "an officer whose `X-User-ID` equals `prepared_by_user_id` is refused
        with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/validations/drawdown_self_certify_rejected
        """
        ctx = setup_grant_with_verified_invoice()
        # Prepared by operator user-fin-1.
        drawdown = create_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]],
                                   preparer_user_id=FINANCE_USER_ID)
        res = api_client.certify_drawdown(
            drawdown["id"], make_compliance_officer_headers(FINANCE_USER_ID))
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

        certified = certify_drawdown(drawdown["id"],
                                     certifier_user_id=COMPLIANCE_USER_ID_2)
        assert certified["status"] == "CERTIFIED"

    def test_drawdown_approve_immediately_visible(self):
        """PRD §3.7: "On approval the request reaches its terminal `APPROVED` status, the
        grant's `federal_drawn` increases by `federal_amount` with `federal_available`
        recomputed, every included invoice moves from `INCLUDED` to `PAID`, and the grant's
        `version` increments by one."

        Design: Corner/consistency_model/drawdown_approve_immediately_visible
        """
        ctx = setup_grant_with_verified_invoice()
        drawdown = create_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]])
        certify_drawdown(drawdown["id"])
        submit_drawdown(drawdown["id"])
        approved = approve_drawdown(drawdown["id"])
        assert approved["status"] == "APPROVED"

        # The immediate follow-up reads already reflect the new ledger.
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        assert_money(grant["federal_drawn"], 81_000.00, "federal_drawn")
        assert_money(grant["federal_available"], 819_000.00, "federal_available")
        invoice = validate_success(
            api_client.get_invoice(ctx["invoice"]["id"], SPONSOR), 200)
        assert invoice["status"] == "PAID"

    def test_closeout_blocked_by_pending_drawdown(self):
        """PRD §3.9: "no reimbursement request of the grant may remain in `DRAFT`,
        `CERTIFIED`, or `SUBMITTED`, and no construction phase of the grant may remain in
        `PLANNED` or `ACTIVE` — with either blockage rejected as `ERR_CLOSEOUT_BLOCKED`
        (HTTP 422)."

        Design: Corner/validations/closeout_blocked_by_pending_drawdown
        """
        ctx = setup_grant_with_verified_invoice()
        create_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]])  # DRAFT drawdown
        res = api_client.request_closeout(ctx["grant"]["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_CLOSEOUT_BLOCKED, expected_status=422)
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        assert grant["status"] == "ACTIVE"
