"""Clinic appointment booking: capacity boundary, session-state guard, half-open
overlap, seat conservation, completion side effects, and OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_clinic_appointment,
    assert_clinic_session,
    assert_immunization_record,
    assert_instants_equal,
    assert_version_incremented,
    book_appointment,
    create_appointment_payload,
    create_clinic_session_payload,
    create_mmr_requirement,
    create_open_session,
    create_student,
    get_session,
    get_student,
    setup_two_sessions_one_booked,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCapacityBoundary:

    def test_booking_at_capacity_minus_one_accepted(self, clerk_headers):
        """PRD section 3.7: "Capacity is judged on `booked_count` against
        `capacity`: a session whose `booked_count` already equals its `capacity`
        rejects the booking with `ERR_SESSION_FULL`, while one short of capacity
        accepts it."

        Design: Difficulty/boundary_precision_check/session_capacity_exact_boundary
        """
        session = create_open_session("SCH-C1", capacity=1)
        student = create_student("SCH-Y", legal_name="Ann A")

        session_now = get_session(session["id"])
        resp = api_client.book_appointment(
            session["id"],
            create_appointment_payload(student["id"], session_now["version"]),
            clerk_headers,
        )
        appointment = validate_success(resp, 201)
        assert_clinic_appointment(appointment)
        assert appointment["status"] == "BOOKED"

        after = get_session(session["id"])
        assert after["booked_count"] == 1, (
            "booked_count 0 == capacity - 1 must accept the booking"
        )
        assert_version_incremented(after["version"], session_now["version"])

    def test_booking_at_capacity_rejected(self, clerk_headers):
        """PRD section 3.7: "Capacity is judged on `booked_count` against
        `capacity`: a session whose `booked_count` already equals its `capacity`
        rejects the booking with `ERR_SESSION_FULL`, while one short of capacity
        accepts it."

        Design: Difficulty/boundary_precision_check/session_capacity_exact_boundary
        """
        session = create_open_session("SCH-C1", capacity=1)
        student_a = create_student("SCH-Y", legal_name="Ann A")
        student_b = create_student("SCH-Y", legal_name="Ben B")
        book_appointment(session["id"], student_a["id"],
                         start_time="2026-09-01T10:00:00Z",
                         end_time="2026-09-01T10:30:00Z")

        session_now = get_session(session["id"])
        assert session_now["booked_count"] == 1 == session_now["capacity"]
        resp = api_client.book_appointment(
            session["id"],
            create_appointment_payload(
                student_b["id"], session_now["version"],
                start_time="2026-09-01T10:30:00Z",
                end_time="2026-09-01T11:00:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)
        assert get_session(session["id"])["booked_count"] == 1, (
            "a rejected booking must not consume a seat"
        )


class TestSessionOpenGuard:

    def test_booking_into_scheduled_session_rejected(self, clerk_headers):
        """PRD section 2.7: "opening a session requires `SCHEDULED`
        (`ERR_SESSION_NOT_OPENABLE`), closing requires `OPEN`
        (`ERR_SESSION_NOT_CLOSABLE`), cancelling requires `SCHEDULED` or `OPEN`
        (`ERR_SESSION_NOT_CANCELLABLE`), and booking requires `OPEN`
        (`ERR_SESSION_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/booking_requires_session_open
        """
        session = validate_success(
            api_client.create_clinic_session(
                create_clinic_session_payload(school_code="SCH-C2"),
                TEST_USERS["nurse_headers"],
            ),
            201,
        )
        assert session["status"] == "SCHEDULED"
        student = create_student("SCH-Y", legal_name="Cid Why")

        resp = api_client.book_appointment(
            session["id"],
            create_appointment_payload(student["id"], session["version"]),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)

    def test_booking_after_open_succeeds(self, clerk_headers, nurse_headers):
        """PRD section 3.7: "A session is born `SCHEDULED` with `booked_count` 0;
        the nurse then opens it (`SCHEDULED` → `OPEN`) to accept bookings, closes
        it (`OPEN` → `CLOSED`) when done, or cancels it from either `SCHEDULED` or
        `OPEN`."
        PRD section 2.7: "booking requires `OPEN` (`ERR_SESSION_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/booking_requires_session_open
        """
        session = validate_success(
            api_client.create_clinic_session(
                create_clinic_session_payload(school_code="SCH-C2"), nurse_headers
            ),
            201,
        )
        student = create_student("SCH-Y", legal_name="Cid Why")
        opened = validate_success(
            api_client.open_clinic_session(session["id"], nurse_headers), 200
        )
        assert opened["status"] == "OPEN"

        resp = api_client.book_appointment(
            session["id"],
            create_appointment_payload(student["id"], opened["version"]),
            clerk_headers,
        )
        appointment = validate_success(resp, 201)
        assert appointment["status"] == "BOOKED"
        assert get_session(session["id"])["booked_count"] == 1


class TestHalfOpenOverlap:

    def test_adjacent_bookings_allowed(self, clerk_headers):
        """PRD section 3.7: "the interval must not overlap any other `BOOKED`
        appointment of the same student — two appointments that merely touch, one's
        `end_time` equal to the other's `start_time`, do not conflict — else
        `ERR_APPOINTMENT_TIME_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/appointment_half_open_overlap_adjacency
        """
        session = create_open_session("SCH-C3", duration_minutes=240, capacity=10)
        student = create_student("SCH-Y", legal_name="Hal Why")
        book_appointment(session["id"], student["id"],
                         start_time="2026-09-01T10:00:00Z",
                         end_time="2026-09-01T10:30:00Z")

        session_now = get_session(session["id"])
        resp = api_client.book_appointment(
            session["id"],
            create_appointment_payload(
                student["id"], session_now["version"],
                start_time="2026-09-01T10:30:00Z",
                end_time="2026-09-01T11:00:00Z",
            ),
            clerk_headers,
        )
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "BOOKED", (
            "an appointment starting exactly at another's end_time is adjacent, "
            "not overlapping"
        )
        assert get_session(session["id"])["booked_count"] == 2

    def test_overlapping_booking_rejected(self, clerk_headers):
        """PRD section 3.7: "the interval must not overlap any other `BOOKED`
        appointment of the same student — two appointments that merely touch, one's
        `end_time` equal to the other's `start_time`, do not conflict — else
        `ERR_APPOINTMENT_TIME_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/appointment_half_open_overlap_adjacency
        """
        session = create_open_session("SCH-C3", duration_minutes=240, capacity=10)
        student = create_student("SCH-Y", legal_name="Hal Why")
        book_appointment(session["id"], student["id"],
                         start_time="2026-09-01T10:00:00Z",
                         end_time="2026-09-01T10:30:00Z")

        session_now = get_session(session["id"])
        resp = api_client.book_appointment(
            session["id"],
            create_appointment_payload(
                student["id"], session_now["version"],
                start_time="2026-09-01T10:15:00Z",
                end_time="2026-09-01T10:45:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_TIME_CONFLICT)
        assert get_session(session["id"])["booked_count"] == 1, (
            "a rejected overlapping booking must not consume a seat"
        )


class TestStateBeatsTemporal:

    def test_state_beats_temporal_overlap_on_booking(self, clerk_headers):
        """PRD section 2.7: "When multiple checks could reject the same request, the
        system evaluates them in a fixed priority order and surfaces the first
        failure encountered."
        PRD section 2.7: "cancelling requires `SCHEDULED` or `OPEN`
        (`ERR_SESSION_NOT_CANCELLABLE`), and booking requires `OPEN`
        (`ERR_SESSION_NOT_OPEN`)".
        PRD section 2.7: "7. **Temporal placement** — in this order: (7a) session
        spacing for the school, else `ERR_SESSION_GAP_VIOLATION`; (7b) the
        appointment must lie within the session window, else
        `ERR_APPOINTMENT_OUTSIDE_SESSION`; (7c) the appointment must not overlap
        another booked appointment of the same student, else
        `ERR_APPOINTMENT_TIME_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_booking
        """
        student, session_1, session_2 = setup_two_sessions_one_booked()
        assert session_2["status"] == "SCHEDULED"
        # 10:15-10:45 overlaps the student's 10:00-10:30 BOOKED appointment in
        # session 1 (priority 7c), but the session-2 state check (priority 5)
        # must surface first.
        resp = api_client.book_appointment(
            session_2["id"],
            create_appointment_payload(
                student["id"], session_2["version"],
                start_time="2026-09-01T10:15:00Z",
                end_time="2026-09-01T10:45:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)

    def test_state_beats_outside_window_on_booking(self, clerk_headers):
        """PRD section 2.7: "When multiple checks could reject the same request, the
        system evaluates them in a fixed priority order and surfaces the first
        failure encountered."
        PRD section 2.7: "cancelling requires `SCHEDULED` or `OPEN`
        (`ERR_SESSION_NOT_CANCELLABLE`), and booking requires `OPEN`
        (`ERR_SESSION_NOT_OPEN`)".
        PRD section 2.7: "7. **Temporal placement** — in this order: (7a) session
        spacing for the school, else `ERR_SESSION_GAP_VIOLATION`; (7b) the
        appointment must lie within the session window, else
        `ERR_APPOINTMENT_OUTSIDE_SESSION`; (7c) the appointment must not overlap
        another booked appointment of the same student, else
        `ERR_APPOINTMENT_TIME_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_booking
        """
        _, _, session_2 = setup_two_sessions_one_booked()
        assert session_2["status"] == "SCHEDULED"
        other = create_student("SCH-Y", legal_name="Outside Window")
        # 13:00-13:30 lies outside session 2's 09:00-12:00 window (priority 7b),
        # but the session state check (priority 5) must surface first.
        resp = api_client.book_appointment(
            session_2["id"],
            create_appointment_payload(
                other["id"], session_2["version"],
                start_time="2026-09-01T13:00:00Z",
                end_time="2026-09-01T13:30:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)


class TestSeatConservation:

    def test_book_cancel_seat_conservation(self, clerk_headers):
        """PRD section 3.7: "The `booked_count` on a session is always the live
        count of its appointments in `BOOKED` status — completed, cancelled, and
        no-show appointments do not count. It is recomputed after every appointment
        mutation affecting the session: booking increments it by 1, while
        cancellation, completion, and the no-show sweep each decrement it by 1, and
        every such recompute increments the session's `version`."

        Design: Difficulty/compensating_invariant/book_cancel_seat_conservation
        """
        session = create_open_session("SCH-C5", capacity=3)
        student = create_student("SCH-Y", legal_name="Ivy Why")
        before = get_session(session["id"])
        assert before["booked_count"] == 0

        appointment = book_appointment(session["id"], student["id"])
        mid = get_session(session["id"])
        assert mid["booked_count"] == 1
        assert_version_incremented(mid["version"], before["version"])

        cancelled = validate_success(
            api_client.cancel_appointment(appointment["id"], clerk_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"
        after = get_session(session["id"])
        assert after["booked_count"] == 0, (
            "book followed by cancel must restore the pre-pair seat count"
        )
        assert_version_incremented(after["version"], mid["version"])

    def test_booked_count_equals_live_booked_appointments(self, nurse_headers):
        """PRD section 3.7: "The `booked_count` on a session is always the live
        count of its appointments in `BOOKED` status — completed, cancelled, and
        no-show appointments do not count. It is recomputed after every appointment
        mutation affecting the session: booking increments it by 1, while
        cancellation, completion, and the no-show sweep each decrement it by 1, and
        every such recompute increments the session's `version`."

        Design: Difficulty/compensating_invariant/book_cancel_seat_conservation
        """
        session = create_open_session("SCH-C5", capacity=3)
        student_a = create_student("SCH-Y", legal_name="Ivy A")
        student_b = create_student("SCH-Y", legal_name="Ivy B")
        appt_a = book_appointment(session["id"], student_a["id"],
                                  start_time="2026-09-01T10:00:00Z",
                                  end_time="2026-09-01T10:30:00Z")
        book_appointment(session["id"], student_b["id"],
                         start_time="2026-09-01T10:30:00Z",
                         end_time="2026-09-01T11:00:00Z")
        assert get_session(session["id"])["booked_count"] == 2

        api_client.cancel_appointment(appt_a["id"], TEST_USERS["clerk_headers"])

        appointments, meta = validate_paginated(
            api_client.list_session_appointments(session["id"], nurse_headers)
        )
        live_booked = [a for a in appointments if a["status"] == "BOOKED"]
        session_after = get_session(session["id"])
        assert session_after["booked_count"] == 1
        assert len(live_booked) == session_after["booked_count"], (
            "booked_count must equal the live count of BOOKED appointments"
        )


class TestCompletionAndCancellation:

    def test_complete_appointment_creates_verified_dose(self, nurse_headers):
        """PRD section 3.7: "completion creates an ImmunizationRecord for the
        appointment's student and vaccine with `source` set to `CLINIC`, `status`
        born `VERIFIED`, `clinic_appointment_id` pointing back at the appointment,
        `administered_date` taken from the appointment's `start_time`, and
        `dose_number` assigned as one more than the highest `dose_number` among the
        student's existing non-`VOIDED` records for that vaccine — 1 if none exist.
        Completion then re-evaluates the student exactly as a verification does,
        including the notice-cure cascade of §3.5."
        PRD section 3.5: "A student in `ENROLLED_PROVISIONAL` who reaches full
        satisfaction through the same events transitions directly to
        `ENROLLED_COMPLIANT` with the deficiency list cleared."

        Design: Corner/state_machines/complete_appointment_creates_verified_dose
        """
        create_mmr_requirement(doses_required=1)
        student = create_student("SCH-Y", legal_name="Com Plete")
        session = create_open_session("SCH-C6",
                                      session_date="2026-08-10T09:00:00Z")
        appointment = book_appointment(session["id"], student["id"],
                                       start_time="2026-08-10T09:30:00Z",
                                       end_time="2026-08-10T10:00:00Z")

        completed = validate_success(
            api_client.complete_appointment(appointment["id"], nurse_headers), 200
        )
        assert completed["status"] == "COMPLETED"

        records, meta = validate_paginated(
            api_client.list_appointment_records(appointment["id"], nurse_headers)
        )
        assert meta["total_count"] == 1
        record = records[0]
        assert_immunization_record(record)
        assert record["source"] == "CLINIC"
        assert record["status"] == "VERIFIED"
        assert record["dose_number"] == 1
        assert record["clinic_appointment_id"] == appointment["id"]
        assert_instants_equal(record["administered_date"], "2026-08-10T09:30:00Z",
                              "administered_date must be the appointment start_time")

        assert get_student(student["id"])["status"] == "ENROLLED_COMPLIANT"
        assert get_session(session["id"])["booked_count"] == 0

    def test_cancel_twice_appointment_rejected(self, clerk_headers):
        """PRD section 3.7: "Cancel or complete attempted on an appointment no
        longer in `BOOKED` is rejected with `ERR_APPOINTMENT_NOT_BOOKED`."

        Design: Corner/state_machines/cancel_twice_appointment_rejected
        """
        student = create_student("SCH-Y", legal_name="Cancel Twice")
        session = create_open_session("SCH-C14")
        appointment = book_appointment(session["id"], student["id"])
        cancelled = validate_success(
            api_client.cancel_appointment(appointment["id"], clerk_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"

        resp = api_client.cancel_appointment(appointment["id"], clerk_headers)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_BOOKED)

    def test_appointment_outside_session_window_rejected(self, clerk_headers):
        """PRD section 3.7: "Three placement rules guard booking, in the order of
        §2.7: the interval must lie entirely within the session window, else
        `ERR_APPOINTMENT_OUTSIDE_SESSION` (HTTP 422); the interval must not overlap
        any other `BOOKED` appointment of the same student — two appointments that
        merely touch, one's `end_time` equal to the other's `start_time`, do not
        conflict — else `ERR_APPOINTMENT_TIME_CONFLICT`; and the session must still
        have a free seat."

        Design: Corner/validations/appointment_outside_session_window_rejected
        """
        student = create_student("SCH-Y", legal_name="Out Side")
        session = create_open_session("SCH-C8", duration_minutes=60)
        # Window is [2026-09-01T09:00, 2026-09-01T10:00); 10:30-11:00 lies outside.
        resp = api_client.book_appointment(
            session["id"],
            create_appointment_payload(
                student["id"], session["version"],
                start_time="2026-09-01T10:30:00Z",
                end_time="2026-09-01T11:00:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OUTSIDE_SESSION)


class TestSessionOcc:

    def test_occ_stale_session_version_on_booking(self, clerk_headers, nurse_headers):
        """PRD section 2.6: "Booking an appointment into a clinic session requires
        the request to carry `expected_clinic_session_version`, holding the
        `version` of the ClinicSession the client last observed. Every booking,
        cancellation, completion, or no-show sweep legitimately recomputes
        `booked_count` and increments the session's `version`, so a mismatch
        between the supplied value and the session's current `version` is rejected
        with `ERR_STALE_SESSION_VERSION` (HTTP 412): the client is booking against
        a superseded view of the session's remaining capacity."

        Design: Corner/cross_cutting_layers/occ_stale_session_version_on_booking
        """
        student_a = create_student("SCH-Y", legal_name="Occ A")
        student_b = create_student("SCH-Y", legal_name="Occ B")
        session = create_open_session("SCH-OCS", duration_minutes=240, capacity=5)
        stale_version = session["version"]

        first = validate_success(
            api_client.book_appointment(
                session["id"],
                create_appointment_payload(
                    student_a["id"], stale_version,
                    start_time="2026-09-01T10:00:00Z",
                    end_time="2026-09-01T10:30:00Z",
                ),
                clerk_headers,
            ),
            201,
        )
        assert first["status"] == "BOOKED"

        # The first booking bumped booked_count and advanced the session version;
        # replaying the captured version must now be rejected.
        resp = api_client.book_appointment(
            session["id"],
            create_appointment_payload(
                student_b["id"], stale_version,
                start_time="2026-09-01T11:00:00Z",
                end_time="2026-09-01T11:30:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SESSION_VERSION)
        assert get_session(session["id"])["booked_count"] == 1, (
            "a rejected booking must not consume a seat"
        )


class TestReverseListing:

    def test_student_appointments_reverse_listing(self, nurse_headers):
        """PRD section 3.7: "The dose record a completion produced remains
        traceable: the records linked to an appointment can be listed (zero or one
        entries), and a student's appointments can be listed across sessions."
        PRD section 2.8: "Endpoints that address a resource nested under another —
        a student's dose records, a session's appointments — validate path
        identifiers strictly left to right."

        Design: Corner/endpoints/student_appointments_reverse_listing
        """
        student = create_student("SCH-Y", legal_name="Rev Fk")
        other = create_student("SCH-Y", legal_name="Rev Other")
        session = create_open_session("SCH-C10")
        appointment = book_appointment(session["id"], student["id"],
                                       start_time="2026-09-01T10:00:00Z",
                                       end_time="2026-09-01T10:30:00Z")
        book_appointment(session["id"], other["id"],
                         start_time="2026-09-01T10:30:00Z",
                         end_time="2026-09-01T11:00:00Z")

        resp = api_client.list_student_appointments(student["id"], nurse_headers)
        appointments, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert meta["total_count"] == 1, (
            "the reverse listing must return exactly this student's appointments"
        )
        assert appointments[0]["id"] == appointment["id"]
        assert appointments[0]["student_id"] == student["id"]
        assert appointments[0]["clinic_session_id"] == session["id"]
