"""Maintenance windows — create, accept, reject, system-driven cycles,
clock-driven cascades.

PRD §3.7 (Maintenance Windows), §3.6 (abnormal handover), §2.10
(concurrency on equipment status).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    accept_maintenance,
    accept_maintenance_window_payload,
    advance_clock_to,
    find_audit_events,
    get_equipment,
    get_reservation,
    list_audit_events,
    make_lab_owner_headers,
    make_reservation,
    reject_maintenance,
    reject_maintenance_window_payload,
    schedule_maintenance,
    setup_basic_scenario,
    setup_maintenance_cascade_scenario,
    validate_error,
    validate_success,
)


# ===========================================================================
# Ad-hoc maintenance flips equipment to MAINTENANCE (PRD §3.7)
# ===========================================================================
class TestAdHocMaintenanceImmediate:
    """PRD §3.7: 'When kind is AD_HOC and the window already encompasses
    the server clock — that is, start_at is less than or equal to the
    clock and the clock is strictly before end_at — the equipment
    transitions AVAILABLE → MAINTENANCE immediately, the window is
    recorded in status IN_PROGRESS'.
    """

    def test_ad_hoc_window_flips_equipment_to_maintenance(self, api):
        """PRD §3.7: 'the equipment transitions AVAILABLE → MAINTENANCE
        immediately, the window is recorded in status IN_PROGRESS'."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        window = schedule_maintenance(
            equipment=s["equipment"], owner_user=s["owner_user"],
            start_at="2026-05-12T08:00:00.000Z",
            end_at="2026-05-13T08:00:00.000Z",
            kind="AD_HOC",
        )
        assert window["status"] == "IN_PROGRESS"
        eq = get_equipment(s["equipment"]["id"])
        assert eq["status"] == "MAINTENANCE"


# ===========================================================================
# System-driven SCHEDULED → IN_PROGRESS (PRD §3.7)
# ===========================================================================
class TestScheduledToInProgress:
    """PRD §3.7: 'When the clock advances to or beyond start_at on a
    SCHEDULED window, and the equipment is currently AVAILABLE, the
    window transitions to IN_PROGRESS, the equipment transitions
    AVAILABLE → MAINTENANCE, and overlapping BOOKED reservations are
    cascaded to CANCELLED with full refund.'
    """

    def test_clock_advance_triggers_in_progress(self, api):
        """PRD §3.7: 'the window transitions to IN_PROGRESS, the
        equipment transitions AVAILABLE → MAINTENANCE'."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        window = schedule_maintenance(
            equipment=s["equipment"], owner_user=s["owner_user"],
            start_at="2026-05-12T10:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
            kind="PERIODIC",
        )
        assert window["status"] == "SCHEDULED"
        advance_clock_to("2026-05-12T10:00:00.000Z")
        eq = get_equipment(s["equipment"]["id"])
        assert eq["status"] == "MAINTENANCE"

    def test_overlapping_reservation_cascaded_with_full_refund(self, api):
        """PRD §3.7: 'overlapping BOOKED reservations are cascaded to
        CANCELLED with full refund'."""
        s = setup_maintenance_cascade_scenario()
        advance_clock_to("2026-05-12T10:00:00.000Z")
        r = get_reservation(s["reservation"]["id"])
        assert r["status"] == "CANCELLED"
        assert r["cancellation_refund_bps"] == 10000


# ===========================================================================
# Acceptance and end_at sweep (PRD §3.7)
# ===========================================================================
class TestAcceptanceFlow:
    """PRD §3.7: 'When the clock further advances to or beyond end_at,
    the window transitions to AWAITING_ACCEPTANCE; the equipment remains
    in MAINTENANCE until acceptance ... Acceptance moves the window to
    ACCEPTED, populates archived_record_uri with a pointer to the
    archived maintenance record, attaches the optional acceptance_notes
    text, and — when no other IN_PROGRESS or AWAITING_ACCEPTANCE window
    covers the equipment — transitions the equipment MAINTENANCE →
    AVAILABLE.'
    """

    def test_full_cycle_returns_equipment_to_available(self, api):
        """PRD §3.7: 'transitions the equipment MAINTENANCE → AVAILABLE'.
        """
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        window = schedule_maintenance(
            equipment=s["equipment"], owner_user=s["owner_user"],
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T10:00:00.000Z",
            kind="PERIODIC",
        )
        advance_clock_to("2026-05-12T09:00:00.000Z")
        advance_clock_to("2026-05-12T10:00:00.000Z")
        accepted = accept_maintenance(
            window=window, owner_user=s["owner_user"],
        )
        assert accepted["status"] == "ACCEPTED"
        eq = get_equipment(s["equipment"]["id"])
        assert eq["status"] == "AVAILABLE"


# ===========================================================================
# Rejection spawns follow-up window (PRD §3.7)
# ===========================================================================
class TestRejectionSpawnsFollowUp:
    """PRD §3.7: 'Rejection moves the window to REJECTED, records the
    supplied acceptance_notes describing why acceptance was withheld,
    and spawns a follow-up AD_HOC MaintenanceWindow with start_at equal
    to the server clock and end_at equal to the server clock plus 24
    hours; the equipment remains in MAINTENANCE because it is now
    covered by the new window.'
    """

    def test_reject_leaves_equipment_in_maintenance(self, api):
        """PRD §3.7: 'the equipment remains in MAINTENANCE because it is
        now covered by the new window'."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        window = schedule_maintenance(
            equipment=s["equipment"], owner_user=s["owner_user"],
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T10:00:00.000Z",
            kind="PERIODIC",
        )
        advance_clock_to("2026-05-12T09:00:00.000Z")
        advance_clock_to("2026-05-12T10:00:00.000Z")
        rejected = reject_maintenance(
            window=window, owner_user=s["owner_user"],
        )
        assert rejected["status"] == "REJECTED"
        eq = get_equipment(s["equipment"]["id"])
        assert eq["status"] == "MAINTENANCE"
