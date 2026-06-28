"""Calculation tests: dual-variant estimate-vs-drawdown, combinatorial net-fee
and installment schedule, and numeric boundary precision.

Translates queue A (Difficulty) instances: dual_variant_calc,
combinatorial_formula, boundary_precision_check; and queue B (Corner)
calculations-section instances.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_orthodontist_headers, make_guardian_headers,
)
from test_helpers import fixtures as fx


# =============================================================================
# Difficulty / dual_variant_calc
# =============================================================================

class TestDualVariantEstimateVsDrawdown:

    def test_plan_estimate_diverges_from_chronological_claim_benefit(self, api):
        """PRD 3.5: "the system projects a benefit equal to net_fee_cents
        multiplied by the policy's ortho_coverage_pct, rounded half-up to whole
        cents, and then takes the smaller of that projection and the policy's
        remaining_max_cents as it stands at activation"
        PRD 3.6: "the awarded benefit_cents is the smaller of two quantities: the
        billed_amount_cents multiplied by the policy's ortho_coverage_pct rounded
        half-up to whole cents, and the policy's remaining_max_cents as it stands
        at the instant of this approval"

        Design: Difficulty/dual_variant_calc/estimated_benefit_on_plan_vs_actual_drawdown_on_policy
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        fx.finalize_records_complete(patient["id"], puid)
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=200000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [400000],
                                          modality="BRACES", policy_id=policy["id"])
        fx.propose_plan(plan["id"], puid)
        activated = fx.activate_plan(plan["id"], family["guardian_user_id"])
        assert activated["estimated_insurance_benefit_cents"] == 200000

        # Emergency claim drains the pool first: benefit 50000 -> remaining 150000.
        emerg = fx.submit_claim(policy["id"], plan["id"], 100000)
        fx.approve_claim(emerg["id"])

        # The plan's own claim is awarded only the remaining pool (150000).
        main = fx.submit_claim(policy["id"], plan["id"], 400000)
        approved = validate_success(api.approve_insurance_claim(main["id"], TEST_USERS["billing_headers"]))
        assert approved["benefit_cents"] == 150000

        pol = validate_success(api.get_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))
        assert pol["remaining_max_cents"] == 0

        plan_final = validate_success(api.get_treatment_plan(plan["id"], TEST_USERS["billing_headers"]))
        assert approved["benefit_cents"] != plan_final["estimated_insurance_benefit_cents"]

    def test_pool_exhaustion_across_two_plans_one_policy(self, api):
        """PRD 3.6: "the awarded benefit_cents is the smaller of two quantities:
        the billed_amount_cents multiplied by the policy's ortho_coverage_pct
        rounded half-up to whole cents, and the policy's remaining_max_cents as
        it stands at the instant of this approval"
        PRD 3.6: "Because claims consume the pool in order of their created_at
        ascending, a plan's later claim may find the pool already partly spent by
        earlier emergency claims"

        Design: Difficulty/dual_variant_calc/net_fee_pinned_estimate_vs_chronological_pool_exhaustion_two_plans
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        fx.finalize_records_complete(patient["id"], puid)
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=250000)

        p1 = fx.create_plan_with_phases(patient["id"], puid, [400000],
                                        modality="BRACES", policy_id=policy["id"])
        fx.propose_plan(p1["id"], puid)
        fx.activate_plan(p1["id"], family["guardian_user_id"])

        p2 = fx.create_plan_with_phases(patient["id"], puid, [200000],
                                        modality="BRACES", policy_id=policy["id"])
        fx.propose_plan(p2["id"], puid)
        p2_active = fx.activate_plan(p2["id"], family["guardian_user_id"])
        assert p2_active["estimated_insurance_benefit_cents"] == 100000

        c1 = fx.submit_claim(policy["id"], p1["id"], 400000)
        fx.approve_claim(c1["id"])  # benefit 200000 -> remaining 50000

        c2 = fx.submit_claim(policy["id"], p2["id"], 200000)
        c2_app = validate_success(api.approve_insurance_claim(c2["id"], TEST_USERS["billing_headers"]))
        assert c2_app["benefit_cents"] == 50000

        pol = validate_success(api.get_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))
        assert pol["remaining_max_cents"] == 0


# =============================================================================
# Difficulty / combinatorial_formula
# =============================================================================

class TestNetFeeCombinatorial:

    def test_invisalign_second_family_plan_net_fee_with_discount(self, api):
        """PRD 3.5: "the system sums the phase_fee_cents of every phase on the
        plan and multiplies that sum by the modality multiplier"
        PRD 3.5: "1.15 for INVISALIGN, or 1.00 for BRACES"
        PRD 3.5: "when it equals exactly two, it is 0.05 (five percent)"
        PRD 3.5: "the raw discount is the gross fee multiplied by
        discount_pct_applied, rounded half-up to whole cents; the discount
        actually applied is the smaller of that raw discount and the 75000-cent
        ceiling; and net_fee_cents is the gross fee minus that applied discount"

        Design: Difficulty/combinatorial_formula/net_fee_modality_and_sibling_discount_with_cap_mode_a
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        guardian = family["guardian_user_id"]
        _prov, puid = fx.create_provider()

        # Patient A: first BRACES plan, activated -> family now has 1 in-treatment.
        patA = fx.create_patient(family["id"])
        fx.finalize_records_complete(patA["id"], puid)
        planA = fx.create_plan_with_phases(patA["id"], puid, [300000], modality="BRACES")
        fx.propose_plan(planA["id"], puid)
        fx.activate_plan(planA["id"], guardian)

        # Patient B: INVISALIGN plan; activating it makes n==2 -> 5% tier.
        patB = fx.create_patient(family["id"])
        fx.finalize_records_complete(patB["id"], puid)
        planB = fx.create_plan_with_phases(patB["id"], puid, [500000], modality="INVISALIGN")
        fx.propose_plan(planB["id"], puid)
        activated = validate_success(api.activate_treatment_plan(
            planB["id"], make_guardian_headers(guardian)))

        assert activated["gross_fee_cents"] == 575000
        assert activated["discount_pct_applied"] == 0.05
        assert activated["net_fee_cents"] == 546250

    def test_installment_schedule_floor_then_remainder(self, api):
        """PRD 3.7: "The per-month amount is the financed amount divided by the
        term and rounded down to whole cents (floored)."
        PRD 3.7: "Installments with sequence_no 1 through the term minus one each
        take that floored per-month amount"
        PRD 3.7: "so the installment amounts sum to the financed amount exactly
        with no rounding drift"

        Design: Difficulty/combinatorial_formula/installment_schedule_floor_then_remainder_mode_b
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(100000,), term_months=3, down_payment_cents=0)
        contract = ctx["contract"]
        assert contract["financed_amount_cents"] == 100000

        insts = sorted(ctx["installments"], key=lambda i: i["sequence_no"])
        assert len(insts) == 3
        assert insts[0]["amount_cents"] == 33333
        assert insts[1]["amount_cents"] == 33333
        assert insts[2]["amount_cents"] == 33334
        assert sum(i["amount_cents"] for i in insts) == 100000


# =============================================================================
# Difficulty / boundary_precision_check
# =============================================================================

class TestBoundaryPrecision:

    def test_claim_benefit_at_exactly_remaining_max(self, api):
        """PRD 3.6: "the awarded benefit_cents is the smaller of two quantities:
        the billed_amount_cents multiplied by the policy's ortho_coverage_pct
        rounded half-up to whole cents, and the policy's remaining_max_cents as
        it stands at the instant of this approval. The policy's remaining_max_cents
        is then reduced by that awarded benefit"

        Design: Difficulty/boundary_precision_check/claim_benefit_at_exactly_remaining_max_boundary
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        fx.finalize_records_complete(patient["id"], puid)
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=100000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [200000],
                                          modality="BRACES", policy_id=policy["id"])
        fx.propose_plan(plan["id"], puid)
        fx.activate_plan(plan["id"], family["guardian_user_id"])

        # projected = round(200000 * 0.50) = 100000 == remaining_max 100000.
        claim = fx.submit_claim(policy["id"], plan["id"], 200000)
        approved = validate_success(api.approve_insurance_claim(claim["id"], TEST_USERS["billing_headers"]))
        assert approved["benefit_cents"] == 100000

        pol = validate_success(api.get_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))
        assert pol["remaining_max_cents"] == 0

    def test_zero_financed_produces_zero_amount_installments(self, api):
        """PRD 3.7: "The financed amount financed_amount_cents is the plan's
        estimated_patient_responsibility_cents minus down_payment_cents"
        PRD 3.7: "A new contract starts with billing_status CURRENT and
        lifecycle_status ACTIVE, with balance_remaining_cents initialized equal
        to financed_amount_cents"

        Design: Difficulty/boundary_precision_check/zero_financed_produces_zero_amount_installments_empty_balance
        """
        # Self-pay net 120000 -> est_resp 120000; down_payment 120000 -> financed 0.
        ctx = fx.setup_active_plan([120000])
        plan = ctx["plan"]
        assert plan["estimated_patient_responsibility_cents"] == 120000
        contract = fx.create_contract(plan["id"], plan["version"],
                                      term_months=4, down_payment_cents=120000)
        assert contract["financed_amount_cents"] == 0
        assert contract["balance_remaining_cents"] == 0

        insts = sorted(fx.list_installments(contract["id"]), key=lambda i: i["sequence_no"])
        assert len(insts) == 4
        assert insts[0]["amount_cents"] == 0
        assert insts[3]["amount_cents"] == 0


