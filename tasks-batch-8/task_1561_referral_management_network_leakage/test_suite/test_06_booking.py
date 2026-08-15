"""Booking: OCC guard, participation gate, overlap buffer, supersede, slot ledger."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    book_appointment_payload, document_patient_choice_payload,
    create_plan, create_provider, create_specialist, create_patient,
    create_participation, create_referral, accept_referral, assign_specialist,
    create_assigned_referral, create_booked_referral, book_appointment,
    set_clock, get_referral, get_specialist, get_appointment,
    list_referral_leakage_records, complete_appointment, confirm_appointment,
    cancel_appointment,
    make_coordinator_headers,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _bootstrap(with_participation=True, **kwargs):
    """Clock 2026-08-01 + plan + CARDIOLOGY specialist (+2026 participation)
    + provider + patient."""
    set_clock("2026-08-01T00:00:00Z")
    plan = create_plan()
    specialist = create_specialist()
    if with_participation:
        create_participation(specialist["id"], plan["id"])
    provider = create_provider()
    patient = create_patient(plan["id"])
    return plan, specialist, provider, patient


class TestBookingWindowShape:
    def test_window_shape_validation_matrix(self, api):
        """PRD §3.6: "Separately, the window itself must be well-formed:
        `scheduled_end` strictly after `scheduled_start`, and `scheduled_start` not
        in the past relative to the current clock — violations fail with
        `ERR_INVALID_WINDOW`."
        PRD §3.1: "the window is malformed when `effective_to` falls before
        `effective_from`, which fails with `ERR_INVALID_WINDOW`."
        PRD §2.7: "Within that final temporal priority, window-shape errors are
        reported before overlap errors, and overlap errors before threshold or grace
        errors."

        Design: Corner/validations/window_shape_validation_matrix
        """
        plan, specialist, provider, patient = _bootstrap()
        referral = create_assigned_referral(provider["id"], patient["id"], specialist["id"])
        version = referral["version"]

        e1 = api.book_appointment(
            referral["id"],
            book_appointment_payload(version, "2026-08-02T11:00:00Z", "2026-08-02T10:00:00Z"),
            COORD,
        )
        validate_error(e1, ApiErrorId.ERR_INVALID_WINDOW, expected_status=400)

        e2 = api.book_appointment(
            referral["id"],
            book_appointment_payload(version, "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z"),
            COORD,
        )
        validate_error(e2, ApiErrorId.ERR_INVALID_WINDOW, expected_status=400)

        e3 = api.create_participation(
            {
                "specialist_id": specialist["id"], "insurance_plan_id": plan["id"],
                "tier": "STANDARD", "effective_from": "2026-12-31",
                "effective_to": "2026-01-01",
            },
            TEST_USERS["network_admin_headers"],
        )
        validate_error(e3, ApiErrorId.ERR_INVALID_WINDOW, expected_status=400)

        assert get_referral(referral["id"])["version"] == version, (
            "Rejected bookings must not mutate the referral"
        )


class TestTargetFidelity:
    def test_target_mismatch_on_booking(self, api):
        """PRD §3.6: "Target fidelity third: when a `target_specialist_id` is set and
        the payload names a different specialist, the request fails with
        `ERR_TARGET_MISMATCH`."

        Design: Corner/validations/target_mismatch_on_booking
        """
        plan, specialist, provider, patient = _bootstrap()
        s2 = create_specialist(name="S2", npi="1000000002")
        create_participation(s2["id"], plan["id"])
        referral = create_assigned_referral(provider["id"], patient["id"], specialist["id"])

        res = api.book_appointment(
            referral["id"],
            book_appointment_payload(
                referral["version"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
                specialist_id=s2["id"],
            ),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_TARGET_MISMATCH, expected_status=422)


class TestParticipationGate:
    def _setup_out_of_window(self, api):
        """Specialist's only participation window ended 2026-06-30; clock is
        2026-08-01, so no ACTIVE participation covers the current date."""
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        specialist = create_specialist()
        create_participation(specialist["id"], plan["id"], tier="PREFERRED",
                             effective_from="2026-01-01", effective_to="2026-06-30")
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_assigned_referral(provider["id"], patient["id"], specialist["id"])
        return plan, specialist, provider, patient, referral

    def test_booking_without_active_participation_rejected(self, api):
        """PRD §3.6: "Network participation fourth: an `ACTIVE` participation row
        must cover the specialist and the referral's plan on the current date; when
        none exists, booking still proceeds only if `patient_choice_documented` is
        true and `patient_choice_type` is `OUT_OF_NETWORK_PATIENT_REQUEST` or
        `OUT_OF_NETWORK_CAPACITY`, and otherwise fails with
        `ERR_NO_ACTIVE_PARTICIPATION`."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_active_participation
        """
        plan, specialist, provider, patient, referral = self._setup_out_of_window(api)
        res = api.book_appointment(
            referral["id"],
            book_appointment_payload(
                referral["version"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z"
            ),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_PARTICIPATION, expected_status=409)
        assert get_referral(referral["id"])["status"] == "ACCEPTED"

    def test_documented_out_of_network_choice_bypasses_gate(self, api):
        """PRD §3.6: "when none exists, booking still proceeds only if
        `patient_choice_documented` is true and `patient_choice_type` is
        `OUT_OF_NETWORK_PATIENT_REQUEST` or `OUT_OF_NETWORK_CAPACITY`".
        PRD §3.6: "When the participation gate was bypassed on the strength of a
        documented out-of-network choice, the booking additionally marks the referral
        `out_of_network` true and creates a `LeakageRecord`: its `category` is
        `PATIENT_CHOICE_OUT_OF_NETWORK` when the documented choice type was
        `OUT_OF_NETWORK_PATIENT_REQUEST`, and `CAPACITY_OUT_OF_NETWORK` when it was
        `OUT_OF_NETWORK_CAPACITY`; the referral's `leaked` flag turns true".

        Design: Difficulty/cross_entity_state_dependency/booking_requires_active_participation
        """
        plan, specialist, provider, patient, referral = self._setup_out_of_window(api)
        updated = validate_success(api.document_patient_choice(
            referral["id"],
            document_patient_choice_payload("OUT_OF_NETWORK_PATIENT_REQUEST",
                                            "Patient insists on Dr S1"),
            COORD,
        ))
        appointment = book_appointment(
            updated, "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z"
        )
        assert appointment["status"] == "SCHEDULED"

        after = get_referral(referral["id"])
        assert after["status"] == "SCHEDULED"
        assert after["out_of_network"] is True
        assert after["leaked"] is True
        records = list_referral_leakage_records(referral["id"])
        assert len(records) == 1
        assert records[0]["category"] == "PATIENT_CHOICE_OUT_OF_NETWORK"


class TestAppointmentOverlap:
    def _setup_four_accepted(self, api):
        plan, specialist, provider, patient = _bootstrap()
        booked_referral, _appt = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z", diagnosis_code="I10",
        )
        waiting = [
            create_assigned_referral(provider["id"], patient["id"], specialist["id"],
                                     diagnosis_code=code)
            for code in ("I11", "I20", "I25")
        ]
        return specialist, booked_referral, waiting

    def test_overlap_inside_buffer_rejected(self, api):
        """PRD §3.6: "Overlap fifth: the new appointment's occupied interval — from
        its start to its end plus a 15-minute buffer, half-open — must not intersect
        any other `SCHEDULED` or `CONFIRMED` appointment of the same specialist,
        whose occupied intervals use the same start to end-plus-15-minutes half-open
        shape; a new appointment starting at or after an existing appointment's end
        plus 15 minutes is fine, but any genuine intersection fails with
        `ERR_APPOINTMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/appointment_overlap_buffer_semantics
        """
        specialist, _booked, waiting = self._setup_four_accepted(api)
        # Existing occupies [10:00, 11:15). 10:45 intersects.
        e1 = api.book_appointment(
            waiting[0]["id"],
            book_appointment_payload(waiting[0]["version"],
                                     "2026-08-02T10:45:00Z", "2026-08-02T11:30:00Z"),
            COORD,
        )
        validate_error(e1, ApiErrorId.ERR_APPOINTMENT_OVERLAP, expected_status=409)
        # 11:00 is inside the trailing buffer (end alone is not enough).
        e2 = api.book_appointment(
            waiting[1]["id"],
            book_appointment_payload(waiting[1]["version"],
                                     "2026-08-02T11:00:00Z", "2026-08-02T11:30:00Z"),
            COORD,
        )
        validate_error(e2, ApiErrorId.ERR_APPOINTMENT_OVERLAP, expected_status=409)

    def test_touching_buffer_boundary_allowed(self, api):
        """PRD §3.6: "a new appointment starting at or after an existing
        appointment's end plus 15 minutes is fine".
        PRD §3.1: "Every specialist also carries a computed
        `booked_appointments_count`, initialized to zero, tracking how many of that
        specialist's appointments currently sit in `SCHEDULED` or `CONFIRMED` status;
        the counter is maintained on every booking, cancellation, no-show,
        completion, and supersede."

        Design: Difficulty/resource_temporal_overlap/appointment_overlap_buffer_semantics
        """
        specialist, _booked, waiting = self._setup_four_accepted(api)
        # 11:15 is exactly end (11:00) + 15m buffer: allowed.
        appointment = book_appointment(
            waiting[2], "2026-08-02T11:15:00Z", "2026-08-02T12:00:00Z"
        )
        assert appointment["status"] == "SCHEDULED"
        assert get_specialist(specialist["id"])["booked_appointments_count"] == 2


class TestOptimisticConcurrencyOnBooking:
    def test_stale_version_booking_rejected_then_fresh_succeeds(self, api):
        """PRD §2.5: "Booking an appointment for a referral requires the request to
        carry `expected_referral_version`, a non-optional input field holding the
        client last observed `version` of that referral. ... if the supplied value
        does not equal the referral's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
        PRD §3.6: "If the referral already has an appointment in `SCHEDULED` or
        `CONFIRMED`, that appointment transitions to `CANCELLED` with `superseded`
        set to true and its specialist's `booked_appointments_count` decremented
        by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_booking_rejected
        """
        plan, specialist, provider, patient = _bootstrap()
        referral = create_assigned_referral(provider["id"], patient["id"], specialist["id"])
        stale_version = referral["version"]  # 3
        a1 = book_appointment(referral, "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")

        res = api.book_appointment(
            referral["id"],
            book_appointment_payload(stale_version,
                                     "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z"),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        current = get_referral(referral["id"])
        assert current["version"] == stale_version + 1, "Nothing is written on a stale booking"
        data, meta = validate_paginated(api.list_referral_appointments(referral["id"], COORD))
        assert len(data) == 1, "The stale booking must not create an appointment"

        a2 = book_appointment(current, "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        assert a2["status"] == "SCHEDULED"
        a1_after = get_appointment(a1["id"])
        assert a1_after["status"] == "CANCELLED"
        assert a1_after["superseded"] is True
        assert get_referral(referral["id"])["version"] == stale_version + 2


class TestSupersedeSlotLedger:
    def test_supersede_keeps_booked_count_consistent(self, api):
        """PRD §3.6: "If the referral already has an appointment in `SCHEDULED` or
        `CONFIRMED`, that appointment transitions to `CANCELLED` with `superseded`
        set to true and its specialist's `booked_appointments_count` decremented by
        1. The new `Appointment` is created in `SCHEDULED` status with
        `scheduled_by_user_id` recorded from the caller's `X-User-ID`, and the
        effective specialist's `booked_appointments_count` increments by 1."

        Design: Corner/cross_cutting_complexity_layers/supersede_keeps_booked_count_consistent
        """
        plan, specialist, provider, patient = _bootstrap()
        referral = create_assigned_referral(provider["id"], patient["id"], specialist["id"])
        a1 = book_appointment(referral, "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        assert get_specialist(specialist["id"])["booked_appointments_count"] == 1

        current = get_referral(referral["id"])
        a2 = book_appointment(current, "2026-08-04T10:00:00Z", "2026-08-04T11:00:00Z")

        a1_after = get_appointment(a1["id"])
        assert a1_after["status"] == "CANCELLED"
        assert a1_after["superseded"] is True
        assert get_appointment(a2["id"])["status"] == "SCHEDULED"
        assert get_specialist(specialist["id"])["booked_appointments_count"] == 1, (
            "Supersede nets to zero: -1 for the old appointment, +1 for the new one"
        )
        assert get_referral(referral["id"])["status"] == "SCHEDULED"


class TestBookedSlotCompensation:
    def test_cancel_compensates_booking(self, api):
        """PRD §3.1: "the counter is maintained on every booking, cancellation,
        no-show, completion, and supersede."
        PRD §3.6: "A coordinator may also cancel an appointment outright from
        `SCHEDULED` or `CONFIRMED` (else `ERR_INVALID_STATE`), which frees the booked
        slot by decrementing `booked_appointments_count` and, when the cancellation
        was a direct one — not a supersede, not a referral-level cascade — and no
        sibling appointment remains active and the referral still reads `SCHEDULED`,
        returns the referral to `ACCEPTED`."

        Design: Difficulty/compensating_invariant/booked_slot_compensation
        """
        plan, specialist, provider, patient = _bootstrap()
        r1, a1 = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                        "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
                                        diagnosis_code="I10")
        r2, a2 = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                        "2026-08-02T12:00:00Z", "2026-08-02T13:00:00Z",
                                        diagnosis_code="I11")
        assert get_specialist(specialist["id"])["booked_appointments_count"] == 2

        cancel_appointment(a1["id"])
        assert get_specialist(specialist["id"])["booked_appointments_count"] == 1, (
            "Cancel compensates the booking"
        )
        assert get_referral(r1["id"])["status"] == "ACCEPTED", (
            "Direct cancel with no active sibling returns the referral to ACCEPTED"
        )

    def test_confirm_complete_releases_slot(self, api):
        """PRD §3.6: "A successful completion stamps `completed_at`, decrements the
        specialist's `booked_appointments_count` by 1, advances the referral from
        `SCHEDULED` to `VISIT_COMPLETED`".

        Design: Difficulty/compensating_invariant/booked_slot_compensation
        """
        plan, specialist, provider, patient = _bootstrap()
        r1, a1 = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                        "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
                                        diagnosis_code="I10")
        r2, a2 = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                        "2026-08-02T12:00:00Z", "2026-08-02T13:00:00Z",
                                        diagnosis_code="I11")
        assert get_specialist(specialist["id"])["booked_appointments_count"] == 2

        cancel_appointment(a1["id"])
        confirm_appointment(a2["id"])
        set_clock("2026-08-02T12:00:00Z")
        complete_appointment(a2["id"], specialist["id"])

        assert get_specialist(specialist["id"])["booked_appointments_count"] == 0, (
            "Completion releases the slot: 2 bookings - 1 cancel - 1 completion == 0"
        )
        assert get_referral(r2["id"])["status"] == "VISIT_COMPLETED"


class TestBookingExistencePriority:
    def test_nonexistent_specialist_on_pending_referral(self, api):
        """PRD §2.7: "Fifth, existence: path resource ids are validated left to
        right, then body foreign-key references in their declared input order
        (priority 5 — the 404 family such as ... `ERR_SPECIALIST_NOT_FOUND` ...). ...
        Seventh, state preconditions of the invoked transition (priority 7 —
        `ERR_INVALID_STATE`, ...)".

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_booking
        """
        plan = create_plan()
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_referral(provider["id"], patient["id"])  # PENDING_TRIAGE
        res = api.book_appointment(
            referral["id"],
            book_appointment_payload(referral["version"],
                                     "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
                                     specialist_id=NON_EXISTENT_UUID),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_SPECIALIST_NOT_FOUND, expected_status=404)

    def test_failed_booking_leaves_referral_unchanged(self, api):
        """PRD §2.7: existence (priority 5) is evaluated before state (priority 7),
        so the state violation (booking from PENDING_TRIAGE) never fires.
        PRD §2.4: "`version`, an integer starting at 1 that increments by exactly 1
        on every mutation of that resource."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_booking
        """
        plan = create_plan()
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_referral(provider["id"], patient["id"])  # PENDING_TRIAGE, v1
        res = api.book_appointment(
            referral["id"],
            book_appointment_payload(referral["version"],
                                     "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
                                     specialist_id=NON_EXISTENT_UUID),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_SPECIALIST_NOT_FOUND, expected_status=404)
        after = get_referral(referral["id"])
        assert after["status"] == "PENDING_TRIAGE"
        assert after["version"] == 1
