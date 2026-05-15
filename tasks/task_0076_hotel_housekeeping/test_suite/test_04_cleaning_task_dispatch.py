"""Cleaning-task creation, auto-dispatch, manual dispatch, and
eligible-housekeeper selection (PRD §3.3, §3.6).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    TEST_DEFAULTS,
    assert_cleaning_task,
    create_cleaning_task_payload,
    make_housekeeper_headers,
    toggle_shift_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_cleaning_task,
    create_housekeeper,
    create_housekeeper_on_shift,
    create_room,
    setup_room_and_housekeeper,
    setup_room_hk_task,
    unique_code,
    unique_zone,
)


def test_create_cleaning_task_auto_dispatches_when_eligible_housekeeper_on_shift(api):
    """PRD §3.3: "If at least one Housekeeper is on shift in the room's
    zone at the moment of creation, the system auto-dispatches the
    task right away and advances it from PENDING to ASSIGNED."
    """
    room, hk, task = setup_room_hk_task()
    assert task["status"] == "ASSIGNED"
    assert task["assigned_housekeeper_id"] == hk["id"]


def test_create_cleaning_task_stays_pending_when_no_housekeeper_on_shift(api):
    """PRD §3.3: "if no eligible housekeeper is on shift, the task
    remains PENDING until a supervisor triggers a manual dispatch."
    """
    room = create_room()
    # Create off-shift housekeeper in same zone:
    hk = create_housekeeper(
        assigned_zone=room["zone_code"], on_shift=False,
    )
    res = api.create_cleaning_task(
        create_cleaning_task_payload(
            room_id=room["id"], task_source="SCHEDULED",
        ),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res, expected_status=201)
    assert_cleaning_task(data)
    assert data["status"] == "PENDING"
    assert data.get("assigned_housekeeper_id") is None


def test_manual_dispatch_with_no_eligible_housekeeper_returns_err_no_eligible(api):
    """PRD §3.3: "if the candidate pool is empty, the task stays
    PENDING and a manual dispatch attempt returns
    ERR_NO_ELIGIBLE_HOUSEKEEPER."
    """
    room = create_room()
    # Off-shift housekeeper in zone (so create succeeds without
    # auto-dispatch); attempt manual dispatch:
    create_housekeeper(
        assigned_zone=room["zone_code"], on_shift=False,
    )
    res = api.create_cleaning_task(
        create_cleaning_task_payload(
            room_id=room["id"], task_source="SCHEDULED",
        ),
        TEST_USERS["supervisor_headers"],
    )
    task = validate_success(res, expected_status=201)
    assert task["status"] == "PENDING"
    res = api.dispatch_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_HOUSEKEEPER.value)


def test_auto_dispatch_picks_lowest_provisional_workload(api):
    """PRD §3.3: "The selector applied at every dispatch picks the
    on-shift housekeeper whose assigned_zone equals the room's
    zone_code and whose provisional_workload_minutes is lowest."

    Setup: two on-shift housekeepers in the same zone. Assign a
    CHECK_OUT task to housekeeper A (so A has workload 40); then create
    a SCHEDULED task on the same room — the selector should pick B
    (workload 0) over A (workload 40).
    """
    # Unique zone isolates the dispatch pool from prior tests (PRD §3.3
    # scopes selection to same-zone housekeepers, so unique zone =
    # empty prior pool). Codes share a common suffix so A < B
    # lexicographically.
    import uuid as _uuid
    zone = unique_zone()
    sfx = _uuid.uuid4().hex[:6]
    room = create_room(zone_code=zone)
    hk_a = create_housekeeper_on_shift(
        assigned_zone=zone, employee_code=f"HK-A-aaaa-{sfx}",
    )
    hk_b = create_housekeeper_on_shift(
        assigned_zone=zone, employee_code=f"HK-B-bbbb-{sfx}",
    )
    # Auto-dispatched to whichever has lowest workload; ties broken by
    # employee_code ASC. Both at 0, "HK-A-aaaa" < "HK-B-bbbb" so first
    # task goes to A.
    task1 = create_cleaning_task(
        room_id=room["id"], task_source="CHECK_OUT",
    )
    assert task1["assigned_housekeeper_id"] == hk_a["id"]
    # Now A has 40 minutes; create a SCHEDULED task on the same room;
    # provisional workload selector should pick B (0) over A (40).
    task2 = create_cleaning_task(
        room_id=room["id"], task_source="SCHEDULED",
    )
    assert task2["assigned_housekeeper_id"] == hk_b["id"], (
        "Selector must prefer the housekeeper with the lower "
        "provisional_workload_minutes (B=0 over A=40)."
    )


def test_auto_dispatch_tie_break_by_employee_code_ascending(api):
    """PRD §3.3: "with ties broken by employee_code in ascending
    order."

    Two on-shift housekeepers with zero workload; the one with
    lexicographically smaller employee_code must be picked.
    """
    import uuid as _uuid
    zone = unique_zone()
    sfx = _uuid.uuid4().hex[:6]
    room = create_room(zone_code=zone)
    hk_lo = create_housekeeper_on_shift(
        assigned_zone=zone, employee_code=f"HK-AAA-001-{sfx}",
    )
    hk_hi = create_housekeeper_on_shift(
        assigned_zone=zone, employee_code=f"HK-ZZZ-999-{sfx}",
    )
    task = create_cleaning_task(
        room_id=room["id"], task_source="SCHEDULED",
    )
    assert task["assigned_housekeeper_id"] == hk_lo["id"], (
        "PRD §3.3: ties broken by employee_code ASC; "
        f"expected {hk_lo['employee_code']} to win over "
        f"{hk_hi['employee_code']}."
    )


def test_auto_dispatch_only_considers_same_zone(api):
    """PRD §3.3: "The selector applied at every dispatch picks the
    on-shift housekeeper whose assigned_zone equals the room's
    zone_code."

    A housekeeper in a different zone must not be selected; if no
    same-zone housekeeper is on shift the task remains PENDING.
    """
    # Unique zone for the room; a fresh distinct zone for the
    # off-zone housekeeper guarantees neither overlaps prior tests.
    room_zone = unique_zone(prefix="ROOMZ")
    hk_zone = unique_zone(prefix="HKZ")
    room = create_room(zone_code=room_zone)
    # Different zone:
    create_housekeeper_on_shift(
        assigned_zone=hk_zone,
    )
    res = api.create_cleaning_task(
        create_cleaning_task_payload(
            room_id=room["id"], task_source="SCHEDULED",
        ),
        TEST_USERS["supervisor_headers"],
    )
    task = validate_success(res, expected_status=201)
    assert task["status"] == "PENDING", (
        "Different-zone housekeeper must not be picked by the selector."
    )
    assert task.get("assigned_housekeeper_id") is None


def test_manual_dispatch_succeeds_after_shift_toggle(api):
    """PRD §3.3: "if no eligible housekeeper is on shift, the task
    remains PENDING until a supervisor triggers a manual dispatch."

    After toggling the housekeeper ON_SHIFT, manual dispatch must
    succeed (status → ASSIGNED).
    """
    room = create_room()
    hk = create_housekeeper(
        assigned_zone=room["zone_code"], on_shift=False,
    )
    res = api.create_cleaning_task(
        create_cleaning_task_payload(
            room_id=room["id"], task_source="SCHEDULED",
        ),
        TEST_USERS["supervisor_headers"],
    )
    task = validate_success(res, expected_status=201)
    assert task["status"] == "PENDING"
    # Bring housekeeper on shift, then manual dispatch.
    api.toggle_housekeeper_shift(
        hk["id"], toggle_shift_payload("ON_SHIFT"),
        TEST_USERS["supervisor_headers"],
    )
    res = api.dispatch_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "ASSIGNED"
    assert data["assigned_housekeeper_id"] == hk["id"]
