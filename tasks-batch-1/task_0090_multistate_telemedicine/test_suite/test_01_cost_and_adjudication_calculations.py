"""Patient-cost and claim-adjudication calculations (depth: dual-variant + combinatorial).

Covers the two divergent cost variants on a Visit (insurance vs self-pay), the two
divergent plan-payment variants on a Claim (parity vs non-parity), the nested min/max
conditional adjudication formula, and the order-dependent per-component self-pay rounding.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    make_physician_headers,
    officer_headers,
    setup_approved_visit,
    setup_cleared_visit,
)


class TestPatientCostDualVariant:
    """Same list fee, divergent patient_cost_cents purely on the routing branch."""

    def test_insurance_routed_visit_costs_copay(self, api):
        """PRD §3.5: "When the patient on the visit carries insurance — their
        `insurance_payer_id` is not null — approval routes to insurance: the visit
        moves from `COMPLIANCE_CLEARED` to `APPROVED_INSURANCE`, its `routing` is set
        to `INSURANCE`, and its `patient_cost_cents` is computed by the insurance cost
        path described below."
        PRD §3.5: "If the payer offers telehealth parity (`telehealth_parity` is true),
        the patient owes exactly the payer's `copay_cents`."

        Design: Difficulty/dual_variant_calc/patient_cost_dual_variant_insurance_vs_self_pay_on_visit
        """
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 10000},
        )
        visit = ctx["visit"]
        assert visit["routing"] == "INSURANCE", f"expected INSURANCE, got {visit['routing']}"
        assert visit["patient_cost_cents"] == 2500, (
            f"parity copay expected 2500, got {visit['patient_cost_cents']}"
        )

    def test_self_pay_routed_visit_costs_discounted_list_fee(self, api):
        """PRD §3.5: "When the patient carries no insurance — `insurance_payer_id` is
        null — approval routes to self-pay: the visit moves to `APPROVED_SELF_PAY`, its
        `routing` is set to `SELF_PAY`, and `patient_cost_cents` is computed by the
        self-pay path."
        PRD §3.5: "the clinical share is the visit's `list_fee_cents` multiplied by 0.80
        and then rounded half-up to a whole cent; the platform share is the visit's
        `platform_fee_cents` multiplied by 0.80 and then rounded half-up to a whole cent;
        and the patient's cost is the sum of those two already-rounded shares."

        Design: Difficulty/dual_variant_calc/patient_cost_dual_variant_insurance_vs_self_pay_on_visit
        """
        # list_fee 10000, platform_fee omitted (defaults 0): round(10000*0.8)=8000 + round(0)=0.
        _, _, _, cleared = setup_cleared_visit(visit_overrides={"list_fee_cents": 10000})
        phys = cleared
        # cleared returns the visit; physician id is on it.
        phys_headers = make_physician_headers(cleared["physician_id"])
        approved = validate_success(api.approve_visit(cleared["id"], phys_headers), 200)
        assert approved["routing"] == "SELF_PAY", f"expected SELF_PAY, got {approved['routing']}"
        assert approved["patient_cost_cents"] == 8000, (
            f"discounted list fee expected 8000, got {approved['patient_cost_cents']}"
        )


class TestClaimAdjudicationDualVariant:
    """Identical billed/allowed, divergent plan_paid_cents purely on the parity flag."""

    def _single_claim(self, api, visit_id):
        data, _ = validate_paginated(api.list_visit_claims(visit_id, officer_headers()))
        assert len(data) == 1, f"expected exactly one claim, got {len(data)}"
        return data[0]

    def test_parity_payer_plan_paid(self, api):
        """PRD §3.6: "If the payer offers telehealth parity, the plan pays the allowed
        amount minus the payer's `copay_cents`, floored at zero — that is,
        `plan_paid_cents` is the allowed amount less the copay, but never below zero."
        PRD §3.6: "The allowed amount, `allowed_cents`, is the smaller of the claim's
        `billed_cents` and the payer's `allowed_amount_cents`."

        Design: Difficulty/dual_variant_calc/claim_adjudication_dual_variant_parity_vs_non_parity_on_claim
        """
        # billed 10000, allowed_amount 8000 -> allowed 8000; parity: 8000-2500=5500.
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 10000},
        )
        claim = self._single_claim(api, ctx["visit"]["id"])
        assert claim["allowed_cents"] == 8000, f"expected allowed 8000, got {claim['allowed_cents']}"
        assert claim["plan_paid_cents"] == 5500, f"expected plan_paid 5500, got {claim['plan_paid_cents']}"

    def test_non_parity_payer_plan_paid(self, api):
        """PRD §3.6: "If the payer does not offer parity, the plan pays only the
        non-parity share: take half of the allowed amount (the allowed amount multiplied
        by 0.50, rounded half-up to a whole cent), subtract the payer's `copay_cents`, and
        floor the result at zero."
        PRD §3.6: "The allowed amount, `allowed_cents`, is the smaller of the claim's
        `billed_cents` and the payer's `allowed_amount_cents`."

        Design: Difficulty/dual_variant_calc/claim_adjudication_dual_variant_parity_vs_non_parity_on_claim
        """
        # billed 10000, allowed_amount 8000 -> allowed 8000; non-parity: round(8000*0.5)-2500=1500.
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": False, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 10000},
        )
        claim = self._single_claim(api, ctx["visit"]["id"])
        assert claim["allowed_cents"] == 8000, f"expected allowed 8000, got {claim['allowed_cents']}"
        assert claim["plan_paid_cents"] == 1500, f"expected plan_paid 1500, got {claim['plan_paid_cents']}"


class TestClaimAdjudicationCombinatorial:
    """Nested min/max with a parity-conditional branch (mode a)."""

    def test_billed_above_allowed_uses_allowed_ceiling_non_parity(self, api):
        """PRD §3.6: "The allowed amount, `allowed_cents`, is the smaller of the claim's
        `billed_cents` and the payer's `allowed_amount_cents`."
        PRD §3.6: "If the payer does not offer parity, the plan pays only the non-parity
        share: take half of the allowed amount (the allowed amount multiplied by 0.50,
        rounded half-up to a whole cent), subtract the payer's `copay_cents`, and floor
        the result at zero."

        Design: Difficulty/combinatorial_formula/claim_adjudication_nested_min_max_conditional_mode_a
        """
        # billed 12000 (> allowed_amount 8000) -> allowed = min(12000,8000)=8000;
        # non-parity: max(0, round(8000*0.5) - 2500) = max(0, 4000-2500) = 1500.
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": False, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 12000},
        )
        data, _ = validate_paginated(api.list_visit_claims(ctx["visit"]["id"], officer_headers()))
        claim = data[0]
        assert claim["allowed_cents"] == 8000, (
            f"min(12000,8000) expected 8000, got {claim['allowed_cents']}"
        )
        assert claim["plan_paid_cents"] == 1500, (
            f"max(0, round(8000*0.5)-2500) expected 1500, got {claim['plan_paid_cents']}"
        )

    def test_billed_below_allowed_uses_billed_floor_parity(self, api):
        """PRD §3.6: "The allowed amount, `allowed_cents`, is the smaller of the claim's
        `billed_cents` and the payer's `allowed_amount_cents`."
        PRD §3.6: "If the payer offers telehealth parity, the plan pays the allowed amount
        minus the payer's `copay_cents`, floored at zero — that is, `plan_paid_cents` is the
        allowed amount less the copay, but never below zero."

        Design: Difficulty/combinatorial_formula/claim_adjudication_nested_min_max_conditional_mode_a
        """
        # billed 5000 (< allowed_amount 8000) -> allowed = min(5000,8000)=5000 (min picks billed);
        # parity branch: max(0, 5000 - 2500) = 2500.
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 5000},
        )
        data, _ = validate_paginated(api.list_visit_claims(ctx["visit"]["id"], officer_headers()))
        claim = data[0]
        assert claim["allowed_cents"] == 5000, (
            f"min(5000,8000) expected 5000, got {claim['allowed_cents']}"
        )
        assert claim["plan_paid_cents"] == 2500, (
            f"max(0, 5000-2500) expected 2500, got {claim['plan_paid_cents']}"
        )


class TestSelfPayPerComponentRounding:
    """Order-dependent rounding: round each discounted component BEFORE summing (mode b)."""

    def test_per_component_rounding_order(self, api):
        """PRD §3.5: "the clinical share is the visit's `list_fee_cents` multiplied by
        0.80 and then rounded half-up to a whole cent; the platform share is the visit's
        `platform_fee_cents` multiplied by 0.80 and then rounded half-up to a whole cent;
        and the patient's cost is the sum of those two already-rounded shares."
        PRD §3.5: "Each discounted component is rounded *before* the two are added
        together — rounding each component first and summing afterward can differ by a
        cent from discounting a combined total, and the per-component-then-sum order is
        the one this platform uses."

        Design: Difficulty/combinatorial_formula/self_pay_cost_per_component_rounding_order_mode_b
        """
        # list 1501*0.8=1200.8->1201 ; platform 1502*0.8=1201.6->1202 ; sum=2403.
        # sum-then-round would give round(3003*0.8)=round(2402.4)=2402; per-component wins -> 2403.
        _, _, _, cleared = setup_cleared_visit(
            visit_overrides={"list_fee_cents": 1501, "platform_fee_cents": 1502},
        )
        phys_headers = make_physician_headers(cleared["physician_id"])
        approved = validate_success(api.approve_visit(cleared["id"], phys_headers), 200)
        assert approved["routing"] == "SELF_PAY", f"expected SELF_PAY, got {approved['routing']}"
        assert approved["patient_cost_cents"] == 2403, (
            f"per-component rounding expected 2403, got {approved['patient_cost_cents']}"
        )

    def test_per_component_rounding_order_second_boundary(self, api):
        """PRD §3.5: "the clinical share is the visit's `list_fee_cents` multiplied by 0.80
        and then rounded half-up to a whole cent; the platform share is the visit's
        `platform_fee_cents` multiplied by 0.80 and then rounded half-up to a whole cent;
        and the patient's cost is the sum of those two already-rounded shares."
        PRD §3.5: "Each discounted component is rounded *before* the two are added together
        — rounding each component first and summing afterward can differ by a cent from
        discounting a combined total, and the per-component-then-sum order is the one this
        platform uses."

        Design: Difficulty/combinatorial_formula/self_pay_cost_per_component_rounding_order_mode_b
        """
        # list 7*0.8=5.6->6 ; platform 2*0.8=1.6->2 ; sum=8.
        # sum-then-round would give round(9*0.8)=round(7.2)=7; per-component wins -> 8.
        _, _, _, cleared = setup_cleared_visit(
            visit_overrides={"list_fee_cents": 7, "platform_fee_cents": 2},
        )
        phys_headers = make_physician_headers(cleared["physician_id"])
        approved = validate_success(api.approve_visit(cleared["id"], phys_headers), 200)
        assert approved["routing"] == "SELF_PAY", f"expected SELF_PAY, got {approved['routing']}"
        assert approved["patient_cost_cents"] == 8, (
            f"per-component rounding expected 8, got {approved['patient_cost_cents']}"
        )
