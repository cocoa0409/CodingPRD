"""Mediation cycle and settled cascade (PRD 3.5)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    create_answer_payload,
    create_outcome_payload,
    create_referral_payload,
    get_answer,
    get_case,
    get_hearing,
    get_referral,
    make_mediator_headers,
    schedule_hearing,
    setup_case_answered_with_referral,
    setup_case_hearing_scheduled,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestCaseMediationCycle:
    """Depth instance: HEARING_SCHEDULED -> ANSWERED -> MEDIATION_PENDING ->
    HEARING_SCHEDULED loop on failed mediation."""

    def test_failed_mediation_loops_case_back(self, api):
        """PRD 3.5: "A FAILED outcome moves the referral to FAILED, the answer
        to RETURNED, any stayed hearing to CANCELLED, and loops the case back
        to HEARING_SCHEDULED, where a fresh hearing may be scheduled."

        Design: Difficulty/non_linear_state_machine/case_mediation_cycle
        """
        ctx = setup_case_answered_with_referral()
        referral_id = ctx["referral"]["id"]
        # Hearing was STAYED by the referral.
        stayed = get_hearing(ctx["hearing"]["id"])
        assert stayed["status"] == "STAYED"

        resp = api.record_referral_outcome(
            referral_id, create_outcome_payload("FAILED", notes="no agreement"),
            make_mediator_headers(ctx["referral"]["mediator_id"]),
        )
        referral = validate_success(resp, 200)
        assert referral["status"] == "FAILED"

        assert get_answer(ctx["answer"]["id"])["status"] == "RETURNED"
        assert get_case(ctx["case"]["id"])["status"] == "HEARING_SCHEDULED"
        assert get_hearing(ctx["hearing"]["id"])["status"] == "CANCELLED"

        # A fresh hearing can be scheduled after the loop closes.
        ctx["case"] = get_case(ctx["case"]["id"])
        new_hearing = schedule_hearing(
            ctx, start_at="2026-06-22T10:00:00Z", end_at="2026-06-22T10:30:00Z"
        )
        assert new_hearing["status"] == "SCHEDULED"

    def test_referral_stays_the_scheduled_hearing(self, api):
        """PRD 3.5: "Referral creates the MediationReferral in PENDING,
        permanently linked to the answer through its answer_id, moves the
        answer to REFERRED, moves the case to MEDIATION_PENDING, and stays
        the case's SCHEDULED hearing if one exists (SCHEDULED → STAYED)."

        Design: Difficulty/non_linear_state_machine/case_mediation_cycle
        """
        ctx = setup_case_hearing_scheduled("CA")
        answer = validate_success(api.create_answer(
            ctx["case"]["id"], create_answer_payload(), CLERK_A), 201)
        referral = validate_success(api.create_mediation_referral(
            answer["id"], create_referral_payload(), CLERK_A), 201)
        assert referral["status"] == "PENDING"
        assert referral["answer_id"] == answer["id"]
        assert get_answer(answer["id"])["status"] == "REFERRED"
        assert get_case(ctx["case"]["id"])["status"] == "MEDIATION_PENDING"
        assert get_hearing(ctx["hearing"]["id"])["status"] == "STAYED"


class TestMediationSettledCascade:
    """Depth instance: referral SETTLED -> case SETTLED -> stayed hearing
    CANCELLED (depth-2 cascade)."""

    def test_settled_outcome_cascades_case_and_hearing(self, api):
        """PRD 3.5: "A SETTLED outcome moves the referral to SETTLED, the
        answer to RESOLVED, any stayed hearing to CANCELLED, and the case to
        the terminal SETTLED status."

        Design: Difficulty/transitive_cascade/mediation_settled_cascade_depth2
        """
        ctx = setup_case_answered_with_referral(defense_codes=["PAYMENT_TENDERED"])
        resp = api.record_referral_outcome(
            ctx["referral"]["id"],
            create_outcome_payload("SETTLED", notes="payment plan agreed"),
            make_mediator_headers(ctx["referral"]["mediator_id"]),
        )
        referral = validate_success(resp, 200)
        assert referral["status"] == "SETTLED"
        assert get_case(ctx["case"]["id"])["status"] == "SETTLED"
        assert get_hearing(ctx["hearing"]["id"])["status"] == "CANCELLED"
        assert get_answer(ctx["answer"]["id"])["status"] == "RESOLVED"

    def test_settled_records_outcome_notes_and_timestamp(self, api):
        """PRD 3.5: "the payload's outcome is SETTLED or FAILED, with optional
        notes preserved as outcome_notes alongside the outcome_recorded_at
        stamp."

        Design: Difficulty/transitive_cascade/mediation_settled_cascade_depth2
        """
        ctx = setup_case_answered_with_referral()
        resp = api.record_referral_outcome(
            ctx["referral"]["id"],
            create_outcome_payload("SETTLED", notes="payment plan agreed"),
            make_mediator_headers(ctx["referral"]["mediator_id"]),
        )
        referral = validate_success(resp, 200)
        assert referral["outcome_notes"] == "payment plan agreed"
        assert referral["outcome_recorded_at"] is not None


class TestUnassignedMediatorRejected:
    """Corner instance: only the referral's mediator_id may record outcome."""

    def test_other_mediator_rejected(self, api):
        """PRD 2.9: "a mediation outcome is only accepted from the operator
        whose X-User-ID equals the referral's mediator_id
        (ERR_NOT_ASSIGNED_MEDIATOR, HTTP 403)."

        Design: Corner/state_machines/outcome_by_unassigned_mediator_rejected
        """
        ctx = setup_case_answered_with_referral(mediator_id="med-1")
        resp = api.record_referral_outcome(
            ctx["referral"]["id"], create_outcome_payload("SETTLED"),
            make_mediator_headers("med-9"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_MEDIATOR, 403)
        # Referral unchanged.
        assert get_referral(ctx["referral"]["id"])["status"] == "PENDING"

    def test_outcome_on_nonpending_referral_rejected(self, api):
        """PRD 3.5: "The outcome may only be recorded by the operator whose
        X-User-ID equals the referral's mediator_id ... and only while the
        referral is PENDING."

        Design: Corner/state_machines/outcome_by_unassigned_mediator_rejected
        """
        ctx = setup_case_answered_with_referral(mediator_id="med-1")
        med = make_mediator_headers("med-1")
        validate_success(api.record_referral_outcome(
            ctx["referral"]["id"], create_outcome_payload("FAILED"), med), 200)
        # Second outcome on the now-FAILED referral: state gate.
        resp = api.record_referral_outcome(
            ctx["referral"]["id"], create_outcome_payload("SETTLED"), med)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
