"""Hours-of-service derivation and the duty-event ledger.

Covers PRD §3.1: chronological replay, session vs calendar-day variants, the
pinned hos_status priority order (cycle 4200 / session 660 / window 840 /
break 480, all inclusive), and the three temporal checks guarding every
appended event.
"""
from test_helpers import (
    TEST_USERS,
    create_duty_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    append_duty_event,
    create_driver,
    create_load,
    create_shipper,
    create_trailer,
    get_driver,
    get_load,
    plan_load,
    allocate_all,
    set_clock,
    setup_verified_load,
)

DISP = TEST_USERS["dispatcher_headers"]

ADMIN = TEST_USERS["admin_headers"]


def _drive(driver_id, start, end):
    """Record a DUTY_ON..DRIVING_ON..DRIVING_OFF..DUTY_OFF shift."""
    append_duty_event(driver_id, "DUTY_ON", start)
    append_duty_event(driver_id, "DRIVING_ON", start)
    append_duty_event(driver_id, "DRIVING_OFF", end)
    append_duty_event(driver_id, "DUTY_OFF", end)


class TestSessionVsCalendarDay:
    def test_session_and_calendar_day_diverge_across_midnight(self, api):
        """PRD §3.1: "Independently of the session model,
        `calendar_day_driving_minutes` sums driving minutes clipped to the
        current UTC calendar day from midnight to now, with intervals clipped at
        midnight — an identical event stream produces different session and
        calendar-day figures whenever a trip crosses midnight."
        PRD §3.1: "`session_driving_minutes` sums the driving intervals
        (`DRIVING_ON` to `DRIVING_OFF`) inside the session window, with a
        still-open driving interval counted up to the current time."

        Design: Difficulty/dual_variant_calc/driver_session_vs_calendar_day_driving_minutes_diverge_across_midnight
        """
        set_clock("2026-08-05T01:00:00Z")
        driver = create_driver()
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-04T22:00:00Z")
        append_duty_event(driver["id"], "DRIVING_ON", "2026-08-04T23:00:00Z")
        append_duty_event(driver["id"], "DRIVING_OFF", "2026-08-05T00:30:00Z")

        d = validate_success(api.get_driver(driver["id"], ADMIN))
        # session variant: the whole 23:00 -> 00:30 drive counts
        assert d["session_driving_minutes"] == 90
        # calendar-day variant: only the 00:00 -> 00:30 portion is today
        assert d["calendar_day_driving_minutes"] == 30
        assert d["session_driving_minutes"] != d["calendar_day_driving_minutes"]
        assert d["hos_status"] == "ELIGIBLE"

    def test_calendar_day_clips_driving_at_midnight_boundary(self, api):
        """PRD §3.1: "Hours-of-service derivation replays the log in
        chronological order — `occurred_at` ascending, ties broken by
        `created_at` ascending, never by `id`."
        PRD §3.1: "Independently of the session model,
        `calendar_day_driving_minutes` sums driving minutes clipped to the
        current UTC calendar day from midnight to now, with intervals clipped at
        midnight — an identical event stream produces different session and
        calendar-day figures whenever a trip crosses midnight."

        Design: Difficulty/dual_variant_calc/driver_session_vs_calendar_day_driving_minutes_diverge_across_midnight
        """
        set_clock("2026-08-05T01:00:00Z")
        driver = create_driver()
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-04T22:00:00Z")
        append_duty_event(driver["id"], "DRIVING_ON", "2026-08-04T23:00:00Z")
        append_duty_event(driver["id"], "DRIVING_OFF", "2026-08-05T00:30:00Z")

        events, meta = validate_paginated(
            api.list_duty_events(driver["id"], ADMIN))
        assert len(events) == 3
        assert [e["event_type"] for e in events] == [
            "DUTY_ON", "DRIVING_ON", "DRIVING_OFF"]

        d = validate_success(api.get_driver(driver["id"], ADMIN))
        assert d["calendar_day_driving_minutes"] == 30
        assert d["session_driving_minutes"] == 90


