"""Orientation scheduling: window boundaries, overlap semantics, reschedule
OCC and cap, cancellation branches, and listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


class TestOrientationWindowBoundary:
    def test_exactly_min_days_before_closing_allowed(self, api):
        """PRD §3.2: "the gap must be at least the community's
        `orientation_min_days_before_closing` days and at most its
        `orientation_max_days_before_closing` days, with both bounds inclusive —
        an orientation scheduled exactly the minimum number of days before
        closing is acceptable, while one minute less is rejected with
        `ERR_OUTSIDE_SCHEDULING_WINDOW`."

        Design: Difficulty/boundary_precision_check/orientation_window_min_days_inclusive_boundary
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"],
                             closing_date="2026-09-01T17:00:00Z")
        resp = api.create_appointment(
            {"home_id": home["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-27T17:00:00Z"},
            make_rep_headers(rep["id"]),
        )
        appt = validate_success(resp, expected_status=201)
        assert appt["status"] == "REQUESTED", (
            f"exactly 7200 minutes before closing must be accepted, got {appt['status']}"
        )

    def test_one_minute_inside_min_days_rejected(self, api):
        """PRD §3.2: "the gap must be at least the community's
        `orientation_min_days_before_closing` days and at most its
        `orientation_max_days_before_closing` days, with both bounds inclusive —
        an orientation scheduled exactly the minimum number of days before
        closing is acceptable, while one minute less is rejected with
        `ERR_OUTSIDE_SCHEDULING_WINDOW`."

        Design: Difficulty/boundary_precision_check/orientation_window_min_days_inclusive_boundary
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"],
                             closing_date="2026-09-01T17:00:00Z")
        resp = api.create_appointment(
            {"home_id": home["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-27T17:01:00Z"},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SCHEDULING_WINDOW)

    def test_schedule_in_past_rejected(self, api):
        """PRD §3.2: "Independently, `scheduled_start` must lie strictly after the
        current logical-clock instant; a start in the past or at the present
        instant is rejected with `ERR_SCHEDULE_IN_PAST`."

        Design: Corner/errors/schedule_in_past_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"],
                             closing_date="2026-09-20T17:00:00Z")
        fx.set_clock("2026-08-20T00:00:00Z")
        resp = api.create_appointment(
            {"home_id": home["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-19T14:00:00Z"},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST)


class TestOrientationOverlap:
    def test_touching_buffered_interval_conflicts(self, api):
        """PRD §3.2: "The new appointment conflicts — and is rejected with
        `ERR_REP_SCHEDULE_CONFLICT` — whenever its own buffer-extended interval
        touches or overlaps an existing one; because the intervals are closed,
        two appointments whose extended edges merely touch still count as a
        conflict."

        Design: Difficulty/resource_temporal_overlap/orientation_buffer_closed_interval_touching_conflict
        """
        community, buyer, rep = fx.setup_base()
        h1 = fx.setup_home(community["id"], buyer["id"], lot_number="L-101",
                           address="1 Riverbend Way")
        h2 = fx.setup_home(community["id"], buyer["id"], lot_number="L-102",
                           address="2 Riverbend Way")
        fx.create_appointment(h1["id"], rep["id"], "2026-08-25T14:00:00Z")
        # Existing occupies the closed buffered interval [13:30, 16:30]; a new
        # appointment at 17:00 extends to [16:30, 19:30] and touches at 16:30.
        resp = api.create_appointment(
            {"home_id": h2["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-25T17:00:00Z"},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REP_SCHEDULE_CONFLICT)

    def test_one_minute_past_buffered_edge_allowed(self, api):
        """PRD §3.2: "Each of the rep's existing orientation appointments in
        `REQUESTED`, `CONFIRMED`, or `IN_PROGRESS` occupies a closed interval
        that begins `appointment_buffer_minutes` before its start and ends
        `appointment_buffer_minutes` after its finish."

        Design: Difficulty/resource_temporal_overlap/orientation_buffer_closed_interval_touching_conflict
        """
        community, buyer, rep = fx.setup_base()
        h1 = fx.setup_home(community["id"], buyer["id"], lot_number="L-101",
                           address="1 Riverbend Way")
        h3 = fx.setup_home(community["id"], buyer["id"], lot_number="L-103",
                           address="3 Riverbend Way")
        fx.create_appointment(h1["id"], rep["id"], "2026-08-25T14:00:00Z")
        resp = api.create_appointment(
            {"home_id": h3["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-25T17:01:00Z"},
            make_rep_headers(rep["id"]),
        )
        appt = validate_success(resp, expected_status=201)
        assert appt["status"] == "REQUESTED", (
            f"buffered start 16:31 clears the closed interval, got {appt['status']}"
        )

    def test_window_error_beats_rep_conflict(self, api):
        """PRD §2.8: "When a request would violate several rules at once, the
        server evaluates its gates in a fixed order and reports only the earliest
        failure."
        PRD §2.8: "9. Temporal gates — the orientation scheduling window,
        schedule-in-past, the appointment start window, the survey window, and
        visit completion timing; otherwise `ERR_OUTSIDE_SCHEDULING_WINDOW` or
        `ERR_SCHEDULE_IN_PAST` (HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/scheduling_window_priority_over_rep_conflict
        """
        community, buyer, rep = fx.setup_base()
        h1 = fx.setup_home(community["id"], buyer["id"], lot_number="L-101",
                           address="1 Riverbend Way")
        h2 = fx.setup_home(community["id"], buyer["id"], lot_number="L-102",
                           address="2 Riverbend Way",
                           closing_date="2026-08-26T17:00:00Z")
        # r1 occupies buffered closed interval [13:30, 16:30] on 2026-08-25.
        fx.create_appointment(h1["id"], rep["id"], "2026-08-25T14:00:00Z")
        # 15:00 is BOTH ~26h before h2's closing (window violation) AND inside
        # the buffered interval (overlap): the temporal error must win.
        resp = api.create_appointment(
            {"home_id": h2["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-25T15:00:00Z"},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SCHEDULING_WINDOW)

    def test_window_violation_alone_reports_window_error(self, api):
        """PRD §3.2: "The **window check** measures the gap between the
        appointment's `scheduled_start` and the home's `closing_date` in whole
        minutes, counting 1,440 minutes per day: the gap must be at least the
        community's `orientation_min_days_before_closing` days and at most its
        `orientation_max_days_before_closing` days, with both bounds inclusive
        — an orientation scheduled exactly the minimum number of days before
        closing is acceptable, while one minute less is rejected with
        `ERR_OUTSIDE_SCHEDULING_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/scheduling_window_priority_over_rep_conflict
        """
        community, buyer, rep = fx.setup_base()
        rep2 = fx.setup_rep()
        h1 = fx.setup_home(community["id"], buyer["id"], lot_number="L-101",
                           address="1 Riverbend Way")
        h2 = fx.setup_home(community["id"], buyer["id"], lot_number="L-102",
                           address="2 Riverbend Way",
                           closing_date="2026-08-26T17:00:00Z")
        fx.create_appointment(h1["id"], rep["id"], "2026-08-25T14:00:00Z")
        # Same violating slot, but on a rep with an empty calendar: only the
        # window gate can fire, so the temporal error must still be reported.
        resp = api.create_appointment(
            {"home_id": h2["id"], "rep_id": rep2["id"],
             "scheduled_start": "2026-08-25T15:00:00Z"},
            make_rep_headers(rep2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SCHEDULING_WINDOW)


class TestOpenAppointmentUniqueness:
    def test_second_open_appointment_rejected(self, api):
        """PRD §3.2: "the home must not already have an appointment in
        `REQUESTED`, `CONFIRMED`, or `IN_PROGRESS` — a second open appointment
        is rejected with `ERR_OPEN_APPOINTMENT_EXISTS`."

        Design: Corner/errors/open_appointment_uniqueness_rejected
        """
        community, buyer, rep = fx.setup_base()
        rep2 = fx.setup_rep()
        home = fx.setup_home(community["id"], buyer["id"])
        fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        # A different, conflict-free rep does not lift the per-home uniqueness.
        resp = api.create_appointment(
            {"home_id": home["id"], "rep_id": rep2["id"],
             "scheduled_start": "2026-08-26T14:00:00Z"},
            make_rep_headers(rep2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_APPOINTMENT_EXISTS)


class TestInactiveRep:
    def test_inactive_rep_cannot_be_named(self, api):
        """PRD §3.1: "An inactive representative cannot take on new work: naming
        one at appointment or visit creation is rejected with `ERR_REP_INACTIVE`."

        Design: Corner/errors/inactive_rep_rejected
        """
        community, buyer, _rep = fx.setup_base()
        inactive = fx.setup_rep(active=False)
        home = fx.setup_home(community["id"], buyer["id"])
        resp = api.create_appointment(
            {"home_id": home["id"], "rep_id": inactive["id"],
             "scheduled_start": "2026-08-25T14:00:00Z"},
            make_rep_headers(inactive["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REP_INACTIVE)


class TestRescheduleOccAndCap:
    def test_stale_appointment_version_rejected(self, api):
        """PRD §2.7: "Rescheduling an orientation appointment —
        `POST /api/appointments/{id}/reschedule` — requires
        `expected_appointment_version`, carrying the client's last observed
        `version` of the appointment. If the appointment's current version
        differs, the request is rejected with `ERR_STALE_VERSION` (HTTP 412):
        another write has advanced the appointment since the client last read it."

        Design: Corner/errors/appointment_reschedule_stale_version_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        stale_version = appt["version"]  # observed at create time
        confirmed = fx.confirm_appointment(appt["id"])
        ok = api.reschedule_appointment(
            appt["id"],
            {"scheduled_start": "2026-08-26T14:00:00Z",
             "expected_appointment_version": confirmed["version"]},
            make_rep_headers(rep["id"]),
        )
        moved = validate_success(ok)
        assert moved["reschedule_count"] == 1, (
            f"reschedule_count must advance to 1, got {moved['reschedule_count']}"
        )
        stale = api.reschedule_appointment(
            appt["id"],
            {"scheduled_start": "2026-08-27T14:00:00Z",
             "expected_appointment_version": stale_version},
            make_rep_headers(rep["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    def test_reschedule_limit_reached(self, api):
        """PRD §3.2: "a stale version is rejected with `ERR_STALE_VERSION`, a
        `reschedule_count` that has already reached 3 is rejected with
        `ERR_RESCHEDULE_LIMIT_REACHED`, and the new start is re-validated
        against the window and overlap rules exactly as at creation."

        Design: Corner/errors/reschedule_limit_reached_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"],
                             closing_date="2026-09-20T17:00:00Z")
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        confirmed = fx.confirm_appointment(appt["id"])
        version = confirmed["version"]
        for day in ("2026-08-26T14:00:00Z", "2026-08-27T14:00:00Z", "2026-08-28T14:00:00Z"):
            resp = api.reschedule_appointment(
                appt["id"],
                {"scheduled_start": day, "expected_appointment_version": version},
                make_rep_headers(rep["id"]),
            )
            moved = validate_success(resp)
            version = moved["version"]
        assert moved["reschedule_count"] == 3, (
            f"three reschedules must land at count 3, got {moved['reschedule_count']}"
        )
        resp = api.reschedule_appointment(
            appt["id"],
            {"scheduled_start": "2026-08-31T14:00:00Z",
             "expected_appointment_version": version},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_LIMIT_REACHED)


class TestVersionIncrements:
    def test_appointment_version_advances_per_mutation(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation, including mutations caused by
        server-side cascades rather than a direct client call on that resource."
        PRD §3.2: "A successful reschedule updates the schedule, increments
        `reschedule_count` by one, and bumps the appointment's `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_mutation
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        assert appt["version"] == 1, f"create must mint version 1, got {appt['version']}"
        confirmed = fx.confirm_appointment(appt["id"])
        assert confirmed["version"] == 2, (
            f"confirm must advance version to 2, got {confirmed['version']}"
        )
        resp = api.reschedule_appointment(
            appt["id"],
            {"scheduled_start": "2026-08-26T14:00:00Z",
             "expected_appointment_version": confirmed["version"]},
            make_rep_headers(rep["id"]),
        )
        moved = validate_success(resp)
        assert moved["version"] == 3, (
            f"reschedule must advance version to 3, got {moved['version']}"
        )
        assert moved["reschedule_count"] == 1
        assert moved["scheduled_start"].startswith("2026-08-26T14:00"), (
            f"scheduled_start must move to 2026-08-26T14:00, got {moved['scheduled_start']}"
        )


class TestCancellationBranches:
    def test_cancel_confirmed_as_no_show(self, api):
        """PRD §3.2: "From `CONFIRMED`, a cancel carrying reason `BUYER_NO_SHOW`
        lands in `NO_SHOW`, while any other reason or an omitted reason lands in
        `CANCELLED`; in both confirmed cases the home reverts from
        `ORIENTATION_SCHEDULED` to `PRE_CLOSE_READY`."

        Design: Corner/state_machines/cancel_confirmed_as_no_show_branch
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        resp = api.cancel_appointment(
            appt["id"], {"reason": "BUYER_NO_SHOW"}, make_rep_headers(rep["id"])
        )
        cancelled = validate_success(resp)
        assert cancelled["status"] == "NO_SHOW", (
            f"BUYER_NO_SHOW from CONFIRMED must land in NO_SHOW, got {cancelled['status']}"
        )
        assert cancelled["cancel_reason"] == "BUYER_NO_SHOW"
        home = get_success_data(api.get_home(home["id"], fx.MANAGER))
        assert home["status"] == "PRE_CLOSE_READY", (
            f"confirmed no-show must revert the home, got {home['status']}"
        )

    def test_cancel_confirmed_with_other_reason_reverts_home(self, api, manager_headers):
        """PRD §3.2: "From `CONFIRMED`, a cancel carrying reason `BUYER_NO_SHOW`
        lands in `NO_SHOW`, while any other reason or an omitted reason lands in
        `CANCELLED`; in both confirmed cases the home reverts from
        `ORIENTATION_SCHEDULED` to `PRE_CLOSE_READY`."

        Design: Corner/state_machines/cancel_confirmed_reverts_home_state
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        resp = api.cancel_appointment(appt["id"], {"reason": "BUYER_REQUEST"},
                                      manager_headers)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED", (
            f"non-no-show reason must land in CANCELLED, got {cancelled['status']}"
        )
        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert home["status"] == "PRE_CLOSE_READY", (
            f"confirmed cancel must revert the home, got {home['status']}"
        )

    def test_start_after_cancel_rejected(self, api):
        """PRD §3.2: "`COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal."
        PRD §2.8: "State — the target entity is in a valid from-state for the
        requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/appointment_start_after_cancel_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        api.cancel_appointment(appt["id"], {}, make_rep_headers(rep["id"]))
        fx.set_clock("2026-08-25T14:00:00Z")
        resp = api.start_appointment(appt["id"], make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_start_before_window_rejected(self, api):
        """PRD §3.3: "Starting the appointment is the conducting representative's
        act, allowed only while the logical clock sits within a closed window
        that opens 30 minutes before `scheduled_start` and closes
        `duration_minutes` after it; an attempt outside that window is rejected
        with `ERR_APPOINTMENT_START_WINDOW`."

        Design: Corner/errors/appointment_start_before_window_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T12:00:00Z")  # more than 30 minutes early
        resp = api.start_appointment(appt["id"], make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_START_WINDOW)


class TestAppointmentListing:
    def test_list_appointments_filtered_by_home(self, api, manager_headers):
        """PRD §3.2: "Appointments may be listed filtered by `home_id`, `rep_id`,
        or `status`."

        Design: Corner/entities/fk_reverse_list_appointments_by_home
        """
        community, buyer, rep = fx.setup_base()
        h1 = fx.setup_home(community["id"], buyer["id"], lot_number="L-101",
                           address="1 Riverbend Way")
        h2 = fx.setup_home(community["id"], buyer["id"], lot_number="L-102",
                           address="2 Riverbend Way")
        appt = fx.create_appointment(h1["id"], rep["id"], "2026-08-25T14:00:00Z")

        data1, meta1 = validate_paginated(
            api.list_appointments(manager_headers, params={"home_id": h1["id"]})
        )
        assert len(data1) == 1, f"h1 must have exactly one appointment, got {len(data1)}"
        assert data1[0]["id"] == appt["id"]
        data2, meta2 = validate_paginated(
            api.list_appointments(manager_headers, params={"home_id": h2["id"]})
        )
        assert len(data2) == 0, f"h2 must have no appointments, got {len(data2)}"
        assert meta2["total_count"] == 0


class TestClockStartupDefault:
    def test_startup_default_clock_is_2026_08_01(self, api):
        """PRD §2.4: "A server-side logical clock is the single source of "now"
        for every temporal rule in this document — orientation scheduling
        windows, the appointment start window, the survey submission window, and
        re-inspection visit timing all read it, and the server must never fall
        back to wall-clock time. Before any client sets it, the clock starts at
        exactly 2026-08-01T00:00:00Z."

        Design: Corner/cross_cutting_complexity_layers/clock_default_at_startup
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        # No set_current_utc call in this test: 2026-08-06T10:00 is strictly
        # after the startup default and 26 days before the closing — inside
        # the default [5, 30] day window.
        resp = api.create_appointment(
            {"home_id": home["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-06T10:00:00Z"},
            make_rep_headers(rep["id"]),
        )
        appt = validate_success(resp, expected_status=201)
        assert appt["status"] == "REQUESTED"
