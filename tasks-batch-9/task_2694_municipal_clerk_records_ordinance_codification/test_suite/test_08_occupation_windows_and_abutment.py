"""Two calendars whose exclusion zones are wider than the intervals they are
drawn from: a room held past the gavel by its teardown buffer, and supplement
windows that may not even touch.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import CITY_CLERK, CODIFICATION_EDITOR

SECOND_SITTING = {
    "body_type": "PLANNING_COMMISSION",
    "meeting_type": "SPECIAL",
    "quorum_required": 3,
}


def _room_occupied_until_half_past_nine():
    """One room with a 30-minute buffer, holding a SCHEDULED evening meeting that
    runs 18:00 to 21:00."""
    venue = fx.create_venue(teardown_buffer_minutes=30)
    meeting = fx.create_meeting(
        venue["id"],
        scheduled_start="2026-09-15T18:00:00Z",
        scheduled_end="2026-09-15T21:00:00Z",
    )
    return {"venue": venue, "meeting": meeting}


def test_a_sitting_starting_one_minute_inside_the_buffer_is_refused():
    """The 18:00-21:00 booking holds the room until 21:30, so 21:29 collides even
    though the meetings themselves do not.

    PRD 3.1: "The room's occupation is the half-open interval from
    `scheduled_start` up to but not including `scheduled_end`, **extended at the
    end by the venue's `teardown_buffer_minutes`**."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_window_plus_teardown_buffer_admits_the_meeting_starting_exactly_at_21_30
    """
    ctx = _room_occupied_until_half_past_nine()

    response = api_client.create_meeting(
        f.meeting_payload(
            ctx["venue"]["id"],
            scheduled_start="2026-09-15T21:29:00Z",
            scheduled_end="2026-09-15T22:30:00Z",
            **SECOND_SITTING,
        ),
        CITY_CLERK,
    )

    validate_error(response, ApiErrorId.VENUE_WINDOW_CONFLICT.value, 409)
    a.assert_status(fx.read_meeting(ctx["meeting"]["id"]), "SCHEDULED")
    _, meta = validate_paginated(
        api_client.list_meetings(CITY_CLERK, {"venue_id": ctx["venue"]["id"]})
    )
    a.assert_pagination_meta(meta, total_count=1)


def test_a_sitting_starting_exactly_when_the_buffer_lapses_is_admitted():
    """21:30 is the first instant the room is free, and the second body takes it
    without disturbing the first booking.

    PRD 3.1: "That extended interval must not overlap the extended interval of any
    other meeting on the same venue whose `status` is `SCHEDULED`, `NOTICED` or
    `IN_SESSION`; an overlap is rejected with `ERR_VENUE_WINDOW_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_window_plus_teardown_buffer_admits_the_meeting_starting_exactly_at_21_30
    """
    ctx = _room_occupied_until_half_past_nine()
    api_client.create_meeting(
        f.meeting_payload(
            ctx["venue"]["id"],
            scheduled_start="2026-09-15T21:29:00Z",
            scheduled_end="2026-09-15T22:30:00Z",
            **SECOND_SITTING,
        ),
        CITY_CLERK,
    )

    admitted = validate_success(
        api_client.create_meeting(
            f.meeting_payload(
                ctx["venue"]["id"],
                scheduled_start="2026-09-15T21:30:00Z",
                scheduled_end="2026-09-15T22:30:00Z",
                **SECOND_SITTING,
            ),
            CITY_CLERK,
        ),
        201,
    )

    a.assert_fields(
        admitted, scheduled_start="2026-09-15T21:30:00Z", status="SCHEDULED"
    )
    a.assert_status(fx.read_meeting(ctx["meeting"]["id"]), "SCHEDULED")
    _, meta = validate_paginated(
        api_client.list_meetings(CITY_CLERK, {"venue_id": ctx["venue"]["id"]})
    )
    a.assert_pagination_meta(meta, total_count=2)


def _title_with_an_october_cycle():
    """Title 12 carrying one OPEN cycle over the whole of October."""
    return fx.code_title_with_open_cycle(
        window_open_on="2026-10-01", window_close_on="2026-10-31"
    )


def test_a_window_opening_the_day_after_the_last_one_closes_is_refused():
    """1 November shares no day with an October window and is still refused,
    because abutment counts as collision.

    PRD 3.7: "Windows on the same title may not collide, and the collision rule is
    strict: a new window may neither overlap **nor abut** any existing cycle on
    that title whose `status` is `OPEN` or `LOCKED`, so a window opening the very
    day after another closes is still refused with
    `ERR_SUPPLEMENT_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/supplement_cycle_windows_must_not_abut_so_november_first_is_refused_and_november_second_is_accepted
    """
    pair = _title_with_an_october_cycle()

    response = api_client.create_supplement_cycle(
        pair["code_title"]["id"],
        f.supplement_cycle_payload(8, "2026-11-01", "2026-11-30"),
        CODIFICATION_EDITOR,
    )

    validate_error(response, ApiErrorId.SUPPLEMENT_WINDOW_CONFLICT.value, 409)
    a.assert_status(fx.read_cycle(pair["cycle"]["id"]), "OPEN")
    _, meta = validate_paginated(
        api_client.list_title_supplement_cycles(
            pair["code_title"]["id"], CODIFICATION_EDITOR
        )
    )
    a.assert_pagination_meta(meta, total_count=1)


def test_one_clear_day_of_separation_opens_the_next_supplement():
    """2 November leaves a single unclaimed day between the two windows, which is
    all the schedule needs.

    PRD 3.7: "A cycle enters at `status` `OPEN` with `submission_count`,
    `client_submission_count` and `conflict_count` all 0 and `certified_on` null."

    Design: Difficulty/resource_temporal_overlap/supplement_cycle_windows_must_not_abut_so_november_first_is_refused_and_november_second_is_accepted
    """
    pair = _title_with_an_october_cycle()
    api_client.create_supplement_cycle(
        pair["code_title"]["id"],
        f.supplement_cycle_payload(8, "2026-11-01", "2026-11-30"),
        CODIFICATION_EDITOR,
    )

    accepted = validate_success(
        api_client.create_supplement_cycle(
            pair["code_title"]["id"],
            f.supplement_cycle_payload(8, "2026-11-02", "2026-11-30"),
            CODIFICATION_EDITOR,
        ),
        201,
    )

    a.assert_fields(
        accepted,
        window_open_on="2026-11-02",
        window_close_on="2026-11-30",
        status="OPEN",
        submission_count=0,
        client_submission_count=0,
        conflict_count=0,
    )
    a.assert_nulls(accepted, "certified_on")
    a.assert_status(fx.read_cycle(pair["cycle"]["id"]), "OPEN")
    _, meta = validate_paginated(
        api_client.list_title_supplement_cycles(
            pair["code_title"]["id"], CODIFICATION_EDITOR
        )
    )
    a.assert_pagination_meta(meta, total_count=2)
