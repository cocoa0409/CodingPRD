"""CleaningTask lifecycle: accept, start, submit, reassign, terminal
errors (PRD §3.3, §3.4).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cleaning_task,
    make_housekeeper_headers,
    reassign_cleaning_task_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    accept_task,
    advance_clock,
    create_housekeeper,
    create_housekeeper_on_shift,
    drive_task_to_state,
    setup_room_and_housekeeper,
    setup_room_hk_task,
    setup_task_in_state,
)


# ===========================================================================
# Estimated duration formula (PRD §3.4)
# ===========================================================================
@pytest.mark.parametrize("room_type,task_source,expected", [
    ("STANDARD",     "CHECK_OUT", 25 + 15),
    ("STANDARD",     "STAYOVER",  25 + 0),
    ("STANDARD",     "SCHEDULED", 25 + 10),
    ("SUITE",        "CHECK_OUT", 45 + 15),
    ("SUITE",        "STAYOVER",  45 + 0),
    ("SUITE",        "SCHEDULED", 45 + 10),
    ("PRESIDENTIAL", "CHECK_OUT", 75 + 15),
    ("PRESIDENTIAL", "STAYOVER",  75 + 0),
    ("PRESIDENTIAL", "SCHEDULED", 75 + 10),
])
def test_estimated_minutes_formula(api, room_type, task_source, expected):
    """PRD §3.4: "A cleaning task's estimated_minutes is the base
    duration for the room's room_type plus an overhead that depends on
    the task_source. Base durations are 25 minutes for STANDARD, 45
    minutes for SUITE, and 75 minutes for PRESIDENTIAL. Overheads are
    15 minutes for a CHECK_OUT cleaning, 0 minutes for a STAYOVER, and
    10 minutes for a SCHEDULED task."
    """
    # For STAYOVER we need an OCCUPIED_CLEAN room — use OCCUPIED
    # pms_occupancy so the room is OCCUPIED_DIRTY (acceptable) and the
    # task creates without state errors.
    pms_occ = "OCCUPIED" if task_source == "STAYOVER" else None
    room, hk, task = setup_room_hk_task(
        room_type=room_type, task_source=task_source,
        pms_occupancy=pms_occ,
    )
    assert task["estimated_minutes"] == expected, (
        f"{room_type} + {task_source}: expected {expected} minutes, "
        f"got {task['estimated_minutes']}"
    )


# ===========================================================================
# accept / start / submit flow (PRD §3.3)
# ===========================================================================
def test_accept_by_assignee_succeeds_and_sets_accepted_at(api):
    """PRD §3.3: "From ASSIGNED, the assignee accepts the task (writing
    accepted_at), advancing it to ACCEPTED."
    """
    room, hk, task = setup_room_hk_task()
    res = api.accept_cleaning_task(
        task["id"], make_housekeeper_headers(hk["id"]),
    )
    data = validate_success(res)
    assert data["status"] == "ACCEPTED"
    assert data["accepted_at"] is not None


def test_accept_by_non_assignee_rejected(api):
    """PRD §3.3: "Acceptance, starting, and submission must all be
    invoked by the assignee — when X-User-ID does not match
    assigned_housekeeper_id, the request is rejected with
    ERR_NOT_TASK_ASSIGNEE."
    """
    room, hk_a, task = setup_room_hk_task()
    # Different on-shift housekeeper in same zone:
    hk_b = create_housekeeper_on_shift(assigned_zone=room["zone_code"])
    res = api.accept_cleaning_task(
        task["id"], make_housekeeper_headers(hk_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NOT_TASK_ASSIGNEE.value)


def test_start_from_accepted_sets_started_at(api):
    """PRD §3.3: "From ACCEPTED, the assignee starting the room
    transitions the task to IN_PROGRESS and records started_at."
    """
    room, hk, task = setup_room_hk_task()
    accept_task(task["id"], hk["id"])
    res = api.start_cleaning_task(
        task["id"], make_housekeeper_headers(hk["id"]),
    )
    data = validate_success(res)
    assert data["status"] == "IN_PROGRESS"
    assert data["started_at"] is not None


def test_submit_from_in_progress_sets_actual_minutes(api):
    """PRD §3.3: "From IN_PROGRESS, submitting for inspection
    transitions to SUBMITTED, sets submitted_at, and computes
    actual_minutes as the number of minutes between started_at and
    submitted_at rounded half-up to a whole minute."
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        clock_advance_minutes_between_start_submit=45,
    )
    assert task["status"] == "SUBMITTED"
    assert task["submitted_at"] is not None
    # 45 minutes ± rounding tolerance (we drove the clock by exactly 45)
    assert task["actual_minutes"] == 45


