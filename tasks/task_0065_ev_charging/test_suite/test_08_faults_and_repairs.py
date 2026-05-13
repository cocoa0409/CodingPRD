"""Fault report and repair-ticket lifecycle (PRD §3.5).

Includes the isolation cascade (fault ISOLATED → pile FAULT →
reservation CANCELLED / session ABORTED) and the cyclic
AWAITING_ACCEPTANCE ↔ IN_REPAIR loop.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    accept_repair_ticket,
    assert_fault_report,
    assert_repair_ticket,
    begin_repair_ticket,
    complete_repair_ticket,
    create_fault_report,
    create_repair_ticket,
    dispatch_repair_ticket,
    find_audit_logs,
    get_fault_report,
    get_member,
    get_pile,
    get_reservation,
    get_session,
    isolate_fault_report,
    list_audit_logs,
    reject_repair_ticket,
    setup_charging_session,
    setup_operator_station_shelved_pile,
    setup_repair_awaiting_acceptance,
    setup_repair_closed,
    setup_reservation_held,
    validate_error,
    validate_success,
    PO, FT,
    make_field_technician_headers,
    make_station_owner_headers,
)


# ===========================================================================
# Fault report creation
# ===========================================================================
class TestFaultReportCreation:
    """PRD §3.5: 'A FaultReport against a pile is opened by an EVDriver
    ... by a FieldTechnician or auto-detection system ... or by a
    PlatformOperator.'"""

    def test_create_auto_detect_fault_report_starts_open(self, api):
        """PRD §3.5: 'The initial status is OPEN.'"""
        ctx = setup_operator_station_shelved_pile()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"],
            reporter_kind="AUTO_DETECT",
            severity="MAJOR",
        )
        assert_fault_report(fault)
        assert fault["status"] == "OPEN"
        assert fault["reporter_kind"] == "AUTO_DETECT"
        assert fault["severity"] == "MAJOR"

    def test_critical_fault_auto_isolates_on_creation(self, api):
        """PRD §3.5: 'A CRITICAL fault auto-isolates on creation.'"""
        ctx = setup_operator_station_shelved_pile()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"],
            reporter_kind="AUTO_DETECT",
            severity="CRITICAL",
        )
        assert fault["status"] == "ISOLATED"
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "FAULT"

    def test_fault_report_writes_fault_event_audit_log(self, api):
        """PRD §3.5: 'Any fault report write — whether on creation or on
        a later isolation — appends an AuditLog row with event_kind
        FAULT_EVENT.'"""
        ctx = setup_operator_station_shelved_pile()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"], reporter_kind="AUTO_DETECT",
            severity="MAJOR",
        )
        logs = list_audit_logs(
            event_kind="FAULT_EVENT", entity_kind="FaultReport",
            entity_id=fault["id"],
        )
        assert len(logs) >= 1


# ===========================================================================
# Manual isolate cascade
# ===========================================================================
class TestIsolateCascade:
    """PRD §3.5: 'The isolation cascade is the system's most
    consequential side-effect chain: the pile's operational_state moves
    to FAULT ... every HELD reservation on the pile is moved to
    CANCELLED (no strike — this is the compensating semantics
    distinguishing fault-driven cancellations from normal cancellations
    and from sweep-driven expiries); every WAITING queue entry at the
    station has its position re-ranked but the entries themselves are
    not removed; any in-flight session in CHARGING on this pile
    transitions to ABORTED.'"""

    def test_isolate_moves_pile_to_fault(self, api):
        ctx = setup_operator_station_shelved_pile()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"], reporter_kind="AUTO_DETECT",
            severity="MAJOR",
        )
        isolate_fault_report(fault_id=fault["id"])
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "FAULT"

    def test_isolate_cancels_held_reservation_without_strike(self, api):
        ctx = setup_reservation_held()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"], reporter_kind="AUTO_DETECT",
            severity="MAJOR",
        )
        isolate_fault_report(fault_id=fault["id"])
        r = get_reservation(ctx["reservation"]["id"])
        assert r["status"] == "CANCELLED"
        # PRD §3.5: 'no strike — this is the compensating semantics
        # distinguishing fault-driven cancellations.'
        m = get_member(ctx["member"]["id"])
        assert m["no_show_strikes"] == 0

    def test_isolate_aborts_in_flight_charging_session(self, api):
        """PRD §3.5: 'any in-flight session in CHARGING on this pile
        transitions to ABORTED.'"""
        ctx = setup_charging_session()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"], reporter_kind="AUTO_DETECT",
            severity="MAJOR",
        )
        isolate_fault_report(fault_id=fault["id"])
        s = get_session(ctx["session"]["id"])
        assert s["status"] == "ABORTED"
        # PRD §3.4: ABORTED branch must keep total_cents at zero.
        assert s["total_cents"] == 0


