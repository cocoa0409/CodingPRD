"""State-machine cycles and guarded transitions: the appointment reschedule loop,
the estimate decline/revise loop, and corner invalid/terminal/precondition cases.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_appointment, assert_estimate,
    create_household, create_patient, create_estimate, present_estimate,
    create_appointment, appointment_check_in, appointment_begin_exam,
    create_appointment_in_exam, place_lab_order,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


class TestAppointmentRescheduleCycle:
    """IN_EXAM -> SCHEDULED reschedule loop increments reschedule_count (PRD 3.3)."""

    def test_reschedule_returns_to_scheduled_and_increments_count(self, api):
        """PRD 3.3: "On success the status returns to `SCHEDULED`, `reschedule_count`
        increases by one, and the `scheduled_start` and `scheduled_end` are replaced by
        the new window supplied in the request body."

        Design: Difficulty/non_linear_state_machine/appointment_reschedule_cycle_in_exam_back_to_scheduled
        """
        hh = create_household("Singh")
        _, pat = create_patient(household_id=hh["id"], name="Ace",
                                species="DOG", weight_kg=20)
        appt = create_appointment_in_exam(pat["id"],
                                          scheduled_start="2026-07-03T09:00:00Z",
                                          scheduled_end="2026-07-03T10:00:00Z")
        res = api.transition_appointment(appt["id"], {
            "action": "reschedule",
            "scheduled_start": "2026-07-10T09:00:00Z",
            "scheduled_end": "2026-07-10T10:00:00Z",
        }, VETERINARIAN)
        updated = validate_success(res, 200)
        assert_appointment(updated)
        assert updated["status"] == "SCHEDULED", f"Expected SCHEDULED, got {updated['status']}"
        assert updated["reschedule_count"] == 1, (
            f"Expected reschedule_count 1, got {updated['reschedule_count']}")
        assert updated["scheduled_start"][:19] == "2026-07-10T09:00:00", (
            f"Expected new window start, got {updated['scheduled_start']}")

    def test_fourth_reschedule_exceeds_limit_rejected(self, api):
        """PRD 3.3: "requires `reschedule_count` to be strictly fewer than 3 (a fourth
        attempt is refused with `ERR_APPOINTMENT_INVALID_STATE` for exceeding the
        reschedule limit)".

        After three reschedules (count==3), the fourth back-to-IN_EXAM-then-reschedule
        attempt is rejected.

        Design: Difficulty/non_linear_state_machine/appointment_reschedule_cycle_in_exam_back_to_scheduled
        """
        hh = create_household("Limit")
        _, pat = create_patient(household_id=hh["id"], name="Loop",
                                species="DOG", weight_kg=20)
        appt = create_appointment(pat["id"], scheduled_start="2026-07-03T09:00:00Z",
                                  scheduled_end="2026-07-03T10:00:00Z")
        # Cycle three successful reschedules.
        for i in range(3):
            appointment_check_in(appt["id"])
            appointment_begin_exam(appt["id"])
            done = validate_success(api.transition_appointment(appt["id"], {
                "action": "reschedule",
                "scheduled_start": "2026-07-10T09:00:00Z",
                "scheduled_end": "2026-07-10T10:00:00Z",
            }, VETERINARIAN), 200)
            assert done["reschedule_count"] == i + 1
        # Fourth attempt from IN_EXAM must be refused (count is now 3, not < 3).
        appointment_check_in(appt["id"])
        appointment_begin_exam(appt["id"])
        res = api.transition_appointment(appt["id"], {
            "action": "reschedule",
            "scheduled_start": "2026-07-11T09:00:00Z",
            "scheduled_end": "2026-07-11T10:00:00Z",
        }, VETERINARIAN)
        validate_error(res, "ERR_APPOINTMENT_INVALID_STATE", expected_status=409)


class TestEstimateReviseCycle:
    """DECLINED -> DRAFT revision loop increments revision, replaces line_items (PRD 3.6)."""

    def test_revise_cycles_to_draft_and_increments_revision(self, api):
        """PRD 3.6: "a veterinarian may **revise**, cycling the estimate back to `DRAFT`
        — this is the revision loop; revision requires the estimate to be `DECLINED`,
        increments `revision` by one, and replaces `line_items` with the new array in
        the request body."

        Design: Difficulty/non_linear_state_machine/estimate_decline_revise_cycle_back_to_draft
        """
        hh = create_household("Vidal")
        _, pat = create_patient(household_id=hh["id"], name="Kit",
                                species="CAT", weight_kg=5)
        est = create_estimate(pat["id"], line_items=[
            {"service_code": "X", "qty": 1, "unit_price_cents": 10000, "eligible_for_plan_discount": False}])
        present_estimate(est["id"])
        validate_success(api.transition_estimate(est["id"], {"action": "decline"}, RECEPTIONIST), 200)
        res = api.transition_estimate(est["id"], {
            "action": "revise",
            "line_items": [{"service_code": "Y", "qty": 2, "unit_price_cents": 7000, "eligible_for_plan_discount": False}],
        }, VETERINARIAN)
        updated = validate_success(res, 200)
        assert_estimate(updated)
        assert updated["status"] == "DRAFT", f"Expected DRAFT, got {updated['status']}"
        assert updated["revision"] == 2, f"Expected revision 2, got {updated['revision']}"

    def test_revise_requires_declined_state(self, api):
        """PRD 3.6: "revision requires the estimate to be `DECLINED`" (otherwise
        `ERR_ESTIMATE_INVALID_STATE`).

        Revising a DRAFT (never declined) estimate is rejected.

        Design: Difficulty/non_linear_state_machine/estimate_decline_revise_cycle_back_to_draft
        """
        hh = create_household("Draft")
        _, pat = create_patient(household_id=hh["id"], name="Stay",
                                species="CAT", weight_kg=5)
        est = create_estimate(pat["id"], line_items=[
            {"service_code": "X", "qty": 1, "unit_price_cents": 10000, "eligible_for_plan_discount": False}])
        res = api.transition_estimate(est["id"], {
            "action": "revise",
            "line_items": [{"service_code": "Z", "qty": 1, "unit_price_cents": 5000, "eligible_for_plan_discount": False}],
        }, VETERINARIAN)
        validate_error(res, "ERR_ESTIMATE_INVALID_STATE", expected_status=409)


def test_begin_exam_from_scheduled_invalid(api):
    """PRD 3.3: "A veterinarian **begins the exam** on a `CHECKED_IN` appointment,
    advancing it to `IN_EXAM` (the appointment must be `CHECKED_IN`, else
    `ERR_APPOINTMENT_INVALID_STATE`)."

    begin-exam on a still-SCHEDULED appointment is rejected.

    Design: Corner/state_machines/appointment_begin_exam_from_scheduled_invalid
    """
    hh = create_household("Eta")
    _, pat = create_patient(household_id=hh["id"], name="Pat",
                            species="DOG", weight_kg=10)
    appt = create_appointment(pat["id"], scheduled_start="2026-08-01T09:00:00Z",
                              scheduled_end="2026-08-01T10:00:00Z")
    res = api.transition_appointment(appt["id"], {"action": "begin-exam"}, VETERINARIAN)
    validate_error(res, "ERR_APPOINTMENT_INVALID_STATE", expected_status=409)


def test_cancel_already_cancelled_appointment_invalid(api):
    """PRD 3.3: "A receptionist may **cancel** an appointment from any of `SCHEDULED`,
    `CHECKED_IN`, or `IN_EXAM` (otherwise `ERR_APPOINTMENT_INVALID_STATE`)".

    Cancelling an already-CANCELLED (terminal) appointment is rejected.

    Design: Corner/state_machines/appointment_terminal_cancelled_lockdown
    """
    hh = create_household("Theta")
    _, pat = create_patient(household_id=hh["id"], name="Pat",
                            species="DOG", weight_kg=10)
    appt = create_appointment(pat["id"], scheduled_start="2026-08-02T09:00:00Z",
                              scheduled_end="2026-08-02T10:00:00Z")
    validate_success(api.transition_appointment(appt["id"], {"action": "cancel"}, RECEPTIONIST), 200)
    res = api.transition_appointment(appt["id"], {"action": "cancel"}, RECEPTIONIST)
    validate_error(res, "ERR_APPOINTMENT_INVALID_STATE", expected_status=409)


def test_no_show_too_early_rejected(api):
    """PRD 3.3: "declaring a no-show while still `SCHEDULED` is correct, but doing so
    before `scheduled_end` is too early and is refused with `ERR_APPOINTMENT_INVALID_STATE`".

    A no-show on an appointment whose scheduled_end is far in the future (2099) is rejected.

    Design: Corner/state_machines/appointment_no_show_too_early_rejected
    """
    hh = create_household("Iota")
    _, pat = create_patient(household_id=hh["id"], name="Pat",
                            species="DOG", weight_kg=10)
    appt = create_appointment(pat["id"], scheduled_start="2099-01-01T09:00:00Z",
                              scheduled_end="2099-01-01T10:00:00Z")
    res = api.transition_appointment(appt["id"], {"action": "no-show"}, RECEPTIONIST)
    validate_error(res, "ERR_APPOINTMENT_INVALID_STATE", expected_status=409)


def test_complete_blocked_by_open_lab_order(api):
    """PRD 3.3: "completion requires that no lab order on the appointment is still
    `ORDERED` or `COLLECTED` (open diagnostics block completion) ... `ERR_APPOINTMENT_INVALID_STATE`."

    complete on an IN_EXAM appointment with a still-ORDERED lab order is rejected.

    Design: Corner/state_machines/appointment_complete_blocked_by_open_lab_order
    """
    hh = create_household("Kappa")
    _, pat = create_patient(household_id=hh["id"], name="Pat",
                            species="DOG", weight_kg=10)
    appt = create_appointment_in_exam(pat["id"],
                                      scheduled_start="2026-08-03T09:00:00Z",
                                      scheduled_end="2026-08-03T10:00:00Z")
    place_lab_order(appt["id"], order_type="BLOODWORK", fee_cents=6000)
    res = api.transition_appointment(appt["id"], {"action": "complete"}, VETERINARIAN)
    validate_error(res, "ERR_APPOINTMENT_INVALID_STATE", expected_status=409)


def test_deactivate_blocked_by_open_visit(api):
    """PRD 3.1: "only when the patient has no appointment in any open state — that is,
    no appointment in `SCHEDULED`, `CHECKED_IN`, or `IN_EXAM`; if such an open visit
    exists the deactivation is refused with `ERR_PATIENT_HAS_OPEN_VISITS`."

    Design: Corner/state_machines/patient_deactivate_blocked_by_open_visit
    """
    hh = create_household("Lam")
    _, pat = create_patient(household_id=hh["id"], name="Pat",
                            species="DOG", weight_kg=10)
    create_appointment(pat["id"], scheduled_start="2026-08-04T09:00:00Z",
                       scheduled_end="2026-08-04T10:00:00Z")
    res = api.deactivate_patient(pat["id"], RECEPTIONIST)
    validate_error(res, "ERR_PATIENT_HAS_OPEN_VISITS", expected_status=409)


def test_lab_result_requires_result_text(api):
    """PRD 3.10: "resulting requires the order to be `COLLECTED` ... and requires a
    `result_text` in the request body (a missing result text is refused with
    `ERR_INVALID_REQUEST`)".

    result action on a COLLECTED lab order with no result_text is rejected.

    Design: Corner/state_machines/lab_order_result_requires_result_text
    """
    hh = create_household("Mu")
    _, pat = create_patient(household_id=hh["id"], name="Pat",
                            species="CAT", weight_kg=4)
    appt = create_appointment_in_exam(pat["id"],
                                      scheduled_start="2026-08-05T09:00:00Z",
                                      scheduled_end="2026-08-05T10:00:00Z")
    lo = place_lab_order(appt["id"], order_type="URINALYSIS", fee_cents=3000)
    validate_success(api.transition_lab_order(lo["id"], {"action": "collect"}, VETERINARIAN), 200)
    res = api.transition_lab_order(lo["id"], {"action": "result"}, VETERINARIAN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
