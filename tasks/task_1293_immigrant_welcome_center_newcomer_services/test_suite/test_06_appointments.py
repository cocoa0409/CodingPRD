"""Appointments: half-open conflict arithmetic, logical-clock time gates, and
state ordering (PRD §2.4, §2.8, §3.6)."""

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    create_appointment_payload,
    register_client, create_staff_member, open_case,
    create_appointment, confirm_appointment, drive_case_to_active,
    transition_case, staff_headers,
)

ADMIN = TEST_USERS["center_admin_headers"]


class TestAdvocateConflicts:
    def test_adjacent_appointment_allowed_but_overlap_rejected(self):
        """PRD §3.6: "Adjacency is explicitly permitted: a new appointment
        starting exactly when an existing one ends (or ending exactly when one
        starts) does not conflict. A genuine overlap is rejected with
        `ERR_ADVOCATE_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/advocate_half_open_interval_adjacency
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        create_appointment(case, mgr, starts_at="2026-08-10T10:00:00Z",
                           ends_at="2026-08-10T11:00:00Z")

        adjacent = validate_success(api_client.create_appointment(
            create_appointment_payload(case["id"], mgr["id"], kind="ORIENTATION",
                                       starts_at="2026-08-10T11:00:00Z",
                                       ends_at="2026-08-10T12:00:00Z"),
            staff_headers(mgr)), expected_status=201)
        assert adjacent["status"] == "REQUESTED"

        resp = api_client.create_appointment(
            create_appointment_payload(case["id"], mgr["id"], kind="BENEFITS",
                                       starts_at="2026-08-10T11:30:00Z",
                                       ends_at="2026-08-10T12:30:00Z"),
            staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_ADVOCATE_TIME_CONFLICT)

    def test_left_adjacency_allowed(self):
        """PRD §3.6: "Adjacency is explicitly permitted: a new appointment
        starting exactly when an existing one ends (or ending exactly when one
        starts) does not conflict."
        PRD §3.6: "a new appointment conflicts when another appointment with the
        same `advocate_id` sits in `REQUESTED` or `CONFIRMED` and the intervals
        genuinely overlap".

        Design: Difficulty/resource_temporal_overlap/advocate_half_open_interval_adjacency
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        create_appointment(case, mgr, starts_at="2026-08-10T10:00:00Z",
                           ends_at="2026-08-10T11:00:00Z")
        left = validate_success(api_client.create_appointment(
            create_appointment_payload(case["id"], mgr["id"], kind="ORIENTATION",
                                       starts_at="2026-08-10T09:00:00Z",
                                       ends_at="2026-08-10T10:00:00Z"),
            staff_headers(mgr)), expected_status=201)
        assert left["status"] == "REQUESTED", \
            "ending exactly when the existing one starts is adjacency, not conflict"


