"""Lifecycle / state-machine breadth: initial states, invalid transitions,
precondition enforcement, terminal lockdown, side-effect execution,
idempotency.

Queue B (Corner): section state_machines.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_shop_admin_headers, make_instructor_headers,
    create_diver, create_course, create_instructor, create_boat, create_enrollment,
    create_session, create_dive_trip, sign_waiver, create_waiver_cleared_diver,
    set_clock, book_seat, attend_booking, certify_diver_open_water,
    setup_eligible_enrollment,
)
from test_helpers import factories as f
from test_helpers import ApiErrorId

ADMIN = make_shop_admin_headers()


class TestInitialAndInvalidStates:
    def test_enrollment_starts_active(self, api):
        """PRD 3.3: "A new enrollment begins in `ACTIVE` status with `elearning_pct`
        at 0, both attendance counters (`pool_sessions_attended` and
        `open_water_sessions_attended`) at 0".

        Design: Corner/state_machines/enrollment_starts_active
        """
        course = create_course()
        diver = create_diver(full_name="Init Ida")
        enr = validate_success(
            api.create_enrollment(
                f.create_enrollment_payload(diver["id"], course["id"]), ADMIN
            ), expected_status=201,
        )
        assert enr["status"] == "ACTIVE", enr

    def test_cancel_already_cancelled_session_invalid_state(self, api):
        """PRD 3.4: "A `ShopAdmin` may instead cancel a `SCHEDULED` session, driving
        it `SCHEDULED → CANCELLED`".
        PRD 2.9: "sixth, state — the target resource is in a state from which the
        requested transition is legal (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/cancel_already_cancelled_session_invalid_state
        """
        course = create_course()
        instructor = create_instructor(full_name="Term Inst")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-07-01T08:00:00Z", ends_at="2026-07-01T10:00:00Z",
        )
        validate_success(api.cancel_session(session["id"], ADMIN))
        resp = api.cancel_session(session["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_complete_session_before_start_invalid(self, api):
        """PRD 3.4: "An `Instructor` who is the session's `primary_instructor_id`
        may complete the session once the logical clock has reached or passed the
        session's `starts_at` and the session is still `SCHEDULED`; an attempt by
        any other instructor, or before the start time, or against a session not in
        `SCHEDULED`, fails (a wrong-state target yields `ERR_INVALID_STATE`, HTTP
        409)."

        Design: Corner/state_machines/complete_session_before_start_invalid
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Early Inst")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-07-01T08:00:00Z", ends_at="2026-07-01T10:00:00Z",
        )
        resp = api.complete_session(session["id"], make_instructor_headers(instructor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_terminal_completed_enrollment_no_withdraw(self, api):
        """PRD 3.3: "A diver or a `ShopAdmin` may withdraw an enrollment. Withdrawal
        is permitted from either the `ACTIVE` or the `ELIGIBLE` state and drives the
        enrollment to the terminal `WITHDRAWN` status; from any other state it is
        rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/terminal_completed_enrollment_no_withdraw
        """
        diver, course, enr, _card = certify_diver_open_water(diver_full_name="Done Dora")
        resp = api.withdraw_enrollment(enr["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_issue_cert_from_active_invalid_state(self, api):
        """PRD 3.6: "Issuance is permitted only against an enrollment in the
        `ELIGIBLE` state; against any other state it is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/issue_cert_from_active_invalid_state
        """
        course = create_course()
        diver = create_diver(full_name="Hasty Hank")
        enr = create_enrollment(diver["id"], course["id"])
        resp = api.issue_certification(
            enr["id"], {"expected_enrollment_version": enr["version"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_attend_already_attended_idempotency(self, api):
        """PRD 3.5: "Recording attendance is permitted only by the `Instructor` who
        is the owning session's `primary_instructor_id`, only while the booking is
        `BOOKED`, and only while the owning session is still `SCHEDULED`."

        Design: Corner/state_machines/attend_already_attended_idempotency
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Idem Inst")
        diver = create_waiver_cleared_diver(full_name="Idem Iris")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        enr = create_enrollment(diver["id"], course["id"])
        booking = book_seat(session["id"], enr["id"], session["version"])
        set_clock("2026-06-04T09:00:00Z")
        attend_booking(booking["id"], instructor["id"])
        resp = api.attend_session_booking(
            booking["id"], make_instructor_headers(instructor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestSideEffectExecution:
    def test_enrollment_withdraw_cancels_booked_sessions(self, api):
        """PRD 3.3: "Withdrawing cascades to release seats: every session booking
        belonging to the enrollment that is still `BOOKED` is moved to `CANCELLED`,
        and each release decrements the owning session's `confirmed_seats`."

        Design: Corner/state_machines/enrollment_withdraw_cancels_booked_sessions
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Side Inst")
        diver = create_waiver_cleared_diver(full_name="Wd Will")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-10T08:00:00Z", ends_at="2026-06-10T10:00:00Z",
        )
        enr = create_enrollment(diver["id"], course["id"])
        booking = book_seat(session["id"], enr["id"], session["version"])
        withdrawn = validate_success(api.withdraw_enrollment(enr["id"], ADMIN))
        assert withdrawn["status"] == "WITHDRAWN", withdrawn
        booking_after = get_success_data(api.get_session_booking(booking["id"], ADMIN))
        assert booking_after["status"] == "CANCELLED", booking_after
        sess_after = get_success_data(api.get_session(session["id"], ADMIN))
        assert sess_after["confirmed_seats"] == 0, sess_after

    def test_session_complete_marks_unattended_no_show(self, api):
        """PRD 3.4: "Completing a session drives it `SCHEDULED → COMPLETED`,
        decrements the lead instructor's `active_session_count`, and converts every
        booking on the session that is still `BOOKED` and was never recorded as
        attended into `NO_SHOW`, with each such conversion decrementing the
        session's `confirmed_seats`."

        Design: Corner/state_machines/session_complete_marks_unattended_no_show
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="NS Inst")
        diver = create_waiver_cleared_diver(full_name="NoShow Nan")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        enr = create_enrollment(diver["id"], course["id"])
        booking = book_seat(session["id"], enr["id"], session["version"])
        set_clock("2026-06-04T09:00:00Z")
        completed = validate_success(
            api.complete_session(session["id"], make_instructor_headers(instructor["id"]))
        )
        assert completed["status"] == "COMPLETED", completed
        booking_after = get_success_data(api.get_session_booking(booking["id"], ADMIN))
        assert booking_after["status"] == "NO_SHOW", booking_after
        assert completed["confirmed_seats"] == 0, completed

    def test_trip_depart_zeroes_balance_due(self, api):
        """PRD 3.7: "departure drives the trip `OPEN → DEPARTED` and, for every
        `CONFIRMED` booking on it, sets that booking's `balance_due_cents` to 0 (the
        balance is treated as settled at departure) and moves the booking
        `CONFIRMED → DEPARTED`."

        Design: Corner/state_machines/trip_depart_zeroes_balance_due
        """
        diver, course, enr, _card = certify_diver_open_water(diver_full_name="Dep Dave")
        boat = create_boat(name="Departer", capacity=6)
        trip = create_dive_trip(
            boat["id"], starts_at="2026-06-05T08:00:00Z",
            ends_at="2026-06-05T12:00:00Z", min_cert_level="OPEN_WATER",
            base_fare_cents=10000, fill_addon_cents=0,
        )
        tb = validate_success(
            api.create_trip_booking(
                f.create_trip_booking_payload(
                    trip["id"], diver["id"], trip["version"], tanks=0, party_size=1
                ), ADMIN,
            ), expected_status=201,
        )
        assert tb["balance_due_cents"] > 0, tb
        set_clock("2026-06-05T09:00:00Z")
        departed_trip = validate_success(api.depart_dive_trip(trip["id"], ADMIN))
        assert departed_trip["status"] == "DEPARTED", departed_trip
        tb_after = get_success_data(api.get_trip_booking(tb["id"], ADMIN))
        assert tb_after["status"] == "DEPARTED", tb_after
        assert tb_after["balance_due_cents"] == 0, tb_after

    def test_trip_cancel_cascades_bookings(self, api):
        """PRD 3.7: "A `ShopAdmin` may instead cancel an `OPEN` trip, driving it
        `OPEN → CANCELLED` and moving every `CONFIRMED` booking on it to
        `CANCELLED` with the trip's `confirmed_divers` driven to 0."

        Design: Corner/state_machines/trip_cancel_cascades_bookings
        """
        diver, course, enr, _card = certify_diver_open_water(diver_full_name="Tc Tom")
        boat = create_boat(name="Canceller", capacity=6)
        trip = create_dive_trip(
            boat["id"], starts_at="2026-06-30T08:00:00Z",
            ends_at="2026-06-30T12:00:00Z", min_cert_level="OPEN_WATER",
            base_fare_cents=10000, fill_addon_cents=0,
        )
        tb = validate_success(
            api.create_trip_booking(
                f.create_trip_booking_payload(
                    trip["id"], diver["id"], trip["version"], tanks=0, party_size=1
                ), ADMIN,
            ), expected_status=201,
        )
        cancelled_trip = validate_success(api.cancel_dive_trip(trip["id"], ADMIN))
        assert cancelled_trip["status"] == "CANCELLED", cancelled_trip
        tb_after = get_success_data(api.get_trip_booking(tb["id"], ADMIN))
        assert tb_after["status"] == "CANCELLED", tb_after
        assert cancelled_trip["confirmed_divers"] == 0, cancelled_trip

    def test_gear_service_complete_sets_next_due(self, api):
        """PRD 3.9: "completion drives it `OPEN → COMPLETED`, stamps `serviced_at`
        from the logical clock, and computes the `next_due_at` as `serviced_at` plus
        the service interval — 365 days for a `VIP` order, or 1825 days for a
        `HYDRO` order."

        Design: Corner/state_machines/gear_service_complete_sets_next_due
        """
        set_clock("2026-06-01T00:00:00Z")
        diver = create_diver(full_name="Hydro Hal")
        order = get_success_data(
            api.create_gear_service_order(
                f.create_gear_service_order_payload(diver["id"], service_type="HYDRO"), ADMIN
            )
        )
        completed = validate_success(api.complete_gear_service_order(order["id"], ADMIN))
        assert completed["status"] == "COMPLETED", completed
        # serviced_at 2026-06-01, +1825 days => 2031-05-31
        assert completed["serviced_at"].startswith("2026-06-01T00:00:00"), completed
        assert completed["next_due_at"].startswith("2031-05-31T00:00:00"), completed
