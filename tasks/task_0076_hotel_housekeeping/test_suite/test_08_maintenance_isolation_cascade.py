"""Maintenance ticket lifecycle, isolation cascade, and re-clean
auto-creation (PRD §3.7).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_maintenance_ticket,
    create_maintenance_ticket_payload,
    dispatch_maintenance_ticket_payload,
    engineering_update_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_maintenance_ticket,
    create_room,
    dispatch_ticket,
    drive_ticket_through_repair,
    setup_room_and_housekeeper,
    setup_room_hk_task,
    setup_room_isolated_by_ticket,
)


# ===========================================================================
# Reporting and isolates_room derivation (PRD §3.7)
# ===========================================================================
@pytest.mark.parametrize("severity,expected_isolates", [
    ("LOW", False),
    ("MEDIUM", False),
    ("HIGH", True),
    ("CRITICAL", True),
])
def test_isolates_room_derived_from_severity(api, severity, expected_isolates):
    """PRD §3.7: "the server computes isolates_room as true exactly when
    severity is one of HIGH or CRITICAL — that single field is the
    gate to the isolation cascade."
    """
    room, hk = setup_room_and_housekeeper()
    ticket = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity=severity,
    )
    assert_maintenance_ticket(ticket)
    assert ticket["isolates_room"] is expected_isolates
    assert ticket["status"] == "REPORTED"


# ===========================================================================
# Dispatch & isolation (PRD §3.7)
# ===========================================================================
def test_dispatch_low_severity_does_not_isolate_room(api):
    """PRD §3.7: "If the ticket isolates the room, that dispatch
    atomically forces the parent room into OUT_OF_ORDER."

    Claim (contrapositive): a LOW-severity ticket has isolates_room
    false, so dispatching it leaves room.status unchanged.
    """
    room, hk = setup_room_and_housekeeper()  # VACANT_CLEAN
    ticket = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="LOW",
    )
    assert ticket["isolates_room"] is False
    dispatched = dispatch_ticket(ticket["id"])
    assert dispatched["status"] == "DISPATCHED"
    # Room should still be VACANT_CLEAN.
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    assert final["status"] == "VACANT_CLEAN"
    assert final.get("out_of_order_ticket_id") is None


def test_dispatch_critical_severity_forces_room_out_of_order(api):
    """PRD §3.7: "If the ticket isolates the room, that dispatch
    atomically forces the parent room into OUT_OF_ORDER from whichever
    non-isolating status it was in (VACANT_CLEAN, VACANT_DIRTY,
    OCCUPIED_CLEAN, OCCUPIED_DIRTY, or INSPECTED), sets
    Room.out_of_order_ticket_id to the ticket's id."
    """
    room, hk = setup_room_and_housekeeper()  # VACANT_CLEAN
    ticket = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    dispatched = dispatch_ticket(ticket["id"])
    assert dispatched["status"] == "DISPATCHED"
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    assert final["status"] == "OUT_OF_ORDER"
    assert final["out_of_order_ticket_id"] == ticket["id"]


def test_isolation_cancels_open_cleaning_tasks_on_room(api):
    """PRD §3.7: "cascades every cleaning task on that room whose
    status is PENDING, ASSIGNED, ACCEPTED, or IN_PROGRESS to
    CANCELLED."
    """
    room, hk, task = setup_room_hk_task(
        task_source="CHECK_OUT",
    )
    assert task["status"] == "ASSIGNED"
    ticket = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    dispatch_ticket(ticket["id"])
    # The previously-ASSIGNED task must now be CANCELLED.
    res = api.get_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    final = validate_success(res)
    assert final["status"] == "CANCELLED", (
        "PRD §3.7 cascade: open cleaning tasks must be CANCELLED on "
        "room isolation."
    )


def test_isolation_recomputes_housekeeper_provisional_workload(api):
    """PRD §3.7: "The cascade depth — dispatch isolates the room, the
    room flips, the open cleaning tasks cancel, and every affected
    housekeeper's provisional_workload_minutes is recomputed — is
    intentional."
    """
    room, hk, task = setup_room_hk_task(task_source="CHECK_OUT")
    # Estimated minutes for STANDARD + CHECK_OUT = 40.
    assert task["estimated_minutes"] == 40
    res = api.get_housekeeper(
        hk["id"], TEST_USERS["supervisor_headers"],
    )
    before = validate_success(res)
    assert before["provisional_workload_minutes"] == 40
    ticket = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    dispatch_ticket(ticket["id"])
    res = api.get_housekeeper(
        hk["id"], TEST_USERS["supervisor_headers"],
    )
    after = validate_success(res)
    assert after["provisional_workload_minutes"] == 0, (
        "PRD §3.7 cascade: provisional_workload_minutes must be "
        "recomputed after cleaning tasks are cancelled by the cascade."
    )


def test_dispatch_isolating_ticket_on_already_isolated_room_rejected(api):
    """PRD §3.7: "the room must be free of any prior isolation:
    dispatching an isolating ticket against a room whose
    out_of_order_ticket_id is already set to a different ticket is
    rejected with ERR_ROOM_ALREADY_ISOLATED."
    """
    room, hk, m1 = setup_room_isolated_by_ticket(severity="CRITICAL")
    # Create and try to dispatch a SECOND isolating ticket on the same
    # room.
    m2 = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    res = api.dispatch_maintenance_ticket(
        m2["id"],
        dispatch_maintenance_ticket_payload("eng-2"),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ROOM_ALREADY_ISOLATED.value)


def test_dispatch_already_dispatched_ticket_returns_ticket_not_reported(api):
    """PRD §2.6: "state-machine eligibility for the requested
    transition (raising the family of state errors enumerated in §5,
    such as ... ERR_TICKET_NOT_REPORTED ...); then the business-safety
    checks (manual-correction target validity and isolating-ticket
    conflicts)."

    Claim: re-dispatch of a DISPATCHED ticket surfaces
    ERR_TICKET_NOT_REPORTED (state check fires before business_safety
    isolating-ticket check).
    """
    room, hk, m1 = setup_room_isolated_by_ticket(severity="CRITICAL")
    # m1 is now DISPATCHED. Re-dispatching it must surface the state
    # error.
    res = api.dispatch_maintenance_ticket(
        m1["id"],
        dispatch_maintenance_ticket_payload("eng-1b"),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_REPORTED.value)


# ===========================================================================
# Engineering progress and verify cascade (PRD §3.7)
# ===========================================================================
def test_engineering_update_in_repair_advances_dispatched(api):
    """PRD §3.7: "an event with new_status of IN_REPAIR advances a
    DISPATCHED ticket."
    """
    room, hk, ticket = setup_room_isolated_by_ticket()  # DISPATCHED
    res = api.engineering_update_event(
        engineering_update_payload(ticket["id"], "IN_REPAIR"),
        TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "IN_REPAIR"


def test_engineering_update_repair_completed_sets_completed_at(api):
    """PRD §3.7: "an event with new_status of REPAIR_COMPLETED
    advances an IN_REPAIR ticket and records completed_at."
    """
    room, hk, ticket = setup_room_isolated_by_ticket()
    drive_ticket_through_repair(ticket["id"])
    res = api.get_maintenance_ticket(
        ticket["id"], TEST_USERS["supervisor_headers"],
    )
    final = validate_success(res)
    assert final["status"] == "REPAIR_COMPLETED"
    assert final["completed_at"] is not None


def test_verify_cascades_room_back_to_vacant_dirty_and_creates_reclean(api):
    """PRD §3.7: "verification advances the ticket to VERIFIED, sets
    verified_at, appends an AuditLog, and — when the ticket had
    isolated the room — cascades the room from OUT_OF_ORDER back to
    VACANT_DIRTY, clears Room.out_of_order_ticket_id, auto-creates a
    re-clean cleaning task whose task_source is SCHEDULED and whose
    expedite_flag is true, writes that new task's id into
    re_clean_task_id, and appends a RoomStatusEvent whose
    change_reason is MAINTENANCE_VERIFY."
    """
    room, hk, ticket = setup_room_isolated_by_ticket(severity="CRITICAL")
    drive_ticket_through_repair(ticket["id"])
    res = api.verify_maintenance_ticket(
        ticket["id"], TEST_USERS["supervisor_headers"],
    )
    verified = validate_success(res)
    assert verified["status"] == "VERIFIED"
    assert verified["verified_at"] is not None
    assert verified["re_clean_task_id"] is not None
    # Room must now be VACANT_DIRTY with out_of_order cleared.
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final_room = validate_success(res)
    assert final_room["status"] == "VACANT_DIRTY"
    assert final_room["out_of_order_ticket_id"] is None
    # Re-clean task: SCHEDULED + expedite=true.
    res = api.get_cleaning_task(
        verified["re_clean_task_id"], TEST_USERS["supervisor_headers"],
    )
    rc = validate_success(res)
    assert rc["task_source"] == "SCHEDULED"
    assert rc["expedite_flag"] is True


def test_reject_reported_ticket_terminal(api):
    """PRD §3.7: "Alternatively, a supervisor rejects a reported
    ticket, advancing it to REJECTED and appending an AuditLog;
    rejection is terminal alongside VERIFIED."
    """
    room, hk = setup_room_and_housekeeper()
    ticket = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="LOW",
    )
    res = api.reject_maintenance_ticket(
        ticket["id"], TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "REJECTED"
