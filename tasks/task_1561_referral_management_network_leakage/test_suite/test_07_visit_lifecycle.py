"""Visit lifecycle: confirm/complete branch vs no-show/excuse branch, cancel cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    cancel_referral_payload,
    create_plan, create_provider, create_specialist, create_patient,
    create_participation, create_booked_referral, book_appointment,
    confirm_appointment, complete_appointment, mark_no_show, excuse_appointment,
    set_clock, get_referral, get_specialist, get_appointment, get_patient,
    list_referral_leakage_records,
    make_specialist_provider_headers,
    assert_instant_equals,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _bootstrap():
    set_clock("2026-08-01T00:00:00Z")
    plan = create_plan()
    specialist = create_specialist()
    create_participation(specialist["id"], plan["id"])
    provider = create_provider()
    patient = create_patient(plan["id"])
    return plan, specialist, provider, patient


class TestBranchDivergence:
    def test_confirm_complete_branch(self, api):
        """PRD §3.6: "A successful completion stamps `completed_at`, decrements the
        specialist's `booked_appointments_count` by 1, advances the referral from
        `SCHEDULED` to `VISIT_COMPLETED`".
        PRD §3.6: "only a `SCHEDULED` appointment can be confirmed, otherwise
        `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/appointment_branch_divergence
        """
        plan, specialist, provider, patient = _bootstrap()
        rx, ax = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                        "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
                                        diagnosis_code="I10")
        confirm_appointment(ax["id"], channel="PORTAL")
        set_clock("2026-08-02T10:00:00Z")
        complete_appointment(ax["id"], specialist["id"])

        ax_after = get_appointment(ax["id"])
        assert ax_after["status"] == "COMPLETED"
        assert_instant_equals(ax_after["completed_at"], "2026-08-02T10:00:00Z",
                              label="completed_at (stamped with the current clock)")
        assert get_referral(rx["id"])["status"] == "VISIT_COMPLETED"

    def test_no_show_excuse_branch(self, api):
        """PRD §3.6: "Marking no-show sets the appointment to `NO_SHOW`, decrements
        the specialist's `booked_appointments_count` by 1 ... Finally, if no sibling
        appointment of the referral remains in `SCHEDULED` or `CONFIRMED`, the
        referral falls back from `SCHEDULED` to `ACCEPTED`, ready to be rebooked."
        PRD §3.6: "excusing a `NO_SHOW` appointment (from no other status, else
        `ERR_INVALID_STATE`) stores the supplied `reason` in `excuse_reason`, moves
        the appointment to `EXCUSED`, decrements the patient's `no_show_strikes` by
        1".

        Design: Difficulty/non_linear_state_machine/appointment_branch_divergence
        """
        plan, specialist, provider, patient = _bootstrap()
        ry, ay = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                        "2026-08-02T12:00:00Z", "2026-08-02T13:00:00Z",
                                        diagnosis_code="I11")
        set_clock("2026-08-02T12:15:00Z")
        mark_no_show(ay["id"])
        assert get_referral(ry["id"])["status"] == "ACCEPTED", (
            "Referral reverts to ACCEPTED when its last active appointment goes NO_SHOW"
        )
        excuse_appointment(ay["id"], reason="Patient called ahead")

        ay_after = get_appointment(ay["id"])
        assert ay_after["status"] == "EXCUSED"
        assert ay_after["excuse_reason"] == "Patient called ahead"
        assert get_patient(patient["id"])["no_show_strikes"] == 0, (
            "Excuse compensates the strike"
        )
        assert get_specialist(specialist["id"])["booked_appointments_count"] == 0


class TestCompletionGuards:
    def test_complete_without_confirm_rejected(self, api):
        """PRD §3.6: "The acting specialist must be the appointment's owner — the
        appointment's `specialist_id` compared to `X-User-ID`, else
        `ERR_OWNERSHIP_VIOLATION` — and the appointment must be `CONFIRMED`, else
        `ERR_NOT_CONFIRMED`."

        Design: Corner/state_machines/complete_without_confirm_rejected
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
        )
        set_clock("2026-08-02T11:00:00Z")
        res = api.complete_appointment(
            appointment["id"], make_specialist_provider_headers(specialist["id"])
        )
        validate_error(res, ApiErrorId.ERR_NOT_CONFIRMED, expected_status=409)
        assert get_appointment(appointment["id"])["status"] == "SCHEDULED"
        assert get_referral(referral["id"])["status"] == "SCHEDULED"

    def test_complete_too_early_rejected(self, api):
        """PRD §3.6: "Completion before the appointment's scheduled start is rejected
        with `ERR_COMPLETE_TOO_EARLY`."

        Design: Corner/validations/complete_too_early_rejected
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
        )
        confirm_appointment(appointment["id"])
        # Clock is still 2026-08-01, before the 2026-08-02T10:00 scheduled start.
        res = api.complete_appointment(
            appointment["id"], make_specialist_provider_headers(specialist["id"])
        )
        validate_error(res, ApiErrorId.ERR_COMPLETE_TOO_EARLY, expected_status=422)

    def test_specialist_cannot_complete_others_appointment(self, api):
        """PRD §2.1: "When `X-User-Role` is `SpecialistProvider`, `X-User-ID` is the
        `id` of the acting `SpecialistProvider`; completing an appointment or
        submitting a consult note requires the appointment's `specialist_id` to equal
        `X-User-ID`, with `ERR_OWNERSHIP_VIOLATION` (HTTP 403) on mismatch."

        Design: Corner/rbac/specialist_cannot_complete_others_appointment
        """
        plan, specialist, provider, patient = _bootstrap()
        other = create_specialist(name="S2", npi="1000000002")
        referral, appointment = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
        )
        confirm_appointment(appointment["id"])
        set_clock("2026-08-02T10:30:00Z")
        res = api.complete_appointment(
            appointment["id"], make_specialist_provider_headers(other["id"])
        )
        validate_error(res, ApiErrorId.ERR_OWNERSHIP_VIOLATION, expected_status=403)
        assert get_appointment(appointment["id"])["status"] == "CONFIRMED"


class TestReferralCancelCascade:
    def test_cancel_cascades_appointment_and_no_leakage_for_declined(self, api):
        """PRD §3.6: "The supplied `reason` — one of `PATIENT_WENT_OUT_OF_NETWORK`,
        `PATIENT_DECLINED`, `CLINICAL_DUPLICATE`, or `OTHER` — is stored in
        `cancel_reason`. Any appointment of the referral still in `SCHEDULED` or
        `CONFIRMED` is cascade-cancelled and its slot freed. When the reason is
        `PATIENT_WENT_OUT_OF_NETWORK` and the referral has not already leaked, the
        cancellation additionally creates a `LeakageRecord` of category
        `PATIENT_CHOICE_OUT_OF_NETWORK` ..." (so PATIENT_DECLINED creates none).

        Design: Corner/state_machines/cancel_cascades_appointment_and_no_leakage_for_declined
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
        )
        cancelled = validate_success(api.cancel_referral(
            referral["id"], cancel_referral_payload("PATIENT_DECLINED"), COORD
        ))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "PATIENT_DECLINED"
        assert get_appointment(appointment["id"])["status"] == "CANCELLED", (
            "Active appointment is cascade-cancelled"
        )
        assert get_specialist(specialist["id"])["booked_appointments_count"] == 0, (
            "The slot is freed"
        )
        assert list_referral_leakage_records(referral["id"]) == [], (
            "PATIENT_DECLINED is not a leakage reason"
        )
