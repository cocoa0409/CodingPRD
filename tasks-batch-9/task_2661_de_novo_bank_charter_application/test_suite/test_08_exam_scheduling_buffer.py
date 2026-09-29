"""
The report-writing buffer on a readiness examination and the calendar it occupies.

The canonical field visit runs [2026-10-05T09:00:00Z, 2026-10-07T17:00:00Z) and comes
back deficient, so its buffer-extended interval ends at 2026-10-09T17:00:00Z and it
goes on holding that slot as a matter of record.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import CHARTERING_EXAMINER_HEADERS, fixtures as fx
from test_helpers.assertions import assert_fields_equal, assert_system_fields
from test_helpers.factories import readiness_exam_payload
from test_helpers.types import (
    BLOCKED_REASON_EXAM_DEFICIENT,
    EXAM_DEFICIENT,
    EXAM_SCHEDULED,
    EXAM_SCOPE_TARGETED_FOLLOW_UP,
    STAGE_CONDITIONALLY_APPROVED,
)


def _assert_instant(row, field, expected):
    """Compare a stored instant against an expected instant, ignoring fractional digits."""
    actual = row[field]
    assert actual.startswith(expected.rstrip("Z")), (
        f"{field} must be {expected}, got {actual!r}"
    )


def _schedule_follow_up(api, world, window_start_utc, window_end_utc):
    return api.create_readiness_exam(
        world["group_id"],
        readiness_exam_payload(
            window_start_utc, window_end_utc, EXAM_SCOPE_TARGETED_FOLLOW_UP
        ),
        CHARTERING_EXAMINER_HEADERS,
    )


# ---------------------------------------------------------------------------
# Difficulty / boundary_precision_check
# ---------------------------------------------------------------------------
def test_a_follow_up_one_second_inside_the_buffer_tail_conflicts(api, deficient_exam_group):
    """
    The deficient visit's own window closed at 2026-10-07T17:00:00Z, but its interval runs
    on to 2026-10-09T17:00:00Z. A return trip proposed for one second before that instant
    is still inside the occupied interval and is refused.

    PRD: "Each examination's `buffer_end_utc` is derived as its `window_end_utc` plus 48 hours — two full days of report-writing time — and the interval it occupies runs from `window_start_utc` inclusive to `buffer_end_utc` exclusive."

    Design: Difficulty/boundary_precision_check/exam_window_starting_exactly_at_buffer_end_is_allowed
    """
    world = deficient_exam_group
    ex1 = fx.read_exam(api, world["ex1"])
    assert_fields_equal(ex1, status=EXAM_DEFICIENT, finding_count=9)
    _assert_instant(ex1, "buffer_end_utc", "2026-10-09T17:00:00")
    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        stage=STAGE_CONDITIONALLY_APPROVED,
        opening_blocked_reason=BLOCKED_REASON_EXAM_DEFICIENT,
    )

    validate_error(
        _schedule_follow_up(
            api, world, "2026-10-09T16:59:59Z", "2026-10-10T12:00:00Z"
        ),
        "ERR_EXAM_WINDOW_CONFLICT",
        expected_status=409,
    )


def test_a_follow_up_starting_exactly_at_the_buffer_end_is_scheduled(
    api, deficient_exam_group
):
    """
    One second later the interval has closed. The same return trip proposed to start at
    exactly 2026-10-09T17:00:00Z is adjacent rather than overlapping and books cleanly,
    beginning scheduled with nothing found and carrying its own forty-eight hour tail out
    to 2026-10-12T12:00:00Z.

    PRD: "Because the interval is half-open, a new examination starting at exactly an existing examination's `buffer_end_utc` is permitted, while one starting a single second earlier conflicts."
    PRD: "A new examination begins in `SCHEDULED` with `finding_count` 0, and the group's `version` increments by one."

    Design: Difficulty/boundary_precision_check/exam_window_starting_exactly_at_buffer_end_is_allowed
    """
    world = deficient_exam_group

    ex2 = get_success_data(
        _schedule_follow_up(api, world, "2026-10-09T17:00:00Z", "2026-10-10T12:00:00Z"),
        expected_status=201,
    )
    assert_system_fields(ex2, expected_version=1)
    assert_fields_equal(
        ex2,
        status=EXAM_SCHEDULED,
        exam_scope=EXAM_SCOPE_TARGETED_FOLLOW_UP,
        finding_count=0,
    )
    _assert_instant(ex2, "window_start_utc", "2026-10-09T17:00:00")
    _assert_instant(ex2, "buffer_end_utc", "2026-10-12T12:00:00")


# ---------------------------------------------------------------------------
# Difficulty / resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_the_buffer_tail_blocks_a_window_that_clears_the_visit_itself(
    api, deficient_exam_group
):
    """
    A return trip on 2026-10-08 begins a full day after the deficient visit's window
    closed, so nothing about the two windows overlaps. Only the report-writing tail can
    explain the refusal, and the single deficient occupant is enough to produce it — a
    deficient visit never releases its slot.

    PRD: "The occupants of the group's calendar are its examinations whose `status` is `SCHEDULED`, `DEFICIENT` or `PASSED`; only a `CANCELLED` examination releases its interval, so a deficient visit continues to hold its slot as a matter of record."
    PRD: "A conflict exists when the proposed start is strictly before an occupant's `buffer_end_utc` **and** that occupant's `window_start_utc` is strictly before the proposed `buffer_end_utc`; the request is then refused with `ERR_EXAM_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/readiness_exam_buffer_tail_blocks_non_overlapping_window
    """
    world = deficient_exam_group
    ex1 = fx.read_exam(api, world["ex1"])
    _assert_instant(ex1, "window_end_utc", "2026-10-07T17:00:00")
    assert ex1["window_end_utc"] < "2026-10-08T09:00:00", (
        "the proposed window must start after the deficient visit's own window closed, "
        "so only the buffer can explain the refusal"
    )

    validate_error(
        _schedule_follow_up(api, world, "2026-10-08T09:00:00Z", "2026-10-08T17:00:00Z"),
        "ERR_EXAM_WINDOW_CONFLICT",
        expected_status=409,
    )
    assert_fields_equal(fx.read_exam(api, world["ex1"]), status=EXAM_DEFICIENT)


def test_a_window_clear_of_the_buffer_tail_books_and_takes_its_own_tail(
    api, deficient_exam_group
):
    """
    Pushed out to 2026-10-11 the return trip clears the deficient visit's tail entirely
    and is accepted, taking a tail of its own out to 2026-10-13T12:00:00Z. Neither the
    refused request nor the accepted one disturbs the audit record of the visit that
    failed.

    PRD: "Note that the buffer is added to the end only and never to the start."
    PRD: "The deficient examination itself is left untouched as the audit record."

    Design: Difficulty/resource_temporal_overlap/readiness_exam_buffer_tail_blocks_non_overlapping_window
    """
    world = deficient_exam_group
    before = fx.read_exam(api, world["ex1"])

    ex3 = get_success_data(
        _schedule_follow_up(api, world, "2026-10-11T00:00:00Z", "2026-10-11T12:00:00Z"),
        expected_status=201,
    )
    assert_fields_equal(
        ex3, status=EXAM_SCHEDULED, exam_scope=EXAM_SCOPE_TARGETED_FOLLOW_UP
    )
    _assert_instant(ex3, "window_start_utc", "2026-10-11T00:00:00")
    _assert_instant(ex3, "buffer_end_utc", "2026-10-13T12:00:00")

    after = fx.read_exam(api, world["ex1"])
    assert_fields_equal(
        after,
        status=EXAM_DEFICIENT,
        finding_count=9,
        version=before["version"],
    )
