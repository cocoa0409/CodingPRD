"""
Repair ticket lifecycle (PRD §3.8): OPEN → ASSIGNED → IN_PROGRESS ↔ ON_HOLD →
RESOLVED, the ASSIGNED → CANCELLED early exit, and the resolve cascade
(Device FAULTY → AVAILABLE, Slot FAULTY → EMPTY/OCCUPIED).
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    OPERATOR_HEADERS,
    advance_clock_to,
    api_client,
    assert_repair_ticket,
    heartbeat,
    make_user_headers,
    setup_borrow_environment,
    trigger_anomaly_cascade,
    validate_error,
    validate_success,
)


def _get_ticket_from_anomaly(api):
    """Helper: trigger anomaly cascade and return (env, ticket)."""
    env = trigger_anomaly_cascade(base_clock="2026-01-01T10:00:00Z")
    # The PRD does not provide a list endpoint; we don't know the ticket id
    # without a list. The implementation must return ticket id somehow —
    # tests rely on a list endpoint or on the ticket being discoverable.
    # PRD §4 only defines GET /repair-tickets/{id}. We rely on the
    # implementation auto-creating exactly one ticket reachable via the
    # OperatorTask.linked_repair_ticket_id field of the cascaded task —
    # which we discover via /operator-tasks/auto-assign.
    res = api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS)
    task = validate_success(res, 200)
    ticket_id = task["linked_repair_ticket_id"]
    assert ticket_id is not None, (
        "anomaly cascade must populate operator_task.linked_repair_ticket_id"
    )
    ticket = validate_success(
        api.get_repair_ticket(ticket_id, OPERATOR_HEADERS), 200
    )
    return env, task, ticket


# ---------------------------------------------------------------------------
# OPEN → ASSIGNED
# ---------------------------------------------------------------------------


def test_assign_open_ticket_transitions_to_assigned(api):
    """PRD §3.8: "An operator self-assigns to an open ticket; this transition
    writes assigned_operator_id to the calling operator's X-User-ID and
    advances the ticket from OPEN to ASSIGNED."
    """
    env, _, ticket = _get_ticket_from_anomaly(api)
    res = api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    assigned = validate_success(res, 200)
    assert_repair_ticket(assigned)
    assert assigned["status"] == "ASSIGNED"
    assert assigned["assigned_operator_id"] is not None


def test_assign_already_assigned_ticket_rejected(api):
    """PRD §2.7 priority 5: target-resource state — assign requires status
    OPEN; second assign call hits ERR_INVALID_STATE."""
    env, _, ticket = _get_ticket_from_anomaly(api)
    api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    res = api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# ASSIGNED → IN_PROGRESS auto-transition (PRD §3.8)
# ---------------------------------------------------------------------------


def test_first_hold_auto_advances_assigned_to_in_progress_then_on_hold(api):
    """PRD §3.8: "The ticket auto-transitions from ASSIGNED to IN_PROGRESS
    on the first hold or resolve call — clients need not transition
    explicitly."
    """
    env, _, ticket = _get_ticket_from_anomaly(api)
    api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    res = api.hold_ticket(ticket["id"], OPERATOR_HEADERS)
    held = validate_success(res, 200)
    # ON_HOLD reached after auto-transition through IN_PROGRESS.
    assert held["status"] == "ON_HOLD"


# ---------------------------------------------------------------------------
# IN_PROGRESS ↔ ON_HOLD cycle (PRD §3.8)
# ---------------------------------------------------------------------------


def test_resume_held_ticket_returns_to_in_progress(api):
    """PRD §3.8: "an in-progress ticket may be paused with the hold
    capability ... and a held ticket may be resumed (advancing it from
    ON_HOLD back to IN_PROGRESS)."
    """
    env, _, ticket = _get_ticket_from_anomaly(api)
    api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    api.hold_ticket(ticket["id"], OPERATOR_HEADERS)
    res = api.resume_ticket(ticket["id"], OPERATOR_HEADERS)
    resumed = validate_success(res, 200)
    assert resumed["status"] == "IN_PROGRESS"


def test_hold_resume_cycle_iterates_twice(api):
    """PRD §3.8: "these two transitions form a cycle that may iterate any
    number of times before resolution."
    """
    env, _, ticket = _get_ticket_from_anomaly(api)
    api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    # Iter 1
    a = validate_success(api.hold_ticket(ticket["id"], OPERATOR_HEADERS), 200)
    assert a["status"] == "ON_HOLD"
    b = validate_success(api.resume_ticket(ticket["id"], OPERATOR_HEADERS), 200)
    assert b["status"] == "IN_PROGRESS"
    # Iter 2
    c = validate_success(api.hold_ticket(ticket["id"], OPERATOR_HEADERS), 200)
    assert c["status"] == "ON_HOLD"
    d = validate_success(api.resume_ticket(ticket["id"], OPERATOR_HEADERS), 200)
    assert d["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# IN_PROGRESS → RESOLVED + cascade (PRD §3.8)
# ---------------------------------------------------------------------------


def test_resolve_in_progress_ticket_transitions_to_resolved(api):
    """PRD §3.8: "The resolve capability accepts an optional boolean cancel;
    when cancel is omitted or false the ticket advances to RESOLVED."
    """
    env, _, ticket = _get_ticket_from_anomaly(api)
    api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    api.hold_ticket(ticket["id"], OPERATOR_HEADERS)
    api.resume_ticket(ticket["id"], OPERATOR_HEADERS)
    res = api.resolve_ticket(ticket["id"], OPERATOR_HEADERS, {"cancel": False})
    resolved = validate_success(res, 200)
    assert resolved["status"] == "RESOLVED"


def test_resolve_advances_device_from_faulty_to_available(api):
    """PRD §3.8: "On resolution, when target_type is DEVICE the device's
    status advances from FAULTY to AVAILABLE."
    """
    env, _, ticket = _get_ticket_from_anomaly(api)
    api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    api.resolve_ticket(ticket["id"], OPERATOR_HEADERS, {"cancel": False})
    device_after = validate_success(
        api.get_device(env["device"]["id"], ADMIN_HEADERS), 200
    )
    assert device_after["status"] == "AVAILABLE"


def test_resolve_advances_slot_from_faulty(api):
    """PRD §3.8: "the slot housing the device transitions from FAULTY to
    either EMPTY or OCCUPIED depending on whether the slot's device_id is null."
    """
    env, _, ticket = _get_ticket_from_anomaly(api)
    api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    api.resolve_ticket(ticket["id"], OPERATOR_HEADERS, {"cancel": False})
    cab = validate_success(api.get_cabinet(env["cabinet"]["id"], ADMIN_HEADERS), 200)
    slot0 = next(s for s in cab["slots"] if s["slot_index"] == 0)
    # Slot.device_id was retained throughout the cascade per PRD §3.6 / §3.8.
    assert slot0["slot_status"] in {"EMPTY", "OCCUPIED"}


def test_resolve_with_cancel_true_from_assigned_cancels(api):
    """PRD §3.8: "when cancel is true and the ticket is currently in
    ASSIGNED the ticket advances to CANCELLED instead."
    """
    env, _, ticket = _get_ticket_from_anomaly(api)
    api.assign_ticket(ticket["id"], OPERATOR_HEADERS)
    res = api.resolve_ticket(ticket["id"], OPERATOR_HEADERS, {"cancel": True})
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Report fault (PRD §3.2)
# ---------------------------------------------------------------------------


def test_report_fault_by_holder_creates_open_ticket(api):
    """PRD §3.2: "The endpoint always creates a RepairTicket with target_type
    DEVICE, target_id equal to the device, source USER_REPORTED, and status
    OPEN."
    """
    env = setup_borrow_environment()
    from test_helpers import borrow_for

    rental = borrow_for(env["user"], env["cabinet"]["id"])
    res = api.report_fault(
        rental["device_id"],
        {"issue_code": "PHYSICAL_DAMAGE"},
        make_user_headers(env["user"]["id"]),
    )
    ticket = validate_success(res, 200)
    assert_repair_ticket(ticket)
    assert ticket["target_type"] == "DEVICE"
    assert ticket["target_id"] == rental["device_id"]
    assert ticket["source"] == "USER_REPORTED"
    assert ticket["status"] == "OPEN"


def test_report_fault_by_non_holder_forbidden(api):
    """PRD §3.2: "If no such rental exists, the report is rejected with
    ERR_FORBIDDEN."
    """
    env = setup_borrow_environment()
    from test_helpers import create_user

    other = create_user()
    res = api.report_fault(
        env["device"]["id"],
        {"issue_code": "PHYSICAL_DAMAGE"},
        make_user_headers(other["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_report_fault_keeps_borrowed_device_status(api):
    """PRD §3.2: "When the device is in BORROWED at the moment of the report,
    the device's status is left untouched."
    """
    env = setup_borrow_environment()
    from test_helpers import borrow_for

    rental = borrow_for(env["user"], env["cabinet"]["id"])
    api.report_fault(
        rental["device_id"],
        {"issue_code": "PHYSICAL_DAMAGE"},
        make_user_headers(env["user"]["id"]),
    )
    device_after = validate_success(
        api.get_device(rental["device_id"], ADMIN_HEADERS), 200
    )
    assert device_after["status"] == "BORROWED"