# =============================================================================
# Corner / calculations
# =============================================================================

class TestCalculationCorners:

    def test_braces_multiplier_is_one_no_surcharge(self, api):
        """PRD 3.5: "the system sums the phase_fee_cents of every phase on the
        plan and multiplies that sum by the modality multiplier"
        PRD 3.5: "1.15 for INVISALIGN, or 1.00 for BRACES"

        Design: Corner/calculations/braces_modality_multiplier_is_one_no_surcharge
        """
        ctx = fx.setup_active_plan([300000], modality="BRACES")
        plan = ctx["plan"]
        assert plan["gross_fee_cents"] == 300000
        assert plan["discount_pct_applied"] == 0
        assert plan["net_fee_cents"] == 300000

    def test_discount_cap_limits_large_family_discount(self, api):
        """PRD 2.5: "the discount actually subtracted from a plan's gross fee can
        never exceed 75000 cents (that is, 750 dollars), regardless of how large
        a percentage the family qualifies for"
        PRD 3.5: "when it is three or more, it is 0.10 (ten percent)"

        Design: Corner/calculations/discount_cap_limits_large_family_discount
        """
        fx.set_clock("2026-01-01T00:00:00Z")
        family = fx.create_family()
        guardian = family["guardian_user_id"]
        _prov, puid = fx.create_provider()

        # Two already-ACTIVE BRACES plans.
        for fee in (200000, 200000):
            pat = fx.create_patient(family["id"])
            fx.finalize_records_complete(pat["id"], puid, taken_at="2026-01-01T00:00:00Z")
            pl = fx.create_plan_with_phases(pat["id"], puid, [fee], modality="BRACES")
            fx.propose_plan(pl["id"], puid)
            fx.activate_plan(pl["id"], guardian)

        # Third plan: activating makes n==3 -> 10% tier; gross 1000000, raw
        # discount 100000 capped to 75000 -> net 925000.
        patC = fx.create_patient(family["id"])
        fx.finalize_records_complete(patC["id"], puid, taken_at="2026-01-01T00:00:00Z")
        planC = fx.create_plan_with_phases(patC["id"], puid, [1000000], modality="BRACES")
        fx.propose_plan(planC["id"], puid)
        activated = validate_success(api.activate_treatment_plan(
            planC["id"], make_guardian_headers(guardian)))
        assert activated["gross_fee_cents"] == 1000000
        assert activated["discount_pct_applied"] == 0.10
        assert activated["net_fee_cents"] == 925000

    def test_zero_benefit_when_policy_has_no_ortho_rider(self, api):
        """PRD 3.5: "If the plan has no policy_id, or the named policy's
        ortho_rider is false, the estimated benefit is 0"
        PRD 3.5: "estimated_patient_responsibility_cents is set to net_fee_cents
        minus estimated_insurance_benefit_cents"

        Design: Corner/calculations/zero_benefit_when_policy_has_no_ortho_rider
        """
        fx.set_clock("2026-01-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        fx.finalize_records_complete(patient["id"], puid, taken_at="2026-01-01T00:00:00Z")
        policy = fx.create_policy(patient["id"], ortho_rider=False,
                                  ortho_coverage_pct=0.0, lifetime_max_cents=0)
        plan = fx.create_plan_with_phases(patient["id"], puid, [200000],
                                          modality="BRACES", policy_id=policy["id"])
        fx.propose_plan(plan["id"], puid)
        activated = validate_success(api.activate_treatment_plan(
            plan["id"], make_guardian_headers(family["guardian_user_id"])))
        assert activated["estimated_insurance_benefit_cents"] == 0
        assert activated["estimated_patient_responsibility_cents"] == 200000
