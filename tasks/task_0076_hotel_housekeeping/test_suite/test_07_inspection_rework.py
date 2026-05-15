"""Inspection lifecycle: PASS / FAIL branching, rework cascade,
checklist validation, and the deterministic sampling rule (PRD §3.3,
§3.8).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_inspection_record,
    inspect_cleaning_task_payload,
    make_housekeeper_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    drive_task_to_state,
    inspect_task,
    setup_room_hk_task,
    setup_task_in_state,
)


# ===========================================================================
# Inspection envelope and rules (PRD §3.8)
# ===========================================================================
def test_inspect_pass_advances_task_to_completed(api):
    """PRD §3.8: "On a PASS inspection, the cleaning task advances to
    COMPLETED, the room state machine advances atomically as described
    in §3.3 and §3.9, Room.last_cleaned_at is set to the inspection's
    created_at, an AuditLog is appended, and provisional_workload_minutes
    for the assignee is recomputed."
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        clock_advance_minutes_between_start_submit=30,
    )
    inspection = inspect_task(task["id"], outcome="PASS")
    assert_inspection_record(inspection)
    assert inspection["outcome"] == "PASS"
    # Read back the task — must be COMPLETED.
    res = api.get_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    final = validate_success(res)
    assert final["status"] == "COMPLETED"


def test_inspect_pass_sets_room_last_cleaned_at(api):
    """PRD §3.8: "Room.last_cleaned_at is set to the inspection's
    created_at."
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        room_type="STANDARD",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=20,
    )
    assert room.get("last_cleaned_at") is None
    inspection = inspect_task(task["id"], outcome="PASS")
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    assert final["last_cleaned_at"] is not None
    assert final["last_cleaned_at"] == inspection["created_at"]


def test_inspect_pass_on_checkout_task_takes_room_to_inspected(api):
    """PRD §3.3: "Once a room reaches INSPECTED (driven by a passing
    inspection on a check-out cleaning), it sits there until the test
    clock observes that at least the inspected-grace threshold of
    minutes have elapsed since the inspection."

    A PASS on a CHECK_OUT task must move the room to INSPECTED.
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        room_type="STANDARD",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=15,
    )
    inspect_task(task["id"], outcome="PASS")
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    assert final["status"] == "INSPECTED"


def test_inspect_pass_on_stayover_takes_room_back_to_occupied_clean(api):
    """PRD §3.3: "A passing inspection on a stayover task transitions
    the room from OCCUPIED_DIRTY back to OCCUPIED_CLEAN without taking
    the INSPECTED detour."
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        room_type="STANDARD",
        task_source="STAYOVER",
        pms_occupancy="OCCUPIED",
        clock_advance_minutes_between_start_submit=20,
    )
    inspect_task(task["id"], outcome="PASS")
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    assert final["status"] == "OCCUPIED_CLEAN", (
        "PRD §3.3: a PASS on STAYOVER returns the room to OCCUPIED_CLEAN."
    )


# ===========================================================================
# FAIL branch and rework cascade (PRD §3.3, §3.8)
# ===========================================================================
def test_inspect_fail_advances_task_to_cancelled_and_creates_rework(api):
    """PRD §3.3: "a failing inspection advances it to CANCELLED and
    auto-creates a rework task whose parent_task_id is the failed
    task's id, whose task_source is the failed task's original
    task_source, and whose expedite_flag is forced to true."
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=20,
    )
    inspect_task(task["id"], outcome="FAIL")
    res = api.get_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    failed = validate_success(res)
    assert failed["status"] == "CANCELLED"
    # Find rework task: lookup by room.
    tlist = api.list_cleaning_tasks(
        TEST_USERS["supervisor_headers"],
        params={"room_id": room["id"]},
    )
    tasks, _ = validate_paginated(tlist)
    rework = [
        t for t in tasks if t.get("parent_task_id") == task["id"]
    ]
    assert len(rework) == 1, (
        "PRD §3.3: a FAIL inspection auto-creates exactly one rework "
        "CleaningTask with parent_task_id == failed task id."
    )
    r = rework[0]
    assert r["task_source"] == "CHECK_OUT", (
        "PRD §3.3: rework task_source matches the failed task's "
        "original task_source."
    )
    assert r["expedite_flag"] is True, (
        "PRD §3.3: 'expedite_flag is forced to true' on the rework "
        "task."
    )


