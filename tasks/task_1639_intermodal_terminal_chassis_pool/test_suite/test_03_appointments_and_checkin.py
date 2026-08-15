"""Appointment booking discipline, check-in windows, and cancellation rules
(PRD §2.8, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_appointment,
    check_in_payload,
    get_appointment,
    get_terminal,
    run_ops,
    set_clock,
    setup_booked_out_appointment,
    setup_congested_terminal,
    setup_pending_out_transaction,
    TEST_USERS,
    validate_error,
    validate_success,
)

TM = TEST_USERS["terminal_manager_headers"]
GC = TEST_USERS["gate_clerk_headers"]
GS = TEST_USERS["gate_supervisor_headers"]
PA = TEST_USERS["pool_administrator_headers"]


class TestCheckInWindowBoundaries:
    def test_checkin_at_window_start_succeeds(self, api):
        """PRD §2.8: "A driver may check in only while the logical clock is
        within the booked window, boundaries included: check-in at exactly
        `window_start_utc` or exactly `window_end_utc` is valid, while anything
        earlier or later is rejected with `ERR_OUTSIDE_APPOINTMENT_WINDOW`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/appointment_window_membership_inclusive
        """
        ctx = setup_booked_out_appointment(
            window_start="2026-08-02T09:00:00Z",
            window_end="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        set_clock("2026-08-02T09:00:00Z")

        resp = api.check_in_appointment(
            tid, ctx["appointment"]["id"], check_in_payload("DRV-A"), GC)
        checked_in = validate_success(resp, 200)
        assert checked_in["status"] == "CHECKED_IN", (
            "Check-in at exactly window_start_utc is valid (inclusive bound)")
        assert checked_in["checked_in_at"] == "2026-08-02T09:00:00Z"
        assert checked_in["assigned_driver_id"] == "DRV-A"

    def test_checkin_at_window_end_succeeds(self, api):
        """PRD §2.8: "A driver may check in only while the logical clock is
        within the booked window, boundaries included: check-in at exactly
        `window_start_utc` or exactly `window_end_utc` is valid, while anything
        earlier or later is rejected with `ERR_OUTSIDE_APPOINTMENT_WINDOW`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/appointment_window_membership_inclusive
        """
        ctx = setup_booked_out_appointment(
            window_start="2026-08-02T09:00:00Z",
            window_end="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        set_clock("2026-08-02T11:00:00Z")

        resp = api.check_in_appointment(
            tid, ctx["appointment"]["id"], check_in_payload("DRV-A"), GC)
        checked_in = validate_success(resp, 200)
        assert checked_in["status"] == "CHECKED_IN", (
            "Check-in at exactly window_end_utc is valid (inclusive bound)")

    @pytest.mark.parametrize("clock", [
        "2026-08-02T08:59:59Z",  # one second before window_start_utc
        "2026-08-02T11:00:01Z",  # one second after window_end_utc
    ])
    def test_checkin_outside_window_rejected(self, api, clock):
        """PRD §2.8: "A driver may check in only while the logical clock is
        within the booked window, boundaries included: check-in at exactly
        `window_start_utc` or exactly `window_end_utc` is valid, while anything
        earlier or later is rejected with `ERR_OUTSIDE_APPOINTMENT_WINDOW`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/appointment_window_membership_inclusive
        """
        ctx = setup_booked_out_appointment(
            window_start="2026-08-02T09:00:00Z",
            window_end="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        set_clock(clock)

        resp = api.check_in_appointment(
            tid, ctx["appointment"]["id"], check_in_payload("DRV-A"), GC)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_APPOINTMENT_WINDOW)
        assert get_appointment(tid, ctx["appointment"]["id"])["status"] == "BOOKED"


class TestCheckInValidationOrdering:
    def test_window_failure_masks_membership_failure(self, api):
        """PRD §2.11: "Every request passes through a fixed validation
        sequence, and the order is observable: an earlier failure masks every
        later one." with "8. Appointment window — check-in occurs inside the
        booked window, else `ERR_OUTSIDE_APPOINTMENT_WINDOW`." preceding
        "10. Membership — the booking carrier holds an `ACTIVE` membership on
        the chassis pool for outbound booking and check-in, else
        `ERR_MEMBERSHIP_NOT_ACTIVE`."

        Both conditions fail here (clock outside the window; membership
        SUSPENDED); the window failure must be reported.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_checkin
        """
        ctx = setup_booked_out_appointment(
            window_start="2026-08-02T09:00:00Z",
            window_end="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        validate_success(api.suspend_membership(
            tid, ctx["pool"]["id"], ctx["membership"]["id"], PA), 200)
        set_clock("2026-08-02T12:00:00Z")  # one hour past window_end_utc

        resp = api.check_in_appointment(
            tid, ctx["appointment"]["id"], check_in_payload("DRV-A"), GC)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_APPOINTMENT_WINDOW)

    def test_suspended_membership_checkin_rejected(self, api):
        """PRD §3.5: "An `OUT` check-in additionally re-verifies that the
        carrier's membership is still `ACTIVE`, again failing with
        `ERR_MEMBERSHIP_NOT_ACTIVE`."

        Only the membership condition fails here (clock inside the window), so
        the referential failure surfaces on its own.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_checkin
        """
        ctx = setup_booked_out_appointment(
            window_start="2026-08-02T09:00:00Z",
            window_end="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        validate_success(api.suspend_membership(
            tid, ctx["pool"]["id"], ctx["membership"]["id"], PA), 200)
        set_clock("2026-08-02T10:00:00Z")  # inside the window

        resp = api.check_in_appointment(
            tid, ctx["appointment"]["id"], check_in_payload("DRV-A"), GC)
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)
        assert get_appointment(tid, ctx["appointment"]["id"])["status"] == "BOOKED"


class TestNoShowAtRunOps:
    def test_booked_appointment_marks_no_show_at_run_ops(self, api):
        """PRD §3.5: "An appointment that is still `BOOKED` when the logical
        clock passes its `window_end_utc` is marked `NO_SHOW` at the next
        operations checkpoint (§3.8)."

        Design: Corner/state_machines/appointment_no_show_transition_at_run_ops
        """
        ctx = setup_booked_out_appointment(
            window_start="2026-08-02T09:00:00Z",
            window_end="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        set_clock("2026-08-02T12:00:00Z")

        run_ops(tid)
        appointment = get_appointment(tid, ctx["appointment"]["id"])
        assert_appointment(appointment)
        assert appointment["status"] == "NO_SHOW"


class TestCongestedWindowCap:
    def test_congested_window_exactly_3600_seconds_allowed(self, api):
        """PRD §2.8: "When the terminal's posture is `CONGESTED` at booking
        time, the window is additionally capped: the difference between
        `window_end_utc` and `window_start_utc` may not exceed 3600 seconds —
        a window of exactly sixty minutes is permitted, but one second longer
        is rejected with `ERR_CONGESTED_WINDOW_CAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/congested_window_cap_boundary
        """
        ctx = setup_congested_terminal()
        tid = ctx["terminal"]["id"]

        resp = api.create_appointment(
            tid,
            {"carrier_id": ctx["carrier"]["id"],
             "container_id": ctx["spare_container"]["id"],
             "direction": "OUT",
             "window_start_utc": "2026-08-02T09:00:00Z",
             "window_end_utc": "2026-08-02T10:00:00Z"},  # exactly 3600 seconds
            GS,
        )
        appointment = validate_success(resp, 201)
        assert appointment["status"] == "BOOKED", (
            "A window of exactly 3600 seconds is permitted under CONGESTED posture")

    def test_congested_window_3601_seconds_rejected(self, api):
        """PRD §2.8: "When the terminal's posture is `CONGESTED` at booking
        time, the window is additionally capped: the difference between
        `window_end_utc` and `window_start_utc` may not exceed 3600 seconds —
        a window of exactly sixty minutes is permitted, but one second longer
        is rejected with `ERR_CONGESTED_WINDOW_CAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/congested_window_cap_boundary
        """
        ctx = setup_congested_terminal()
        tid = ctx["terminal"]["id"]

        resp = api.create_appointment(
            tid,
            {"carrier_id": ctx["carrier"]["id"],
             "container_id": ctx["spare_container"]["id"],
             "direction": "OUT",
             "window_start_utc": "2026-08-02T09:00:00Z",
             "window_end_utc": "2026-08-02T10:00:01Z"},  # 3601 seconds
            GS,
        )
        validate_error(resp, ApiErrorId.ERR_CONGESTED_WINDOW_CAP)


class TestAppointmentCancellation:
    def test_cancel_with_pending_transaction_blocked(self, api):
        """PRD §3.5: "Cancellation from `CHECKED_IN` is blocked when a gate
        transaction exists against the appointment in `PENDING` or `COMPLETED`
        status (`ERR_TRANSACTION_IN_FLIGHT`); cancellation from `BOOKED`
        carries no such check."

        Design: Corner/validations/cancel_appointment_with_pending_transaction_blocked
        """
        ctx = setup_pending_out_transaction()
        tid = ctx["terminal"]["id"]
        assert ctx["appointment"]["status"] == "CHECKED_IN"
        assert ctx["transaction"]["status"] == "PENDING"

        resp = api.cancel_appointment(tid, ctx["appointment"]["id"], GC)
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_IN_FLIGHT)
        assert get_appointment(tid, ctx["appointment"]["id"])["status"] == "CHECKED_IN"
