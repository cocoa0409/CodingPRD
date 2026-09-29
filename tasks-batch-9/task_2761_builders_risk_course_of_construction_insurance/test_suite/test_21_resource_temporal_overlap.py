"""Shared resources contended for over time: peak overlap, not sums of rows."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_storage_assignment_payload,
    create_testing_notice_payload,
)

STORAGE_PART_PLAN = (
    ("TEMPORARY_STORAGE", 400000000),
    ("MATERIALS_ON_SITE", 1000000000),
)

AUTUMN = ("2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z")
WINTER = ("2026-12-01T00:00:00Z", "2027-02-01T00:00:00Z")
STRADDLE = ("2026-11-15T00:00:00Z", "2026-12-15T00:00:00Z")
MID_AUTUMN = ("2026-10-15T00:00:00Z", "2026-11-15T00:00:00Z")


def _account_and_facility():
    """One ACTIVE facility with 500000000 of aggregate capacity and nothing on it."""
    account = fx.in_force_account(parts=STORAGE_PART_PLAN)
    facility = fx.register_facility(
        name="Northgate Bonded Warehouse", site_code="STG-NORTH-11",
        distance_from_site_miles=42.5, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")
    return account, facility


def _assign(account, facility, stored_value_cents, window):
    payload = create_storage_assignment_payload(
        account.policy_id, facility["id"], stored_value_cents, *window)
    return api_client.create_storage_assignment(payload, fx.UW)


def _approved(account, facility, stored_value_cents, window):
    assignment = get_success_data(
        _assign(account, facility, stored_value_cents, window), expected_status=201)
    assert assignment["status"] == "APPROVED", assignment
    return assignment


def test_adjacent_windows_hand_off_without_aggregating_while_a_straddle_is_refused():
    """The windows are half-open with no buffer, so a commitment starting exactly
    when the incumbent ends is admissible even though the two stored values total
    700000000 against a 500000000 capacity — the peak was only ever 400000000. A
    third window that genuinely overlaps both incumbents peaks at 800000000 and is
    refused with ERR_FACILITY_CAPACITY_EXCEEDED.

    Design: Difficulty/resource_temporal_overlap/facility_capacity_uses_peak_overlap_and_admits_adjacent_handoffs
    """
    account, facility = _account_and_facility()

    _approved(account, facility, 300000000, AUTUMN)
    _approved(account, facility, 400000000, WINTER)

    straddling = _assign(account, facility, 100000000, STRADDLE)
    validate_error(straddling, "ERR_FACILITY_CAPACITY_EXCEEDED", expected_status=422)

    held = get_success_data(api_client.get_facility(facility["id"], fx.RE))
    assert held["committed_value_cents"] == 700000000, held


def test_the_capacity_test_rejects_strictly_above_and_forgets_released_rows():
    """One cent of peak above the aggregate capacity is refused while a peak of
    exactly the capacity is admitted, so the comparison is strictly
    greater-than. Releasing an incumbent drops it out of the peak, which makes
    the window that was refused for a straddle admissible on the identical body.

    Design: Difficulty/resource_temporal_overlap/facility_capacity_uses_peak_overlap_and_admits_adjacent_handoffs
    """
    account, facility = _account_and_facility()
    first = _approved(account, facility, 300000000, AUTUMN)
    _approved(account, facility, 400000000, WINTER)
    validate_error(_assign(account, facility, 100000000, STRADDLE),
                   "ERR_FACILITY_CAPACITY_EXCEEDED", expected_status=422)

    one_cent_over = _assign(account, facility, 200000001, MID_AUTUMN)
    validate_error(one_cent_over, "ERR_FACILITY_CAPACITY_EXCEEDED",
                   expected_status=422)
    _approved(account, facility, 200000000, MID_AUTUMN)

    released = fx.release_storage(first)
    assert released["status"] == "RELEASED", released
    assert released["release_reason"] == "MANUAL", released

    _approved(account, facility, 100000000, STRADDLE)

    final = get_success_data(api_client.get_facility(facility["id"], fx.RE))
    assert final["committed_value_cents"] == 700000000, final

    rows, _meta = validate_paginated(api_client.list_facility_storage_assignments(
        facility["id"], fx.RE, params={"limit": 100}))
    assert len(rows) == 4, f"the two refusals must not persist: {rows}"
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["APPROVED", "APPROVED", "APPROVED", "RELEASED"], statuses


def _notice(project, system_type, window, hot_work, water_charged=False):
    payload = create_testing_notice_payload(
        project["id"], window[0], window[1], system_type=system_type,
        hot_work=hot_work, water_charged=water_charged)
    return api_client.create_testing_notice(payload, fx.RE)


def _scheduled(project, system_type, window, hot_work, water_charged=False):
    notice = get_success_data(
        _notice(project, system_type, window, hot_work, water_charged),
        expected_status=201)
    assert notice["status"] == "SCHEDULED", notice
    return notice


def _screened_project():
    """Notices hang off the project, so no policy is needed. Grade B means no
    hot-work notice here needs a mitigation plan."""
    project = fx.eligible_project(engineering_grade="B")
    assert project["engineering_grade"] == "B", project
    _scheduled(project, "SPRINKLER_HYDROSTATIC",
               ("2027-03-01T08:00:00Z", "2027-03-01T17:00:00Z"),
               hot_work=False, water_charged=True)
    _scheduled(project, "HVAC",
               ("2027-03-01T17:00:00Z", "2027-03-02T02:00:00Z"), hot_work=False)
    return project


def test_the_calendar_is_bare_overlap_without_hot_work_and_buffered_with_it():
    """With hot_work false on both sides the separation rule degrades to plain
    half-open overlap, so a window starting exactly when the incumbent ends is
    admissible. Flip hot_work on and the same calendar refuses a window 8 hours
    after the incumbent ends, because the 24-hour buffer reaches past it; the
    byte-identical body with hot_work false is then accepted, which proves the
    refusal was the buffer and not an overlap.

    Design: Difficulty/resource_temporal_overlap/testing_window_hot_work_buffer_is_symmetric_and_rejects_a_one_second_shortfall
    """
    project = _screened_project()
    energization = ("2027-03-02T10:00:00Z", "2027-03-02T18:00:00Z")

    with_hot_work = _notice(
        project, "ELECTRICAL_ENERGIZATION", energization, hot_work=True)
    validate_error(with_hot_work, "ERR_TESTING_WINDOW_CONFLICT", expected_status=409)

    _scheduled(project, "ELECTRICAL_ENERGIZATION", energization, hot_work=False)


def test_the_hot_work_buffer_is_exactly_twenty_four_hours_and_symmetric():
    """A hot-work window starting one second short of 24 hours after the
    incumbent's end is refused while exactly 24 hours passes. The buffer then
    applies in the other direction too: a notice carrying no hot work is still
    refused when it starts at the end of an incumbent that does, and is admitted
    24 hours later. None of the refusals left a row behind.

    Design: Difficulty/resource_temporal_overlap/testing_window_hot_work_buffer_is_symmetric_and_rejects_a_one_second_shortfall
    """
    project = _screened_project()
    _scheduled(project, "ELECTRICAL_ENERGIZATION",
               ("2027-03-02T10:00:00Z", "2027-03-02T18:00:00Z"), hot_work=False)

    one_second_short = _notice(
        project, "BOILER_STARTUP",
        ("2027-03-03T17:59:59Z", "2027-03-04T01:59:59Z"), hot_work=True)
    validate_error(one_second_short, "ERR_TESTING_WINDOW_CONFLICT",
                   expected_status=409)

    _scheduled(project, "BOILER_STARTUP",
               ("2027-03-03T18:00:00Z", "2027-03-04T02:00:00Z"), hot_work=True)

    other_direction = _notice(
        project, "ELEVATOR",
        ("2027-03-04T02:00:00Z", "2027-03-04T10:00:00Z"), hot_work=False)
    validate_error(other_direction, "ERR_TESTING_WINDOW_CONFLICT",
                   expected_status=409)

    _scheduled(project, "ELEVATOR",
               ("2027-03-05T02:00:00Z", "2027-03-05T10:00:00Z"), hot_work=False)

    rows, _meta = validate_paginated(api_client.list_project_testing_notices(
        project["id"], fx.RE, params={"limit": 100}))
    assert len(rows) == 5, f"the three refusals must not persist: {rows}"
    assert all(row["status"] == "SCHEDULED" for row in rows), rows
