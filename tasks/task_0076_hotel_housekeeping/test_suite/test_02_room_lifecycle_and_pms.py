"""Room creation, initial state derivation, PMS sync workflow, manual
status correction, and the discrepancy invariant.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_room,
    assert_room_discrepancy_invariant,
    assert_room_status_event,
    correct_room_status_payload,
    create_room_payload,
    pms_sync_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_room,
    list_room_status_events,
    setup_room_and_housekeeper,
    setup_room_isolated_by_ticket,
)


# ===========================================================================
# Room creation and initial state (PRD §3.1)
# ===========================================================================
def test_create_room_default_pms_occupancy_starts_vacant_clean(api):
    """PRD §3.1: "When pms_occupancy is supplied as VACANT (or omitted,
    in which case it defaults to VACANT), the new room enters
    VACANT_CLEAN."
    """
    res = api.create_room(
        create_room_payload(), TEST_USERS["frontdesk_headers"],
    )
    data = validate_success(res, expected_status=201)
    assert_room(data)
    assert data["status"] == "VACANT_CLEAN"
    assert data["pms_occupancy"] == "VACANT"


def test_create_room_occupied_starts_occupied_dirty(api):
    """PRD §3.1: "when it is supplied as OCCUPIED, the room enters
    OCCUPIED_DIRTY to reflect that an occupied bed has not yet been
    turned."
    """
    payload = create_room_payload(pms_occupancy="OCCUPIED")
    res = api.create_room(payload, TEST_USERS["frontdesk_headers"])
    data = validate_success(res, expected_status=201)
    assert data["pms_occupancy"] == "OCCUPIED"
    assert data["status"] == "OCCUPIED_DIRTY"


def test_initial_room_status_event_recorded(api):
    """PRD §3.1: "Every new room receives an initial RoomStatusEvent
    whose change_reason is INITIAL and whose previous_status is null."
    """
    room = create_room()
    events = list_room_status_events(room["id"])
    initial_events = [e for e in events if e["change_reason"] == "INITIAL"]
    assert len(initial_events) >= 1
    init = initial_events[0]
    assert_room_status_event(init)
    assert init["previous_status"] is None
    assert init["new_status"] == room["status"]


def test_room_last_cleaned_at_initially_null(api):
    """PRD §3.1: "last_cleaned_at is null until the first time the room
    is inspected with a passing outcome."
    """
    room = create_room()
    assert room.get("last_cleaned_at") is None


def test_room_out_of_order_ticket_id_initially_null(api):
    """PRD §3.1 (entity model): out_of_order_ticket_id is the active
    MaintenanceTicket id that put the room OUT_OF_ORDER, "null
    otherwise". A freshly created room has no ticket.
    """
    room = create_room()
    assert room.get("out_of_order_ticket_id") is None


# ===========================================================================
# PMS sync (PRD §3.2)
# ===========================================================================
def test_pms_check_in_advances_vacant_clean_to_occupied_clean(api):
    """PRD §3.2: "A CHECK_IN event whose pms_occupancy transitions to
    OCCUPIED advances a VACANT_CLEAN room to OCCUPIED_CLEAN."
    """
    room = create_room()  # VACANT_CLEAN
    assert room["status"] == "VACANT_CLEAN"
    payload = pms_sync_payload(
        room_number=room["room_number"],
        event_type="CHECK_IN",
        pms_occupancy="OCCUPIED",
    )
    res = api.pms_sync_event(
        payload, TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["pms_occupancy"] == "OCCUPIED"
    assert data["status"] == "OCCUPIED_CLEAN"


def test_pms_check_out_flips_occupied_dirty_to_vacant_dirty(api):
    """PRD §3.2: "A CHECK_OUT event flips an OCCUPIED_DIRTY room to
    VACANT_DIRTY and atomically auto-creates a cleaning task with
    task_source equal to CHECK_OUT and expedite_flag equal to false."
    """
    room = create_room(pms_occupancy="OCCUPIED")  # OCCUPIED_DIRTY
    assert room["status"] == "OCCUPIED_DIRTY"
    payload = pms_sync_payload(
        room_number=room["room_number"],
        event_type="CHECK_OUT",
        pms_occupancy="VACANT",
    )
    res = api.pms_sync_event(
        payload, TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "VACANT_DIRTY"
    # Verify auto-created cleaning task on this room.
    task_list = api.list_cleaning_tasks(
        TEST_USERS["supervisor_headers"],
        params={"room_id": room["id"]},
    )
    tasks, _ = validate_paginated(task_list)
    checkout_tasks = [
        t for t in tasks
        if t["task_source"] == "CHECK_OUT"
        and t.get("expedite_flag") is False
    ]
    assert len(checkout_tasks) >= 1, (
        "PRD §3.2: A CHECK_OUT PMS event must auto-create a "
        "task_source=CHECK_OUT, expedite_flag=false CleaningTask."
    )


def test_pms_daily_turn_flips_occupied_clean_to_occupied_dirty(api):
    """PRD §3.2: "A DAILY_TURN event flips an OCCUPIED_CLEAN room to
    OCCUPIED_DIRTY to seed a stayover cleaning."
    """
    room = create_room()  # VACANT_CLEAN
    # Walk to OCCUPIED_CLEAN
    api.pms_sync_event(
        pms_sync_payload(
            room["room_number"], "CHECK_IN", "OCCUPIED",
        ),
        TEST_USERS["system_integration_headers"],
    )
    res = api.pms_sync_event(
        pms_sync_payload(
            room["room_number"], "DAILY_TURN", "OCCUPIED",
        ),
        TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "OCCUPIED_DIRTY"


# ===========================================================================
# Discrepancy flag (PRD §2.10)
# ===========================================================================
def test_discrepancy_flag_false_when_pms_and_status_agree(api):
    """PRD §2.10: "in every other combination the flag is false."

    Fresh VACANT_CLEAN + pms_occupancy=VACANT → no discrepancy.
    """
    room = create_room()
    assert room["pms_occupancy"] == "VACANT"
    assert room["status"] == "VACANT_CLEAN"
    assert_room_discrepancy_invariant(room)
    assert room["discrepancy_flag"] is False


def test_discrepancy_flag_true_when_pms_occupied_but_status_vacant(api):
    """PRD §2.10: "a room whose pms_occupancy is OCCUPIED or DUE_OUT
    while its status is none of OCCUPIED_CLEAN, OCCUPIED_DIRTY, or
    INSPECTED is flagged."

    Use OCCUPANCY_SYNC to drive pms_occupancy=OCCUPIED on a
    VACANT_CLEAN room — PRD §3.2 says OCCUPANCY_SYNC "refreshes
    pms_occupancy and pms_synced_at without driving the housekeeping
    state machine, but still recomputes discrepancy_flag."
    """
    room = create_room()  # VACANT_CLEAN, VACANT
    res = api.pms_sync_event(
        pms_sync_payload(
            room["room_number"], "OCCUPANCY_SYNC", "OCCUPIED",
        ),
        TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["pms_occupancy"] == "OCCUPIED"
    assert data["status"] == "VACANT_CLEAN", (
        "OCCUPANCY_SYNC must not drive the housekeeping state machine."
    )
    assert_room_discrepancy_invariant(data)
    assert data["discrepancy_flag"] is True


# ===========================================================================
# Manual status correction (PRD §3.10)
# ===========================================================================
def test_manual_correction_valid_transition_succeeds(api):
    """PRD §3.10: "A successful correction appends a RoomStatusEvent
    whose change_reason is MANUAL_CORRECTION, whose correction_note is
    preserved verbatim, and whose actor_id is the supervisor's
    X-User-ID."
    """
    room = create_room()  # VACANT_CLEAN
    payload = correct_room_status_payload(
        new_status="VACANT_DIRTY",
        correction_note="floor needs re-mopping after spill",
    )
    res = api.correct_room_status(
        room["id"], payload, TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "VACANT_DIRTY"

    events = list_room_status_events(room["id"])
    mc_events = [
        e for e in events if e["change_reason"] == "MANUAL_CORRECTION"
    ]
    assert len(mc_events) >= 1
    mc = mc_events[-1]
    assert mc["correction_note"] == "floor needs re-mopping after spill"
    # PRD §3.10: "whose actor_id is the supervisor's X-User-ID"
    assert mc["actor_id"] == TEST_USERS["supervisor_headers"][
        "X-User-ID"
    ]


def test_manual_correction_to_same_status_rejected(api):
    """PRD §3.10: "new_status must differ from the current status; any
    of these violations is rejected with
    ERR_MANUAL_CORRECTION_INVALID_TARGET."
    """
    room = create_room()  # VACANT_CLEAN
    payload = correct_room_status_payload(
        new_status="VACANT_CLEAN", correction_note="no-op",
    )
    res = api.correct_room_status(
        room["id"], payload, TEST_USERS["supervisor_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_MANUAL_CORRECTION_INVALID_TARGET.value,
    )


def test_manual_correction_to_out_of_order_rejected(api):
    """PRD §3.10: "the supplied new_status must not be OUT_OF_ORDER...
    any of these violations is rejected with
    ERR_MANUAL_CORRECTION_INVALID_TARGET."
    """
    room = create_room()
    payload = correct_room_status_payload(
        new_status="OUT_OF_ORDER",
        correction_note="attempt to enter OOO via manual correction",
    )
    res = api.correct_room_status(
        room["id"], payload, TEST_USERS["supervisor_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_MANUAL_CORRECTION_INVALID_TARGET.value,
    )


def test_manual_correction_from_out_of_order_rejected(api):
    """PRD §3.10: "the room's current status must not be OUT_OF_ORDER
    ... any of these violations is rejected with
    ERR_MANUAL_CORRECTION_INVALID_TARGET."
    """
    room, _hk, _ticket = setup_room_isolated_by_ticket()
    payload = correct_room_status_payload(
        new_status="VACANT_DIRTY",
        correction_note="attempt to exit OOO via manual correction",
    )
    res = api.correct_room_status(
        room["id"], payload, TEST_USERS["supervisor_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_MANUAL_CORRECTION_INVALID_TARGET.value,
    )


def test_manual_correction_appends_audit_log(api):
    """PRD §3.10: "an AuditLog entry with action_type MANUAL_CORRECTION
    is appended."
    """
    from test_helpers.fixtures import list_audit_entries_for_subject
    room = create_room()
    api.correct_room_status(
        room["id"],
        correct_room_status_payload(
            "VACANT_DIRTY", "supervisor manual correction note",
        ),
        TEST_USERS["supervisor_headers"],
    )
    audit = list_audit_entries_for_subject(
        room["id"], action_type="MANUAL_CORRECTION",
    )
    assert len(audit) >= 1, (
        "PRD §3.10: every manual correction must append an AuditLog "
        "entry with action_type MANUAL_CORRECTION."
    )
