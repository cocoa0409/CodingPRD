"""Validation, priority-conflict, cross-entity-state and scheduling-overlap tests.

Translates queue A (Difficulty): priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap; and queue B (Corner)
validations-section instances.
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
# Difficulty / priority_pair_validation_conflict
# =============================================================================

class TestValidationPriorityConflicts:

    def test_invalid_state_beats_down_payment_exceeds(self, api):
        """PRD 2.10: "followed by the state-machine legality check that the target
        is in a state from which the requested transition is defined
        (ERR_INVALID_STATE)... then the down-payment fiscal guard on contract
        creation (ERR_DOWN_PAYMENT_EXCEEDS)"
        PRD 2.10: "Earlier checks mask later ones"

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_down_payment_exceeds_on_contract
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        # Plan stays in DRAFT (never proposed/activated) -> est_resp unset; a
        # 999999 down payment also violates the fiscal guard.
        plan = get_success_data(api.create_treatment_plan(
            F.create_treatment_plan_payload(patient["id"], modality="BRACES"), ortho))
        resp = api.create_contract(
            F.create_contract_payload(plan["id"], plan["version"],
                                      term_months=3, down_payment_cents=999999),
            TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cross_entity_state_beats_provider_conflict(self, api):
        """PRD 2.10: "After legality, cross-entity state preconditions are
        evaluated (ERR_CROSS_ENTITY_STATE)... then the provider temporal-overlap
        check (ERR_PROVIDER_CONFLICT)"
        PRD 3.9: "an ADJUSTMENT visit needs its plan ACTIVE"

        Design: Difficulty/priority_pair_validation_conflict/cross_entity_state_beats_provider_conflict_on_appointment
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patX = fx.create_patient(family["id"])
        patY = fx.create_patient(family["id"])
        prov, puid = fx.create_provider()
        chair2 = fx.create_chair(turnover_buffer_minutes=10)
        chair3 = fx.create_chair(turnover_buffer_minutes=10)

        # Provider already booked 15:00-15:30 (EMERGENCY, no plan).
        fx.create_appointment(patX["id"], prov["id"], chair2["id"], "EMERGENCY",
                              "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        # Patient Y plan still DRAFT.
        planY = fx.create_plan_with_phases(patY["id"], puid, [100000], modality="BRACES")

        # ADJUSTMENT against a DRAFT plan, also colliding on the provider's
        # calendar: the higher-priority cross-entity-state check wins.
        resp = api.create_appointment(
            F.create_appointment_payload(
                patY["id"], prov["id"], chair3["id"], "ADJUSTMENT",
                "2026-04-01T15:15:00Z", "2026-04-01T15:45:00Z", plan_id=planY["id"]),
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)


# =============================================================================
# Difficulty / cross_entity_state_dependency
# =============================================================================

class TestCrossEntityStateDependency:

    def test_adjustment_against_proposed_plan_rejected(self, api):
        """PRD 3.9: "The cross-entity precondition requires that any referenced
        plan is in the state the visit requires"
        PRD 3.9: "an ADJUSTMENT visit needs its plan ACTIVE"
        PRD 3.9: "a violation is rejected with ERR_CROSS_ENTITY_STATE"

        Design: Difficulty/cross_entity_state_dependency/adjustment_appointment_requires_plan_active
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        prov, puid = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000], modality="BRACES")
        fx.propose_plan(plan["id"], puid)  # PROPOSED, not ACTIVE

        resp = api.create_appointment(
            F.create_appointment_payload(
                patient["id"], prov["id"], chair["id"], "ADJUSTMENT",
                "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z", plan_id=plan["id"]),
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)

    def test_claim_approval_requires_policy_active(self, api):
        """PRD 3.6: "it additionally requires that the owning policy is ACTIVE
        (otherwise ERR_POLICY_TERMINATED)"

        Design: Difficulty/cross_entity_state_dependency/claim_approval_requires_policy_active
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        fx.finalize_records_complete(patient["id"], puid)
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=300000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000],
                                          modality="BRACES", policy_id=policy["id"])
        claim = fx.submit_claim(policy["id"], plan["id"], 100000)
        # A SUBMITTED (not APPROVED) claim does not block termination.
        validate_success(api.terminate_insurance_policy(policy["id"], TEST_USERS["billing_headers"]))

        resp = api.approve_insurance_claim(claim["id"], TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_POLICY_TERMINATED)


# =============================================================================
# Difficulty / resource_temporal_overlap
# =============================================================================

class TestResourceTemporalOverlap:

    def test_chair_overlap_with_turnover_buffer(self, api):
        """PRD 3.9: "the requested interval extended by the chair's
        turnover_buffer_minutes"
        PRD 3.9: "the half-open interval that runs from the appointment's start up
        to but not including its end plus the buffer"
        PRD 3.9: "must not overlap any non-terminal appointment already booked in
        that chair; an overlap is rejected with ERR_CHAIR_CONFLICT"

        Design: Difficulty/resource_temporal_overlap/chair_overlap_with_turnover_buffer_closed_interval
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        pat1 = fx.create_patient(family["id"])
        pat2 = fx.create_patient(family["id"])
        prov1, _ = fx.create_provider()
        prov2, _ = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)

        # Existing 15:00-15:30 in this chair blocks through 15:40 (30 + 10 buffer).
        fx.create_appointment(pat1["id"], prov1["id"], chair["id"], "EMERGENCY",
                              "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        # New 15:35-16:05 in the same chair (different provider) overlaps the buffer.
        resp = api.create_appointment(
            F.create_appointment_payload(
                pat2["id"], prov2["id"], chair["id"], "EMERGENCY",
                "2026-04-01T15:35:00Z", "2026-04-01T16:05:00Z"),
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_CHAIR_CONFLICT)

    def test_provider_half_open_overlap_no_buffer(self, api):
        """PRD 3.9: "the requested half-open interval from start up to but not
        including end must not overlap any non-terminal appointment for the same
        provider"
        PRD 3.9: "an overlap is rejected with ERR_PROVIDER_CONFLICT"

        Design: Difficulty/resource_temporal_overlap/provider_half_open_overlap_no_buffer
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        pat1 = fx.create_patient(family["id"])
        pat2 = fx.create_patient(family["id"])
        prov, _ = fx.create_provider()
        chair6 = fx.create_chair(turnover_buffer_minutes=10)
        chair7 = fx.create_chair(turnover_buffer_minutes=10)

        # Same provider booked 15:00-15:30 in chair6.
        fx.create_appointment(pat1["id"], prov["id"], chair6["id"], "EMERGENCY",
                              "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        # New 15:15-15:45 in a different chair overlaps the provider's interval.
        resp = api.create_appointment(
            F.create_appointment_payload(
                pat2["id"], prov["id"], chair7["id"], "EMERGENCY",
                "2026-04-01T15:15:00Z", "2026-04-01T15:45:00Z"),
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_PROVIDER_CONFLICT)


# =============================================================================
# Corner / validations
# =============================================================================

class TestValidationCorners:

    def test_propose_plan_without_phases_no_phases(self, api):
        """PRD 3.4: "only when the plan has at least one treatment phase; a plan
        with no phases is rejected with ERR_NO_PHASES"

        Design: Corner/validations/propose_plan_without_phases_returns_no_phases
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        plan = get_success_data(api.create_treatment_plan(
            F.create_treatment_plan_payload(patient["id"], modality="BRACES"), ortho))
        resp = api.propose_treatment_plan(plan["id"], ortho)
        validate_error(resp, ApiErrorId.ERR_NO_PHASES)

    def test_activate_plan_without_records_records_incomplete(self, api):
        """PRD 3.4: "only when the patient's records_complete is true; otherwise
        the activation is rejected with ERR_RECORDS_INCOMPLETE"

        Design: Corner/validations/activate_plan_without_records_returns_records_incomplete
        """
        ctx = fx.setup_proposed_plan([100000], records_complete=False)
        resp = api.activate_treatment_plan(
            ctx["plan"]["id"], make_guardian_headers(ctx["guardian_user_id"]))
        validate_error(resp, ApiErrorId.ERR_RECORDS_INCOMPLETE)

    def test_approve_claim_without_rider_no_ortho_rider(self, api):
        """PRD 3.6: "that the policy carries an ortho rider (otherwise
        ERR_NO_ORTHO_RIDER)"

        Design: Corner/validations/approve_claim_without_rider_returns_no_ortho_rider
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        policy = fx.create_policy(patient["id"], ortho_rider=False,
                                  ortho_coverage_pct=0.0, lifetime_max_cents=0)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000],
                                          modality="BRACES", policy_id=policy["id"])
        claim = fx.submit_claim(policy["id"], plan["id"], 50000)
        resp = api.approve_insurance_claim(claim["id"], TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_ORTHO_RIDER)

    def test_terminate_policy_with_approved_claim_open_claims(self, api):
        """PRD 3.6: "termination is legal only from ACTIVE and additionally is
        refused while any claim on that policy is in APPROVED status"
        PRD 3.6: "that refusal carries ERR_POLICY_HAS_OPEN_CLAIMS"

        Design: Corner/validations/terminate_policy_with_approved_claim_returns_open_claims
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=200000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000],
                                          modality="BRACES", policy_id=policy["id"])
        claim = fx.submit_claim(policy["id"], plan["id"], 50000)
        fx.approve_claim(claim["id"])  # APPROVED, unpaid

        resp = api.terminate_insurance_policy(policy["id"], TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_POLICY_HAS_OPEN_CLAIMS)

    def test_charge_installment_before_due_not_yet_due(self, api):
        """PRD 3.7: "A failed charge sets the installment to MISSED, but only when
        the logical clock has reached or passed the installment's due_at; a failed
        charge attempted before the due date is rejected with ERR_NOT_YET_DUE"

        Design: Corner/validations/charge_installment_before_due_returns_not_yet_due
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(90000,), term_months=3, down_payment_cents=0)
        inst1 = sorted(ctx["installments"], key=lambda i: i["sequence_no"])[0]
        # Clock still at activation time (2026-02-01), before installment 1 due_at.
        resp = api.charge_installment(inst1["id"], {"outcome": "FAILED"}, TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_YET_DUE)

    def test_overpayment_exceeds_balance(self, api):
        """PRD 3.8: "A payment may not exceed the contract's balance_remaining_cents;
        an overpayment is rejected with ERR_OVERPAYMENT"

        Design: Corner/validations/overpayment_exceeds_balance_returns_overpayment
        """
        ctx = fx.setup_active_plan_with_contract(
            phase_fees=(90000,), term_months=3, down_payment_cents=0)
        resp = api.create_payment(
            F.create_payment_payload(ctx["contract"]["id"], 999999, method="CARD"),
            TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

    def test_down_payment_exceeds_responsibility(self, api):
        """PRD 3.7: "this must be at least zero, so a down payment exceeding the
        plan's estimated patient responsibility is rejected with
        ERR_DOWN_PAYMENT_EXCEEDS"

        Design: Corner/validations/down_payment_exceeds_responsibility_returns_error
        """
        ctx = fx.setup_active_plan([90000])  # est_resp 90000 self-pay
        resp = api.create_contract(
            F.create_contract_payload(ctx["plan"]["id"], ctx["plan"]["version"],
                                      term_months=3, down_payment_cents=999999),
            TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_DOWN_PAYMENT_EXCEEDS)

    def test_checkin_too_early(self, api):
        """PRD 3.9: "check-in is legal only from SCHEDULED and only once the
        logical clock has reached the window that opens 60 minutes before
        starts_at"
        PRD 3.9: "an attempt more than 60 minutes early is rejected with
        ERR_TOO_EARLY_CHECKIN"

        Design: Corner/validations/checkin_too_early_returns_too_early_checkin
        """
        fx.set_clock("2026-04-01T13:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        prov, _ = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)
        appt = fx.create_appointment(patient["id"], prov["id"], chair["id"], "EMERGENCY",
                                     "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        resp = api.checkin_appointment(appt["id"], TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_TOO_EARLY_CHECKIN)

    def test_noshow_before_start(self, api):
        """PRD 3.9: "moving the appointment to NO_SHOW, but only once the logical
        clock has reached starts_at; marking a no-show before the start is rejected
        with ERR_TOO_EARLY_NOSHOW"

        Design: Corner/validations/noshow_before_start_returns_too_early_noshow
        """
        fx.set_clock("2026-04-01T14:59:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        prov, _ = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)
        appt = fx.create_appointment(patient["id"], prov["id"], chair["id"], "EMERGENCY",
                                     "2026-04-01T15:00:00Z", "2026-04-01T15:30:00Z")
        resp = api.noshow_appointment(appt["id"], TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_TOO_EARLY_NOSHOW)

    def test_appointment_ends_before_starts_invalid_request(self, api):
        """PRD 3.9: "The end must be strictly after the start, or the request fails
        with ERR_INVALID_REQUEST"

        Design: Corner/validations/appointment_ends_before_starts_returns_invalid_request
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        prov, _ = fx.create_provider()
        chair = fx.create_chair(turnover_buffer_minutes=10)
        resp = api.create_appointment(
            F.create_appointment_payload(
                patient["id"], prov["id"], chair["id"], "EMERGENCY",
                "2026-04-01T15:30:00Z", "2026-04-01T15:00:00Z"),
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_coverage_pct_out_of_range_validation(self, api):
        """PRD 2.5: "a value outside the closed interval from 0 to 1 is
        semantically invalid and rejected with ERR_VALIDATION (HTTP 422) even
        though it is shape-valid"

        Design: Corner/validations/coverage_pct_out_of_range_returns_validation
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        resp = api.create_insurance_policy(
            F.create_insurance_policy_payload(
                patient["id"], carrier_name="Bad", ortho_rider=True,
                ortho_coverage_pct=1.5, lifetime_max_cents=100000),
            TEST_USERS["billing_headers"])
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
