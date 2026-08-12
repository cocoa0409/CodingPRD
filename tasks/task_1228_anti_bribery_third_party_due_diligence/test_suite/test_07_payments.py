"""Payments: ratio computation, country-blended caps, SoD, ledger invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    FINANCE_1_ID,
    FINANCE_2_ID,
    SPONSOR_1_ID,
    approve_payment,
    create_payment,
    create_verified_certification,
    create_draft_contract,
    finance_headers,
    get_third_party,
    officer_headers,
    set_clock,
    setup_active_contract,
    setup_approved_with_active_contract,
    setup_third_party_in_state,
    sponsor_headers,
    validate_error,
    validate_success,
)


def _ng_active_contract(api, value_cents=1000000):
    """NG cpi 25 -> country_norm 75 -> multiplier 0.60 -> effective cap 9.00,
    hard cap 25.00; MEDIUM third party, ACTIVE contract, VERIFIED cert."""
    ctx = setup_approved_with_active_contract("NG", 25, "TECHNOLOGY", "NONE",
                                              value_cents=value_cents)
    return ctx


class TestFlatVsBlendedBenchmark:
    """A 12.00% commission in a country_norm >= 70 country: the naive flat cap
    (15.00) would approve it; the pinned blended cap (15.00 x 0.60 = 9.00)
    makes it evidence-required."""

    def test_ratio_pct_computed_at_creation(self, api):
        """PRD §3.7: "Creation requires the contract to be `ACTIVE`
        (`ERR_CONTRACT_NOT_ACTIVE`), stamps `submitted_by_user_id` from the
        caller, sets `payment_status` to `SUBMITTED`, and computes `ratio_pct` at
        creation: multiply the amount in cents by 10000, divide by the contract's
        `contract_value_cents`, round half-up to the nearest integer, then divide
        by 100 — yielding the payment's two-decimal percentage of contract
        value."

        Design: Difficulty/dual_variant_calc/commission_flat_vs_blended_benchmark_on_payment
        """
        ctx = _ng_active_contract(api)
        pay = create_payment(ctx["contract"]["id"], amount_cents=120000)
        # round_half_up(120000 * 10000 / 1000000) / 100 = 12.00
        assert pay["ratio_pct"] == pytest.approx(12.0, abs=0.001)
        assert pay["payment_status"] == "SUBMITTED"
        assert pay["submitted_by_user_id"] == SPONSOR_1_ID

    def test_blended_cap_forces_evidence_required(self, api, finance_headers):
        """PRD §3.7: "Reasonableness is judged at approval time by the
        country-blended cap, with a pinned evaluation order: the ratio being
        tested is computed first; then `country_norm` for the party's country;
        then a multiplier of 0.60 when `country_norm` is 70 or higher, 0.80 when
        `country_norm` is between 40 and 69 inclusive, and 1.00 when
        `country_norm` is below 40; then the `effective_cap_pct`, which is the
        policy's `commission_base_cap_pct` multiplied by that multiplier and
        carried as an exact two-decimal value."
        PRD §3.7: "a `ratio_pct` greater than `effective_cap_pct` but not greater
        than the hard cap is approvable only with evidence, so approval without
        `enhanced_review_evidence` set to true fails with
        `ERR_ENHANCED_REVIEW_REQUIRED`"
        PRD §3.7: "Applying the base cap flat, without the country multiplier, is
        a known misreading and is non-conformant: the blended cap is the
        production rule."

        Design: Difficulty/dual_variant_calc/commission_flat_vs_blended_benchmark_on_payment
        """
        ctx = _ng_active_contract(api)
        pay = create_payment(ctx["contract"]["id"], amount_cents=120000)

        resp = api.approve_payment(pay["id"], finance_headers)
        # effective cap 15.00 x 0.60 = 9.00; 9.00 < 12.00 <= 25.00.
        validate_error(resp, ApiErrorId.ERR_ENHANCED_REVIEW_REQUIRED)

        payments = validate_success(
            api.list_payment_requests(ctx["contract"]["id"], finance_headers), 200)
        assert payments[0]["payment_status"] == "SUBMITTED", "rejection leaves it SUBMITTED"


class TestBracketEvaluationOrder:
    """Three requests on one contract land in the three different brackets."""

    def _setup_three_payments(self, api):
        ctx = _ng_active_contract(api)
        ct_id = ctx["contract"]["id"]
        pay_a = create_payment(ct_id, amount_cents=90000)    # ratio 9.00
        pay_b = create_payment(ct_id, amount_cents=120000)   # ratio 12.00
        pay_c = create_payment(ct_id, amount_cents=260000,   # ratio 26.00
                               enhanced_review_evidence=True)
        return ctx, ct_id, pay_a, pay_b, pay_c

    def test_ratio_at_effective_cap_boundary_approvable(self, api, finance_headers):
        """PRD §3.7: "and a `ratio_pct` at or below `effective_cap_pct` — the
        boundary is inclusive — is approvable outright."
        PRD §3.7: "Approval stamps `approved_by_user_id` from the reviewer and
        adds the `amount_cents` into the contract's
        `approved_payments_total_cents` ledger."

        Design: Difficulty/combinatorial_formula/commission_ratio_bracket_evaluation_order
        """
        _, ct_id, pay_a, _, _ = self._setup_three_payments(api)
        approved = approve_payment(pay_a["id"], FINANCE_1_ID)
        # ratio 9.00 <= effective cap 9.00 (inclusive boundary).
        assert approved["payment_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == FINANCE_1_ID

        contract = validate_success(api.get_contract(ct_id, finance_headers), 200)
        assert contract["approved_payments_total_cents"] == 90000

    def test_evidence_band_and_hard_cap_rejections(self, api, finance_headers):
        """PRD §3.7: "The bracket verdict follows: a `ratio_pct` strictly greater
        than `commission_hard_cap_pct` can never be approved, and any attempt
        fails with `ERR_COMMISSION_CAP_EXCEEDED`; a `ratio_pct` greater than
        `effective_cap_pct` but not greater than the hard cap is approvable only
        with evidence, so approval without `enhanced_review_evidence` set to true
        fails with `ERR_ENHANCED_REVIEW_REQUIRED`"

        Design: Difficulty/combinatorial_formula/commission_ratio_bracket_evaluation_order
        """
        _, _, _, pay_b, pay_c = self._setup_three_payments(api)

        resp_b = api.approve_payment(pay_b["id"], finance_headers)
        # 9.00 < 12.00 <= 25.00: evidence-required band, no evidence supplied.
        validate_error(resp_b, ApiErrorId.ERR_ENHANCED_REVIEW_REQUIRED)

        resp_c = api.approve_payment(pay_c["id"], finance_headers)
        # 26.00 > 25.00: blocked outright even though evidence was attached.
        validate_error(resp_c, ApiErrorId.ERR_COMMISSION_CAP_EXCEEDED)


class TestPaymentCreateGate:
    def test_payment_create_requires_contract_active(self, api, sponsor_headers):
        """PRD §3.7: "Creation requires the contract to be `ACTIVE`
        (`ERR_CONTRACT_NOT_ACTIVE`), stamps `submitted_by_user_id` from the
        caller, sets `payment_status` to `SUBMITTED`, and computes `ratio_pct` at
        creation"

        Design: Difficulty/cross_entity_state_dependency/payment_create_requires_contract_active
        """
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        contract = create_draft_contract(tp_id, SPONSOR_1_ID, 500000)

        resp = api.create_payment_request(
            contract["id"], {"payment_type": "COMMISSION", "amount_cents": 50000},
            sponsor_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_payment_create_succeeds_once_contract_active(self, api, sponsor_headers):
        """PRD §3.7: "Creation requires the contract to be `ACTIVE`
        (`ERR_CONTRACT_NOT_ACTIVE`), stamps `submitted_by_user_id` from the
        caller, sets `payment_status` to `SUBMITTED`, and computes `ratio_pct` at
        creation: multiply the amount in cents by 10000, divide by the contract's
        `contract_value_cents`, round half-up to the nearest integer, then divide
        by 100 — yielding the payment's two-decimal percentage of contract
        value."

        Design: Difficulty/cross_entity_state_dependency/payment_create_requires_contract_active
        """
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        contract = setup_active_contract(tp_id, SPONSOR_1_ID, value_cents=500000)

        resp = api.create_payment_request(
            contract["id"], {"payment_type": "COMMISSION", "amount_cents": 50000},
            sponsor_headers)
        pay = validate_success(resp, 201)
        assert pay["payment_status"] == "SUBMITTED"
        assert pay["ratio_pct"] == pytest.approx(10.0, abs=0.001)


class TestReverseRestoresLedger:
    def _setup_two_approved_payments(self, api):
        """CH (norm 20 -> multiplier 1.00 -> effective cap 15.00): 9.00 and 4.00
        both pass; ledger after two approvals is 130000."""
        ctx = setup_approved_with_active_contract("CH", 80, "TECHNOLOGY", "NONE",
                                                  value_cents=1000000)
        ct_id = ctx["contract"]["id"]
        p1 = create_payment(ct_id, amount_cents=90000)
        p2 = create_payment(ct_id, amount_cents=40000)
        approve_payment(p1["id"], FINANCE_1_ID)
        approve_payment(p2["id"], FINANCE_1_ID)
        return ctx, ct_id, p1, p2

    def test_reverse_compensates_ledger_exactly(self, api, finance2_headers):
        """PRD §3.7: "Reversal moves an `APPROVED` payment to `REVERSED`,
        requires the reverser to differ from the recorded `approved_by_user_id`
        (`ERR_SOD_VIOLATION`) so no reviewer unwinds their own approval, and
        subtracts the `amount_cents` back out of the ledger. The ledger is a
        compensating invariant: it always equals the sum of approved amounts
        minus the sum of reversed amounts, and it never goes negative."

        Design: Difficulty/compensating_invariant/payment_reverse_restores_contract_ledger
        """
        _, ct_id, p1, _ = self._setup_two_approved_payments(api)
        before = validate_success(api.get_contract(ct_id, finance2_headers), 200)
        assert before["approved_payments_total_cents"] == 130000

        validate_success(
            api.reverse_payment(p1["id"], {"reason": "duplicate invoice"},
                                finance2_headers), 200)
        after = validate_success(api.get_contract(ct_id, finance2_headers), 200)
        assert after["approved_payments_total_cents"] == 40000, (
            "130000 - 90000: the reversal compensates the approval exactly"
        )

    def test_reverse_marks_only_the_reversed_payment(self, api, finance_headers,
                                                     finance2_headers):
        """PRD §3.7: "Reversal moves an `APPROVED` payment to `REVERSED`,
        requires the reverser to differ from the recorded `approved_by_user_id`
        (`ERR_SOD_VIOLATION`) so no reviewer unwinds their own approval, and
        subtracts the `amount_cents` back out of the ledger. The ledger is a
        compensating invariant: it always equals the sum of approved amounts
        minus the sum of reversed amounts, and it never goes negative."

        Design: Difficulty/compensating_invariant/payment_reverse_restores_contract_ledger
        """
        _, ct_id, p1, p2 = self._setup_two_approved_payments(api)
        reversed_pay = validate_success(
            api.reverse_payment(p1["id"], {"reason": "duplicate invoice"},
                                finance2_headers), 200)
        assert reversed_pay["payment_status"] == "REVERSED"

        payments = validate_success(api.list_payment_requests(ct_id, finance_headers), 200)
        by_id = {p["id"]: p for p in payments}
        assert by_id[p1["id"]]["payment_status"] == "REVERSED"
        assert by_id[p2["id"]]["payment_status"] == "APPROVED"


class TestStateErrorBeatsFiscalCap:
    """A BLOCKED (terminal) payment whose ratio also exceeds the hard cap must
    report the terminal-state error, not the fiscal one."""

    def _setup_blocked_over_cap_payment(self, api):
        ctx = _ng_active_contract(api)
        ct_id = ctx["contract"]["id"]
        pay = create_payment(ct_id, amount_cents=260000)  # ratio 26.00 > 25.00
        validate_success(
            api.block_payment(pay["id"], {"reason": "ratio over hard cap"},
                              finance_headers(FINANCE_1_ID)), 200)
        return ctx, ct_id, pay

    def test_approve_blocked_payment_returns_already_terminal(self, api):
        """PRD §2.9: "Fifth, state-machine legality: within this tier the
        terminal-state check is evaluated first and takes precedence, so an
        action against an entity already in a terminal state reports
        `ERR_ALREADY_TERMINAL`, and only otherwise does an illegal from-state
        report `ERR_INVALID_STATE`."
        PRD §2.9: "Tenth, fiscal caps: `ERR_ENHANCED_REVIEW_REQUIRED`,
        `ERR_COMMISSION_CAP_EXCEEDED`, and `ERR_GIFT_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/payment_approve_state_error_beats_fiscal_cap
        """
        _, ct_id, pay = self._setup_blocked_over_cap_payment(api)
        resp = api.approve_payment(pay["id"], finance_headers(FINANCE_2_ID))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

        payments = validate_success(api.list_payment_requests(
            ct_id, finance_headers(FINANCE_2_ID)), 200)
        assert payments[0]["payment_status"] == "BLOCKED"

    def test_same_ratio_submitted_payment_reports_fiscal_cap(self, api):
        """PRD §2.9: "Fifth, state-machine legality: within this tier the
        terminal-state check is evaluated first and takes precedence, so an
        action against an entity already in a terminal state reports
        `ERR_ALREADY_TERMINAL`, and only otherwise does an illegal from-state
        report `ERR_INVALID_STATE`."
        PRD §3.7: "a `ratio_pct` strictly greater than `commission_hard_cap_pct`
        can never be approved, and any attempt fails with
        `ERR_COMMISSION_CAP_EXCEEDED`"

        Design: Difficulty/priority_pair_validation_conflict/payment_approve_state_error_beats_fiscal_cap
        """
        ctx = _ng_active_contract(api)
        pay = create_payment(ctx["contract"]["id"], amount_cents=260000)
        # Same 26.00 ratio but still SUBMITTED: the fiscal check is reached.
        resp = api.approve_payment(pay["id"], finance_headers(FINANCE_1_ID))
        validate_error(resp, ApiErrorId.ERR_COMMISSION_CAP_EXCEEDED)


class TestReimbursementBypass:
    def test_reimbursement_skips_commission_brackets(self, api, finance_headers):
        """PRD §3.7: "Payments of type `REIMBURSEMENT` skip the brackets entirely
        and are always approvable on the merits of the other gates."

        Design: Corner/calculations/reimbursement_skips_commission_brackets
        """
        ctx = setup_approved_with_active_contract("CH", 80, value_cents=1000000)
        ct_id = ctx["contract"]["id"]
        pay = create_payment(ct_id, payment_type="REIMBURSEMENT", amount_cents=600000)

        approved = approve_payment(pay["id"], FINANCE_1_ID)
        # ratio would be 60.00 > hard cap 25.00, yet the brackets do not apply.
        assert approved["payment_status"] == "APPROVED"

        contract = validate_success(api.get_contract(ct_id, finance_headers), 200)
        assert contract["approved_payments_total_cents"] == 600000


class TestCertificationGateAtApproval:
    def test_payment_approve_with_lapsed_certification_rejected(self, api, finance_headers,
                                                                officer_headers,
                                                                admin_headers):
        """PRD §3.7: "at least one certification `VERIFIED` and not lapsed at
        approval time (`ERR_CERTIFICATION_LAPSED`)"
        PRD §3.6: "The `valid_until` field stays empty until verification, and
        the clock sweep moves a `VERIFIED` certification to `LAPSED` once the
        current date passes `valid_until`."

        Design: Corner/validations/payment_approve_with_lapsed_certification_rejected
        """
        ctx = setup_approved_with_active_contract("CH", 80, value_cents=500000,
                                                  end_date="2028-05-01")
        ct_id = ctx["contract"]["id"]
        pay = create_payment(ct_id, amount_cents=50000)  # ratio 10.00 <= 15.00

        # Certification verified 2026-05-01 lapses when the clock passes
        # valid_until 2027-05-01; the party is still inside its overdue grace
        # and the contract (end 2028-05-01) is still ACTIVE.
        set_clock("2027-05-02T00:00:00Z")
        certs = validate_success(
            api.list_certifications(ctx["third_party"]["id"], officer_headers), 200)
        assert certs[0]["cert_status"] == "LAPSED"

        resp = api.approve_payment(pay["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_LAPSED)

        payments = validate_success(api.list_payment_requests(ct_id, finance_headers), 200)
        assert payments[0]["payment_status"] == "SUBMITTED"


class TestPaymentRbacAndSod:
    def test_compliance_officer_cannot_approve_payment(self, api, officer_headers,
                                                       finance_headers):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4 lists POST /compliance/payment-requests/{payment_id}/approve
        with FinanceReviewer as its only authorized role.

        Design: Corner/rbac/compliance_officer_cannot_approve_payment
        """
        ctx = setup_approved_with_active_contract("CH", 80, value_cents=500000)
        ct_id = ctx["contract"]["id"]
        pay = create_payment(ct_id, amount_cents=50000)

        resp = api.approve_payment(pay["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        payments = validate_success(api.list_payment_requests(ct_id, finance_headers), 200)
        assert payments[0]["payment_status"] == "SUBMITTED"

    def test_payment_maker_checker_sod_pairs(self, api):
        """PRD §2.8: "Maker and checker are always different people. The operator
        who approves a payment request must differ from the
        `submitted_by_user_id` recorded on it; the operator who reverses an
        approved payment must differ from the `approved_by_user_id` recorded on
        it, so a reviewer can never unwind their own approval; and the officer
        who decides an escalation case must differ from the case's
        `escalated_by_user_id` whenever that field is non-null. System-initiated
        escalations carry a null `escalated_by_user_id` and impose no restriction
        on the decider. Each violation is rejected with `ERR_SOD_VIOLATION`
        (HTTP 403)."

        Design: Corner/rbac/payment_maker_checker_sod_pairs
        """
        ctx = setup_approved_with_active_contract("CH", 80, value_cents=500000)
        ct_id = ctx["contract"]["id"]
        pay = create_payment(ct_id, amount_cents=50000)  # submitted by u_sp1

        # The submitter cannot approve their own request, even with a
        # FinanceReviewer role header.
        own_approve = api.approve_payment(pay["id"], finance_headers(SPONSOR_1_ID))
        validate_error(own_approve, ApiErrorId.ERR_SOD_VIOLATION)

        approved = validate_success(
            api.approve_payment(pay["id"], finance_headers(FINANCE_1_ID)), 200)
        assert approved["payment_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == FINANCE_1_ID

        # The approving reviewer cannot reverse their own approval.
        own_reverse = api.reverse_payment(pay["id"], {"reason": "self-reversal attempt"},
                                          finance_headers(FINANCE_1_ID))
        validate_error(own_reverse, ApiErrorId.ERR_SOD_VIOLATION)

        reversed_pay = validate_success(
            api.reverse_payment(pay["id"], {"reason": "independent reversal"},
                                finance_headers(FINANCE_2_ID)), 200)
        assert reversed_pay["payment_status"] == "REVERSED"
