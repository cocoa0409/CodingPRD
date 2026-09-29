"""Two different interval rules on two different resources.

The reminder cadence measures separation between instants in whole elapsed days;
the announcement overlap check intersects two closed calendar-date intervals, in
which a single shared boundary date already counts as a collision.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals, assert_priority_score
from test_helpers.fixtures import ANNOUNCE_INSTANT, ORIGIN_INSTANT, announced_wave
from test_helpers.types import Ctx
from test_helpers.test_users import ANALYST, PROGRAM_ADMIN

# The announcement anchors the first reminder, so the seventh day is 2026-09-08.
FIRST_REMINDER_INSTANT = "2026-09-08T00:00:00Z"
# One second short of the next seven-day gap: this floors to six whole days.
SHORT_GAP_INSTANT = "2026-09-14T23:59:59Z"
SECOND_REMINDER_INSTANT = "2026-09-15T00:00:00Z"


def _notified_case_with_one_reminder(b):
    """A silent case that has received exactly one reminder, seven days in."""
    ctx = announced_wave(b, relationships=("SPOUSE",))
    case = b.read_case(ctx.case["id"])
    assert case["status"] == "NOTIFIED"
    assert_instant_equals(case["notified_at"], ANNOUNCE_INSTANT)
    assert case["reminders_sent_count"] == 0

    b.set_clock(FIRST_REMINDER_INSTANT)
    ctx.first_reminder = b.reminder(ctx.case["id"])
    return ctx


def test_a_gap_of_exactly_the_configured_minimum_admits_the_reminder(b):
    """Seven whole days from the announcement is accepted by the inclusive test.

    PRD: "the reminder is accepted only when that whole-day count is greater than
    or equal to the program's `reminder_min_gap_days`. A gap exactly equal to the
    configured minimum is therefore allowed"

    Design: Difficulty/resource_temporal_overlap/reminder_minimum_gap_uses_floor_of_whole_elapsed_days
    """
    ctx = _notified_case_with_one_reminder(b)

    case = b.read_case(ctx.case["id"])
    assert case["reminders_sent_count"] == 1
    assert_instant_equals(case["last_reminder_at"], FIRST_REMINDER_INSTANT)
    assert case["communication_sequence_no"] == 2


def test_a_gap_one_second_short_floors_to_six_days_and_is_refused(b, client):
    """The partial day is discarded rather than rounded up.

    PRD: "The elapsed time from the anchor to the current clock instant is
    converted to whole elapsed days by discarding any partial day — six days and
    twenty-three hours, fifty-nine minutes, fifty-nine seconds counts as six
    days, not seven"

    Design: Difficulty/resource_temporal_overlap/reminder_minimum_gap_uses_floor_of_whole_elapsed_days
    """
    ctx = _notified_case_with_one_reminder(b)
    b.set_clock(SHORT_GAP_INSTANT)

    response = client.send_reminder(
        ctx.case["id"], f.reminder_payload(), ANALYST
    )

    validate_error(response, E.ERR_REMINDER_CADENCE_VIOLATION, 409)
    case = b.read_case(ctx.case["id"])
    assert case["reminders_sent_count"] == 1
    assert_instant_equals(case["last_reminder_at"], FIRST_REMINDER_INSTANT)


def test_the_second_reminder_re_anchors_the_timeline_and_re_scores_the_case(b):
    """Each reminder anchors the next, and the triage score follows the count.

    PRD: "An accepted reminder increments the case's `reminders_sent_count`, sets
    `last_reminder_at` to the current clock instant, increments
    `communication_sequence_no`, and appends one `CommunicationEvent` with `kind`
    `REMINDER` carrying that new sequence number."

    Design: Difficulty/resource_temporal_overlap/reminder_minimum_gap_uses_floor_of_whole_elapsed_days
    """
    ctx = _notified_case_with_one_reminder(b)

    b.set_clock(SECOND_REMINDER_INSTANT)
    b.reminder(ctx.case["id"])

    case = b.read_case(ctx.case["id"])
    assert case["reminders_sent_count"] == 2
    assert_instant_equals(case["last_reminder_at"], SECOND_REMINDER_INSTANT)
    assert case["communication_sequence_no"] == 3
    assert_priority_score(
        case,
        unverified=1,
        in_scope=1,
        sensitive=False,
        reminders=2,
        max_reminders=3,
        silent=True,
    )
    assert case["priority_score"] == 68

    _rows, meta = b.communications(ctx.case["id"], kind="REMINDER")
    assert meta["total_count"] == 2


# Wave one occupies the closed interval [2026-09-01, 2026-10-16] for this
# subscriber; wave two's projected window opens on the clock's own date.
WAVE_ONE_NAME = "PY2026 Spouse Audit Wave 1"
WAVE_TWO_NAME = "PY2026 Child Audit Wave 2"
SECOND_DEPENDENT_INSTANT = "2026-09-02T00:00:00Z"
SECOND_SCOPE_INSTANT = "2026-09-03T00:00:00Z"
TOUCHING_INSTANT = "2026-10-16T00:00:00Z"
CLEAR_INSTANT = "2026-10-17T00:00:00Z"
WAVE_ONE_DEADLINE = "2026-10-16T00:00:00Z"
WAVE_TWO_AMNESTY_END = "2026-11-07T00:00:00Z"
WAVE_TWO_DEADLINE = "2026-12-01T00:00:00Z"


def _two_waves_over_one_subscriber(b):
    """One announced spouse audit, plus a scoped child audit over a later add."""
    b.set_clock(ORIGIN_INSTANT)
    employee = b.employee()
    spouse = b.dependent(employee["id"], "SPOUSE")

    wave_one = b.program(program_name=WAVE_ONE_NAME)
    b.doc_rule(wave_one["id"], "SPOUSE", "AUDIT")
    b.scope(wave_one["id"], "FULL_CENSUS")
    b.set_clock(ANNOUNCE_INSTANT)
    b.communicate(wave_one["id"])

    b.set_clock(SECOND_DEPENDENT_INSTANT)
    child = b.dependent(employee["id"], "CHILD_BIOLOGICAL")
    wave_two = b.program(program_name=WAVE_TWO_NAME)
    b.doc_rule(wave_two["id"], "CHILD_BIOLOGICAL", "AUDIT")
    b.set_clock(SECOND_SCOPE_INSTANT)
    b.scope(wave_two["id"], "FULL_CENSUS")

    return Ctx(
        employee=employee,
        spouse=spouse,
        child=child,
        wave_one=b.read_program(wave_one["id"]),
        wave_two=b.read_program(wave_two["id"]),
    )


def test_a_projected_window_touching_the_occupied_one_on_a_single_date_collides(b, client):
    """Adjacency at the shared boundary date 2026-10-16 is already an intersection.

    PRD: "If those two closed intervals intersect at all — and intervals that
    merely touch on a single shared boundary date **do** intersect — the
    announcement is refused with `ERR_CASE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/second_program_announcement_collides_on_shared_response_window_boundary_date
    """
    ctx = _two_waves_over_one_subscriber(b)
    assert_instant_equals(ctx.wave_one["response_deadline_at"], WAVE_ONE_DEADLINE)
    b.set_clock(TOUCHING_INSTANT)

    response = client.communicate(
        ctx.wave_two["id"], f.communicate_payload(), PROGRAM_ADMIN
    )

    validate_error(response, E.ERR_CASE_WINDOW_OVERLAP, 409)
    refused = b.read_program(ctx.wave_two["id"])
    assert refused["status"] == "SCOPED"
    assert refused["announcement_at"] is None


def test_the_refused_announcement_writes_nothing_at_all(b, client):
    """The collision check is atomic across the batch.

    PRD: "The check is atomic across the whole batch: if any one case collides, no
    case is notified and no program field is written."

    Design: Difficulty/resource_temporal_overlap/second_program_announcement_collides_on_shared_response_window_boundary_date
    """
    ctx = _two_waves_over_one_subscriber(b)
    b.set_clock(TOUCHING_INSTANT)

    response = client.communicate(
        ctx.wave_two["id"], f.communicate_payload(), PROGRAM_ADMIN
    )
    validate_error(response, E.ERR_CASE_WINDOW_OVERLAP, 409)

    assert b.read_dependent(ctx.child["id"])["coverage_status"] == "PENDING_VERIFICATION"
    assert b.cases(ctx.wave_two["id"])[0]["status"] == "SELECTED"


def test_one_day_past_the_shared_boundary_the_second_wave_announces(b, client):
    """Clearing the interval by a single day admits the identical announcement.

    PRD: "This program's projected window runs from the calendar date of the
    current clock through that date advanced by `response_days` whole days."

    Design: Difficulty/resource_temporal_overlap/second_program_announcement_collides_on_shared_response_window_boundary_date
    """
    ctx = _two_waves_over_one_subscriber(b)
    b.set_clock(TOUCHING_INSTANT)
    refused = client.communicate(
        ctx.wave_two["id"], f.communicate_payload(), PROGRAM_ADMIN
    )
    validate_error(refused, E.ERR_CASE_WINDOW_OVERLAP, 409)

    b.set_clock(CLEAR_INSTANT)
    b.communicate(ctx.wave_two["id"])

    announced = b.read_program(ctx.wave_two["id"])
    assert announced["status"] == "AMNESTY_OPEN"
    assert_instant_equals(announced["announcement_at"], CLEAR_INSTANT)
    assert_instant_equals(announced["amnesty_end_at"], WAVE_TWO_AMNESTY_END)
    assert_instant_equals(announced["response_deadline_at"], WAVE_TWO_DEADLINE)
    assert_instant_equals(
        b.read_program(ctx.wave_one["id"])["response_deadline_at"], WAVE_ONE_DEADLINE
    )
