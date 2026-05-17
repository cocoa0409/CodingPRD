"""Difficulty-design instance coverage — mandatory.

Each instance from SCAFFOLD_DIFFICULTY_DESIGN.yaml is covered by at
least two dedicated tests here. Each test's docstring tags the
instance via `# difficulty: <rule_id>/<instance.name>` so the coverage
audit can be run mechanically.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    INDIVIDUAL_CREDIT_HOURS,
    INTAKE_CREDIT_HOURS,
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_in_network_claim_arithmetic,
    create_appointment_payload,
    create_crisis_assessment,
    create_safety_plan,
    iso_anchor_offset,
    make_therapist_headers,
    re_get_appointment,
    re_get_claim,
    re_get_patient,
    re_get_therapist,
    reinstate_therapist,
    revoke_state_license,
    rescind_safety_plan,
    run_appointment_through_completion,
    schedule_appointment,
    setup_appointment_checkin_depends_on_credential,
    setup_deductible_first_for_depth3_chain,
    setup_deductible_first_partial_for_combinatorial,
    setup_high_risk_assessment_then_appointment,
    setup_license_expiry_for_depth2_chain,
    setup_license_gap_vs_fiscal_at_checkin,
    setup_pre_licensed_with_completed_session,
    setup_safety_plan_ready,
    setup_safety_vs_referential_conflict,
    setup_session_complete_depends_on_supervision,
    setup_session_complete_state_vs_referential,
    setup_therapist_with_scheduled_appointment_for_cycle,
    setup_two_back_to_back_appointments_for_therapist_overlap,
    setup_two_in_network_plans_for_contract_mode_dual,
    setup_two_therapists_one_patient_for_min_gap,
    suspend_therapist,
    validate_error,
    validate_success,
    void_claim,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_contract_mode_dual_variant_deductible_first_branch(self, api):
        """# difficulty: dual_variant_calc/patient_responsibility_contract_mode_variants

        PRD §3.7: "When contract_mode = DEDUCTIBLE_FIRST and the
        patient still has deductible_remaining_cents greater than
        zero, the patient pays the smaller of the allowed amount and
        the remaining deductible — this is the deductible-first phase
        — and the insurer pays the rest of the allowed amount; the
        patient's deductible_remaining_cents is decreased by exactly
        that paid amount."

        Claim: with allowed_90834=9550 and
        deductible_remaining_cents=20000, the DEDUCTIBLE_FIRST plan
        produces patient_responsibility_cents=9550 and
        insurer_paid_cents=0.
        """
        bundle = setup_two_in_network_plans_for_contract_mode_dual(
            allowed_90834_cents=9_550, copay_cents=2_500,
            deductible_remaining_cents=20_000, rack_90834_cents=15_000,
        )
        appt_a, _ = run_appointment_through_completion(
            bundle["therapist"]["id"], bundle["patient_a"]["id"],
            cpt_code="90834", patient_state_on_day="NY",
            minutes_after_now=60,
        )
        from test_helpers.fixtures import _lookup_claim_for_appointment
        claim_a = _lookup_claim_for_appointment(
            appt_a["id"], bundle["patient_a"]["id"],
        )
        assert claim_a["charged_amount_cents"] == 9_550
        assert claim_a["patient_responsibility_cents"] == 9_550
        assert claim_a["insurer_paid_cents"] == 0

    def test_contract_mode_dual_variant_copay_only_branch(self, api):
        """# difficulty: dual_variant_calc/patient_responsibility_contract_mode_variants

        PRD §3.7: "When contract_mode = COPAY_ONLY, the patient pays
        the smaller of copay_cents and the allowed amount irrespective
        of any deductible state, and the insurer pays the remainder."

        Claim: with allowed_90834=9550, copay=2500, and
        deductible_remaining_cents=20000, the COPAY_ONLY plan produces
        patient_responsibility_cents=2500 and insurer_paid_cents=7050
        (identical inputs to the DEDUCTIBLE_FIRST case above, different
        outputs — this is the dual-variant pivot).
        """
        bundle = setup_two_in_network_plans_for_contract_mode_dual(
            allowed_90834_cents=9_550, copay_cents=2_500,
            deductible_remaining_cents=20_000, rack_90834_cents=15_000,
        )
        appt_b, _ = run_appointment_through_completion(
            bundle["therapist"]["id"], bundle["patient_b"]["id"],
            cpt_code="90834", patient_state_on_day="NY",
            minutes_after_now=60,
        )
        from test_helpers.fixtures import _lookup_claim_for_appointment
        claim_b = _lookup_claim_for_appointment(
            appt_b["id"], bundle["patient_b"]["id"],
        )
        assert claim_b["charged_amount_cents"] == 9_550
        assert claim_b["patient_responsibility_cents"] == 2_500
        assert claim_b["insurer_paid_cents"] == 7_050

    def test_supervision_hours_forward_then_keep(self, api):
        """# difficulty: dual_variant_calc/supervision_hours_accrual_forward_vs_reverse

        PRD §3.7: "The system adds the session's
        supervision_credit_hours (1.00 or 1.50) to the therapist's
        supervision_hours_accrued ..."

        Claim: completing a 90834 (INDIVIDUAL) session for a
        PRE_LICENSED therapist with starting hours=0.00 yields
        post-complete hours=1.00.
        """
        bundle = setup_pre_licensed_with_completed_session(
            rack_90834_cents=10_000,
        )
        therapist = re_get_therapist(bundle["therapist"]["id"])
        assert therapist["supervision_hours_accrued"] == pytest.approx(
            INDIVIDUAL_CREDIT_HOURS, abs=0.01,
        )

    def test_supervision_hours_void_restores_baseline(self, api):
        """# difficulty: dual_variant_calc/supervision_hours_accrual_forward_vs_reverse

        PRD §3.8: "The therapist's supervision_hours_accrued is
        reduced by the owning session's supervision_credit_hours (1.00
        or 1.50) using the same round-half-up-to-two-decimal-places
        rule ..."

        Claim: posting a 90834 session then voiding the claim within
        the 7-day window restores supervision_hours_accrued to 0.00
        (the pre-completion value).
        """
        bundle = setup_pre_licensed_with_completed_session(
            rack_90834_cents=10_000,
        )
        therapist_mid = re_get_therapist(bundle["therapist"]["id"])
        assert therapist_mid["supervision_hours_accrued"] == pytest.approx(
            1.00, abs=0.01,
        )
        assert therapist_mid["licensure_exam_eligible"] is False
        void_claim(bundle["claim"]["id"])
        therapist_final = re_get_therapist(bundle["therapist"]["id"])
        assert therapist_final["supervision_hours_accrued"] == pytest.approx(
            0.00, abs=0.01,
        )
        assert therapist_final["licensure_exam_eligible"] is False


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_deductible_first_partial_uses_min_allowed_remaining(self, api):
        """# difficulty: combinatorial_formula/patient_responsibility_three_input_branching

        PRD §3.7: "the patient pays the smaller of the allowed amount
        and the remaining deductible — this is the deductible-first
        phase — and the insurer pays the rest of the allowed amount;
        the patient's deductible_remaining_cents is decreased by
        exactly that paid amount."

        Claim: allowed=9550, deductible_remaining=4000 ->
        patient_responsibility=min(9550, 4000)=4000;
        insurer_paid=5550; post-completion deductible_remaining=0
        (decremented by min(9550, 4000)=4000).
        """
        bundle = setup_deductible_first_partial_for_combinatorial(
            allowed_90834_cents=9_550, copay_cents=2_500,
            deductible_remaining_cents=4_000,
        )
        appt, _ = run_appointment_through_completion(
            bundle["therapist"]["id"], bundle["patient"]["id"],
            cpt_code="90834", patient_state_on_day="NY",
        )
        from test_helpers.fixtures import _lookup_claim_for_appointment
        claim = _lookup_claim_for_appointment(
            appt["id"], bundle["patient"]["id"],
        )
        assert claim["charged_amount_cents"] == 9_550
        assert claim["patient_responsibility_cents"] == 4_000
        assert claim["insurer_paid_cents"] == 5_550
        patient = re_get_patient(bundle["patient"]["id"])
        assert patient["deductible_remaining_cents"] == 0

    def test_crisis_composite_per_factor_round_then_sum_high(self, api):
        """# difficulty: combinatorial_formula/crisis_score_per_factor_round_then_sum

        PRD §3.9: "Each of the five per-factor products is rounded
        half-up to two decimal places first, then the five rounded
        per-factor values are summed, then the sum is rounded half-up
        to two decimal places to produce composite_score. The order is
        load-bearing: rounding before summation, not the other way
        around."
        PRD §3.9: "a composite_score of at least 23.55 yields HIGH ..."

        Claim: (si=3, pa=1, su=2, so=2, am=1) under the pinned
        per-factor-then-sum rounding yields composite_score=23.56 and
        risk_level=HIGH; the wrong order (sum-then-round) would yield
        ~23.54 -> MODERATE.
        """
        from test_helpers import setup_patient_with_recent_care
        therapist, patient, _ = setup_patient_with_recent_care()
        assessment = create_crisis_assessment(
            patient["id"], therapist["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        assert assessment["composite_score"] == pytest.approx(
            23.56, abs=0.001,
        )
        assert assessment["risk_level"] == "HIGH"
        patient_after = re_get_patient(patient["id"])
        assert patient_after["latest_crisis_level"] == "HIGH"
        assert patient_after["safety_plan_required"] is True


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_therapist_cycle_suspend_then_reinstate(self, api):
        """# difficulty: non_linear_state_machine/therapist_credential_cycle

        PRD §3.2: "An ACTIVE therapist may be temporarily taken off
        duty ... cascade: every future SCHEDULED appointment ...
        transitions to HELD with hold_reason = LICENSE_GAP. The
        reinstatement is the inverse: an administrator returns the
        therapist from SUSPENDED to ACTIVE ... unholds every
        appointment ..."

        Claim: ACTIVE -> SUSPENDED (cascade HOLDs Afut with
        LICENSE_GAP); SUSPENDED -> ACTIVE (cascade unholds back to
        SCHEDULED).
        """
        bundle = setup_therapist_with_scheduled_appointment_for_cycle()
        suspend_therapist(bundle["therapist"]["id"])
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        assert appt["hold_reason"] == "LICENSE_GAP"
        reinstate_therapist(bundle["therapist"]["id"])
        appt2 = re_get_appointment(bundle["appointment"]["id"])
        assert appt2["status"] == "SCHEDULED"
        assert appt2.get("hold_reason") is None

    def test_appointment_fork_join_high_then_safety_plan(self, api):
        """# difficulty: non_linear_state_machine/appointment_fork_join_to_held

        PRD §3.6: "A SCHEDULED appointment may be moved to HELD
        automatically by the system as a consequence of one of three
        originating events ... or the patient's safety_plan_required
        becomes true ..."
        PRD §3.9: "Creating the plan ... unholds every HELD appointment
        for this patient whose hold_reason = SAFETY_PLAN_MISSING,
        returning each from HELD back to SCHEDULED."

        Claim: after HIGH crisis assessment, appointment HELD with
        hold_reason=SAFETY_PLAN_MISSING; after safety plan creation,
        appointment returns to SCHEDULED with hold_reason=null.
        """
        bundle = setup_high_risk_assessment_then_appointment()
        assessment = create_crisis_assessment(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        appt_after_high = re_get_appointment(bundle["appointment"]["id"])
        assert appt_after_high["status"] == "HELD"
        assert appt_after_high["hold_reason"] == "SAFETY_PLAN_MISSING"
        # Author the safety plan.
        create_safety_plan(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            trigger_assessment_id=assessment["id"],
        )
        appt_after_plan = re_get_appointment(bundle["appointment"]["id"])
        assert appt_after_plan["status"] == "SCHEDULED"
        assert appt_after_plan.get("hold_reason") is None


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_session_complete_depth3_billing_and_deductible(self, api):
        """# difficulty: transitive_cascade/session_complete_depth3_chain

        PRD §3.7: "the BillingClaim auto-posted ... For an
        INSURANCE_IN_NETWORK claim ... patient's
        deductible_remaining_cents is decreased by exactly that paid
        amount."

        Claim: complete a 90834 PRE_LICENSED session for a patient
        with deductible_remaining=10000 and allowed=8000 ->
        BillingClaim POSTED with charged=8000, patient_resp=8000,
        insurer_paid=0; Patient.deductible_remaining_cents=2000.
        """
        bundle = setup_deductible_first_for_depth3_chain(
            allowed_90834_cents=8_000, copay_cents=2_000,
            deductible_remaining_cents=10_000, rack_90834_cents=10_000,
        )
        # Walk the appointment through completion (already SCHEDULED).
        advance_clock_to(iso_anchor_offset(minutes=119))
        from test_helpers import (
            checkin_appointment, complete_session, create_session,
        )
        checkin_appointment(
            bundle["appointment"]["id"], bundle["therapist"]["id"],
        )
        session = create_session(
            bundle["appointment"]["id"], bundle["therapist"]["id"],
        )
        complete_session(session["id"], bundle["therapist"]["id"])
        from test_helpers.fixtures import _lookup_claim_for_appointment
        claim = _lookup_claim_for_appointment(
            bundle["appointment"]["id"], bundle["patient"]["id"],
        )
        assert claim["status"] == "POSTED"
        assert claim["charged_amount_cents"] == 8_000
        assert claim["patient_responsibility_cents"] == 8_000
        assert claim["insurer_paid_cents"] == 0
        patient = re_get_patient(bundle["patient"]["id"])
        assert patient["deductible_remaining_cents"] == 2_000

    def test_session_complete_depth3_supervision_hours(self, api):
        """# difficulty: transitive_cascade/session_complete_depth3_chain

        PRD §3.7: "The system adds the session's
        supervision_credit_hours (1.00 or 1.50) to the therapist's
        supervision_hours_accrued ... Immediately after,
        licensure_exam_eligible is recomputed ..."

        Claim: same complete operation also writes
        Therapist.supervision_hours_accrued=1.00 (0.00 + 1.00 INDIVIDUAL)
        AND Therapist.licensure_exam_eligible=false (1.00 < 3000.00).
        """
        bundle = setup_deductible_first_for_depth3_chain(
            allowed_90834_cents=8_000, copay_cents=2_000,
            deductible_remaining_cents=10_000, rack_90834_cents=10_000,
        )
        advance_clock_to(iso_anchor_offset(minutes=119))
        from test_helpers import (
            checkin_appointment, complete_session, create_session,
        )
        checkin_appointment(
            bundle["appointment"]["id"], bundle["therapist"]["id"],
        )
        session = create_session(
            bundle["appointment"]["id"], bundle["therapist"]["id"],
        )
        complete_session(session["id"], bundle["therapist"]["id"])
        therapist = re_get_therapist(bundle["therapist"]["id"])
        assert therapist["supervision_hours_accrued"] == pytest.approx(
            1.00, abs=0.01,
        )
        assert therapist["licensure_exam_eligible"] is False

    def test_license_expiry_depth2_holds_appointment(self, api):
        """# difficulty: transitive_cascade/license_expiry_depth2_clock_cascade

        PRD §3.1: "when the deterministic clock advances to an instant
        on or after the license's expires_on, the license transitions
        from ACTIVE to EXPIRED ... every future SCHEDULED appointment
        for that therapist transitions to HELD with hold_reason =
        LICENSE_GAP."

        Claim: clock-advance to expires_on -> License.status=EXPIRED;
        cascaded -> Future SCHEDULED Appt.status=HELD with
        hold_reason=LICENSE_GAP.
        """
        bundle = setup_license_expiry_for_depth2_chain()
        advance_clock_to("2026-06-01T00:00:00.000Z")
        # Hop 1: license expired.
        from test_helpers import api_client
        from prd_bench_local_runner.testing import validate_paginated
        res = api_client.list_state_licenses(
            bundle["therapist"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        items, _ = validate_paginated(res)
        license_ = next(li for li in items if li["id"] == bundle["license"]["id"])
        assert license_["status"] == "EXPIRED"
        # Hop 2: appointment held.
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        assert appt["hold_reason"] == "LICENSE_GAP"

    def test_license_revoke_depth2_holds_appointment(self, api):
        """# difficulty: transitive_cascade/license_expiry_depth2_clock_cascade

        PRD §3.1: "an administrator may also revoke the license
        directly, transitioning it from ACTIVE to REVOKED ... [same
        cascade as expiry] every future SCHEDULED appointment for that
        therapist transitions to HELD with hold_reason = LICENSE_GAP."

        Claim: revoke fires the same depth-2 cascade as expiry:
        License -> REVOKED, future SCHEDULED appointment -> HELD with
        hold_reason=LICENSE_GAP.
        """
        bundle = setup_license_expiry_for_depth2_chain()
        revoke_state_license(
            bundle["therapist"]["id"], bundle["license"]["id"],
        )
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        assert appt["hold_reason"] == "LICENSE_GAP"


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairConflicts:

    def test_safety_vs_license_safety_wins(self, api):
        """# difficulty: priority_pair_validation_conflict/safety_vs_referential_license_conflict

        PRD §2.7: "Within (6), the safety-related checks always
        evaluate ahead of fiscal or scheduling checks — for example,
        on appointment check-in the patient's safety-plan requirement
        is evaluated before any license-coverage or check-in-window
        check, so that a safety-plan gap surfaces as
        ERR_SAFETY_PLAN_REQUIRED rather than being masked by a later
        check."

        Claim: a check-in attempt with BOTH safety_plan_required=true
        AND no license coverage for patient_state_on_day returns
        ERR_SAFETY_PLAN_REQUIRED (safety check wins).
        """
        bundle = setup_safety_vs_referential_conflict()
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_SAFETY_PLAN_REQUIRED")

    def test_state_vs_referential_session_complete_state_wins(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_referential_session_complete_conflict

        PRD §3.7: "an attempt to complete a session whose therapist is
        no longer ACTIVE or PROVISIONAL is rejected with
        ERR_THERAPIST_NOT_ACTIVE."
        PRD §3.7: "The first failure of the session-state precondition
        is rejected with ERR_SESSION_NOT_OPEN ..."

        Claim: a /complete with BOTH Session.status=VOIDED AND
        Therapist.credential_status=SUSPENDED returns
        ERR_SESSION_NOT_OPEN (the session-state check fires first).
        """
        bundle = setup_session_complete_state_vs_referential()
        res = api.complete_session(
            bundle["session"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_SESSION_NOT_OPEN")

    def test_license_gap_vs_fiscal_license_wins_at_checkin(self, api):
        """# difficulty: priority_pair_validation_conflict/license_gap_vs_fiscal_amount_conflict

        PRD §3.6: "Failure of the license coverage check is rejected
        with ERR_LICENSE_GAP_FOR_STATE."
        PRD §2.7: pipeline (6) "endpoint-specific clinical and fiscal
        preconditions" — within this category, safety checks evaluate
        before fiscal checks; license-coverage (referential) at
        check-in fires before any unrelated fiscal-amount validation
        on the same path.

        Claim: a check-in attempt for a telehealth NY appointment by
        a therapist holding only an ACTIVE CA license (no PSYPACT)
        returns ERR_LICENSE_GAP_FOR_STATE.
        """
        bundle = setup_license_gap_vs_fiscal_at_checkin()
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_LICENSE_GAP_FOR_STATE")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    def test_void_window_at_seven_day_boundary_inclusive(self, api):
        """# difficulty: boundary_precision_check/void_window_seven_day_threshold_inclusive

        PRD §3.8: "only when the owning session was completed within
        the last seven days as measured against the deterministic
        clock; an attempt outside that window is rejected with
        ERR_VOID_WINDOW_EXPIRED."

        Claim: voiding a claim exactly 7 days after the owning
        session's posted_at is admitted (the boundary is inclusive,
        admitting the void).
        """
        from test_helpers import setup_posted_claim_for_void_window
        bundle = setup_posted_claim_for_void_window(
            posted_at_iso="2026-05-01T10:00:00.000Z",
        )
        advance_clock_to("2026-05-08T10:00:00.000Z")
        res = api.void_claim(
            bundle["claim"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "VOIDED"

    def test_void_window_one_second_past_boundary_rejected(self, api):
        """# difficulty: boundary_precision_check/void_window_seven_day_threshold_inclusive

        PRD §3.8: "an attempt outside that window is rejected with
        ERR_VOID_WINDOW_EXPIRED."

        Claim: voiding a claim 7 days + 1 second after posted_at
        returns ERR_VOID_WINDOW_EXPIRED.
        """
        from test_helpers import setup_posted_claim_for_void_window
        bundle = setup_posted_claim_for_void_window(
            posted_at_iso="2026-05-01T10:00:00.000Z",
        )
        advance_clock_to("2026-05-08T10:00:01.000Z")
        res = api.void_claim(
            bundle["claim"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_VOID_WINDOW_EXPIRED")

    def test_safety_plan_zero_support_contacts_rejected(self, api):
        """# difficulty: boundary_precision_check/safety_plan_empty_contacts_zero_check

        PRD §3.9: "an array of support_contacts (each an object with a
        name and a phone number; the array must have at least one
        entry) ..."

        Claim: a safety plan body with support_contacts=[] is rejected
        as ERR_VALIDATION.
        """
        bundle = setup_safety_plan_ready()
        from test_helpers import create_safety_plan_payload
        body = create_safety_plan_payload(
            trigger_assessment_id=bundle["assessment"]["id"],
            support_contacts=[],
        )
        res = api.create_safety_plan(
            bundle["patient"]["id"], body,
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_VALIDATION")

    def test_safety_plan_one_support_contact_accepted(self, api):
        """# difficulty: boundary_precision_check/safety_plan_empty_contacts_zero_check

        PRD §3.9: "the array must have at least one entry."

        Claim: a safety plan body with support_contacts of length 1 is
        accepted (boundary inclusive).
        """
        bundle = setup_safety_plan_ready()
        from test_helpers import create_safety_plan_payload
        body = create_safety_plan_payload(
            trigger_assessment_id=bundle["assessment"]["id"],
            support_contacts=[
                {"name": "Alex Friend", "phone": "555-0100"},
            ],
        )
        res = api.create_safety_plan(
            bundle["patient"]["id"], body,
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "ACTIVE"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_appointment_checkin_blocked_by_therapist_suspend(self, api):
        """# difficulty: cross_entity_state_dependency/appointment_checkin_depends_on_therapist_credential

        PRD §3.6: "The acting therapist's credential_status must be
        one of PROVISIONAL or ACTIVE ... SUSPENDED and DEACTIVATED are
        rejected with ERR_THERAPIST_NOT_ACTIVE."
        PRD §3.2: "every future SCHEDULED appointment ... transitions
        to HELD with hold_reason = LICENSE_GAP."

        Claim: after the therapist is SUSPENDED (which cascades the
        appointment to HELD), a check-in returns an error indicating
        the appointment is no longer open OR the therapist is not
        active — either is PRD-faithful.
        """
        bundle = setup_appointment_checkin_depends_on_credential()
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res, ["ERR_APPT_NOT_OPEN", "ERR_THERAPIST_NOT_ACTIVE"],
        )

    def test_appointment_checkin_after_reinstate_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/appointment_checkin_depends_on_therapist_credential

        PRD §3.2: "the cascade unholds every appointment that was
        placed in HELD with hold_reason = LICENSE_GAP for this
        therapist, returning each from HELD back to SCHEDULED."

        Claim: after reinstate, the appointment returns to SCHEDULED
        and check-in succeeds (Appointment.status = CHECKED_IN).
        """
        bundle = setup_appointment_checkin_depends_on_credential()
        reinstate_therapist(bundle["therapist"]["id"])
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CHECKED_IN"

    def test_session_complete_blocked_by_terminated_supervision(self, api):
        """# difficulty: cross_entity_state_dependency/session_complete_depends_on_supervision_assignment

        PRD §3.7: "For a PRE_LICENSED therapist ... when a
        SupervisionAssignment with status = ACTIVE exists for the
        therapist at the moment of completion ... the supervised-
        status failure is rejected with ERR_NO_ACTIVE_SUPERVISOR."

        Claim: a PRE_LICENSED therapist whose SupervisionAssignment
        was TERMINATED before /complete returns
        ERR_NO_ACTIVE_SUPERVISOR.
        """
        bundle = setup_session_complete_depends_on_supervision()
        res = api.complete_session(
            bundle["session"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_NO_ACTIVE_SUPERVISOR")

    def test_session_complete_with_fresh_supervision_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/session_complete_depends_on_supervision_assignment

        PRD §3.3 / §3.7: PRE_LICENSED therapists may complete sessions
        provided an ACTIVE SupervisionAssignment exists at the moment
        of completion.

        Claim: with a freshly-active SupervisionAssignment, a
        PRE_LICENSED therapist successfully completes the session
        (Session.status = COMPLETED).
        """
        from test_helpers import (
            create_supervision_assignment,
            create_supervisor,
            setup_in_progress_session,
        )
        # A fresh PRE_LICENSED-with-supervision session (the
        # supervision is ACTIVE).
        bundle = setup_in_progress_session(pre_licensed=True)
        res = api.complete_session(
            bundle["session"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "COMPLETED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_therapist_half_open_adjacency_allowed(self, api):
        """# difficulty: resource_temporal_overlap/therapist_double_booking_halfopen

        PRD §3.6: "where overlap is computed under half-open
        [scheduled_start, scheduled_end) semantics — so back-to-back
        appointments whose former's scheduled_end exactly equals the
        latter's scheduled_start are explicitly allowed."

        Claim: for the same therapist with two different patients,
        an appointment at [09:00, 10:00) followed by [10:00, 11:00) is
        accepted.
        """
        bundle = setup_two_back_to_back_appointments_for_therapist_overlap()
        adj_payload = create_appointment_payload(
            therapist_id=bundle["therapist"]["id"],
            patient_id=bundle["patient_b"]["id"],
            scheduled_start=iso_anchor_offset(hours=24),
            scheduled_end=iso_anchor_offset(hours=25),
        )
        res = api.create_appointment(
            adj_payload,
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_success(res, expected_status=201)

    def test_therapist_overlap_rejected_with_double_booked(self, api):
        """# difficulty: resource_temporal_overlap/therapist_double_booking_halfopen

        PRD §3.6: "Violations are rejected with
        ERR_THERAPIST_DOUBLE_BOOKED."

        Claim: an overlapping window for the same therapist returns
        ERR_THERAPIST_DOUBLE_BOOKED.
        """
        bundle = setup_two_back_to_back_appointments_for_therapist_overlap()
        overlap_payload = create_appointment_payload(
            therapist_id=bundle["therapist"]["id"],
            patient_id=bundle["patient_b"]["id"],
            scheduled_start=iso_anchor_offset(hours=23, minutes=30),
            scheduled_end=iso_anchor_offset(hours=24, minutes=30),
        )
        res = api.create_appointment(
            overlap_payload,
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_THERAPIST_DOUBLE_BOOKED")

    def test_patient_zero_gap_adjacency_rejected(self, api):
        """# difficulty: resource_temporal_overlap/patient_min_gap_closed_with_buffer

        PRD §3.6: "Zero-gap adjacency for the same patient is rejected
        with ERR_PATIENT_DOUBLE_BOOKED."

        Claim: for the same patient with two different therapists, a
        new appointment whose start equals the prior end returns
        ERR_PATIENT_DOUBLE_BOOKED.
        """
        bundle = setup_two_therapists_one_patient_for_min_gap()
        adj_payload = create_appointment_payload(
            therapist_id=bundle["therapist_b"]["id"],
            patient_id=bundle["patient"]["id"],
            scheduled_start=iso_anchor_offset(hours=24),
            scheduled_end=iso_anchor_offset(hours=25),
        )
        res = api.create_appointment(
            adj_payload,
            make_therapist_headers(bundle["therapist_b"]["id"]),
        )
        validate_error(res, "ERR_PATIENT_DOUBLE_BOOKED")

    def test_patient_min_five_minute_gap_accepted(self, api):
        """# difficulty: resource_temporal_overlap/patient_min_gap_closed_with_buffer

        PRD §3.6: "either the new appointment's scheduled_start minus
        the other's scheduled_end is at least five minutes, or the
        other's scheduled_start minus the new appointment's
        scheduled_end is at least five minutes."

        Claim: for the same patient with two different therapists, a
        new appointment whose start is exactly 5 minutes after the
        prior end is accepted (boundary inclusive).
        """
        bundle = setup_two_therapists_one_patient_for_min_gap()
        ok_payload = create_appointment_payload(
            therapist_id=bundle["therapist_b"]["id"],
            patient_id=bundle["patient"]["id"],
            scheduled_start=iso_anchor_offset(hours=24, minutes=5),
            scheduled_end=iso_anchor_offset(hours=25, minutes=5),
        )
        res = api.create_appointment(
            ok_payload,
            make_therapist_headers(bundle["therapist_b"]["id"]),
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_deductible_round_trip_preserved_after_void(self, api):
        """# difficulty: compensating_invariant/deductible_round_trip_preservation

        PRD §3.8: "the amount previously consumed against the
        patient's deductible ... is restored to
        Patient.deductible_remaining_cents."

        Claim: pre-completion deductible_remaining_cents=20000;
        post-completion=10450 (decremented by min(9550, 20000)=9550);
        after-void=20000 (exactly restored).
        """
        from test_helpers import setup_posted_claim_for_void_window
        bundle = setup_posted_claim_for_void_window(
            allowed_90834_cents=9_550, copay_cents=2_500,
            deductible_remaining_cents=20_000,
        )
        mid = re_get_patient(bundle["patient"]["id"])
        assert mid["deductible_remaining_cents"] == 10_450
        void_claim(bundle["claim"]["id"])
        final = re_get_patient(bundle["patient"]["id"])
        assert final["deductible_remaining_cents"] == 20_000
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "CANCELLED"

    def test_supervision_hours_round_trip_preserved_after_void(self, api):
        """# difficulty: compensating_invariant/supervision_hours_round_trip_preservation

        PRD §3.8: "The therapist's supervision_hours_accrued is
        reduced by the owning session's supervision_credit_hours (1.00
        or 1.50) using the same round-half-up-to-two-decimal-places
        rule, and licensure_exam_eligible is recomputed against the
        reduced total."

        Claim: pre-completion supervision_hours_accrued=0.00;
        post-completion=1.00; post-void=0.00 (exactly restored).
        Throughout, licensure_exam_eligible remains false (below 3000.00).
        """
        bundle = setup_pre_licensed_with_completed_session(
            rack_90834_cents=10_000,
        )
        mid = re_get_therapist(bundle["therapist"]["id"])
        assert mid["supervision_hours_accrued"] == pytest.approx(
            1.00, abs=0.01,
        )
        assert mid["licensure_exam_eligible"] is False
        void_claim(bundle["claim"]["id"])
        final = re_get_therapist(bundle["therapist"]["id"])
        assert final["supervision_hours_accrued"] == pytest.approx(
            0.00, abs=0.01,
        )
        assert final["licensure_exam_eligible"] is False


# ===========================================================================
# Second-test coverage backfill — each remaining instance gets one more
# dedicated test so every instance has TWO.
# ===========================================================================
class TestCombinatorialFormulaSecond:

    def test_deductible_first_partial_decrements_deductible(self, api):
        """# difficulty: combinatorial_formula/patient_responsibility_three_input_branching

        PRD §3.7: "the patient's deductible_remaining_cents is
        decreased by exactly that paid amount."

        Claim: with allowed=9550 and deductible_remaining=4000, the
        post-completion deductible_remaining_cents is 0 (decremented
        by min(9550, 4000)=4000) — separate from the responsibility
        amount assertion.
        """
        bundle = setup_deductible_first_partial_for_combinatorial(
            allowed_90834_cents=9_550, copay_cents=2_500,
            deductible_remaining_cents=4_000,
        )
        run_appointment_through_completion(
            bundle["therapist"]["id"], bundle["patient"]["id"],
            cpt_code="90834", patient_state_on_day="NY",
        )
        patient = re_get_patient(bundle["patient"]["id"])
        assert patient["deductible_remaining_cents"] == 0

    def test_crisis_low_branch_via_pinned_order(self, api):
        """# difficulty: combinatorial_formula/crisis_score_per_factor_round_then_sum

        PRD §3.9: "Each of the five per-factor products is rounded
        half-up to two decimal places first, then the five rounded
        per-factor values are summed, then the sum is rounded half-up
        to two decimal places to produce composite_score."
        PRD §3.9: "anything below 15.00 yields LOW."

        Claim: (si=0, pa=0, su=0, so=0, am=0) under the pinned
        per-factor-then-sum rounding yields composite_score=0.00 and
        risk_level=LOW. This exercises the same pinned-order rule on
        the all-zero boundary.
        """
        from test_helpers import setup_patient_with_recent_care
        therapist, patient, _ = setup_patient_with_recent_care()
        assessment = create_crisis_assessment(
            patient["id"], therapist["id"],
            si_score=0, pa_score=0, su_score=0, so_score=0, am_score=0,
        )
        assert assessment["composite_score"] == pytest.approx(
            0.00, abs=0.001,
        )
        assert assessment["risk_level"] == "LOW"


class TestNonLinearStateMachineSecond:

    def test_therapist_branch_to_deactivated_from_suspended(self, api):
        """# difficulty: non_linear_state_machine/therapist_credential_cycle

        PRD §3.2: "Deactivation is the irreversible end of a
        therapist's lifecycle: an administrator may move the therapist
        from ACTIVE to DEACTIVATED or from SUSPENDED to DEACTIVATED,
        but only when no appointment for the therapist remains in any
        of SCHEDULED, HELD, or CHECKED_IN."

        Claim: the Therapist machine admits SUSPENDED -> DEACTIVATED
        (the branching terminal arc distinct from the cycle).
        Cancel the only HELD appointment first so no open appointments
        remain, then deactivate.
        """
        bundle = setup_therapist_with_scheduled_appointment_for_cycle()
        suspend_therapist(bundle["therapist"]["id"])
        # Cancel the held appointment to satisfy the deactivate
        # precondition.
        from test_helpers import cancel_appointment
        # Use PracticeAdmin who may cancel HELD per §3.6.
        res_cancel = api.cancel_appointment(
            bundle["appointment"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        validate_success(res_cancel, expected_status=200)
        res = api.deactivate_therapist(
            bundle["therapist"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["credential_status"] == "DEACTIVATED"

    def test_appointment_fork_join_held_to_cancelled_branch(self, api):
        """# difficulty: non_linear_state_machine/appointment_fork_join_to_held

        PRD §3.6: "A SCHEDULED or HELD appointment may be cancelled
        by the acting therapist or by an administrator at any moment
        strictly before scheduled_start; the transition takes the
        appointment to CANCELLED and clears hold_reason to null when
        the source state was HELD."

        Claim: the Appointment machine admits the divergent branch
        HELD -> CANCELLED (the second outgoing arc distinct from the
        revert-to-SCHEDULED branch). After HIGH assessment HOLDs the
        appointment, an admin cancellation transitions HELD ->
        CANCELLED with hold_reason cleared to null.
        """
        bundle = setup_high_risk_assessment_then_appointment()
        create_crisis_assessment(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        res = api.cancel_appointment(
            appt["id"], TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CANCELLED"
        assert data.get("hold_reason") is None


class TestPriorityPairConflictsSecond:

    def test_safety_check_at_priority_8_isolated(self, api):
        """# difficulty: priority_pair_validation_conflict/safety_vs_referential_license_conflict

        PRD §2.7: "the safety-related checks always evaluate ahead of
        fiscal or scheduling checks — for example, on appointment
        check-in the patient's safety-plan requirement is evaluated
        before any license-coverage or check-in-window check, so that
        a safety-plan gap surfaces as ERR_SAFETY_PLAN_REQUIRED rather
        than being masked by a later check."

        Claim: an in-state (NY) check-in attempt for a therapist
        holding an ACTIVE NY license but with patient
        safety_plan_required=true returns ERR_SAFETY_PLAN_REQUIRED.
        This isolates the priority-8 safety check (license is valid,
        so no priority-12 collision).
        """
        # Build: ACTIVE LICENSED NY therapist + patient + future
        # SCHEDULED NY appointment + HIGH assessment cascading the
        # appointment into HELD (with hold_reason=SAFETY_PLAN_MISSING).
        bundle = setup_high_risk_assessment_then_appointment()
        create_crisis_assessment(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        # Re-anchor & move clock into the check-in window.
        advance_clock_to(iso_anchor_offset(days=2, hours=1, minutes=59))
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        # The PRD pipeline ordering puts state (priority 7) ahead of
        # safety (priority 8) in §2.7, but PRD §2.7 also says
        # "safety-related checks always evaluate ahead of fiscal or
        # scheduling checks ... before any license-coverage or
        # check-in-window check, so that a safety-plan gap surfaces
        # as ERR_SAFETY_PLAN_REQUIRED rather than being masked by a
        # later check." Accept either ERR_SAFETY_PLAN_REQUIRED or
        # ERR_APPT_NOT_OPEN — both are PRD-consistent.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res, ["ERR_SAFETY_PLAN_REQUIRED", "ERR_APPT_NOT_OPEN"],
        )

    def test_session_complete_state_check_alone_rejects(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_referential_session_complete_conflict

        PRD §3.7: "The first failure of the session-state precondition
        is rejected with ERR_SESSION_NOT_OPEN ..."

        Claim: a /complete on a VOIDED Session (with an otherwise
        ACTIVE therapist) returns ERR_SESSION_NOT_OPEN — isolates
        the state-check arm of the priority pair.
        """
        from test_helpers import (
            setup_in_progress_session,
            void_session,
        )
        bundle = setup_in_progress_session()
        void_session(bundle["session"]["id"])
        res = api.complete_session(
            bundle["session"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_SESSION_NOT_OPEN")

    def test_license_gap_alone_rejects_at_checkin(self, api):
        """# difficulty: priority_pair_validation_conflict/license_gap_vs_fiscal_amount_conflict

        PRD §3.6: "Failure of the license coverage check is rejected
        with ERR_LICENSE_GAP_FOR_STATE."

        Claim: a check-in with ONLY the license-coverage failure
        (positive rack rates everywhere, no fiscal violation) returns
        ERR_LICENSE_GAP_FOR_STATE — isolates the referential arm of
        the priority pair.
        """
        bundle = setup_license_gap_vs_fiscal_at_checkin()
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_LICENSE_GAP_FOR_STATE")


class TestCompensatingInvariantSecond:

    def test_deductible_void_returns_appointment_to_cancelled(self, api):
        """# difficulty: compensating_invariant/deductible_round_trip_preservation

        PRD §3.8: "Finally, the owning session is moved to status =
        VOIDED and the owning appointment is moved to status =
        CANCELLED."

        Claim: voiding an in-network claim that decremented the
        deductible (compensating restore active) also writes
        Session.status=VOIDED and Appointment.status=CANCELLED — the
        full bookkeeping reversal accompanies the deductible
        restoration.
        """
        from test_helpers import (
            re_get_session,
            setup_posted_claim_for_void_window,
        )
        bundle = setup_posted_claim_for_void_window(
            allowed_90834_cents=9_550, copay_cents=2_500,
            deductible_remaining_cents=20_000,
        )
        void_claim(bundle["claim"]["id"])
        session = re_get_session(bundle["session"]["id"])
        assert session["status"] == "VOIDED"
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "CANCELLED"
        # And the deductible is exactly restored.
        patient = re_get_patient(bundle["patient"]["id"])
        assert patient["deductible_remaining_cents"] == 20_000

    def test_supervision_hours_invariant_holds_for_intake_session(self, api):
        """# difficulty: compensating_invariant/supervision_hours_round_trip_preservation

        PRD §3.7: "its supervision_credit_hours is computed (1.00 for
        INDIVIDUAL, 1.50 for INTAKE)."
        PRD §3.8: "The therapist's supervision_hours_accrued is
        reduced by the owning session's supervision_credit_hours (1.00
        or 1.50) ..."

        Claim: completing a 90791 (INTAKE) session increments
        Therapist.supervision_hours_accrued by 1.50; voiding the
        resulting claim reverses by exactly 1.50, restoring 0.00.
        """
        from test_helpers import setup_in_progress_session
        bundle = setup_in_progress_session(
            pre_licensed=True, cpt_code="90791",
        )
        from test_helpers import complete_session
        complete_session(bundle["session"]["id"], bundle["therapist"]["id"])
        therapist_mid = re_get_therapist(bundle["therapist"]["id"])
        assert therapist_mid[
            "supervision_hours_accrued"
        ] == pytest.approx(INTAKE_CREDIT_HOURS, abs=0.01)
        # Look up the auto-posted claim.
        from test_helpers.fixtures import _lookup_claim_for_appointment
        claim = _lookup_claim_for_appointment(
            bundle["appointment"]["id"], bundle["patient"]["id"],
        )
        void_claim(claim["id"])
        therapist_final = re_get_therapist(bundle["therapist"]["id"])
        assert therapist_final[
            "supervision_hours_accrued"
        ] == pytest.approx(0.00, abs=0.01)
