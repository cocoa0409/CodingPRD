"""Two temporal-overlap rules that read the same-looking inputs differently.

Bench occupancy compares half-open instant intervals on a (laboratory, bench)
pair and widens every stored booking by a mandatory 60-minute changeover buffer,
so touching windows collide and a 60-minute gap clears. Plugfest registration
compares closed UTC calendar-date ranges on one submission, so clock times are
discarded entirely and events hours apart on one date still collide.
"""

from test_helpers import (
    BENCH_CHANGEOVER_MINUTES,
    PARTICIPATION_REGISTERED,
    SESSION_SCHEDULED,
    build_program,
    calendar_date,
    new_participation,
    new_plugfest,
    new_session,
    new_submission,
    plus_minutes,
    read_laboratory,
    read_plugfest,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_BENCH_WINDOW_CONFLICT,
    ERR_DUPLICATE_PARTICIPATION,
    ERR_PARTICIPATION_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_reserved_bench_minutes, assert_states
from test_helpers.factories import participation_payload, test_session_payload
from test_helpers.test_users import ADMIN_HEADERS, make_member_headers

# ---------------------------------------------------------------------------
# The bench-window geometry, all of it on bench 1 of one laboratory
# ---------------------------------------------------------------------------

#: The anchor booking every bench scenario starts from: two hours, 120 minutes.
ANCHOR_START = "2026-09-02T09:00:00Z"
ANCHOR_END = "2026-09-02T11:00:00Z"
ANCHOR_MINUTES = 120

#: Behind the anchor: touching it, one minute short of the buffer, and clear.
TOUCH_RIGHT_START = ANCHOR_END
TOUCH_RIGHT_END = "2026-09-02T13:00:00Z"
NEAR_RIGHT_START = plus_minutes(ANCHOR_END, BENCH_CHANGEOVER_MINUTES - 1)
NEAR_RIGHT_END = "2026-09-02T13:00:00Z"
CLEAR_RIGHT_START = plus_minutes(ANCHOR_END, BENCH_CHANGEOVER_MINUTES)
CLEAR_RIGHT_END = plus_minutes(CLEAR_RIGHT_START, 120)

#: In front of the anchor: touching its start, and clear of it by the buffer.
TOUCH_LEFT_END = ANCHOR_START
TOUCH_LEFT_START = plus_minutes(ANCHOR_START, -60)
CLEAR_LEFT_END = plus_minutes(ANCHOR_START, -BENCH_CHANGEOVER_MINUTES)
CLEAR_LEFT_START = plus_minutes(CLEAR_LEFT_END, -60)


def _bench_program():
    """An ISSUED plan at a three-bench laboratory holding one anchor booking.

    Three benches put the capacity ceiling at 1800 minutes, far above anything
    these scenarios reserve, so only the occupancy rule can ever refuse a window.
    """
    ctx = build_program(stage="issued", lab_overrides={"bench_capacity": 3})
    ctx.anchor = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start=ANCHOR_START,
        window_end=ANCHOR_END,
        session_type="INTEROP",
    )
    return ctx


def _book(ctx, window_start, window_end, bench_index=1, session_type="SECURITY"):
    """Attempt one bench booking and hand back the raw response."""
    return api_client.create_test_session(
        test_session_payload(
            ctx.plan_id,
            ctx.laboratory_id,
            window_start=window_start,
            window_end=window_end,
            bench_index=bench_index,
            session_type=session_type,
        ),
        ADMIN_HEADERS,
    )


