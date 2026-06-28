"""State-machine and cascade tests.

Translates queue A (Difficulty): non_linear_state_machine, transitive_cascade;
and queue B (Corner) state_machines-section instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId,
    make_orthodontist_headers, make_guardian_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F


# =============================================================================
# Difficulty / non_linear_state_machine
# =============================================================================

class TestNonLinearStateMachine:

    def test_proposed_to_draft_revision_cycle_bumps_version_twice(self, api):
        """PRD 3.4: "the clinician sends the plan back from PROPOSED to DRAFT for
        edits"
        PRD 3.4: "which is legal only from PROPOSED and likewise increments the
        version"
        PRD 3.4: "Proposal increments the plan's version"

        Design: Difficulty/non_linear_state_machine/treatment_plan_proposed_to_draft_revision_cycle
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        plan = fx.create_plan_with_phases(patient["id"], puid, [300000], modality="BRACES")
        proposed1 = validate_success(api.propose_treatment_plan(plan["id"], ortho))
        v_proposed1 = proposed1["version"]

        revised = validate_success(api.revise_treatment_plan(plan["id"], ortho))
        v_draft = revised["version"]
        proposed2 = validate_success(api.propose_treatment_plan(plan["id"], ortho))
        v_proposed2 = proposed2["version"]

        assert proposed2["status"] == "PROPOSED"
        assert v_draft == v_proposed1 + 1
        assert v_proposed2 == v_proposed1 + 2

    def test_contract_billing_and_lifecycle_axes_evolve_independently(self, api):
        """PRD 2.7: "the owning contract's billing_status flips from CURRENT to
        DELINQUENT"
        PRD 2.7: "the contract returns to CURRENT and the plan, if SUSPENDED,
        returns to ACTIVE"

        Design: Difficulty/non_linear_state_machine/contract_parallel_billing_and_lifecycle_axes
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(90000,), term_months=3, down_payment_cents=0)
        contract = ctx["contract"]
        inst1 = sorted(ctx["installments"], key=lambda i: i["sequence_no"])[0]

        # Advance clock past installment 1 due_at, fail the charge -> MISSED,
        # contract DELINQUENT.
        fx.set_clock("2026-03-05T00:00:00Z")
        validate_success(api.charge_installment(
            inst1["id"], {"outcome": "FAILED"}, TEST_USERS["billing_headers"]))

        delinquent = validate_success(api.get_contract(contract["id"], TEST_USERS["billing_headers"]))
        assert delinquent["billing_status"] == "DELINQUENT"
        assert delinquent["lifecycle_status"] == "ACTIVE"

        # Cure: pay the missed installment -> billing CURRENT again, lifecycle
        # still ACTIVE; the two axes moved independently.
        validate_success(api.create_payment(
            F.create_payment_payload(contract["id"], 30000, method="CARD",
                                     installment_id=inst1["id"]),
            TEST_USERS["billing_headers"]), expected_status=201)

        cured = validate_success(api.get_contract(contract["id"], TEST_USERS["billing_headers"]))
        assert cured["billing_status"] == "CURRENT"
        assert cured["lifecycle_status"] == "ACTIVE"

        inst1_final = validate_success(api.get_installment(inst1["id"], TEST_USERS["billing_headers"]))
        assert inst1_final["status"] == "PAID"


# =============================================================================
# Difficulty / transitive_cascade
# =============================================================================

class TestTransitiveCascade:

    def test_missed_payment_cascades_depth4_to_appointment_cancellation(self, api):
        """PRD 2.7: "the owning contract's billing_status flips from CURRENT to
        DELINQUENT; the owning treatment plan moves from ACTIVE to SUSPENDED; and
        every future appointment of that plan that is still SCHEDULED with a start
        strictly after the current clock value is transitioned to CANCELLED"

        Design: Difficulty/transitive_cascade/missed_payment_cascades_installment_contract_plan_appointments_depth4
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        prov, puid = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)
        fx.finalize_records_complete(patient["id"], puid)
        plan = fx.create_plan_with_phases(patient["id"], puid, [90000], modality="BRACES")
        fx.propose_plan(plan["id"], puid)
        activated = fx.activate_plan(plan["id"], family["guardian_user_id"])

        appt = fx.create_appointment(
            patient["id"], prov["id"], chair["id"], "ADJUSTMENT",
            "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z", plan_id=plan["id"])

        contract = fx.create_contract(plan["id"], activated["version"], term_months=3)
        inst1 = sorted(fx.list_installments(contract["id"]), key=lambda i: i["sequence_no"])[0]

        fx.set_clock("2026-03-05T00:00:00Z")
        validate_success(api.charge_installment(
            inst1["id"], {"outcome": "FAILED"}, TEST_USERS["billing_headers"]))

        inst1_final = validate_success(api.get_installment(inst1["id"], TEST_USERS["billing_headers"]))
        assert inst1_final["status"] == "MISSED"
        contract_final = validate_success(api.get_contract(contract["id"], TEST_USERS["billing_headers"]))
        assert contract_final["billing_status"] == "DELINQUENT"
        plan_final = validate_success(api.get_treatment_plan(plan["id"], TEST_USERS["billing_headers"]))
        assert plan_final["status"] == "SUSPENDED"
        appt_final = validate_success(api.get_appointment(appt["id"], TEST_USERS["frontdesk_headers"]))
        assert appt_final["status"] == "CANCELLED"

    def test_plan_complete_cascades_contract_close(self, api):
        """PRD 3.4: "completion is legal only from RETENTION, closes the owning
        contract by moving its lifecycle_status to CLOSED, recomputes the family
        discount, and increments the plan's version"

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
        contract = fx.create_contract(plan["id"], activated["version"], term_months=3)

        # Debond -> RETENTION (retainer issued inline), then complete -> COMPLETED.
        validate_success(api.debond_treatment_plan(plan["id"], ortho, {"retainer_type": "HAWLEY"}))
        completed = validate_success(api.complete_treatment_plan(plan["id"], ortho))
        assert completed["status"] == "COMPLETED"

        contract_final = validate_success(api.get_contract(contract["id"], TEST_USERS["billing_headers"]))
        assert contract_final["lifecycle_status"] == "CLOSED"


# =============================================================================
# Corner / state_machines
# =============================================================================

class TestStateMachineCorners:

    def test_cancel_completed_appointment_invalid_state(self, api):
        """PRD 3.9: "Front-desk staff may cancel a still-scheduled visit, moving
        it from SCHEDULED to CANCELLED (legal only from SCHEDULED)"
        PRD 3.9: "COMPLETED, CANCELLED, and NO_SHOW are terminal"

        Design: Corner/state_machines/cancel_appointment_from_completed_returns_invalid_state
        """
        fx.set_clock("2026-04-01T15:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        prov, puid = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)
        appt = fx.create_appointment(
            patient["id"], prov["id"], chair["id"], "EMERGENCY",
            "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        validate_success(api.checkin_appointment(appt["id"], TEST_USERS["frontdesk_headers"]))
        validate_success(api.complete_appointment(appt["id"], make_orthodontist_headers(puid)))

        resp = api.cancel_appointment(appt["id"], TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_finalize_growth_record_twice_invalid_state(self, api):
        """PRD 3.2: "Finalization is only legal from DRAFT; attempting it from any
        other state is rejected with ERR_INVALID_STATE"

        Design: Corner/state_machines/finalize_growth_record_twice_returns_invalid_state
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        gr = get_success_data(api.create_growth_record(
            F.create_growth_record_payload(patient["id"], "PANO", taken_at="2026-01-01T00:00:00Z"),
            ortho))
        validate_success(api.finalize_growth_record(gr["id"], ortho))

        resp = api.finalize_growth_record(gr["id"], ortho)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_already_approved_claim_invalid_state(self, api):
        """PRD 3.6: "Approval is legal only from SUBMITTED"
        PRD 3.6: "The policy's remaining_max_cents is then reduced by that awarded
        benefit"

        Design: Corner/state_machines/approve_already_approved_claim_returns_invalid_state
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=300000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000],
                                          modality="BRACES", policy_id=policy["id"])
        claim = fx.submit_claim(policy["id"], plan["id"], 100000)
        fx.approve_claim(claim["id"])  # benefit 50000 -> remaining 250000

        resp = api.approve_insurance_claim(claim["id"], TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        pol = validate_success(api.get_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))
        assert pol["remaining_max_cents"] == 250000

    def test_activate_plan_from_draft_invalid_state(self, api):
        """PRD 3.4: "Activation is legal only from PROPOSED"

        Design: Corner/state_machines/activate_plan_from_draft_returns_invalid_state
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000], modality="BRACES")
        # Never proposed -> still DRAFT.
        resp = api.activate_treatment_plan(plan["id"], make_guardian_headers(family["guardian_user_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_terminate_already_terminated_policy_invalid_state(self, api):
        """PRD 3.6: "A billing specialist may terminate a policy, moving its
        status from ACTIVE to TERMINATED; termination is legal only from ACTIVE"

        Design: Corner/state_machines/terminate_already_terminated_policy_returns_invalid_state
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        policy = fx.create_policy(patient["id"], ortho_rider=False,
                                  ortho_coverage_pct=0.0, lifetime_max_cents=0)
        validate_success(api.terminate_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))

        resp = api.terminate_insurance_policy(policy["id"], TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_prior_pano_superseded_when_new_pano_finalized(self, api):
        """PRD 3.2: "if a FINALIZED growth record of the same record_type already
        exists for that patient, that prior record is transitioned to SUPERSEDED"

        Design: Corner/state_machines/prior_pano_superseded_when_new_pano_finalized
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        pano1 = get_success_data(api.create_growth_record(
            F.create_growth_record_payload(patient["id"], "PANO", taken_at="2026-01-01T00:00:00Z"), ortho))
        validate_success(api.finalize_growth_record(pano1["id"], ortho))
        pano2 = get_success_data(api.create_growth_record(
            F.create_growth_record_payload(patient["id"], "PANO", taken_at="2026-02-01T00:00:00Z"), ortho))
        validate_success(api.finalize_growth_record(pano2["id"], ortho))

        gr1 = validate_success(api.get_growth_record(pano1["id"], ortho))
        gr2 = validate_success(api.get_growth_record(pano2["id"], ortho))
        assert gr1["status"] == "SUPERSEDED"
        assert gr2["status"] == "FINALIZED"

    def test_retainer_replace_marks_old_replaced(self, api):
        """PRD 3.10: "a clinician replaces it, moving the old retainer's status
        from ISSUED to REPLACED (legal only from ISSUED) and issuing a fresh
        retainer for the same plan in ISSUED status with issued_at set to the
        current clock value"

        Design: Corner/state_machines/retainer_replace_issues_new_retainer
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        fx.finalize_records_complete(patient["id"], puid)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000], modality="BRACES")
        fx.propose_plan(plan["id"], puid)
        fx.activate_plan(plan["id"], family["guardian_user_id"])
        validate_success(api.debond_treatment_plan(plan["id"], ortho, {"retainer_type": "HAWLEY"}))

        retainers, _meta = validate_paginated(
            api.list_retainers(ortho, params={"plan_id": plan["id"]}))
        ret1_id = sorted(retainers, key=lambda r: r["created_at"])[0]["id"]

        validate_success(api.replace_retainer(ret1_id, ortho, {"retainer_type": "CLEAR"}))
        ret1 = validate_success(api.get_retainer(ret1_id, ortho))
        assert ret1["status"] == "REPLACED"
