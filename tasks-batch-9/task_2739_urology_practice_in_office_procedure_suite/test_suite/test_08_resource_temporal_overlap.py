"""
Temporal overlap of the two resources a committed case holds.

A case books two resources with deliberately different geometries. The room is
held over a half-open interval that runs from the case's start all the way to
the end of its turnover, so a booking that begins the instant the previous
patient leaves the room is still refused — the room is being cleaned. The
operating urologist is held over a closed interval that ignores turnover
altogether and is buffered by ten minutes on each side, so two of that
urologist's holds that merely touch at a single instant already collide.

The two families therefore make opposite predictions about the same clock
arithmetic, and both are exercised here end to end through the API.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_PROVIDER_DOUBLE_BOOKED,
    ERR_ROOM_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_fields, assert_occupancy_window
from test_helpers.constants import (
    CASE_DRAFT,
    CASE_SCHEDULED,
    CLEANUP_HIGH,
    ROOM_TYPE_CYSTO_SUITE,
    TYPE_CYSTOSCOPY,
)

BOOKING_CLOCK = "2026-09-14T07:00:00Z"


def _room_overlap_stage(api, roster):
    """
    One cystoscopy suite with a ten-minute baseline turnover, and a case already
    standing on its calendar from 14:00: a twenty-minute procedure ending 14:20,
    followed by forty minutes of turnover that runs to 15:00.

    Two further cases are drafted against the same room for two different
    urologists than the first, one starting exactly at the first case's end of
    procedure and one starting exactly at the end of its turnover. Because the
    urologists differ, no provider rule can explain either outcome.
    """
    patient = fx.create_patient(
        api,
        roster.urologist,
        full_name="Cyrus Lund",
        egfr=60,
        anticoagulant_flag=False,
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=True,
        requires_antibiotic=False,
        required_prep_codes=[],
    )
    fx.set_clock(api, BOOKING_CLOCK, roster.admin_headers)

    first_case = fx.schedule_new_case(
        api,
        roster,
        patient,
        procedure_type,
        room,
        "2026-09-14T14:00:00Z",
        provider=roster.urologist,
    )
    at_end_of_procedure = fx.draft_case(
        api,
        roster,
        patient,
        procedure_type,
        room,
        "2026-09-14T14:20:00Z",
        provider=roster.urologist_alt,
    )
    at_end_of_turnover = fx.draft_case(
        api,
        roster,
        patient,
        procedure_type,
        room,
        "2026-09-14T15:00:00Z",
        provider=roster.urologist_alt,
    )
    current_room = fx.read_room(api, roster, room["id"])
    return {
        "room": room,
        "room_version": current_room["version"],
        "first_case": first_case,
        "at_end_of_procedure": at_end_of_procedure,
        "at_end_of_turnover": at_end_of_turnover,
    }


def test_room_hold_runs_through_the_turnover_tail(api, roster):
    """PRD §3.2: "First the room's own `turnover_minutes` is multiplied by a
    cleanup multiplier of 2 when the procedure type's `cleanup_class` is `HIGH`
    and by 1 when it is `LOW`."
    PRD §3.2: "Only then, if the procedure type's `requires_scope` is true, a
    further twenty minutes is added for scope handling."
    PRD §3.2: "`scheduled_end_at` is `scheduled_start_at` advanced by
    `procedure_minutes` minutes, and `block_end_at` is `scheduled_end_at`
    advanced by `turnover_minutes` minutes."
    PRD §3.3: "Two cases in the same room conflict when their half-open
    intervals intersect; a new case whose `scheduled_start_at` falls exactly on
    an existing case's `block_end_at` therefore fits perfectly and is accepted,
    while a start one minute earlier than that is refused with
    `ERR_ROOM_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rt_room_halfopen_turnover_inclusive
    """
    stage = _room_overlap_stage(api, roster)

    # The room hold of the standing case reaches 15:00, forty minutes past the
    # 14:20 end of its procedure.
    assert_occupancy_window(
        stage["first_case"],
        procedure_minutes=20,
        turnover_minutes=40,
        scheduled_start_at="2026-09-14T14:00:00.000Z",
        scheduled_end_at="2026-09-14T14:20:00.000Z",
        block_end_at="2026-09-14T15:00:00.000Z",
    )

    response = api.schedule_case(
        stage["at_end_of_procedure"]["id"],
        f.schedule_payload(stage["room_version"]),
        roster.scheduler_headers,
    )
    validate_error(response, ERR_ROOM_WINDOW_CONFLICT)

    still_drafted = fx.read_case(api, roster, stage["at_end_of_procedure"]["id"])
    assert_fields(still_drafted, schedule_status=CASE_DRAFT)


def test_case_starting_exactly_at_block_end_at_fits_the_room(api, roster):
    """PRD §3.3: "Two cases in the same room conflict when their half-open
    intervals intersect; a new case whose `scheduled_start_at` falls exactly on
    an existing case's `block_end_at` therefore fits perfectly and is accepted,
    while a start one minute earlier than that is refused with
    `ERR_ROOM_WINDOW_CONFLICT`."
    PRD §3.3: "A room's occupancy is the *half-open* interval that begins at
    `scheduled_start_at` and ends at `block_end_at`, the endpoint excluded."
    PRD §3.3: "Committing a case to the calendar is the `Scheduler`'s exclusive
    act, and it advances `schedule_status` from `DRAFT` to `SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/rt_room_halfopen_turnover_inclusive
    """
    stage = _room_overlap_stage(api, roster)

    committed = validate_success(
        api.schedule_case(
            stage["at_end_of_turnover"]["id"],
            f.schedule_payload(stage["room_version"]),
            roster.scheduler_headers,
        )
    )
    assert_fields(committed, schedule_status=CASE_SCHEDULED)
    assert_occupancy_window(
        committed,
        procedure_minutes=20,
        turnover_minutes=40,
        scheduled_start_at="2026-09-14T15:00:00.000Z",
        scheduled_end_at="2026-09-14T15:20:00.000Z",
        block_end_at="2026-09-14T16:00:00.000Z",
    )


def test_room_counts_only_the_blocks_that_were_actually_taken(api, roster):
    """PRD §3.1: "Each room also exposes `occupied_block_count`, a derived count
    of the cases naming that room whose `schedule_status` is `SCHEDULED`,
    `IN_ROOM` or `COMPLETED`; it initialises to 0."
    PRD §3.2: "Only cases whose `schedule_status` is `SCHEDULED`, `IN_ROOM` or
    `COMPLETED` occupy a room or a provider; `DRAFT`, `CANCELLED` and `NO_SHOW`
    cases occupy neither."
    PRD §3.3: "Two cases in the same room conflict when their half-open
    intervals intersect; a new case whose `scheduled_start_at` falls exactly on
    an existing case's `block_end_at` therefore fits perfectly and is accepted,
    while a start one minute earlier than that is refused with
    `ERR_ROOM_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rt_room_halfopen_turnover_inclusive
    """
    stage = _room_overlap_stage(api, roster)

    validate_error(
        api.schedule_case(
            stage["at_end_of_procedure"]["id"],
            f.schedule_payload(stage["room_version"]),
            roster.scheduler_headers,
        ),
        ERR_ROOM_WINDOW_CONFLICT,
    )
    validate_success(
        api.schedule_case(
            stage["at_end_of_turnover"]["id"],
            f.schedule_payload(stage["room_version"]),
            roster.scheduler_headers,
        )
    )

    room = validate_success(
        api.get_procedure_room(stage["room"]["id"], roster.scheduler_headers)
    )
    assert_fields(room, occupied_block_count=2)


def _provider_overlap_stage(api, roster):
    """
    Two interchangeable cystoscopy suites and one urologist who operates in
    both. The urologist's standing case runs in the first room from 14:00 to
    14:20 and holds that room until 14:40.

    Two further cases are drafted in the *second* room, so the room calendar can
    never explain a refusal: that room holds nothing at all. One starts at
    14:40, the instant at which the urologist's buffered day and the new case's
    buffered day touch, and one starts a minute later.
    """
    patient = fx.create_patient(
        api,
        roster.urologist,
        full_name="Elias Roth",
        egfr=60,
        anticoagulant_flag=False,
    )
    room_a = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    room_b = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto B", turnover_minutes=10
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=False,
        required_prep_codes=[],
    )
    fx.set_clock(api, BOOKING_CLOCK, roster.admin_headers)

    first_case = fx.schedule_new_case(
        api,
        roster,
        patient,
        procedure_type,
        room_a,
        "2026-09-14T14:00:00Z",
        provider=roster.urologist,
    )
    touching = fx.draft_case(
        api,
        roster,
        patient,
        procedure_type,
        room_b,
        "2026-09-14T14:40:00Z",
        provider=roster.urologist,
    )
    one_minute_clear = fx.draft_case(
        api,
        roster,
        patient,
        procedure_type,
        room_b,
        "2026-09-14T14:41:00Z",
        provider=roster.urologist,
    )
    room_b_current = fx.read_room(api, roster, room_b["id"])
    return {
        "patient": patient,
        "procedure_type": procedure_type,
        "room_a": room_a,
        "room_b": room_b,
        "room_b_version": room_b_current["version"],
        "first_case": first_case,
        "touching": touching,
        "one_minute_clear": one_minute_clear,
    }


def test_provider_holds_that_merely_touch_are_a_double_booking(api, roster):
    """PRD §3.3: "The urologist's occupancy is the *closed* interval that begins
    ten minutes before `scheduled_start_at` and ends ten minutes after
    `scheduled_end_at`."
    PRD §3.3: "Note both differences: the provider interval ignores turnover
    entirely, because the urologist walks out while the room is being cleaned,
    and it treats mere touching as a collision, so two of the same provider's
    buffered intervals sharing a single boundary instant are refused with
    `ERR_PROVIDER_DOUBLE_BOOKED`."
    PRD §2.8: "**Priority 59 — provider double booking.** The case's closed
    buffered provider interval does not intersect that of any other occupying
    case with the same `primary_provider_id`, as defined in §3.3."

    Design: Difficulty/resource_temporal_overlap/rt_provider_closed_buffered_touching
    """
    stage = _provider_overlap_stage(api, roster)

    # The standing case ends its procedure at 14:20 and releases its room at
    # 14:40; the urologist's buffered hold therefore reaches only 14:30.
    assert_occupancy_window(
        stage["first_case"],
        procedure_minutes=20,
        turnover_minutes=20,
        scheduled_start_at="2026-09-14T14:00:00.000Z",
        scheduled_end_at="2026-09-14T14:20:00.000Z",
        block_end_at="2026-09-14T14:40:00.000Z",
    )

    # A 14:40 start buffers back to 14:30 — one shared instant with the hold
    # above. The second room holds nothing, so only the urologist can object.
    response = api.schedule_case(
        stage["touching"]["id"],
        f.schedule_payload(stage["room_b_version"]),
        roster.scheduler_headers,
    )
    validate_error(response, ERR_PROVIDER_DOUBLE_BOOKED)


def test_provider_holds_one_minute_apart_are_both_accepted(api, roster):
    """PRD §3.3: "The urologist's occupancy is the *closed* interval that begins
    ten minutes before `scheduled_start_at` and ends ten minutes after
    `scheduled_end_at`."
    PRD §2.8: "**Priority 59 — provider double booking.** The case's closed
    buffered provider interval does not intersect that of any other occupying
    case with the same `primary_provider_id`, as defined in §3.3."
    PRD §3.3: "Committing a case to the calendar is the `Scheduler`'s exclusive
    act, and it advances `schedule_status` from `DRAFT` to `SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/rt_provider_closed_buffered_touching
    """
    stage = _provider_overlap_stage(api, roster)

    committed = validate_success(
        api.schedule_case(
            stage["one_minute_clear"]["id"],
            f.schedule_payload(stage["room_b_version"]),
            roster.scheduler_headers,
        )
    )
    assert_fields(committed, schedule_status=CASE_SCHEDULED)
    assert_occupancy_window(
        committed,
        procedure_minutes=20,
        turnover_minutes=20,
        scheduled_start_at="2026-09-14T14:41:00.000Z",
        scheduled_end_at="2026-09-14T15:01:00.000Z",
        block_end_at="2026-09-14T15:21:00.000Z",
    )


def test_double_booked_case_stays_a_draft_and_takes_no_room_block(api, roster):
    """PRD §3.3: "Note both differences: the provider interval ignores turnover
    entirely, because the urologist walks out while the room is being cleaned,
    and it treats mere touching as a collision, so two of the same provider's
    buffered intervals sharing a single boundary instant are refused with
    `ERR_PROVIDER_DOUBLE_BOOKED`."
    PRD §3.2: "Only cases whose `schedule_status` is `SCHEDULED`, `IN_ROOM` or
    `COMPLETED` occupy a room or a provider; `DRAFT`, `CANCELLED` and `NO_SHOW`
    cases occupy neither."
    PRD §3.1: "Each room also exposes `occupied_block_count`, a derived count of
    the cases naming that room whose `schedule_status` is `SCHEDULED`, `IN_ROOM`
    or `COMPLETED`; it initialises to 0."

    Design: Difficulty/resource_temporal_overlap/rt_provider_closed_buffered_touching
    """
    stage = _provider_overlap_stage(api, roster)

    validate_error(
        api.schedule_case(
            stage["touching"]["id"],
            f.schedule_payload(stage["room_b_version"]),
            roster.scheduler_headers,
        ),
        ERR_PROVIDER_DOUBLE_BOOKED,
    )

    still_drafted = fx.read_case(api, roster, stage["touching"]["id"])
    assert_fields(still_drafted, schedule_status=CASE_DRAFT)

    room_b = fx.read_room(api, roster, stage["room_b"]["id"])
    assert_fields(room_b, occupied_block_count=0)

    room_a = fx.read_room(api, roster, stage["room_a"]["id"])
    assert_fields(room_a, occupied_block_count=1)


def test_the_same_touching_start_is_fine_for_a_second_urologist(api, roster):
    """PRD §3.3: "Note both differences: the provider interval ignores turnover
    entirely, because the urologist walks out while the room is being cleaned,
    and it treats mere touching as a collision, so two of the same provider's
    buffered intervals sharing a single boundary instant are refused with
    `ERR_PROVIDER_DOUBLE_BOOKED`."
    PRD §2.8: "**Priority 59 — provider double booking.** The case's closed
    buffered provider interval does not intersect that of any other occupying
    case with the same `primary_provider_id`, as defined in §3.3."

    The collision is scoped to a shared `primary_provider_id`, so the identical
    14:40 start that the operating urologist may not take is available to a
    colleague.

    Design: Difficulty/resource_temporal_overlap/rt_provider_closed_buffered_touching
    """
    stage = _provider_overlap_stage(api, roster)

    colleagues_case = fx.draft_case(
        api,
        roster,
        stage["patient"],
        stage["procedure_type"],
        stage["room_b"],
        "2026-09-14T14:40:00Z",
        provider=roster.urologist_alt,
    )
    committed = validate_success(
        api.schedule_case(
            colleagues_case["id"],
            f.schedule_payload(stage["room_b_version"]),
            roster.scheduler_headers,
        )
    )
    assert_fields(committed, schedule_status=CASE_SCHEDULED)
    assert_occupancy_window(
        committed,
        procedure_minutes=20,
        turnover_minutes=20,
        scheduled_start_at="2026-09-14T14:40:00.000Z",
        scheduled_end_at="2026-09-14T15:00:00.000Z",
        block_end_at="2026-09-14T15:20:00.000Z",
    )
