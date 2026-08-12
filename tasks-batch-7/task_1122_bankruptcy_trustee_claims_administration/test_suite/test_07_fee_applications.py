"""Trustee compensation (§326-style tiers, DISBURSED vs PROPOSED basis),
fee approval/payment gates, and validation priority on fee pay."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_sale_payload,
    create_creditor, create_asset, file_claim, get_case, get_case_version,
    set_clock, review_and_allow_claim, create_judgment_action,
    file_fee_application, propose_plan, confirm_plan, get_plan_dividends,
    dividend_for_claim, make_trustee_headers,
    setup_case_in_claims_administration,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]


def _distribution_case_with_posted_dividend(case_number, scheduled_value,
                                            claim_amounts, hammer,
                                            window=2, post_claim_index=-1):
    """Walk a case to DISTRIBUTION with a CONFIRMED plan, then post the
    dividend of exactly one claim. Returns (ctx_dict, claims, plan)."""
    ctx = setup_case_in_claims_administration(case_number=case_number,
                                              objection_window_days=window,
                                              scheduled_value_cents=scheduled_value)
    case_id = ctx["case"]["id"]
    cred_id = ctx["creditor"]["id"]
    claims = []
    for i, amount in enumerate(claim_amounts):
        c = file_claim(case_id, cred_id,
                       received_at=f"2026-02-01T0{i}:00:00Z",
                       filed_amount_cents=amount)
        review_and_allow_claim(c["id"])
        claims.append(c)
    set_clock("2026-06-02T00:00:00Z")
    get_success_data(api_client.begin_liquidation(case_id, TRUSTEE))
    get_success_data(api_client.mark_asset_for_sale(ctx["asset"]["id"], TRUSTEE))
    sale = get_success_data(api_client.create_sale(
        case_id, create_sale_payload(asset_id=ctx["asset"]["id"],
                                     hammer_price_cents=hammer,
                                     sale_costs_cents=0), TRUSTEE))
    get_success_data(api_client.approve_sale(sale["id"], COURT))
    set_clock("2026-06-05T00:00:00Z")
    get_success_data(api_client.consummate_sale(sale["id"], TRUSTEE))
    get_success_data(api_client.begin_distribution(case_id, TRUSTEE))
    plan = propose_plan(case_id)
    confirm_plan(plan["id"], case_id)
    if post_claim_index is not None and post_claim_index >= 0:
        div = dividend_for_claim(plan["id"], claims[post_claim_index]["id"])[0]
        get_success_data(api_client.post_dividend(div["id"], TRUSTEE))
    ctx["case"] = get_case(case_id)
    return ctx, claims, plan


class TestCommissionBasisVariants:
    def test_disbursed_basis_counts_only_posted_dividends(self, api):
        """PRD §3.7: "Under `DISBURSED`, B is the sum of the `amount_cents` of
        all `POSTED` dividends plus the approved amounts of all `PAID`
        non-trustee fee applications at the filing instant — moneys actually
        disbursed to parties in interest, excluding the trustee's own
        compensation."

        One posted dividend of 2,000,000 (the other 4,000,000 still COMPUTED,
        no paid fees): B = 2,000,000 -> 125,000 + 150,000 = 275,000.

        Design: Difficulty/dual_variant_calc/trustee_commission_disbursed_vs_proposed_basis
        """
        ctx, claims, plan = _distribution_case_with_posted_dividend(
            "26-10001", scheduled_value=9000000,
            claim_amounts=[4000000, 2000000], hammer=6000000,
            window=2, post_claim_index=1)
        fee = file_fee_application(ctx["case"]["id"], applicant_role="TRUSTEE",
                                   requested_amount_cents=275000,
                                   commission_basis="DISBURSED")
        assert fee["computed_commission_cents"] == 275000

    def test_proposed_basis_uses_confirmed_plan_allocations(self, api):
        """PRD §3.7: "Under `PROPOSED`, B is the sum of `allocated_cents`
        across the class allocations of the case's `CONFIRMED` plan — amounts
        proposed to be disbursed under the pending plan — which yields a higher
        commission earlier in the case than `DISBURSED` when dividends are not
        yet posted."

        Plan CONFIRMED with 6,000,000 of allocations and no dividend posted
        yet (posting would move the plan on to `EXECUTING`, per §3.6): the
        PROPOSED basis is B = 6,000,000 -> 125,000 + 450,000 + 50,000
        = 625,000, while the DISBURSED basis is still 0 — so the trustee's
        `requested_amount_cents` (pinned to the DISBURSED-basis commission)
        is 0 for both filings.

        Design: Difficulty/dual_variant_calc/trustee_commission_disbursed_vs_proposed_basis
        """
        ctx, claims, plan = _distribution_case_with_posted_dividend(
            "26-10001", scheduled_value=9000000,
            claim_amounts=[4000000, 2000000], hammer=6000000,
            window=2, post_claim_index=-1)
        fee_disb = file_fee_application(ctx["case"]["id"], applicant_role="TRUSTEE",
                                        requested_amount_cents=0,
                                        commission_basis="DISBURSED")
        fee_prop = file_fee_application(ctx["case"]["id"], applicant_role="TRUSTEE",
                                        requested_amount_cents=0,
                                        commission_basis="PROPOSED")
        assert fee_prop["computed_commission_cents"] == 625000
        assert fee_prop["computed_commission_cents"] != \
            fee_disb["computed_commission_cents"]


class TestCommissionTierStraddle:
    def test_basis_exactly_at_one_million_boundary(self, api):
        """PRD §3.7: "The §326(a)-style commission runs in four tiers against a
        basis B expressed in cents: 25 percent of the first $5,000 (the first
        500,000 cents), then 10 percent of the next $45,000 (up to 4,500,000
        cents beyond the first tier), then 5 percent of the next $950,000 (up
        to 95,000,000 cents beyond the second tier), then 3 percent of
        everything above $1,000,000 (100,000,000 cents) of basis."

        B = 100,000,000 -> 125,000 + 450,000 + 4,750,000 + 0 = 5,325,000.

        Design: Difficulty/combinatorial_formula/trustee_commission_tier_straddle_at_million_boundary
        """
        ctx, claims, plan = _distribution_case_with_posted_dividend(
            "26-10003", scheduled_value=200000000,
            claim_amounts=[200000000], hammer=100000000,
            window=1, post_claim_index=0)
        fee = file_fee_application(ctx["case"]["id"], applicant_role="TRUSTEE",
                                   requested_amount_cents=5325000,
                                   commission_basis="DISBURSED")
        assert fee["computed_commission_cents"] == 5325000

    def test_basis_one_hundred_cents_above_boundary_adds_three_cents(self, api):
        """PRD §3.7: "then 3 percent of everything above $1,000,000
        (100,000,000 cents) of basis. Each tier is truncated down to whole
        cents by integer division before the tiers are summed — the per-tier
        floor first, the summation second, in that pinned order."

        B = 100,000,100 -> 5,325,000 + floor(100 * 3 / 100) = 5,325,003.

        Design: Difficulty/combinatorial_formula/trustee_commission_tier_straddle_at_million_boundary
        """
        ctx, claims, plan = _distribution_case_with_posted_dividend(
            "26-10003", scheduled_value=200000000,
            claim_amounts=[200000000], hammer=100000100,
            window=1, post_claim_index=0)
        fee = file_fee_application(ctx["case"]["id"], applicant_role="TRUSTEE",
                                   requested_amount_cents=5325003,
                                   commission_basis="DISBURSED")
        assert fee["computed_commission_cents"] == 5325003


class TestFeeEffectiveWindow:
    def test_fee_pay_gated_until_effective_on(self, api):
        """PRD §3.7: "Payment is the trustee's disbursement of an approved fee,
        permitted only once the logical clock is at or past the application's
        `effective_on` (earlier attempts are rejected with
        `ERR_FEE_NOT_YET_EFFECTIVE`) and only while
        `estate_cash_on_hand_cents` covers the `approved_amount_cents` (else
        `ERR_INSUFFICIENT_ESTATE_FUNDS`)."
        PRD §3.7: "Approval computes `effective_on` as the approval date plus
        the case's `objection_window_days` days, mirroring the sale-order
        window."

        Window 2 days; approved at 2026-06-05 -> effective_on 2026-06-07.

        Design: Corner/cross_cutting_layers/scheduled_action_fee_effective_window
        """
        ctx = setup_case_in_claims_administration(case_number="26-20060",
                                                  objection_window_days=2)
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        create_judgment_action(case_id, cred_id, transfer_amount_cents=200000,
                               demand_amount_cents=200000)  # cash 200,000
        fee = file_fee_application(case_id, applicant_role="COUNSEL",
                                   requested_amount_cents=50000)
        set_clock("2026-06-05T00:00:00Z")
        get_success_data(api_client.approve_fee(fee["id"], 50000, COURT))

        resp = api.pay_fee(fee["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_YET_EFFECTIVE)

        set_clock("2026-06-07T00:00:00Z")  # exactly effective_on
        paid = validate_success(api.pay_fee(fee["id"], TRUSTEE))
        assert paid["status"] == "PAID"


class TestFeeApprovalAmount:
    def test_fee_approval_above_request_rejected(self, api):
        """PRD §3.7: "The court approves with an `approved_amount_cents` no
        greater than the `requested_amount_cents`; anything above the request
        is rejected with `ERR_APPROVAL_EXCEEDS_REQUEST` (HTTP 422)."

        Design: Corner/validations/fee_approval_above_request_rejected
        """
        ctx = setup_case_in_claims_administration(case_number="26-20024")
        fee = file_fee_application(ctx["case"]["id"], applicant_role="COUNSEL",
                                   requested_amount_cents=100000)
        resp = api.approve_fee(fee["id"], 100001, COURT)
        validate_error(resp, ApiErrorId.ERR_APPROVAL_EXCEEDS_REQUEST)


class TestFeeSegregationOfDuties:
    def test_trustee_cannot_approve_own_fee_application(self, api):
        """PRD §3.7: "Approval belongs to the `Court` alone, so the filer can
        never approve its own application — segregation of duties is structural
        here."
        PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/trustee_cannot_approve_own_fee_application
        """
        ctx = setup_case_in_claims_administration(case_number="26-20050")
        fee = file_fee_application(ctx["case"]["id"], applicant_role="TRUSTEE",
                                   requested_amount_cents=0,
                                   commission_basis="DISBURSED")
        resp = api.approve_fee(fee["id"], 0, TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestFeePayValidationPriority:
    def _approved_fee_no_cash(self):
        """APPROVED counsel fee of 100,000 with effective_on in the past and
        estate cash 0 (insufficient funds)."""
        ctx = setup_case_in_claims_administration(case_number="26-10010",
                                                  objection_window_days=1)
        fee = file_fee_application(ctx["case"]["id"], applicant_role="COUNSEL",
                                   requested_amount_cents=100000)
        get_success_data(api_client.approve_fee(fee["id"], 100000, COURT))
        set_clock("2026-06-10T00:00:00Z")
        return ctx, fee

    def test_wrong_trustee_rejected_before_fiscal_check(self, api):
        """PRD §2.11: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the earliest
        failing tier determines the error surfaced:"
        PRD §2.11: "6. Segregation-of-duties identity binding (the
        assigned-trustee match and the creditor self-service match) —
        `ERR_NOT_ASSIGNED_TRUSTEE`."
        PRD §2.11: "11. Fiscal sufficiency per §2.7 —
        `ERR_INSUFFICIENT_ESTATE_FUNDS`, with `ERR_NO_FUNDS_TO_DISTRIBUTE`
        where the failing condition is a non-positive pool."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_fee_pay
        """
        ctx, fee = self._approved_fee_no_cash()
        resp = api.pay_fee(fee["id"], make_trustee_headers("trust-9999"))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_TRUSTEE)

    def test_correct_trustee_with_insufficient_funds_rejected(self, api):
        """PRD §3.7: "Payment is the trustee's disbursement of an approved fee,
        permitted only once the logical clock is at or past the application's
        `effective_on` (earlier attempts are rejected with
        `ERR_FEE_NOT_YET_EFFECTIVE`) and only while
        `estate_cash_on_hand_cents` covers the `approved_amount_cents` (else
        `ERR_INSUFFICIENT_ESTATE_FUNDS`)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_fee_pay
        """
        ctx, fee = self._approved_fee_no_cash()
        resp = api.pay_fee(fee["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESTATE_FUNDS)