class TestStateBeatsTemporal:
    def _setup_suspended_case_with_confirmed_appointment(self):
        ctx = drive_case_to_active()
        mgr = ctx["manager"]
        case = ctx["case"]
        appt = create_appointment(case, mgr, kind="ORIENTATION",
                                  starts_at="2026-08-10T10:00:00Z",
                                  ends_at="2026-08-10T11:00:00Z")
        confirm_appointment(appt["id"], mgr)
        transition_case(case["id"], "SUSPENDED", mgr)
        return mgr, case

    def test_suspended_case_blocks_appointment_despite_overlap(self):
        """PRD §2.8: "When a request violates several rules at once, the error it
        receives is determined by a fixed precedence ladder; the first failing
        rung decides the response."
        PRD §2.8: "4. **State** — the target resource sits in a valid from-state
        for the requested transition, terminal states reject all further
        transitions, and a `SUSPENDED` or `CLOSED` case rejects new child-service
        writes; failure yields `ERR_INVALID_STATE`."
        PRD §3.2: "while a case is `SUSPENDED` the creation of new referrals,
        program enrollments, workshop enrollments, appointments, and screenings
        against it is blocked with `ERR_INVALID_STATE`".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_suspended_case_appointment
        """
        mgr, case = self._setup_suspended_case_with_confirmed_appointment()
        resp = api_client.create_appointment(
            create_appointment_payload(case["id"], mgr["id"], kind="DOCUMENT_ID",
                                       starts_at="2026-08-10T10:30:00Z",
                                       ends_at="2026-08-10T11:30:00Z"),
            staff_headers(mgr))
        data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert data["error_id"] == "ERR_INVALID_STATE", (
            "the state rung (4) outranks the temporal rung (8) even though the "
            "request also overlaps the advocate's CONFIRMED appointment")

    def test_overlap_surfaces_when_state_passes(self):
        """PRD §3.6: "A genuine overlap is rejected with
        `ERR_ADVOCATE_TIME_CONFLICT`."
        PRD §2.8: "8. **Temporal rules** — appointment and workshop start times
        must not precede the logical clock (`ERR_TIME_IN_PAST`), an advocate's
        half-open intervals must not intersect (`ERR_ADVOCATE_TIME_CONFLICT`),
        and a room's buffered intervals must not intersect
        (`ERR_ROOM_TIME_CONFLICT`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_suspended_case_appointment
        """
        ctx = drive_case_to_active()
        mgr = ctx["manager"]
        case = ctx["case"]
        appt = create_appointment(case, mgr, kind="ORIENTATION",
                                  starts_at="2026-08-10T10:00:00Z",
                                  ends_at="2026-08-10T11:00:00Z")
        confirm_appointment(appt["id"], mgr)
        # Case remains ACTIVE: the state rung passes, so the temporal rung fires.
        resp = api_client.create_appointment(
            create_appointment_payload(case["id"], mgr["id"], kind="DOCUMENT_ID",
                                       starts_at="2026-08-10T10:30:00Z",
                                       ends_at="2026-08-10T11:30:00Z"),
            staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_ADVOCATE_TIME_CONFLICT)


class TestTimeAndStateGates:
    def test_appointment_in_past_rejected_by_logical_clock(self):
        """PRD §3.6: "`ends_at` must fall after `starts_at`
        (`ERR_INVALID_REQUEST`), and `starts_at` must not precede the current
        logical clock (`ERR_TIME_IN_PAST`)."
        PRD §2.4: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; until it is explicitly set, all rules see that
        instant."

        Design: Corner/validations/appointment_in_past_rejected_by_logical_clock
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        resp = api_client.create_appointment(
            create_appointment_payload(case["id"], mgr["id"], kind="DOCUMENT_ID",
                                       starts_at="2026-07-31T10:00:00Z",
                                       ends_at="2026-07-31T11:00:00Z"),
            staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_TIME_IN_PAST)

    def test_appointment_complete_from_requested_rejected(self):
        """PRD §3.6: "Confirmation — a `CaseManager` or `CenterAdmin` action
        moving `REQUESTED` to `CONFIRMED`".
        PRD §3.6: "From `CONFIRMED` the appointment is either completed (stamping
        `completed_at` with the logical clock) or, if its `ends_at` passes with no
        completion recorded, marked `NO_SHOW` by the sweep."
        PRD §2.8: "4. **State** — the target resource sits in a valid from-state
        for the requested transition, terminal states reject all further
        transitions, and a `SUSPENDED` or `CLOSED` case rejects new child-service
        writes; failure yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/appointment_complete_from_requested_rejected
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        appt = create_appointment(case, mgr, starts_at="2026-08-10T09:00:00Z",
                                  ends_at="2026-08-10T09:30:00Z")
        assert appt["status"] == "REQUESTED"
        resp = api_client.complete_appointment(appt["id"], staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_appointment(appt["id"], staff_headers(mgr)))
        assert after["status"] == "REQUESTED"
        assert after["completed_at"] is None