class TestBreakRequiredBoundary:
    def test_break_required_at_exactly_480_minutes(self, api):
        """PRD §3.1: "otherwise `BREAK_REQUIRED` when
        `driving_since_break_minutes` has reached 480 (eight hours); otherwise
        `ELIGIBLE`. Every threshold is inclusive — being exactly at a limit
        means the driver is exhausted or a break is due."
        PRD §3.1: "A break credit is a `BREAK_START`–`BREAK_END` pair spanning
        at least 30 minutes, or any off-duty gap of at least 30 minutes;
        `driving_since_break_minutes` accumulates driving minutes since the end
        of the most recent break credit, or since the session start when no
        break credit exists."

        Design: Corner/calculations/hos_break_required_at_exactly_480_minutes
        """
        set_clock("2026-08-02T09:00:00Z")
        d1 = create_driver()
        d2 = create_driver()
        # D1: exactly 480 driving minutes (00:30 -> 08:30), no break
        append_duty_event(d1["id"], "DUTY_ON", "2026-08-02T00:00:00Z")
        append_duty_event(d1["id"], "DRIVING_ON", "2026-08-02T00:30:00Z")
        append_duty_event(d1["id"], "DRIVING_OFF", "2026-08-02T08:30:00Z")
        # D2: 479 driving minutes (00:30 -> 08:29), no break
        append_duty_event(d2["id"], "DUTY_ON", "2026-08-02T00:00:00Z")
        append_duty_event(d2["id"], "DRIVING_ON", "2026-08-02T00:30:00Z")
        append_duty_event(d2["id"], "DRIVING_OFF", "2026-08-02T08:29:00Z")

        r1 = validate_success(api.get_driver(d1["id"], ADMIN))
        r2 = validate_success(api.get_driver(d2["id"], ADMIN))
        assert r1["driving_since_break_minutes"] == 480
        assert r1["hos_status"] == "BREAK_REQUIRED"
        assert r2["driving_since_break_minutes"] == 479
        assert r2["hos_status"] == "ELIGIBLE"


class TestCycleExhaustedBoundary:
    def test_cycle_exhausted_at_exactly_4200_minutes(self, api):
        """PRD §3.1: "`CYCLE_EXHAUSTED` when `cycle_on_duty_minutes_8d` has
        reached 4200 (seventy hours); otherwise `SESSION_EXHAUSTED` when
        `session_driving_minutes` has reached 660 (eleven hours); otherwise
        `WINDOW_CLOSED` when the driver is on duty and the current time is past
        `duty_window_expires_at`; otherwise `BREAK_REQUIRED` when
        `driving_since_break_minutes` has reached 480 (eight hours); otherwise
        `ELIGIBLE`. Every threshold is inclusive — being exactly at a limit
        means the driver is exhausted or a break is due."
        PRD §3.1: "`cycle_on_duty_minutes_8d` sums on-duty minutes (`DUTY_ON` to
        `DUTY_OFF`, an open interval counted to now) clipped to the trailing
        window of the last 11520 minutes (eight days)."

        Design: Corner/calculations/hos_cycle_exhausted_at_exactly_4200_minutes
        """
        set_clock("2026-08-08T00:00:00Z")
        d1 = create_driver()
        d2 = create_driver()
        # six 700-minute on-duty days inside the trailing eight-day window
        for day in range(1, 7):
            on = f"2026-08-0{day}T00:00:00Z"
            off = f"2026-08-0{day}T11:40:00Z"
            append_duty_event(d1["id"], "DUTY_ON", on)
            append_duty_event(d1["id"], "DUTY_OFF", off)
            append_duty_event(d2["id"], "DUTY_ON", on)
            # D2's last day is one minute shorter: 4199 total
            append_duty_event(d2["id"], "DUTY_OFF",
                              off if day < 6 else "2026-08-06T11:39:00Z")

        r1 = validate_success(api.get_driver(d1["id"], ADMIN))
        r2 = validate_success(api.get_driver(d2["id"], ADMIN))
        assert r1["cycle_on_duty_minutes_8d"] == 4200
        assert r1["hos_status"] == "CYCLE_EXHAUSTED"
        assert r2["cycle_on_duty_minutes_8d"] == 4199
        assert r2["hos_status"] == "ELIGIBLE"