class TestBenchChangeoverBuffer:
    """Half-open bench windows widened by the mandatory changeover buffer."""

    def test_01_a_window_touching_the_anchor_end_is_refused(self):
        """Booking the window that starts exactly when the anchor ends is refused:
        half-open bounds alone would let the two touch, but the changeover buffer
        demands a full hour of clearance.

        PRD (§3.6): "The buffer changes the arithmetic in a way worth stating
        plainly: two sessions that merely touch, where one's `window_end` equals the
        next one's `window_start`, still conflict, because the buffer forces a full
        hour of clearance between them; a gap of exactly 60 minutes is accepted."

        Design: Difficulty/resource_temporal_overlap/bench_windows_need_a_full_sixty_minute_changeover_gap_per_bench
        """
        ctx = _bench_program()

        response = _book(ctx, TOUCH_RIGHT_START, TOUCH_RIGHT_END)

        validate_error(response, ERR_BENCH_WINDOW_CONFLICT)
        laboratory = read_laboratory(ctx.laboratory_id)
        assert_reserved_bench_minutes(laboratory, ANCHOR_MINUTES)
        sessions, meta = validate_paginated(
            api_client.list_test_sessions(ADMIN_HEADERS, laboratory_id=ctx.laboratory_id)
        )
        assert meta["total_count"] == 1, (
            "the refused booking must not be stored, so only the anchor session "
            "remains, expected total_count 1, got {}".format(meta["total_count"])
        )
        assert len(sessions) == 1, (
            "only the anchor session is listed, expected 1 row, got {}".format(
                len(sessions)
            )
        )

    def test_02_fifty_nine_minutes_conflicts_while_sixty_is_accepted(self):
        """A gap of 59 minutes behind the anchor is one minute short of the buffer
        and conflicts; a gap of exactly 60 minutes is accepted and reserves its own
        120 minutes.

        PRD (§3.6): "The buffer changes the arithmetic in a way worth stating
        plainly: two sessions that merely touch, where one's `window_end` equals the
        next one's `window_start`, still conflict, because the buffer forces a full
        hour of clearance between them; a gap of exactly 60 minutes is accepted."

        Design: Difficulty/resource_temporal_overlap/bench_windows_need_a_full_sixty_minute_changeover_gap_per_bench
        """
        ctx = _bench_program()

        near = _book(ctx, NEAR_RIGHT_START, NEAR_RIGHT_END)
        validate_error(near, ERR_BENCH_WINDOW_CONFLICT)

        clear = _book(ctx, CLEAR_RIGHT_START, CLEAR_RIGHT_END)

        booked = validate_success(clear, 201)
        assert_states(booked, state=SESSION_SCHEDULED, bench_index=1)
        assert booked["reserved_minutes"] == 120, (
            "the accepted 12:00..14:00 window reserves its own duration, expected "
            "120 minutes, got {}".format(booked["reserved_minutes"])
        )
        laboratory = read_laboratory(ctx.laboratory_id)
        assert_reserved_bench_minutes(laboratory, ANCHOR_MINUTES + 120)

    def test_03_the_buffer_applies_in_front_of_a_booking_as_well(self):
        """A window ending exactly when the anchor starts is refused, and the same
        window pushed back to end a full hour earlier is accepted, so the buffer
        widens the stored booking on both sides.

        PRD (§3.6): "**Bench occupancy** forbids a second session of the same
        laboratory-and-bench pair, in `state` `SCHEDULED` or `IN_PROGRESS`, from
        overlapping the requested window — where overlap is judged on the half-open
        interval running from `window_start` inclusive to `window_end` exclusive,
        *extended by a mandatory 60-minute changeover buffer on both sides*."

        Design: Difficulty/resource_temporal_overlap/bench_windows_need_a_full_sixty_minute_changeover_gap_per_bench
        """
        ctx = _bench_program()

        touching = _book(ctx, TOUCH_LEFT_START, TOUCH_LEFT_END)
        validate_error(touching, ERR_BENCH_WINDOW_CONFLICT)

        clear = _book(ctx, CLEAR_LEFT_START, CLEAR_LEFT_END)

        booked = validate_success(clear, 201)
        assert_states(booked, state=SESSION_SCHEDULED, bench_index=1)
        assert booked["reserved_minutes"] == 60, (
            "the accepted 07:00..08:00 window reserves its own duration, expected "
            "60 minutes, got {}".format(booked["reserved_minutes"])
        )
        laboratory = read_laboratory(ctx.laboratory_id)
        assert_reserved_bench_minutes(laboratory, ANCHOR_MINUTES + 60)

    def test_04_the_refused_window_is_free_on_a_different_bench(self):
        """The exact window the anchor's buffer refuses on bench 1 is accepted on
        bench 2, because occupancy is scoped to one laboratory-and-bench pair.

        PRD (§3.6): "**Bench occupancy** forbids a second session of the same
        laboratory-and-bench pair, in `state` `SCHEDULED` or `IN_PROGRESS`, from
        overlapping the requested window — where overlap is judged on the half-open
        interval running from `window_start` inclusive to `window_end` exclusive,
        *extended by a mandatory 60-minute changeover buffer on both sides*."

        Design: Difficulty/resource_temporal_overlap/bench_windows_need_a_full_sixty_minute_changeover_gap_per_bench
        """
        ctx = _bench_program()

        on_bench_one = _book(ctx, TOUCH_RIGHT_START, TOUCH_RIGHT_END, bench_index=1)
        validate_error(on_bench_one, ERR_BENCH_WINDOW_CONFLICT)

        on_bench_two = _book(ctx, TOUCH_RIGHT_START, TOUCH_RIGHT_END, bench_index=2)

        booked = validate_success(on_bench_two, 201)
        assert_states(booked, state=SESSION_SCHEDULED, bench_index=2)
        assert booked["reserved_minutes"] == 120, (
            "the bench 2 booking reserves its own two hours, expected 120 minutes, "
            "got {}".format(booked["reserved_minutes"])
        )
        laboratory = read_laboratory(ctx.laboratory_id)
        assert_reserved_bench_minutes(laboratory, ANCHOR_MINUTES + 120)

    def test_05_the_changeover_buffer_never_becomes_reserved_time(self):
        """After three refusals and three further accepted bookings the laboratory
        holds exactly 420 minutes — the four windows' own durations — so the buffer
        is never charged and the refusals reserved nothing.

        PRD (§3.3): "`reserved_bench_minutes` is defined as the sum of
        `reserved_minutes` over the laboratory's sessions whose `state` is
        `SCHEDULED` or `IN_PROGRESS`, and that definition is normative: after any
        number of book, start, complete, cancel and cascade-cancel cycles, the
        stored aggregate must equal that sum exactly, with no accumulated drift."

        Design: Difficulty/resource_temporal_overlap/bench_windows_need_a_full_sixty_minute_changeover_gap_per_bench
        """
        ctx = _bench_program()

        validate_error(
            _book(ctx, TOUCH_RIGHT_START, TOUCH_RIGHT_END), ERR_BENCH_WINDOW_CONFLICT
        )
        validate_error(
            _book(ctx, NEAR_RIGHT_START, NEAR_RIGHT_END), ERR_BENCH_WINDOW_CONFLICT
        )
        right = validate_success(_book(ctx, CLEAR_RIGHT_START, CLEAR_RIGHT_END), 201)
        validate_error(
            _book(ctx, TOUCH_LEFT_START, TOUCH_LEFT_END), ERR_BENCH_WINDOW_CONFLICT
        )
        left = validate_success(_book(ctx, CLEAR_LEFT_START, CLEAR_LEFT_END), 201)
        bench_two = validate_success(
            _book(ctx, TOUCH_RIGHT_START, TOUCH_RIGHT_END, bench_index=2), 201
        )

        reserved = (
            ANCHOR_MINUTES
            + right["reserved_minutes"]
            + left["reserved_minutes"]
            + bench_two["reserved_minutes"]
        )
        assert reserved == 420, (
            "the four accepted windows are 120 + 120 + 60 + 120 minutes of bench "
            "time, expected 420, got {}".format(reserved)
        )
        laboratory = read_laboratory(ctx.laboratory_id)
        assert_reserved_bench_minutes(laboratory, 420)

        sessions, meta = validate_paginated(
            api_client.list_test_sessions(ADMIN_HEADERS, laboratory_id=ctx.laboratory_id)
        )
        assert meta["total_count"] == 4, (
            "three bookings were refused and four accepted, expected total_count 4, "
            "got {}".format(meta["total_count"])
        )
        states = [session["state"] for session in sessions]
        assert states == [SESSION_SCHEDULED] * 4, (
            "every stored session is still SCHEDULED, expected four SCHEDULED, "
            "got {}".format(states)
        )