def test_start_from_assigned_without_accept_rejected(api):
    """PRD §2.6: "state-machine eligibility for the requested
    transition (raising the family of state errors enumerated in §5,
    such as ERR_TASK_NOT_ASSIGNED, ERR_TASK_NOT_ACCEPTED,
    ERR_TASK_NOT_IN_PROGRESS, ERR_TASK_NOT_SUBMITTED, ...)"

    PRD §3.3: "From ACCEPTED, the assignee starting the room
    transitions the task to IN_PROGRESS and records started_at."

    Claim: a /start invoked while task is ASSIGNED (the prior state)
    must surface ERR_TASK_NOT_ACCEPTED.
    """
    room, hk, task = setup_room_hk_task()
    assert task["status"] == "ASSIGNED"
    res = api.start_cleaning_task(
        task["id"], make_housekeeper_headers(hk["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TASK_NOT_ACCEPTED.value)


def test_submit_from_accepted_without_start_rejected(api):
    """PRD §2.6: "state-machine eligibility for the requested
    transition (raising the family of state errors enumerated in §5,
    such as ERR_TASK_NOT_ASSIGNED, ERR_TASK_NOT_ACCEPTED,
    ERR_TASK_NOT_IN_PROGRESS, ERR_TASK_NOT_SUBMITTED, ...)"

    PRD §3.3: "From IN_PROGRESS, submitting for inspection transitions
    to SUBMITTED, sets submitted_at, and computes actual_minutes."

    Claim: /submit on an ACCEPTED (not yet IN_PROGRESS) task surfaces
    ERR_TASK_NOT_IN_PROGRESS.
    """
    room, hk, task = setup_room_hk_task()
    accept_task(task["id"], hk["id"])
    res = api.submit_cleaning_task(
        task["id"], make_housekeeper_headers(hk["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TASK_NOT_IN_PROGRESS.value)


# ===========================================================================
# Reassign (PRD §3.3)
# ===========================================================================
def test_reassign_valid_target_resets_accepted_at_and_returns_to_assigned(api):
    """PRD §3.3: "the reassignment target must be on shift and must
    differ from the current assignee, otherwise ERR_INVALID_REASSIGN_TARGET
    is returned; on success the old and new assignees'
    provisional_workload_minutes are both recomputed, accepted_at is
    cleared back to null, and the task moves back to ASSIGNED."
    """
    room, hk_a, task = setup_room_hk_task()
    accept_task(task["id"], hk_a["id"])
    hk_b = create_housekeeper_on_shift(assigned_zone=room["zone_code"])
    res = api.reassign_cleaning_task(
        task["id"],
        reassign_cleaning_task_payload(hk_b["id"]),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "ASSIGNED"
    assert data["assigned_housekeeper_id"] == hk_b["id"]
    assert data["accepted_at"] is None, (
        "PRD §3.3: 'accepted_at is cleared back to null' on reassign."
    )


def test_reassign_to_self_rejected(api):
    """PRD §3.3: "the reassignment target must ... differ from the
    current assignee, otherwise ERR_INVALID_REASSIGN_TARGET is
    returned."
    """
    room, hk_a, task = setup_room_hk_task()
    res = api.reassign_cleaning_task(
        task["id"],
        reassign_cleaning_task_payload(hk_a["id"]),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REASSIGN_TARGET.value)


def test_reassign_to_off_shift_target_rejected(api):
    """PRD §3.3: "the reassignment target must be on shift ... otherwise
    ERR_INVALID_REASSIGN_TARGET is returned."
    """
    room, hk_a, task = setup_room_hk_task()
    hk_off = create_housekeeper(
        assigned_zone=room["zone_code"], on_shift=False,
    )
    res = api.reassign_cleaning_task(
        task["id"],
        reassign_cleaning_task_payload(hk_off["id"]),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REASSIGN_TARGET.value)


# ===========================================================================
# Terminal-state lockdown (PRD §3.3)
# ===========================================================================
def test_accept_terminal_completed_task_rejected(api):
    """PRD §3.3: "Touching a task in COMPLETED or CANCELLED with a
    state-changing request is rejected with ERR_TASK_TERMINAL."
    """
    room, hk, task = setup_task_in_state(
        target="COMPLETED",
        clock_advance_minutes_between_start_submit=20,
    )
    res = api.accept_cleaning_task(
        task["id"], make_housekeeper_headers(hk["id"]),
    )
    # Either ERR_TASK_TERMINAL (terminal-state guard) or
    # ERR_TASK_NOT_ASSIGNED is PRD-faithful — PRD §3.3 states the
    # terminal guard explicitly, and PRD §2.6 evaluates state before
    # terminal: the COMPLETED task is not ASSIGNED, so a server may
    # surface either id. PRD names the terminal id as the dedicated
    # error for the terminal case, so prefer it but accept both.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_TASK_TERMINAL.value,
        ApiErrorId.ERR_TASK_NOT_ASSIGNED.value,
    ])


def test_patch_cleaning_task_recomputes_priority_on_expedite_flag_change(api):
    """PRD §3.3: "A supervisor may also edit a pending or in-flight task
    to change its task_source, expedite_flag, or early_check_in_at,
    optionally passing version to lock the update; the server
    recomputes estimated_minutes and priority_score (and therefore
    priority_tier) on every such change."
    """
    room, hk, task = setup_room_hk_task(
        room_type="STANDARD",
        task_source="SCHEDULED",
        expedite_flag=False,
    )
    # Base 20 (SCHEDULED). With no bonuses → score 20 → NORMAL.
    assert task["priority_score"] == 20
    assert task["priority_tier"] == "NORMAL"
    res = api.patch_cleaning_task(
        task["id"], {"expedite_flag": True},
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    # 20 + 20 (expedite) = 40 → still NORMAL.
    assert data["expedite_flag"] is True
    assert data["priority_score"] == 40
    assert data["priority_tier"] == "NORMAL"