class TestDutyWindowBoundary:
    def test_window_closed_strictly_after_840_minutes(self, api):
        """PRD §3.1: "The duty-window anchor is the latest `DUTY_ON` preceded
        by at least 600 minutes off duty — or the first `DUTY_ON` when no such
        rest exists — and `duty_window_expires_at` is that anchor plus 840
        minutes (fourteen hours); the anchor is cleared once an off-duty
        stretch of at least 600 minutes has elapsed, so
        `duty_window_expires_at` is null when no shift is anchored."
        PRD §3.1: "otherwise `WINDOW_CLOSED` when the driver is on duty and the
        current time is past `duty_window_expires_at`"

        Design: Corner/calculations/hos_window_closed_strictly_after_840_minutes
        """
        from test_helpers import assert_ts_eq
        set_clock("2026-08-02T21:00:00Z")
        d1 = create_driver()  # on duty since 06:00 -> window expired 20:00
        d2 = create_driver()  # on duty since 07:00 -> window expires 21:00
        append_duty_event(d1["id"], "DUTY_ON", "2026-08-02T06:00:00Z")
        append_duty_event(d2["id"], "DUTY_ON", "2026-08-02T07:00:00Z")

        r1 = validate_success(api.get_driver(d1["id"], ADMIN))
        r2 = validate_success(api.get_driver(d2["id"], ADMIN))
        assert_ts_eq(r1["duty_window_expires_at"], "2026-08-02T20:00:00Z",
                     "d1.duty_window_expires_at")
        assert r1["hos_status"] == "WINDOW_CLOSED"
        assert_ts_eq(r2["duty_window_expires_at"], "2026-08-02T21:00:00Z",
                     "d2.duty_window_expires_at")
        # now == expiry is not "past" the window
        assert r2["hos_status"] == "ELIGIBLE"


class TestDutyEventGuards:
    def test_duty_event_in_future_rejected(self, api, admin_headers):
        """PRD §3.1: "First, `occurred_at` must not be later than the current
        logical time, or the append fails with `ERR_EVENT_IN_FUTURE`
        (HTTP 422)."
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; until it is explicitly set, the clock continues
        to report this default and never falls back to wall-clock time."

        Design: Corner/validations/duty_event_in_future_rejected
        """
        driver = create_driver()
        resp = api.create_duty_event(
            driver["id"],
            create_duty_event_payload(event_type="DUTY_ON",
                                      occurred_at="2026-08-01T01:00:00Z"),
            admin_headers)
        validate_error(resp, E.ERR_EVENT_IN_FUTURE)

    def test_duty_event_invalid_sequence_rejected(self, api, admin_headers):
        """PRD §3.1: "Third, the event type must be legal for the driver's
        current duty sub-state: `DUTY_ON` is legal only while off duty;
        `DRIVING_ON` only while on duty and not driving; `DRIVING_OFF` only
        while driving; `BREAK_START` only while on duty, not driving, and not
        on break; `BREAK_END` only while on break; and `DUTY_OFF` only while on
        duty — a `DUTY_OFF` auto-closes any open driving or break interval at
        its own timestamp. An illegal transition is rejected with
        `ERR_DUTY_EVENT_SEQUENCE` (HTTP 409)."

        Design: Corner/validations/duty_event_invalid_sequence_rejected
        """
        set_clock("2026-08-02T12:00:00Z")
        driver = create_driver()
        # DUTY_OFF as the first event: the driver is not on duty
        resp = api.create_duty_event(
            driver["id"],
            create_duty_event_payload(event_type="DUTY_OFF",
                                      occurred_at="2026-08-02T10:00:00Z"),
            admin_headers)
        validate_error(resp, E.ERR_DUTY_EVENT_SEQUENCE)


