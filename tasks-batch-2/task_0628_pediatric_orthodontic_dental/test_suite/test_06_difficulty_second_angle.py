"""Second-angle coverage for every queue A (Difficulty) instance.

Each difficulty instance is covered by at least two tests: one in its primary
file (test_01..test_04) and one here, asserting a complementary PRD-derivable
observable on the same scenario.
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
# dual_variant_calc
# =============================================================================

class TestDualVariantSecondAngle:

    def test_emergency_claim_drawdown_reduces_pool_before_main_claim(self, api):
        """PRD 3.6: "the awarded benefit_cents is the smaller of two quantities:
        the billed_amount_cents multiplied by the policy's ortho_coverage_pct
        rounded half-up to whole cents, and the policy's remaining_max_cents as
        it stands at the instant of this approval. The policy's remaining_max_cents
        is then reduced by that awarded benefit"

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
        fx.activate_plan(plan["id"], family["guardian_user_id"])

        emerg = fx.submit_claim(policy["id"], plan["id"], 100000)
        approved = validate_success(api.approve_insurance_claim(emerg["id"], TEST_USERS["billing_headers"]))
        # round(100000 * 0.50) = 50000; pool drops to 150000.
        assert approved["benefit_cents"] == 50000
        pol = validate_success(api.get_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))
        assert pol["remaining_max_cents"] == 150000

    def test_second_plan_estimate_pinned_independently_of_pool_state(self, api):
        """PRD 3.5: "then takes the smaller of that projection and the policy's
        remaining_max_cents as it stands at activation"

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
        p1a = fx.activate_plan(p1["id"], family["guardian_user_id"])
        # P1 net 400000, coverage 0.50 -> projection 200000, capped at remaining 250000 -> 200000.
        assert p1a["estimated_insurance_benefit_cents"] == 200000

        p2 = fx.create_plan_with_phases(patient["id"], puid, [200000],
                                        modality="BRACES", policy_id=policy["id"])
        fx.propose_plan(p2["id"], puid)
        p2a = fx.activate_plan(p2["id"], family["guardian_user_id"])
        # P2 net 200000 -> projection 100000, still within remaining at activation.
        assert p2a["estimated_insurance_benefit_cents"] == 100000


# =============================================================================
# combinatorial_formula
# =============================================================================

class TestCombinatorialSecondAngle:

    def test_invisalign_plan_net_responsibility_self_pay(self, api):
        """PRD 3.5: "estimated_patient_responsibility_cents is set to net_fee_cents
        minus estimated_insurance_benefit_cents"
        PRD 3.5: "If the plan has no policy_id, or the named policy's ortho_rider
        is false, the estimated benefit is 0"

        Design: Difficulty/combinatorial_formula/net_fee_modality_and_sibling_discount_with_cap_mode_a
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        guardian = family["guardian_user_id"]
        _prov, puid = fx.create_provider()
        patA = fx.create_patient(family["id"])
        fx.finalize_records_complete(patA["id"], puid)
        planA = fx.create_plan_with_phases(patA["id"], puid, [300000], modality="BRACES")
        fx.propose_plan(planA["id"], puid)
        fx.activate_plan(planA["id"], guardian)

        patB = fx.create_patient(family["id"])
        fx.finalize_records_complete(patB["id"], puid)
        planB = fx.create_plan_with_phases(patB["id"], puid, [500000], modality="INVISALIGN")
        fx.propose_plan(planB["id"], puid)
        activated = fx.activate_plan(planB["id"], guardian)
        # Self-pay -> benefit 0, est_resp == net_fee 546250.
        assert activated["net_fee_cents"] == 546250
        assert activated["estimated_patient_responsibility_cents"] == 546250

    def test_installment_due_dates_step_by_thirty_days(self, api):
        """PRD 3.7: "Each installment's due_at is the contract's created_at
        advanced by its index times one month, where one month is 30 days"

        Design: Difficulty/combinatorial_formula/installment_schedule_floor_then_remainder_mode_b
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(100000,), term_months=3, down_payment_cents=0)
        insts = sorted(ctx["installments"], key=lambda i: i["sequence_no"])
        from datetime import datetime

        def parse(ts):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))

        d1, d2, d3 = (parse(i["due_at"]) for i in insts)
        assert (d2 - d1).days == 30
        assert (d3 - d2).days == 30


# =============================================================================
# non_linear_state_machine
# =============================================================================

class TestNonLinearSecondAngle:

    def test_revise_returns_plan_to_draft_status(self, api):
        """PRD 3.4: "the clinician sends the plan back from PROPOSED to DRAFT for
        edits"
        PRD 3.4: "which is legal only from PROPOSED and likewise increments the
        version"

        Design: Difficulty/non_linear_state_machine/treatment_plan_proposed_to_draft_revision_cycle
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        plan = fx.create_plan_with_phases(patient["id"], puid, [300000], modality="BRACES")
        validate_success(api.propose_treatment_plan(plan["id"], ortho))
        revised = validate_success(api.revise_treatment_plan(plan["id"], ortho))
        assert revised["status"] == "DRAFT"

    def test_delinquency_suspends_plan_then_cure_resumes(self, api):
        """PRD 2.7: "the owning treatment plan moves from ACTIVE to SUSPENDED"
        PRD 2.7: "the contract returns to CURRENT and the plan, if SUSPENDED,
        returns to ACTIVE"

        Design: Difficulty/non_linear_state_machine/contract_parallel_billing_and_lifecycle_axes
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(90000,), term_months=3, down_payment_cents=0)
        plan_id = ctx["plan"]["id"]
        contract = ctx["contract"]
        inst1 = sorted(ctx["installments"], key=lambda i: i["sequence_no"])[0]

        fx.set_clock("2026-03-05T00:00:00Z")
        validate_success(api.charge_installment(
            inst1["id"], {"outcome": "FAILED"}, TEST_USERS["billing_headers"]))
        suspended = validate_success(api.get_treatment_plan(plan_id, TEST_USERS["billing_headers"]))
        assert suspended["status"] == "SUSPENDED"

        validate_success(api.create_payment(
            F.create_payment_payload(contract["id"], 30000, method="CARD",
                                     installment_id=inst1["id"]),
            TEST_USERS["billing_headers"]), expected_status=201)
        resumed = validate_success(api.get_treatment_plan(plan_id, TEST_USERS["billing_headers"]))
        assert resumed["status"] == "ACTIVE"


# =============================================================================
# transitive_cascade
# =============================================================================

class TestTransitiveCascadeSecondAngle:

    def test_missed_payment_drives_contract_delinquent_and_plan_suspended(self, api):
        """PRD 2.7: "the owning contract's billing_status flips from CURRENT to
        DELINQUENT; the owning treatment plan moves from ACTIVE to SUSPENDED"

        Design: Difficulty/transitive_cascade/missed_payment_cascades_installment_contract_plan_appointments_depth4
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(90000,), term_months=3, down_payment_cents=0)
        plan_id = ctx["plan"]["id"]
        contract = ctx["contract"]
        inst1 = sorted(ctx["installments"], key=lambda i: i["sequence_no"])[0]

        fx.set_clock("2026-03-05T00:00:00Z")
        validate_success(api.charge_installment(
            inst1["id"], {"outcome": "FAILED"}, TEST_USERS["billing_headers"]))

        c = validate_success(api.get_contract(contract["id"], TEST_USERS["billing_headers"]))
        assert c["billing_status"] == "DELINQUENT"
        p = validate_success(api.get_treatment_plan(plan_id, TEST_USERS["billing_headers"]))
        assert p["status"] == "SUSPENDED"

    def test_complete_requires_retention_and_marks_completed(self, api):
        """PRD 3.4: "Later the clinician completes the plan, moving it from
        RETENTION to COMPLETED; completion is legal only from RETENTION"

        Design: Difficulty/transitive_cascade/plan_complete_cascades_contract_close_depth2
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        fx.finalize_records_complete(patient["id"], puid)
        plan = fx.create_plan_with_phases(patient["id"], puid, [90000], modality="BRACES")
        fx.propose_plan(plan["id"], puid)
        activated = fx.activate_plan(plan["id"], family["guardian_user_id"])
        fx.create_contract(plan["id"], activated["version"], term_months=3)
        retention = validate_success(api.debond_treatment_plan(plan["id"], ortho, {"retainer_type": "HAWLEY"}))
        assert retention["status"] == "RETENTION"
        completed = validate_success(api.complete_treatment_plan(plan["id"], ortho))
        assert completed["status"] == "COMPLETED"


# =============================================================================
# priority_pair_validation_conflict
# =============================================================================

class TestPrioritySecondAngle:

    def test_invalid_state_returns_409_status(self, api):
        """PRD 2.10: "followed by the state-machine legality check that the target
        is in a state from which the requested transition is defined
        (ERR_INVALID_STATE)"

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_down_payment_exceeds_on_contract
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        plan = get_success_data(api.create_treatment_plan(
            F.create_treatment_plan_payload(patient["id"], modality="BRACES"), ortho))
        resp = api.create_contract(
            F.create_contract_payload(plan["id"], plan["version"],
                                      term_months=3, down_payment_cents=999999),
            TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_cross_entity_state_returns_409_status(self, api):
        """PRD 2.10: "After legality, cross-entity state preconditions are
        evaluated (ERR_CROSS_ENTITY_STATE)"

        Design: Difficulty/priority_pair_validation_conflict/cross_entity_state_beats_provider_conflict_on_appointment
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patX = fx.create_patient(family["id"])
        patY = fx.create_patient(family["id"])
        prov, puid = fx.create_provider()
        chair2 = fx.create_chair(turnover_buffer_minutes=10)
        chair3 = fx.create_chair(turnover_buffer_minutes=10)
        fx.create_appointment(patX["id"], prov["id"], chair2["id"], "EMERGENCY",
                              "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        planY = fx.create_plan_with_phases(patY["id"], puid, [100000], modality="BRACES")
        resp = api.create_appointment(
            F.create_appointment_payload(
                patY["id"], prov["id"], chair3["id"], "ADJUSTMENT",
                "2026-04-01T15:15:00Z", "2026-04-01T15:45:00Z", plan_id=planY["id"]),
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE, expected_status=409)


# =============================================================================
# boundary_precision_check
# =============================================================================

class TestBoundarySecondAngle:

    def test_claim_benefit_capped_at_remaining_not_negative(self, api):
        """PRD 3.6: "the awarded benefit_cents is the smaller of two quantities:
        the billed_amount_cents multiplied by the policy's ortho_coverage_pct
        rounded half-up to whole cents, and the policy's remaining_max_cents as
        it stands at the instant of this approval"

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
        claim = fx.submit_claim(policy["id"], plan["id"], 200000)
        approved = fx.approve_claim(claim["id"])
        # projected round(200000*0.5)=100000 == remaining 100000 -> benefit 100000.
        assert approved["benefit_cents"] == 100000
        pol = validate_success(api.get_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))
        assert pol["remaining_max_cents"] >= 0

    def test_zero_financed_balance_remaining_is_zero(self, api):
        """PRD 3.7: "A new contract starts with billing_status CURRENT and
        lifecycle_status ACTIVE, with balance_remaining_cents initialized equal to
        financed_amount_cents"

        Design: Difficulty/boundary_precision_check/zero_financed_produces_zero_amount_installments_empty_balance
        """
        ctx = fx.setup_active_plan([120000])
        plan = ctx["plan"]
        contract = fx.create_contract(plan["id"], plan["version"],
                                      term_months=4, down_payment_cents=120000)
        # financed 0 -> balance 0; all 4 installments zero-amount.
        assert contract["balance_remaining_cents"] == 0
        insts = sorted(fx.list_installments(contract["id"]), key=lambda i: i["sequence_no"])
        assert all(i["amount_cents"] == 0 for i in insts)


