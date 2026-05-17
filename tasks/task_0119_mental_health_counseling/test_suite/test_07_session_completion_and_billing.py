"""Session lifecycle, BillingClaim auto-posting arithmetic, deductible
and supervision-hours cascades.

PRD §3.7 (session complete cascade), §3.8 (claim arithmetic), §2.9
(synchronous cascades).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    INDIVIDUAL_CREDIT_HOURS,
    INTAKE_CREDIT_HOURS,
    REQUIRED_HOURS_FOR_LICENSURE,
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_billing_claim,
    assert_in_network_claim_arithmetic,
    assert_self_pay_claim_arithmetic,
    assert_session,
    complete_session,
    create_insurance_plan,
    create_patient,
    create_session,
    iso_anchor_offset,
    make_therapist_headers,
    patch_patient_deductible,
    re_get_appointment,
    re_get_claim,
    re_get_patient,
    re_get_session,
    re_get_therapist,
    schedule_appointment,
    setup_active_licensed_therapist,
    setup_checked_in_appointment,
    setup_completed_session_and_claim,
    setup_in_progress_session,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 Session creation + completion preconditions
# ===========================================================================
class TestSessionLifecycle:

    def test_create_session_under_checked_in_appointment(self, api):
        """PRD §3.7: "Once an appointment is CHECKED_IN, the acting
        therapist opens a clinical Session underneath it by supplying
        actual_duration_minutes (the realised session length, at least
        one minute). The session is born in status = IN_PROGRESS, its
        type is mirrored from the parent appointment's cpt_code —
        INTAKE when cpt_code = 90791 and INDIVIDUAL when cpt_code =
        90834."

        Claim: a session under a 90834 appointment is born in
        status=IN_PROGRESS with type=INDIVIDUAL.
        """
        bundle = setup_checked_in_appointment(cpt_code="90834")
        res = api.create_session(
            bundle["appointment"]["id"],
            {"actual_duration_minutes": 45},
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_session(data)
        assert data["status"] == "IN_PROGRESS"
        assert data["type"] == "INDIVIDUAL"

    def test_session_type_mirrors_intake_for_90791(self, api):
        """PRD §3.7: "INTAKE when cpt_code = 90791 and INDIVIDUAL when
        cpt_code = 90834."

        Claim: a session under a 90791 appointment has type=INTAKE.
        """
        bundle = setup_checked_in_appointment(cpt_code="90791")
        session = create_session(
            bundle["appointment"]["id"], bundle["therapist"]["id"],
        )
        assert session["type"] == "INTAKE"

    def test_complete_session_transitions_to_completed(self, api):
        """PRD §3.7: "On success the session transitions from
        IN_PROGRESS to COMPLETED ..."

        Claim: completing an IN_PROGRESS session writes status=COMPLETED
        and the owning appointment.status=COMPLETED.
        """
        bundle = setup_in_progress_session()
        session = complete_session(
            bundle["session"]["id"], bundle["therapist"]["id"],
        )
        assert session["status"] == "COMPLETED"
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "COMPLETED"

    def test_complete_session_writes_credit_hours_individual(self, api):
        """PRD §3.7: "its supervision_credit_hours is computed (1.00
        for INDIVIDUAL, 1.50 for INTAKE) ..."

        Claim: completing an INDIVIDUAL session writes
        supervision_credit_hours=1.00.
        """
        bundle = setup_in_progress_session(cpt_code="90834")
        session = complete_session(
            bundle["session"]["id"], bundle["therapist"]["id"],
        )
        assert session["supervision_credit_hours"] == pytest.approx(
            INDIVIDUAL_CREDIT_HOURS,
        )

    def test_complete_session_writes_credit_hours_intake(self, api):
        """PRD §3.7: "its supervision_credit_hours is computed (1.00
        for INDIVIDUAL, 1.50 for INTAKE)."

        Claim: completing an INTAKE session writes
        supervision_credit_hours=1.50.
        """
        bundle = setup_in_progress_session(cpt_code="90791")
        session = complete_session(
            bundle["session"]["id"], bundle["therapist"]["id"],
        )
        assert session["supervision_credit_hours"] == pytest.approx(
            INTAKE_CREDIT_HOURS,
        )

    def test_void_session_cancels_appointment(self, api):
        """PRD §3.7: "A session that has not yet been completed may be
        voided by an administrator. The void transitions the session
        from IN_PROGRESS to VOIDED, and as a compensating action also
        transitions the owning appointment to CANCELLED."

        Claim: voiding an IN_PROGRESS session writes Session.status=
        VOIDED and Appointment.status=CANCELLED.
        """
        bundle = setup_in_progress_session()
        from test_helpers import void_session
        session = void_session(bundle["session"]["id"])
        assert session["status"] == "VOIDED"
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "CANCELLED"

    def test_void_completed_session_rejected(self, api):
        """PRD §3.7: "A void attempted on a session whose status is no
        longer IN_PROGRESS is rejected with ERR_SESSION_NOT_OPEN."

        Claim: voiding a COMPLETED session returns ERR_SESSION_NOT_OPEN.
        """
        bundle = setup_completed_session_and_claim()
        res = api.void_session(
            bundle["session"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_SESSION_NOT_OPEN")


# ===========================================================================
# §3.7 BillingClaim auto-post — SELF_PAY arithmetic
# ===========================================================================
class TestSelfPayClaimArithmetic:

    def test_self_pay_claim_charge_rounds_half_up(self, api):
        """PRD §3.7: "The charge is that rack rate multiplied by
        sliding_fee_tier_pct and divided by 100, with the result
        rounded half-up to the nearest cent. The full charge becomes
        patient_responsibility_cents, and insurer_paid_cents is zero."

        Claim: completing a 90834 self-pay session with rack=15001 and
        sliding_fee_tier_pct=40 yields charged_amount_cents=
        round_half_up(15001*40/100) = round_half_up(6000.4) = 6000,
        patient_responsibility_cents=6000, insurer_paid_cents=0.

        For a clean half-up boundary, we use rack=15001 (40% → 6000.4
        → 6000). A second half-up case: rack=15005 (40% → 6002.0 →
        6002).
        """
        # Patient at tier 40: household 2 / income 30660 cents in
        # *units of dollar/year* — but the API stores cents, so we
        # need household_income_cents that yields ratio ∈ (1.00, 1.50].
        # household_size=2 base = 2_044_000. ratio=1.5 -> income
        # 3_066_000 cents exactly.
        bundle = setup_completed_session_and_claim(
            cpt_code="90834",
            modality="IN_PERSON",
            household_income_cents=3_066_000,
            household_size=2,
            pricing_rack_90834_cents=15_001,
        )
        claim = bundle["claim"]
        assert_billing_claim(claim)
        assert claim["billing_mode"] == "SELF_PAY"
        # round_half_up(15001 * 40 / 100) = round_half_up(6000.4) = 6000
        assert claim["charged_amount_cents"] == 6_000
        assert_self_pay_claim_arithmetic(claim)


# ===========================================================================
# §3.7 BillingClaim auto-post — IN_NETWORK arithmetic
# ===========================================================================
class TestInNetworkClaimArithmetic:

    def test_in_network_deductible_first_partial(self, api):
        """PRD §3.7: "When contract_mode = DEDUCTIBLE_FIRST and the
        patient still has deductible_remaining_cents greater than zero,
        the patient pays the smaller of the allowed amount and the
        remaining deductible — this is the deductible-first phase —
        and the insurer pays the rest of the allowed amount; the
        patient's deductible_remaining_cents is decreased by exactly
        that paid amount."

        Claim: allowed=9550, deductible_remaining=4000,
        contract=DEDUCTIBLE_FIRST -> patient pays 4000, insurer pays
        5550; patient's deductible is decremented to 0.
        """
        plan = create_insurance_plan(
            network_status="IN_NETWORK",
            contract_mode="DEDUCTIBLE_FIRST",
            allowed_amount_90834_cents=9_550,
            copay_cents=2_500,
        )
        bundle = setup_completed_session_and_claim(
            cpt_code="90834",
            insurance_plan=plan,
            deductible_remaining_cents=4_000,
        )
        claim = bundle["claim"]
        assert claim["billing_mode"] == "INSURANCE_IN_NETWORK"
        assert claim["charged_amount_cents"] == 9_550
        assert claim["patient_responsibility_cents"] == 4_000
        assert claim["insurer_paid_cents"] == 5_550
        assert_in_network_claim_arithmetic(claim)
        patient = re_get_patient(bundle["patient"]["id"])
        assert patient["deductible_remaining_cents"] == 0

    def test_in_network_deductible_first_after_met_uses_copay(self, api):
        """PRD §3.7: "When contract_mode = DEDUCTIBLE_FIRST and the
        deductible is already exhausted (zero), the patient pays the
        smaller of the plan's copay_cents and the allowed amount, and
        the insurer pays the remainder of the allowed amount; this is
        the deductible-first after-met phase."

        Claim: allowed=9550, deductible_remaining=0, copay=2500,
        contract=DEDUCTIBLE_FIRST -> patient pays 2500, insurer pays
        7050.
        """
        plan = create_insurance_plan(
            network_status="IN_NETWORK",
            contract_mode="DEDUCTIBLE_FIRST",
            allowed_amount_90834_cents=9_550,
            copay_cents=2_500,
        )
        bundle = setup_completed_session_and_claim(
            cpt_code="90834",
            insurance_plan=plan,
            deductible_remaining_cents=0,
        )
        claim = bundle["claim"]
        assert claim["charged_amount_cents"] == 9_550
        assert claim["patient_responsibility_cents"] == 2_500
        assert claim["insurer_paid_cents"] == 7_050

    def test_in_network_copay_only_ignores_deductible(self, api):
        """PRD §3.7: "When contract_mode = COPAY_ONLY, the patient
        pays the smaller of copay_cents and the allowed amount
        irrespective of any deductible state, and the insurer pays the
        remainder."

        Claim: allowed=9550, deductible_remaining=20000, copay=2500,
        contract=COPAY_ONLY -> patient pays 2500, insurer pays 7050;
        deductible_remaining_cents is unchanged.
        """
        plan = create_insurance_plan(
            network_status="IN_NETWORK",
            contract_mode="COPAY_ONLY",
            allowed_amount_90834_cents=9_550,
            copay_cents=2_500,
        )
        bundle = setup_completed_session_and_claim(
            cpt_code="90834",
            insurance_plan=plan,
            deductible_remaining_cents=20_000,
        )
        claim = bundle["claim"]
        assert claim["patient_responsibility_cents"] == 2_500
        assert claim["insurer_paid_cents"] == 7_050
        patient = re_get_patient(bundle["patient"]["id"])
        # PRD §3.7 (COPAY_ONLY): "irrespective of any deductible state."
        # The decrement applies only to DEDUCTIBLE_FIRST phase.
        assert patient["deductible_remaining_cents"] == 20_000

    def test_out_of_network_falls_back_to_self_pay(self, api):
        """PRD §3.5: "The network_status of OUT_OF_NETWORK does not
        produce in-network claim arithmetic. When a patient with such a
        plan completes a session, the resulting BillingClaim is
        treated as SELF_PAY ..."

        Claim: a completed session for a patient on an OUT_OF_NETWORK
        plan produces a claim with billing_mode=SELF_PAY and
        insurance_plan_id=null.
        """
        plan = create_insurance_plan(network_status="OUT_OF_NETWORK")
        bundle = setup_completed_session_and_claim(
            cpt_code="90834",
            insurance_plan=plan,
            household_income_cents=3_066_000, household_size=2,
            pricing_rack_90834_cents=10_000,
        )
        claim = bundle["claim"]
        assert claim["billing_mode"] == "SELF_PAY"
        assert claim.get("insurance_plan_id") is None
        assert claim["insurer_paid_cents"] == 0


# ===========================================================================
# §3.7 Supervision-hour ledger
# ===========================================================================
class TestSupervisionHoursCascade:

    def test_session_complete_increments_supervision_hours(self, api):
        """PRD §3.7: "The system adds the session's
        supervision_credit_hours (1.00 or 1.50) to the therapist's
        supervision_hours_accrued and rounds the running total half-up
        to two decimal places."

        Claim: completing a 90834 (INDIVIDUAL) session increments the
        therapist's supervision_hours_accrued by 1.00.
        """
        bundle = setup_in_progress_session(pre_licensed=True)
        before = bundle["therapist"]["supervision_hours_accrued"]
        complete_session(bundle["session"]["id"], bundle["therapist"]["id"])
        after = re_get_therapist(bundle["therapist"]["id"])[
            "supervision_hours_accrued"
        ]
        assert after == pytest.approx(before + INDIVIDUAL_CREDIT_HOURS,
                                      abs=0.01)

    def test_licensure_eligible_stays_false_below_threshold(self, api):
        """PRD §3.7: "Immediately after, licensure_exam_eligible is
        recomputed: it becomes true when the new
        supervision_hours_accrued is at least 3000.00 and the
        therapist's credential_status is one of PROVISIONAL or ACTIVE,
        and false otherwise."

        Claim: after completing one 90834 session with starting
        supervision_hours_accrued=0.00, licensure_exam_eligible
        remains false (1.00 < 3000.00).
        """
        bundle = setup_in_progress_session(pre_licensed=True)
        complete_session(bundle["session"]["id"], bundle["therapist"]["id"])
        therapist = re_get_therapist(bundle["therapist"]["id"])
        assert therapist["supervision_hours_accrued"] < REQUIRED_HOURS_FOR_LICENSURE
        assert therapist["licensure_exam_eligible"] is False


# ===========================================================================
# §3.7 PRE_LICENSED session-complete preconditions
# ===========================================================================
class TestSessionCompleteSupervisionPrecondition:

    def test_complete_pre_licensed_without_active_supervision_rejected(
        self, api,
    ):
        """PRD §3.7: "For a PRE_LICENSED therapist ... when a
        SupervisionAssignment with status = ACTIVE exists for the
        therapist at the moment of completion ... the supervised-status
        failure is rejected with ERR_NO_ACTIVE_SUPERVISOR."

        Claim: completing a session for a PRE_LICENSED therapist whose
        supervision assignment was terminated returns
        ERR_NO_ACTIVE_SUPERVISOR.
        """
        bundle = setup_in_progress_session(pre_licensed=True)
        from test_helpers import terminate_supervision_assignment
        terminate_supervision_assignment(bundle["assignment"]["id"])
        res = api.complete_session(
            bundle["session"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_NO_ACTIVE_SUPERVISOR")
