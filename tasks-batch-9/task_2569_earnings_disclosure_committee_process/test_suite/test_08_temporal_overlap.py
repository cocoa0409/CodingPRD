"""Two calendars whose interval geometry is deliberately opposite.

Milestone windows are half-open and exclusive per kind, so touching ends are
admitted; a leader's preparation windows are closed at both ends and guarded by
an aggregate capacity of two rather than by exclusivity.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.assertions import assert_instant_equals, assert_money
from test_helpers.factories import milestone_payload, subcert_payload
from test_helpers.fixtures import (
    add_milestone,
    build_committee,
    build_cycle,
    open_close,
    refresh_cycle,
    withdraw_subcert,
)
from test_helpers.test_users import admin_headers

CALENDAR_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]


def _planning_cycle(api, name):
    committee = build_committee(
        api,
        seats=CALENDAR_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name=name,
    )
    cycle = build_cycle(api, committee)
    assert cycle["status"] == "PLANNING"
    assert_instant_equals(cycle["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    return committee, cycle


def _propose(api, committee, cycle_id, kind, start, end):
    return api.create_milestone(
        cycle_id, milestone_payload(kind, start, end), committee.controller("fin")
    )


def _milestones(api, cycle_id):
    return validate_success(api.list_cycle_milestones(cycle_id, admin_headers()))


def test_a_window_touching_an_existing_end_is_admitted_and_a_one_second_intrusion_is_not(
    api,
):
    """A second CLOSE window starting exactly where the first one ends is accepted
    because half-open windows that merely touch do not overlap, while a window
    starting one second earlier intrudes and is rejected; the cycle's minimum
    slack tracks the newest open window and the rejected candidate leaves no row.

    PRD 3.3: "Overlap is judged under half-open geometry: two windows overlap when the candidate's start is strictly before the sibling's end and the sibling's start is strictly before the candidate's end."

    Design: Difficulty/resource_temporal_overlap/milestone_calendar_half_open_windows_admit_touching_ends_and_reject_a_one_second_intrusion
    """
    committee, cycle = _planning_cycle(api, "Half Open Charter")
    first = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    assert first["slack_calendar_days"] == 7
    assert first["slack_business_days"] == 5

    touching = validate_success(
        _propose(
            api, committee, cycle["id"], "CLOSE",
            "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z",
        ),
        201,
    )
    assert touching["status"] == "PLANNED"
    assert touching["slack_calendar_days"] == 6
    assert touching["slack_business_days"] == 4

    validate_error(
        _propose(
            api, committee, cycle["id"], "CLOSE",
            "2026-08-03T23:59:59Z", "2026-08-05T00:00:00Z",
        ),
        "ERR_MILESTONE_WINDOW_OVERLAP",
        409,
    )

    after = refresh_cycle(api, cycle["id"])
    assert after["min_slack_days_calendar"] == 6
    assert after["min_slack_days_business"] == 4
    assert len(_milestones(api, cycle["id"])) == 2


def test_the_phase_buffer_is_measured_from_the_latest_predecessor_end_and_is_inclusive(api):
    """The review buffer runs from the latest CLOSE end, contributed by the second
    window rather than the first, so a review starting 47:59:59 after it is
    rejected on the buffer rule while one starting exactly 48 hours after it is
    admitted, and the new window then owns the cycle minimum.

    PRD 3.3: "The comparison is inclusive, so a gap of exactly the required number of hours is accepted; a shorter gap is rejected with `ERR_MILESTONE_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/milestone_calendar_half_open_windows_admit_touching_ends_and_reject_a_one_second_intrusion
    """
    committee, cycle = _planning_cycle(api, "Buffer Charter")
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z",
    )

    validate_error(
        _propose(
            api, committee, cycle["id"], "REVIEW",
            "2026-08-05T23:59:59Z", "2026-08-07T00:00:00Z",
        ),
        "ERR_MILESTONE_BUFFER_VIOLATION",
        409,
    )

    review = validate_success(
        _propose(
            api, committee, cycle["id"], "REVIEW",
            "2026-08-06T00:00:00Z", "2026-08-07T00:00:00Z",
        ),
        201,
    )
    assert review["kind"] == "REVIEW"
    assert review["slack_calendar_days"] == 3
    assert review["slack_business_days"] == 1

    after = refresh_cycle(api, cycle["id"])
    assert after["min_slack_days_calendar"] == 3
    assert after["min_slack_days_business"] == 1
    assert len(_milestones(api, cycle["id"])) == 3


def _prep_cycle(api):
    """A CLOSE_OPEN cycle whose internal target leaves every deadline below in
    range, with no sub-certification yet held by the finance leader."""
    committee, cycle = _planning_cycle(api, "Prep Window Charter")
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    opened = open_close(api, committee, cycle["id"])
    assert opened["status"] == "CLOSE_OPEN"
    assert_instant_equals(opened["internal_target_utc"], "2026-08-05T17:30:00Z")
    return committee, cycle


def _assign(api, committee, cycle_id, scope_area, due_utc):
    return api.create_subcert(
        subcert_payload(cycle_id, committee.mid("fin"), scope_area, due_utc),
        committee.chair("legal"),
    )


def _loaded_leader(api):
    """Two live preparation windows on the same leader, the second touching the
    first at a single instant."""
    committee, cycle = _prep_cycle(api)
    first = validate_success(
        _assign(api, committee, cycle["id"], "REVENUE", "2026-08-04T18:00:00Z"), 201
    )
    second = validate_success(
        _assign(api, committee, cycle["id"], "LEGAL_CONTINGENCY", "2026-08-01T18:00:00Z"),
        201,
    )
    return committee, cycle, first, second


def test_windows_touching_at_one_instant_occupy_each_other_yet_stay_under_the_cap(api):
    """A preparation window runs the 72 hours up to its deadline with both ends
    inclusive, so the second request's window touches the first at exactly one
    instant and does occupy it — but one occupant is below the cap of two, so the
    request is accepted, and only the third window, which finds both predecessors
    inside it, is refused.

    PRD 3.4: "If two or more such occupants already exist, the assignment is rejected with `ERR_MEMBER_PREP_WINDOW_CAPACITY`; a leader may carry at most two concurrent preparation windows."

    Design: Difficulty/resource_temporal_overlap/subcertification_prep_windows_are_closed_intervals_with_an_aggregate_capacity_of_two
    """
    committee, cycle, first, second = _loaded_leader(api)

    assert_instant_equals(first["prep_window_start_utc"], "2026-08-01T18:00:00Z")
    assert_instant_equals(second["prep_window_start_utc"], "2026-07-29T18:00:00Z")
    assert second["status"] == "PENDING"

    validate_error(
        _assign(api, committee, cycle["id"], "OPERATIONS", "2026-08-02T00:00:00Z"),
        "ERR_MEMBER_PREP_WINDOW_CAPACITY",
        409,
    )

    still_two = validate_success(
        api.list_subcerts(admin_headers(), cycle_id=cycle["id"], limit=10, offset=0)
    )
    assert len(still_two) == 2


def test_capacity_is_released_by_withdrawal_rather_than_by_the_passage_of_time(api):
    """Withdrawing one predecessor takes it out of the occupant set without moving
    any timestamp, so the identical third assignment that was just refused now
    lands, and the withdrawn row's weight leaves no residue in the cycle total.

    PRD 3.4: "Requests in `EXCEPTION_NOTED`, `WITHDRAWN` or `VOID` are not occupants — the leader has either already delivered or the assignment is gone."

    Design: Difficulty/resource_temporal_overlap/subcertification_prep_windows_are_closed_intervals_with_an_aggregate_capacity_of_two
    """
    committee, cycle, first, second = _loaded_leader(api)
    validate_error(
        _assign(api, committee, cycle["id"], "OPERATIONS", "2026-08-02T00:00:00Z"),
        "ERR_MEMBER_PREP_WINDOW_CAPACITY",
        409,
    )

    withdrawn = withdraw_subcert(api, committee, second["id"])
    assert withdrawn["status"] == "WITHDRAWN"

    third = validate_success(
        _assign(api, committee, cycle["id"], "OPERATIONS", "2026-08-02T00:00:00Z"), 201
    )
    assert_instant_equals(third["prep_window_start_utc"], "2026-07-30T00:00:00Z")
    assert_money(third["scope_weight"], 20.00)
    assert_money(first["scope_weight"], 30.00)

    after = refresh_cycle(api, cycle["id"])
    assert_money(after["total_assigned_scope_weight"], 50.00)
