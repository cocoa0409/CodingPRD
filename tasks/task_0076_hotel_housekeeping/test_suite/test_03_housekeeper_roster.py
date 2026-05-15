"""Housekeeper roster, shift toggles, and workload arithmetic.

Covers PRD §3.6 (workload formulas) and PRD §2.1 ownership rules for
self-toggle of shift_status.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_housekeeper,
    create_housekeeper_payload,
    make_housekeeper_headers,
    toggle_shift_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    advance_clock,
    create_housekeeper,
    create_housekeeper_on_shift,
    drive_task_to_state,
    setup_room_and_housekeeper,
    setup_room_hk_task,
    setup_task_in_state,
)


# ===========================================================================
# Housekeeper creation
# ===========================================================================
def test_create_housekeeper_defaults_off_shift(api):
    """PRD §3.6: "shift_status defaults to OFF_SHIFT."
    """
    res = api.create_housekeeper(
        create_housekeeper_payload(), TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res, expected_status=201)
    assert_housekeeper(data)
    assert data["shift_status"] == "OFF_SHIFT"


def test_create_housekeeper_initial_workload_zero(api):
    """PRD §3.6: "provisional_workload_minutes is the sum, over every
    cleaning task whose assigned_housekeeper_id equals the housekeeper's
    id and whose status is one of ASSIGNED, ACCEPTED, IN_PROGRESS, or
    SUBMITTED, of estimated_minutes."

    For a brand-new housekeeper, that sum is zero on both numbers.
    """
    hk = create_housekeeper()
    assert hk["provisional_workload_minutes"] == 0
    assert hk["realized_workload_minutes"] == 0


# ===========================================================================
# Shift toggle ownership (PRD §2.1, §3.6)
# ===========================================================================
def test_housekeeper_can_toggle_own_shift(api):
    """PRD §3.6: "A self-toggle of shift_status (where the toggling
    actor's X-User-ID equals the housekeeper's id) is allowed."
    """
    hk = create_housekeeper()
    res = api.toggle_housekeeper_shift(
        hk["id"],
        toggle_shift_payload("ON_SHIFT"),
        make_housekeeper_headers(hk["id"]),
    )
    data = validate_success(res)
    assert data["shift_status"] == "ON_SHIFT"


def test_supervisor_can_toggle_any_housekeeper_shift(api):
    """PRD §3.6: "and a supervisor may also toggle any housekeeper's
    shift on or off."
    """
    hk = create_housekeeper()
    res = api.toggle_housekeeper_shift(
        hk["id"],
        toggle_shift_payload("ON_SHIFT"),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["shift_status"] == "ON_SHIFT"


def test_housekeeper_cannot_toggle_other_housekeepers_shift(api):
    """PRD §3.6: "A self-toggle of shift_status (where the toggling
    actor's X-User-ID equals the housekeeper's id) is allowed."

    PRD §2.1: "ownership checks on any resource that references a
    Housekeeper (in particular, ... Housekeeper.id itself for a
    self-toggle of shift status) compare the resource's foreign-key
    field to X-User-ID."

    Claim: another housekeeper's headers fail the ownership check.
    """
    hk_a = create_housekeeper()
    hk_b = create_housekeeper()
    res = api.toggle_housekeeper_shift(
        hk_a["id"],
        toggle_shift_payload("ON_SHIFT"),
        make_housekeeper_headers(hk_b["id"]),
    )
    # Either the role-level check (housekeeper not allowed to toggle
    # someone else's shift) or the assignee ownership check fires —
    # both are PRD-faithful expressions of the same rule.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_NOT_TASK_ASSIGNEE.value,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
    ])


# ===========================================================================
# Workload arithmetic (PRD §3.6)
# ===========================================================================
def test_provisional_workload_sums_assigned_task_estimates(api):
    """PRD §3.6: "provisional_workload_minutes is the sum, over every
    cleaning task whose assigned_housekeeper_id equals the housekeeper's
    id and whose status is one of ASSIGNED, ACCEPTED, IN_PROGRESS, or
    SUBMITTED, of estimated_minutes."

    A single ASSIGNED CHECK_OUT task on a STANDARD room produces
    estimated_minutes = 25 (STANDARD) + 15 (CHECK_OUT) = 40 (PRD §3.4),
    so provisional should be 40.
    """
    room, hk, task = setup_room_hk_task(
        room_type="STANDARD", task_source="CHECK_OUT",
    )
    assert task["status"] == "ASSIGNED"
    # PRD §3.4: STANDARD 25 + CHECK_OUT 15 = 40
    assert task["estimated_minutes"] == 40
    res = api.get_housekeeper(hk["id"], TEST_USERS["supervisor_headers"])
    hk_now = validate_success(res)
    assert hk_now["provisional_workload_minutes"] == 40


def test_provisional_workload_excludes_completed_tasks(api):
    """PRD §3.6: "provisional_workload_minutes is the sum, over every
    cleaning task whose assigned_housekeeper_id equals the housekeeper's
    id and whose status is one of ASSIGNED, ACCEPTED, IN_PROGRESS, or
    SUBMITTED, of estimated_minutes."

    Claim: a COMPLETED task does NOT contribute to provisional.
    """
    room, hk, task = setup_task_in_state(
        target="COMPLETED",
        room_type="STANDARD",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=20,
    )
    assert task["status"] == "COMPLETED"
    res = api.get_housekeeper(hk["id"], TEST_USERS["supervisor_headers"])
    hk_now = validate_success(res)
    assert hk_now["provisional_workload_minutes"] == 0


def test_realized_workload_sums_actual_minutes_today(api):
    """PRD §3.6: "realized_workload_minutes is the sum, over every
    cleaning task whose assigned_housekeeper_id equals the housekeeper's
    id and whose status is COMPLETED with submitted_at on or after the
    start of the current UTC day, of actual_minutes."

    Drive a task to SUBMITTED with an explicit clock advance of 30
    minutes between start and submit → actual_minutes = 30. PASS
    inspection → COMPLETED. Realized should equal 30.
    """
    room, hk, task = setup_task_in_state(
        target="COMPLETED",
        room_type="STANDARD",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=30,
    )
    res = api.get_housekeeper(hk["id"], TEST_USERS["supervisor_headers"])
    hk_now = validate_success(res)
    # PRD §3.3: "actual_minutes as the number of minutes between
    # started_at and submitted_at rounded half-up to a whole minute"
    assert hk_now["realized_workload_minutes"] == 30