class TestAssignHosGate:
    """Assign-driver is gated by the driver's derived hos_status (PRD §3.5)."""

    def test_assign_rejected_when_driver_session_exhausted(self, api):
        """PRD §3.5: "the driver's `hos_status` is `ELIGIBLE`
        (`ERR_DRIVER_NOT_HOS_ELIGIBLE`, HTTP 422)"
        PRD §3.1: "otherwise `SESSION_EXHAUSTED` when `session_driving_minutes`
        has reached 660 (eleven hours); otherwise `WINDOW_CLOSED` when the
        driver is on duty and the current time is past
        `duty_window_expires_at`; otherwise `BREAK_REQUIRED` when
        `driving_since_break_minutes` has reached 480 (eight hours); otherwise
        `ELIGIBLE`. Every threshold is inclusive — being exactly at a limit
        means the driver is exhausted or a break is due."

        Design: Difficulty/cross_entity_state_dependency/assign_blocked_by_driver_hos_ineligibility
        """
        # verified load first (the fixture leaves the clock at 07:00), then
        # the driver's events, so the logical clock only moves forward
        ctx = setup_verified_load()
        driver = create_driver()
        set_clock("2026-08-01T12:00:00Z")
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-01T00:00:00Z")
        append_duty_event(driver["id"], "DRIVING_ON", "2026-08-01T01:00:00Z")
        append_duty_event(driver["id"], "DRIVING_OFF", "2026-08-01T12:00:00Z")

        d = get_driver(driver["id"])
        assert d["session_driving_minutes"] == 660
        assert d["hos_status"] == "SESSION_EXHAUSTED"

        resp = api.assign_driver(
            ctx["load"]["id"],
            {"driver_id": driver["id"],
             "expected_driver_version": d["version"]},
            DISP)
        validate_error(resp, E.ERR_DRIVER_NOT_HOS_ELIGIBLE)

        load = get_load(ctx["load"]["id"])
        assert load["status"] == "PAPERWORK_VERIFIED"
        assert load["driver_id"] is None

    def test_assign_allowed_at_659_session_minutes_with_break(self, api):
        """PRD §3.1: "otherwise `SESSION_EXHAUSTED` when
        `session_driving_minutes` has reached 660 (eleven hours); otherwise
        `WINDOW_CLOSED` when the driver is on duty and the current time is past
        `duty_window_expires_at`; otherwise `BREAK_REQUIRED` when
        `driving_since_break_minutes` has reached 480 (eight hours); otherwise
        `ELIGIBLE`. Every threshold is inclusive — being exactly at a limit
        means the driver is exhausted or a break is due."
        PRD §3.1: "A break credit is a `BREAK_START`–`BREAK_END` pair spanning
        at least 30 minutes, or any off-duty gap of at least 30 minutes;
        `driving_since_break_minutes` accumulates driving minutes since the end
        of the most recent break credit, or since the session start when no
        break credit exists."

        Design: Difficulty/cross_entity_state_dependency/assign_blocked_by_driver_hos_ineligibility
        """
        ctx = setup_verified_load()
        driver = create_driver()
        set_clock("2026-08-01T12:30:00Z")
        # 659 session driving minutes — one below the inclusive 660 limit —
        # followed by a qualifying 30-minute break
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-01T00:00:00Z")
        append_duty_event(driver["id"], "DRIVING_ON", "2026-08-01T01:00:00Z")
        append_duty_event(driver["id"], "DRIVING_OFF", "2026-08-01T11:59:00Z")
        append_duty_event(driver["id"], "BREAK_START", "2026-08-01T11:59:00Z")
        append_duty_event(driver["id"], "BREAK_END", "2026-08-01T12:29:00Z")

        d = get_driver(driver["id"])
        assert d["session_driving_minutes"] == 659
        assert d["hos_status"] == "ELIGIBLE"

        assigned = validate_success(
            api.assign_driver(
                ctx["load"]["id"],
                {"driver_id": driver["id"],
                 "expected_driver_version": d["version"]},
                DISP), 200)
        assert assigned["status"] == "ASSIGNED"
        assert assigned["driver_id"] == driver["id"]


class TestStateOverHosPriority:
    """The fixed validation pipeline runs state preconditions (layer 7) before
    any endpoint-specific business rules (PRD §2.7)."""

    def test_assign_rejection_prioritizes_state_over_hos_safety(self, api):
        """PRD §2.7: "Every request passes through validation layers in a fixed
        precedence order, and a failure in an earlier layer masks every later
        layer."
        PRD §2.7: "Only after all eight layers pass do the endpoint-specific
        business rules run, in the per-endpoint priority order narrated with
        each workflow in §3."
        PRD §3.5: "the load is `PAPERWORK_VERIFIED`
        (`ERR_LOAD_NOT_PAPERWORK_VERIFIED`, HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/assign_rejection_prioritizes_state_over_hos_safety
        """
        # driver is SESSION_EXHAUSTED (660 session minutes, inclusive limit)
        driver = create_driver()
        set_clock("2026-08-01T12:00:00Z")
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-01T00:00:00Z")
        append_duty_event(driver["id"], "DRIVING_ON", "2026-08-01T01:00:00Z")
        append_duty_event(driver["id"], "DRIVING_OFF", "2026-08-01T12:00:00Z")

        # load is only PLANNED (allocations finalized, paperwork never
        # verified): both the state rule and the HOS safety rule are violated
        shipper = create_shipper()
        tt = create_trailer()
        load = create_load(shipper["id"])
        allocate_all(load, [tt["compartments"][0]["id"]])
        plan_load(load["id"])

        d = get_driver(driver["id"])
        assert d["hos_status"] == "SESSION_EXHAUSTED"
        resp = api.assign_driver(
            load["id"],
            {"driver_id": driver["id"],
             "expected_driver_version": d["version"]},
            DISP)
        validate_error(resp, E.ERR_LOAD_NOT_PAPERWORK_VERIFIED)

        assert get_load(load["id"])["status"] == "PLANNED"

    def test_draft_load_assign_reports_state_error_despite_cycle_exhaustion(
            self, api):
        """PRD §2.7: "Every request passes through validation layers in a fixed
        precedence order, and a failure in an earlier layer masks every later
        layer."
        PRD §3.5: "the load is `PAPERWORK_VERIFIED`
        (`ERR_LOAD_NOT_PAPERWORK_VERIFIED`, HTTP 409)"
        PRD §3.1: "`CYCLE_EXHAUSTED` when `cycle_on_duty_minutes_8d` has
        reached 4200 (seventy hours); otherwise `SESSION_EXHAUSTED` when
        `session_driving_minutes` has reached 660 (eleven hours); otherwise
        `WINDOW_CLOSED` when the driver is on duty and the current time is past
        `duty_window_expires_at`; otherwise `BREAK_REQUIRED` when
        `driving_since_break_minutes` has reached 480 (eight hours); otherwise
        `ELIGIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/assign_rejection_prioritizes_state_over_hos_safety
        """
        # driver is CYCLE_EXHAUSTED (six 700-minute on-duty days = 4200)
        set_clock("2026-08-08T00:00:00Z")
        driver = create_driver()
        for day in range(1, 7):
            append_duty_event(driver["id"], "DUTY_ON",
                              f"2026-08-0{day}T00:00:00Z")
            append_duty_event(driver["id"], "DUTY_OFF",
                              f"2026-08-0{day}T11:40:00Z")

        # load is DRAFT: the state precondition fails while the safety rule
        # would also fail
        shipper = create_shipper()
        load = create_load(shipper["id"])

        d = get_driver(driver["id"])
        assert d["cycle_on_duty_minutes_8d"] == 4200
        assert d["hos_status"] == "CYCLE_EXHAUSTED"
        resp = api.assign_driver(
            load["id"],
            {"driver_id": driver["id"],
             "expected_driver_version": d["version"]},
            DISP)
        validate_error(resp, E.ERR_LOAD_NOT_PAPERWORK_VERIFIED)
        assert get_load(load["id"])["status"] == "DRAFT"


