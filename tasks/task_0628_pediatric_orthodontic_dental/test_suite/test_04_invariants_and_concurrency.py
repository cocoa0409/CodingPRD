"""Conserved-pool invariants, optimistic concurrency, payoff, and immediate
consistency.

Translates queue A (Difficulty): compensating_invariant; and queue B (Corner)
cross_cutting_complexity_layers + consistency_model instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    make_orthodontist_headers, make_guardian_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F


# =============================================================================
# Difficulty / compensating_invariant
# =============================================================================

class TestCompensatingInvariants:

    def test_claim_void_restores_lifetime_max_pool(self, api):
        """PRD 3.6: "voiding restores the policy's remaining_max_cents by the
        claim's benefit_cents and then resets that claim's benefit_cents to 0,
        preserving the invariant that lifetime_max_cents always equals
        remaining_max_cents plus the sum of benefit_cents over the policy's
        APPROVED and PAID claims."

        Design: Difficulty/compensating_invariant/claim_void_restores_lifetime_max_pool
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        fx.finalize_records_complete(patient["id"], puid)
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=225000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000],
                                          modality="BRACES", policy_id=policy["id"])
        claim = fx.submit_claim(policy["id"], plan["id"], 150000)
        approved = fx.approve_claim(claim["id"])  # benefit 75000 -> remaining 150000
        assert approved["benefit_cents"] == 75000

        voided = validate_success(api.void_insurance_claim(claim["id"], TEST_USERS["billing_headers"]))
        assert voided["benefit_cents"] == 0

        pol = validate_success(api.get_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))
        assert pol["remaining_max_cents"] == 225000

    def test_payment_reverse_restores_contract_balance(self, api):
        """PRD 3.8: "Reversal increases balance_remaining_cents back by the
        payment's amount_cents, preserving the conservation rule that the
        financed amount equals the remaining balance plus the sum of POSTED
        payment amounts."

        Design: Difficulty/compensating_invariant/payment_reverse_restores_contract_balance
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(90000,), term_months=3, down_payment_cents=0)
        contract = ctx["contract"]
        pay = validate_success(api.create_payment(
            F.create_payment_payload(contract["id"], 30000, method="CARD"),
            TEST_USERS["billing_headers"]), expected_status=201)

        reversed_pay = validate_success(api.reverse_payment(pay["id"], TEST_USERS["billing_headers"]))
        assert reversed_pay["status"] == "REVERSED"

        contract_final = validate_success(api.get_contract(contract["id"], TEST_USERS["billing_headers"]))
        assert contract_final["balance_remaining_cents"] == 90000
        assert contract_final["financed_amount_cents"] == 90000


# =============================================================================
# Corner / cross_cutting_complexity_layers
# =============================================================================

class TestOptimisticConcurrency:

    def test_stale_plan_version_on_second_contract_create(self, api):
        """PRD 2.9: "If that value does not equal the plan's current version at
        the moment the create is processed, the request is rejected with
        ERR_STALE_PLAN_VERSION (HTTP 412)"
        PRD 2.9: "because creating a contract itself increments the plan's version,
        a client that observed the plan before another writer created the first
        contract (or before the plan was revised or re-activated) is working from
        a stale view"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_contract_create_returns_412
        """
        ctx = fx.setup_active_plan([90000])
        plan = ctx["plan"]
        plan_v = plan["version"]
        # First contract create succeeds and bumps the plan version.
        fx.create_contract(plan["id"], plan_v, term_months=3)
        # Second create still carrying the pre-create version is stale.
        resp = api.create_contract(
            F.create_contract_payload(plan["id"], plan_v, term_months=3),
            TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION)

    def test_correct_plan_version_on_contract_create_succeeds(self, api):
        """PRD 2.9: "A request to create a contract must carry
        expected_plan_version, a non-optional field holding the version of the
        target TreatmentPlan the client last observed."
        PRD 3.7: "Successful creation also increments the owning plan's version."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_plan_version_on_contract_create_succeeds
        """
        ctx = fx.setup_active_plan([90000])
        plan = ctx["plan"]
        resp = api.create_contract(
            F.create_contract_payload(plan["id"], plan["version"], term_months=3),
            TEST_USERS["billing_headers"])
        contract = validate_success(resp, expected_status=201)
        assert contract["financed_amount_cents"] == 90000
        assert contract["billing_status"] == "CURRENT"

    def test_payment_payoff_closes_contract_lifecycle(self, api):
        """PRD 3.8: "If the payment brings balance_remaining_cents to zero, the
        contract's lifecycle_status moves to CLOSED."

        Design: Corner/cross_cutting_complexity_layers/payment_payoff_closes_contract_lifecycle
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(90000,), term_months=3, down_payment_cents=0)
        contract = ctx["contract"]
        validate_success(api.create_payment(
            F.create_payment_payload(contract["id"], 90000, method="CARD"),
            TEST_USERS["billing_headers"]), expected_status=201)

        contract_final = validate_success(api.get_contract(contract["id"], TEST_USERS["billing_headers"]))
        assert contract_final["balance_remaining_cents"] == 0
        assert contract_final["lifecycle_status"] == "CLOSED"


# =============================================================================
# Corner / consistency_model
# =============================================================================

class TestImmediateConsistency:

    def test_activation_pins_all_computed_fees_in_response(self, api):
        """PRD 3.4: "Activation is the pinning moment, and it performs the
        following, all within the one request: it pins gross_fee_cents, then
        discount_pct_applied, then net_fee_cents, then
        estimated_insurance_benefit_cents and
        estimated_patient_responsibility_cents"
        PRD 3.5: "1.15 for INVISALIGN."

        Design: Corner/consistency_model/activation_pins_all_computed_fees_in_same_response
        """
        fx.set_clock("2026-01-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        fx.finalize_records_complete(patient["id"], puid, taken_at="2026-01-01T00:00:00Z")
        plan = fx.create_plan_with_phases(patient["id"], puid, [200000], modality="INVISALIGN")
        fx.propose_plan(plan["id"], puid)
        activated = validate_success(api.activate_treatment_plan(
            plan["id"], make_guardian_headers(family["guardian_user_id"])))
        # INVISALIGN: gross = round(200000 * 1.15) = 230000; self-pay -> est_resp 230000.
        assert activated["gross_fee_cents"] == 230000
        assert activated["estimated_patient_responsibility_cents"] == 230000