# ===========================================================================
# Repair ticket lifecycle
# ===========================================================================
class TestRepairTicketLinearWalk:
    """PRD §3.5: 'The normal walk is OPEN → DISPATCHED → IN_REPAIR →
    AWAITING_ACCEPTANCE → CLOSED.'"""

    def test_full_walk_to_closed_resolves_fault_and_resumes_pile(self, api):
        """PRD §3.5: 'Acceptance ... moves the ticket from
        AWAITING_ACCEPTANCE to CLOSED, which cascades the parent fault
        report from ISOLATED to RESOLVED, which in turn moves the
        pile's operational_state from FAULT back to IDLE.'"""
        ctx = setup_repair_closed()
        # Fault was MAJOR (not auto-isolated), but dispatch cascaded
        # the parent to ISOLATED. After acceptance, fault must be
        # RESOLVED and pile must be IDLE.
        fault = get_fault_report(ctx["fault"]["id"])
        assert fault["status"] == "RESOLVED"
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "IDLE"

    def test_begin_by_unassigned_technician_rejected(self, api):
        """PRD §3.5: 'Begin, invoked by a FieldTechnician, moves the
        ticket from DISPATCHED to IN_REPAIR provided
        assigned_technician_id matches X-User-ID.'"""
        ctx = setup_operator_station_shelved_pile()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"], reporter_kind="AUTO_DETECT",
            severity="MAJOR",
        )
        ticket = create_repair_ticket(
            fault_id=fault["id"],
            assigned_technician_id="field-technician-001",
        )
        dispatch_repair_ticket(ticket_id=ticket["id"])
        # Use a different technician id.
        res = api.begin_repair_ticket(
            ticket["id"],
            make_field_technician_headers("field-technician-999"),
        )
        # FORBIDDEN by ownership-style guard. PRD §2.1 says technicians
        # 'may only begin or complete a ticket whose
        # assigned_technician_id equals their own X-User-ID.' We assert
        # the standard 403 ERR_FORBIDDEN.
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Reject loop (AWAITING_ACCEPTANCE → IN_REPAIR)
# ===========================================================================
class TestRepairTicketRejectLoop:
    """PRD §3.5: 'Rejection by the same StationOwner moves the ticket
    back from AWAITING_ACCEPTANCE to IN_REPAIR, cycling the work item
    for the technician.'"""

    def test_reject_returns_to_in_repair(self, api):
        ctx = setup_repair_awaiting_acceptance()
        ticket = reject_repair_ticket(
            ticket_id=ctx["ticket"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert ticket["status"] == "IN_REPAIR"

    def test_complete_then_reject_then_complete_then_accept_finally_closes(
        self, api,
    ):
        """PRD §3.5: the cyclic edge admits multiple
        IN_REPAIR ↔ AWAITING_ACCEPTANCE laps before CLOSED."""
        ctx = setup_repair_awaiting_acceptance()
        # First reject — back to IN_REPAIR.
        ticket = reject_repair_ticket(
            ticket_id=ctx["ticket"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert ticket["status"] == "IN_REPAIR"
        # Re-complete.
        ticket = complete_repair_ticket(
            ticket_id=ticket["id"],
            technician_user_id=ctx["technician_user_id"],
            repair_notes="retry",
        )
        assert ticket["status"] == "AWAITING_ACCEPTANCE"
        # Reject again.
        ticket = reject_repair_ticket(
            ticket_id=ticket["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert ticket["status"] == "IN_REPAIR"
        # Complete one more time.
        ticket = complete_repair_ticket(
            ticket_id=ticket["id"],
            technician_user_id=ctx["technician_user_id"],
            repair_notes="final",
        )
        # Accept.
        ticket = accept_repair_ticket(
            ticket_id=ticket["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert ticket["status"] == "CLOSED"
        fault = get_fault_report(ctx["fault"]["id"])
        assert fault["status"] == "RESOLVED"


# ===========================================================================
# Accept ownership guard
# ===========================================================================
class TestRepairTicketAcceptOwnership:
    """PRD §3.5 + §2.1: 'Acceptance by a StationOwner (whose X-User-ID
    matches the parent station's station_owner_id).'"""

    def test_accept_by_non_owner_rejected(self, api):
        ctx = setup_repair_awaiting_acceptance()
        # Use a wrong StationOwner identity.
        res = api.accept_repair_ticket(
            ctx["ticket"]["id"],
            make_station_owner_headers("not-the-owner"),
        )
        # PRD §2.1: 'a StationOwner ... may add piles ... and accept or
        # reject repair tickets — but only at stations whose
        # station_owner_id matches X-User-ID.' Non-matching → forbidden.
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