class TestDutyIntervalsHalfOpen:
    def test_duty_intervals_half_open_adjacency(self, api):
        """PRD §3.1: "Second, `occurred_at` must not be earlier than the
        previous event's `occurred_at` — equality is allowed, because duty and
        driving intervals are half-open and a `DUTY_ON` stamped at exactly the
        previous `DUTY_OFF`'s timestamp is legal back-to-back adjacency; a
        strictly earlier timestamp would invert an interval and is rejected
        with `ERR_DUTY_INTERVAL_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/driver_duty_intervals_half_open_adjacency
        """
        set_clock("2026-08-02T12:00:00Z")
        driver = create_driver()
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-02T06:00:00Z")
        append_duty_event(driver["id"], "DUTY_OFF", "2026-08-02T10:00:00Z")
        # exactly the previous DUTY_OFF's timestamp: legal adjacency
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-02T10:00:00Z")
        append_duty_event(driver["id"], "DUTY_OFF", "2026-08-02T11:00:00Z")

        events, meta = validate_paginated(
            api.list_duty_events(driver["id"], ADMIN))
        assert len(events) == 4

        # back-dated inside [10:00, 11:00): strictly earlier than the previous
        # event's occurred_at inverts an interval
        resp = api.create_duty_event(
            driver["id"],
            create_duty_event_payload(event_type="DUTY_ON",
                                      occurred_at="2026-08-02T10:30:00Z"),
            ADMIN)
        validate_error(resp, E.ERR_DUTY_INTERVAL_OVERLAP)

    def test_duty_events_listed_chronologically(self, api):
        """PRD §3.1: "The event list of a driver is returned in chronological
        order: `occurred_at` ascending, ties broken by `created_at` ascending."

        Design: Difficulty/resource_temporal_overlap/driver_duty_intervals_half_open_adjacency
        """
        set_clock("2026-08-02T12:00:00Z")
        driver = create_driver()
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-02T06:00:00Z")
        append_duty_event(driver["id"], "DRIVING_ON", "2026-08-02T06:30:00Z")
        append_duty_event(driver["id"], "DRIVING_OFF", "2026-08-02T07:30:00Z")
        append_duty_event(driver["id"], "DUTY_OFF", "2026-08-02T08:00:00Z")

        events, _ = validate_paginated(
            api.list_duty_events(driver["id"], ADMIN))
        occurred = [e["occurred_at"] for e in events]
        assert occurred == sorted(occurred)
        assert [e["event_type"] for e in events] == [
            "DUTY_ON", "DRIVING_ON", "DRIVING_OFF", "DUTY_OFF"]