# ---------------------------------------------------------------------------
# The plugfest calendar, five events around one weekend in October
# ---------------------------------------------------------------------------

#: Windows chosen so the instants and the UTC calendar dates disagree: A and B
#: never overlap by a second yet share 10-06, while B and C are an hour apart
#: across midnight and share no date at all.
PLUGFEST_WINDOWS = {
    "A": ("2026-10-05T09:00:00Z", "2026-10-06T18:00:00Z"),
    "B": ("2026-10-06T20:00:00Z", "2026-10-06T23:00:00Z"),
    "C": ("2026-10-07T00:00:00Z", "2026-10-07T18:00:00Z"),
    "D": ("2026-10-04T09:00:00Z", "2026-10-04T23:00:00Z"),
    "E": ("2026-10-03T09:00:00Z", "2026-10-05T09:00:00Z"),
}
REGISTRATION_DEADLINE = "2026-10-01T00:00:00Z"
REGISTRATION_CLOCK = "2026-09-30T00:00:00Z"


def _plugfest_program():
    """Five REGISTRATION_OPEN events plus two devices of the same member.

    The second submission is what separates a per-device rule from a per-member
    one; the clock sits before every event's registration deadline.
    """
    ctx = build_program(stage="draft")
    ctx.second_submission_id = new_submission(
        ctx.member_id, ctx.specification_id, ctx.declared_codes
    )["id"]
    ctx.plugfest_ids = {}
    for name in sorted(PLUGFEST_WINDOWS):
        window_start, window_end = PLUGFEST_WINDOWS[name]
        ctx.plugfest_ids[name] = new_plugfest(
            ctx.laboratory_id,
            ctx.specification_id,
            window_start=window_start,
            window_end=window_end,
            registration_deadline=REGISTRATION_DEADLINE,
            min_distinct_vendors=2,
        )["id"]
    set_clock(REGISTRATION_CLOCK)
    return ctx