# =============================================================================
# cross_entity_state_dependency
# =============================================================================

class TestCrossEntityDependencySecondAngle:

    def test_adjustment_against_active_plan_succeeds(self, api):
        """PRD 3.9: "a plan_id is required for ADJUSTMENT, BONDING, and DEBOND
        visits and may be omitted only for EMERGENCY new-patient triage"
        PRD 3.9: "A new appointment is SCHEDULED"

        Design: Difficulty/cross_entity_state_dependency/adjustment_appointment_requires_plan_active
        """
        ctx = fx.setup_active_plan([100000])
        prov, _ = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)
        resp = api.create_appointment(
            F.create_appointment_payload(
                ctx["patient"]["id"], prov["id"], chair["id"], "ADJUSTMENT",
                "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z", plan_id=ctx["plan"]["id"]),
            TEST_USERS["frontdesk_headers"])
        appt = validate_success(resp, expected_status=201)
        assert appt["status"] == "SCHEDULED"

    def test_claim_approval_on_terminated_policy_returns_409(self, api):
        """PRD 3.6: "it additionally requires that the owning policy is ACTIVE
        (otherwise ERR_POLICY_TERMINATED)"

        Design: Difficulty/cross_entity_state_dependency/claim_approval_requires_policy_active
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=300000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000],
                                          modality="BRACES", policy_id=policy["id"])
        claim = fx.submit_claim(policy["id"], plan["id"], 100000)
        validate_success(api.terminate_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))
        resp = api.approve_insurance_claim(claim["id"], TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_POLICY_TERMINATED, expected_status=409)


# =============================================================================
# resource_temporal_overlap
# =============================================================================

class TestTemporalOverlapSecondAngle:

    def test_chair_free_after_buffer_window_succeeds(self, api):
        """PRD 3.9: "the half-open interval that runs from the appointment's start
        up to but not including its end plus the buffer"

        Design: Difficulty/resource_temporal_overlap/chair_overlap_with_turnover_buffer_closed_interval
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        pat1 = fx.create_patient(family["id"])
        pat2 = fx.create_patient(family["id"])
        prov1, _ = fx.create_provider()
        prov2, _ = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)
        # Existing 15:00-15:30 blocks the chair through 15:40 (half-open).
        fx.create_appointment(pat1["id"], prov1["id"], chair["id"], "EMERGENCY",
                              "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        # A new appointment starting exactly at 15:40 sits at the half-open
        # boundary and is allowed.
        resp = api.create_appointment(
            F.create_appointment_payload(
                pat2["id"], prov2["id"], chair["id"], "EMERGENCY",
                "2026-04-01T15:40:00Z", "2026-04-01T16:10:00Z"),
            TEST_USERS["frontdesk_headers"])
        appt = validate_success(resp, expected_status=201)
        assert appt["status"] == "SCHEDULED"

    def test_provider_exact_adjacency_allowed(self, api):
        """PRD 3.9: "though exact adjacency where one appointment's end equals the
        next one's start is permitted"

        Design: Difficulty/resource_temporal_overlap/provider_half_open_overlap_no_buffer
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        pat1 = fx.create_patient(family["id"])
        pat2 = fx.create_patient(family["id"])
        prov, _ = fx.create_provider()
        chair1 = fx.create_chair(turnover_buffer_minutes=0)
        chair2 = fx.create_chair(turnover_buffer_minutes=0)
        fx.create_appointment(pat1["id"], prov["id"], chair1["id"], "EMERGENCY",
                              "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        # New appt starts exactly where the prior ended -> adjacency allowed.
        resp = api.create_appointment(
            F.create_appointment_payload(
                pat2["id"], prov["id"], chair2["id"], "EMERGENCY",
                "2026-04-01T15:30:00Z", "2026-04-01T16:00:00Z"),
            TEST_USERS["frontdesk_headers"])
        appt = validate_success(resp, expected_status=201)
        assert appt["status"] == "SCHEDULED"


# =============================================================================
# compensating_invariant
# =============================================================================

class TestCompensatingInvariantSecondAngle:

    def test_void_only_legal_from_approved(self, api):
        """PRD 3.6: "An APPROVED claim can be voided, moving it to VOID (legal
        only from APPROVED)"

        Design: Difficulty/compensating_invariant/claim_void_restores_lifetime_max_pool
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=225000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000],
                                          modality="BRACES", policy_id=policy["id"])
        claim = fx.submit_claim(policy["id"], plan["id"], 150000)
        # Still SUBMITTED (not APPROVED) -> void is rejected.
        resp = api.void_insurance_claim(claim["id"], TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reversed_payment_marks_status_reversed(self, api):
        """PRD 3.8: "A billing specialist may reverse a payment, moving its status
        from POSTED to REVERSED; reversal is legal only from POSTED and only while
        the contract's lifecycle_status is ACTIVE"

        Design: Difficulty/compensating_invariant/payment_reverse_restores_contract_balance
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(90000,), term_months=3, down_payment_cents=0)
        pay = validate_success(api.create_payment(
            F.create_payment_payload(ctx["contract"]["id"], 30000, method="CARD"),
            TEST_USERS["billing_headers"]), expected_status=201)
        reversed_pay = validate_success(api.reverse_payment(pay["id"], TEST_USERS["billing_headers"]))
        assert reversed_pay["status"] == "REVERSED"