def test_inspect_fail_does_not_set_last_cleaned_at(api):
    """PRD §3.3: "Room.last_cleaned_at is set to the inspection's
    created_at" appears in the PASS-only path (PRD §3.3 + §3.8). A FAIL
    leaves last_cleaned_at unchanged.

    Claim: after a FAIL inspection, the room's last_cleaned_at is
    still null (no prior PASS).
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=20,
    )
    assert room.get("last_cleaned_at") is None
    inspect_task(task["id"], outcome="FAIL")
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    assert final["last_cleaned_at"] is None, (
        "PRD §3.3 sets last_cleaned_at only on PASS inspection."
    )


# ===========================================================================
# Checklist validation (PRD §3.8)
# ===========================================================================
def test_inspect_pass_with_failed_checklist_item_rejected(api):
    """PRD §3.8: "A PASS outcome is only valid when every checklist item
    has passed equal to true — submitting PASS while at least one
    item's passed is false, or submitting with an empty checklist, is
    rejected with ERR_INVALID_INSPECTION_CHECKLIST."
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        clock_advance_minutes_between_start_submit=10,
    )
    payload = inspect_cleaning_task_payload(
        outcome="PASS",
        checklist_items=[
            {"item_code": "BED", "passed": True},
            {"item_code": "BATHROOM", "passed": False,
             "note": "stains"},
        ],
    )
    res = api.inspect_cleaning_task(
        task["id"], payload, TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_INSPECTION_CHECKLIST.value)


def test_inspect_empty_checklist_rejected(api):
    """PRD §3.8: "or submitting with an empty checklist, is rejected
    with ERR_INVALID_INSPECTION_CHECKLIST."
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        clock_advance_minutes_between_start_submit=10,
    )
    payload = inspect_cleaning_task_payload(
        outcome="PASS", checklist_items=[],
    )
    res = api.inspect_cleaning_task(
        task["id"], payload, TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_INSPECTION_CHECKLIST.value)


def test_inspect_non_submitted_task_rejected(api):
    """PRD §2.6: "state-machine eligibility for the requested
    transition (raising the family of state errors enumerated in §5,
    such as ... ERR_TASK_NOT_SUBMITTED ...)."

    PRD §3.8: "A supervisor inspects a submitted cleaning task by
    posting an inspection containing the outcome (PASS or FAIL)."

    Claim: /inspect on a task that is not SUBMITTED surfaces
    ERR_TASK_NOT_SUBMITTED.
    """
    room, hk, task = setup_room_hk_task()  # ASSIGNED
    res = api.inspect_cleaning_task(
        task["id"],
        inspect_cleaning_task_payload(outcome="PASS"),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TASK_NOT_SUBMITTED.value)


# ===========================================================================
# InspectionRecord retrieval (PRD §4)
# ===========================================================================
def test_get_inspection_record_after_pass(api):
    """PRD §4: GET /cleaning-tasks/{taskId}/inspection returns the
    InspectionRecord. PRD §3.8: 'The resulting InspectionRecord
    carries cleaning_task_id, a denormalised room_id for archival
    queries, supervisor_id taken from the inspecting supervisor's
    X-User-ID, the checklist_items, outcome, optional notes, and a
    server-set sampled_flag.'
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        clock_advance_minutes_between_start_submit=12,
    )
    inspection = inspect_task(task["id"], outcome="PASS")
    res = api.get_inspection_record(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    fetched = validate_success(res)
    assert_inspection_record(fetched)
    assert fetched["cleaning_task_id"] == task["id"]
    assert fetched["room_id"] == room["id"]
    assert fetched["outcome"] == "PASS"
    assert fetched["supervisor_id"] == TEST_USERS["supervisor_headers"][
        "X-User-ID"
    ]