def _register(ctx, plugfest_name, submission_id=None, device_model="AL-100"):
    """Attempt one registration and hand back the raw response."""
    return api_client.create_participation(
        participation_payload(
            ctx.plugfest_ids[plugfest_name],
            ctx.member_id,
            submission_id or ctx.submission_id,
            device_model=device_model,
        ),
        make_member_headers(ctx.member_id),
    )


class TestPlugfestCalendarDateOverlap:
    """One device against five events whose dates and instants disagree."""

    def test_06_two_events_sharing_a_date_collide_though_their_instants_do_not(self):
        """The device is accepted into the event running 10-05T09:00Z..10-06T18:00Z
        and then refused from the event running 10-06T20:00Z..10-06T23:00Z: two clear
        hours separate the instants, but both occupy 2026-10-06.

        PRD (§3.7): "Those ranges are closed and inclusive at both ends, running from
        the calendar date of `window_start` through the calendar date of
        `window_end`, and clock times are irrelevant: an event that ends at 18:00 UTC
        on the sixth of October and one that begins at 20:00 UTC on the same sixth of
        October both occupy that date and therefore conflict, even though their
        instants do not overlap by a second."

        Design: Difficulty/resource_temporal_overlap/one_device_cannot_attend_two_plugfests_sharing_a_utc_calendar_date
        """
        ctx = _plugfest_program()

        accepted = validate_success(_register(ctx, "A"), 201)

        assert_states(
            accepted,
            state=PARTICIPATION_REGISTERED,
            submission_id=ctx.submission_id,
            interop_pass_count=0,
            outcome_recorded_at=None,
        )
        assert read_plugfest(ctx.plugfest_ids["A"])["distinct_vendor_count"] == 1, (
            "one member has registered one device, so distinct_vendor_count must be "
            "1, got {}".format(
                read_plugfest(ctx.plugfest_ids["A"])["distinct_vendor_count"]
            )
        )

        assert calendar_date(PLUGFEST_WINDOWS["A"][1]) == calendar_date(
            PLUGFEST_WINDOWS["B"][0]
        ), "the two events must share a UTC calendar date for this scenario to bite"

        refused = _register(ctx, "B")

        validate_error(refused, ERR_PARTICIPATION_WINDOW_CONFLICT)
        _, meta = validate_paginated(
            api_client.list_participations(
                ADMIN_HEADERS, submission_id=ctx.submission_id
            )
        )
        assert meta["total_count"] == 1, (
            "the refused registration must not be stored, expected total_count 1, "
            "got {}".format(meta["total_count"])
        )

    def test_07_a_date_disjoint_event_is_accepted_whatever_the_clock_gap(self):
        """With 10-05..10-06 already held, the events on 10-07 and on 10-04 are both
        accepted: their date ranges share nothing with the held range, and the minute
        arithmetic that governs bench windows plays no part.

        PRD (§3.7): "First, **calendar-date overlap**: the registration is refused
        when the same `submission_id` already has a participation, in `state`
        `REGISTERED`, `PASSED` or `FAILED`, belonging to a *different* plugfest whose
        UTC calendar-date range shares any date with the requested event's range."

        Design: Difficulty/resource_temporal_overlap/one_device_cannot_attend_two_plugfests_sharing_a_utc_calendar_date
        """
        ctx = _plugfest_program()
        new_participation(ctx.plugfest_ids["A"], ctx.member_id, ctx.submission_id)

        after_midnight = validate_success(_register(ctx, "C"), 201)
        before = validate_success(_register(ctx, "D"), 201)

        assert_states(after_midnight, state=PARTICIPATION_REGISTERED)
        assert_states(before, state=PARTICIPATION_REGISTERED)
        held_dates = {
            calendar_date(PLUGFEST_WINDOWS["A"][0]),
            calendar_date(PLUGFEST_WINDOWS["A"][1]),
        }
        assert calendar_date(PLUGFEST_WINDOWS["C"][0]) not in held_dates, (
            "the accepted event's date must sit outside the held range {}, got "
            "{}".format(sorted(held_dates), calendar_date(PLUGFEST_WINDOWS["C"][0]))
        )
        assert calendar_date(PLUGFEST_WINDOWS["D"][0]) not in held_dates, (
            "the earlier event's date must sit outside the held range {}, got "
            "{}".format(sorted(held_dates), calendar_date(PLUGFEST_WINDOWS["D"][0]))
        )

    def test_08_a_multi_day_event_must_be_free_on_every_date_it_spans(self):
        """With 10-04 and 10-05..10-06 already held, the event spanning
        10-03..10-05 is refused: its closed range covers two booked dates even though
        its own first date is free.

        PRD (§3.7): "Those ranges are closed and inclusive at both ends, running from
        the calendar date of `window_start` through the calendar date of
        `window_end`, and clock times are irrelevant: an event that ends at 18:00 UTC
        on the sixth of October and one that begins at 20:00 UTC on the same sixth of
        October both occupy that date and therefore conflict, even though their
        instants do not overlap by a second."

        Design: Difficulty/resource_temporal_overlap/one_device_cannot_attend_two_plugfests_sharing_a_utc_calendar_date
        """
        ctx = _plugfest_program()
        new_participation(ctx.plugfest_ids["A"], ctx.member_id, ctx.submission_id)
        new_participation(ctx.plugfest_ids["D"], ctx.member_id, ctx.submission_id)

        refused = _register(ctx, "E")

        validate_error(refused, ERR_PARTICIPATION_WINDOW_CONFLICT)
        assert calendar_date(PLUGFEST_WINDOWS["E"][0]) == "2026-10-03", (
            "the spanning event starts on the free date 2026-10-03, got {}".format(
                calendar_date(PLUGFEST_WINDOWS["E"][0])
            )
        )
        _, meta = validate_paginated(
            api_client.list_participations(
                ADMIN_HEADERS, submission_id=ctx.submission_id
            )
        )
        assert meta["total_count"] == 2, (
            "the spanning registration was refused, so the device still holds only "
            "its two participations, expected total_count 2, got {}".format(
                meta["total_count"]
            )
        )

    def test_09_re_registering_the_same_pair_reports_the_duplicate_not_the_overlap(self):
        """Registering the same device into the same event a second time trivially
        shares every date with itself, so the date check passes over it and the
        duplicate rule decides.

        PRD (§3.7): "Participations of the *requested* event are deliberately
        excluded from that check, so that a second registration of the same
        event-and-submission pair — which trivially shares every date with itself —
        instead falls through to the second rule."

        Design: Difficulty/resource_temporal_overlap/one_device_cannot_attend_two_plugfests_sharing_a_utc_calendar_date
        """
        ctx = _plugfest_program()
        new_participation(ctx.plugfest_ids["A"], ctx.member_id, ctx.submission_id)

        repeat = _register(ctx, "A")

        validate_error(repeat, ERR_DUPLICATE_PARTICIPATION)
        _, meta = validate_paginated(
            api_client.list_participations(
                ADMIN_HEADERS, plugfest_id=ctx.plugfest_ids["A"]
            )
        )
        assert meta["total_count"] == 1, (
            "the repeat registration must not be stored, expected total_count 1, "
            "got {}".format(meta["total_count"])
        )

    def test_10_the_date_conflict_is_scoped_to_one_device_not_to_the_member(self):
        """2026-10-06 is fully booked for the member's first device, yet the member's
        second device registers into the 10-06 event without objection, and the first
        device ends up holding exactly its three date-disjoint participations.

        PRD (§3.7): "First, **calendar-date overlap**: the registration is refused
        when the same `submission_id` already has a participation, in `state`
        `REGISTERED`, `PASSED` or `FAILED`, belonging to a *different* plugfest whose
        UTC calendar-date range shares any date with the requested event's range."

        Design: Difficulty/resource_temporal_overlap/one_device_cannot_attend_two_plugfests_sharing_a_utc_calendar_date
        """
        ctx = _plugfest_program()
        for name in ("A", "C", "D"):
            new_participation(ctx.plugfest_ids[name], ctx.member_id, ctx.submission_id)
        validate_error(_register(ctx, "B"), ERR_PARTICIPATION_WINDOW_CONFLICT)

        second_device = _register(
            ctx, "B", submission_id=ctx.second_submission_id, device_model="AL-200"
        )

        registered = validate_success(second_device, 201)
        assert_states(
            registered,
            state=PARTICIPATION_REGISTERED,
            submission_id=ctx.second_submission_id,
        )
        rows, meta = validate_paginated(
            api_client.list_participations(
                ADMIN_HEADERS, submission_id=ctx.submission_id
            )
        )
        assert meta["total_count"] == 3, (
            "the first device holds the three date-disjoint events, expected "
            "total_count 3, got {}".format(meta["total_count"])
        )
        held = sorted(row["plugfest_id"] for row in rows)
        expected = sorted(ctx.plugfest_ids[name] for name in ("A", "C", "D"))
        assert held == expected, (
            "the first device's participations must be the three accepted events, "
            "expected {}, got {}".format(expected, held)
        )
        assert read_plugfest(ctx.plugfest_ids["B"])["distinct_vendor_count"] == 1, (
            "two devices of one member would still count once, and only one is "
            "registered here, so distinct_vendor_count must be 1, got {}".format(
                read_plugfest(ctx.plugfest_ids["B"])["distinct_vendor_count"]
            )
        )
