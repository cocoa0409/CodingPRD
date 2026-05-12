"""Reservation creation and validation — slot grid, lead time, duration,
maintenance, overlap, peak priority, equipment availability,
authorization referential check, certificates.

PRD §3.3 (booking), §2.7 (slot grid / lead time / peak windows), §2.9
(validation ordering).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_reservation,
    create_reservation_payload,
    make_reservation,
    make_user_headers,
    revoke_authorization,
    schedule_maintenance,
    setup_basic_scenario,
    setup_overlap_scenario_with_two_users,
    setup_maintenance_overlap_scenario,
    validate_error,
    validate_success,
)


# ===========================================================================
# Slot grid alignment  (PRD §2.7 / §3.3)
# ===========================================================================
class TestSlotGridAlignment:
    """PRD §2.7: 'When slot_granularity is HOUR, both start_at and end_at
    must fall on the top of a UTC hour ... In addition, end_at must be
    strictly greater than start_at, and the duration end_at minus
    start_at must be a positive integer multiple of the granularity. Any
    deviation surfaces as ERR_SLOT_GRID_VIOLATION at 422.'
    """

    def test_unaligned_start_rejected(self, api):
        """PRD §2.7: 'When slot_granularity is HOUR, both start_at and
        end_at must fall on the top of a UTC hour ... Any deviation
        surfaces as ERR_SLOT_GRID_VIOLATION at 422'."""
        s = setup_basic_scenario(slot_granularity="HOUR")
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T09:15:00.000Z",
                end_at="2026-05-12T10:15:00.000Z",
            ),
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SLOT_GRID_VIOLATION.value)

    def test_end_not_after_start_rejected(self, api):
        """PRD §2.7: 'end_at must be strictly greater than start_at'."""
        s = setup_basic_scenario(slot_granularity="HOUR")
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T09:00:00.000Z",
                end_at="2026-05-12T09:00:00.000Z",
            ),
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SLOT_GRID_VIOLATION.value)


# ===========================================================================
# Lead time  (PRD §2.7 / §3.3)
# ===========================================================================
class TestLeadTime:
    """PRD §2.7: 'A reservation's start_at must lie at least
    lead_time_hours hours in the future relative to the server clock at
    create time; if the gap is shorter the request is rejected with
    ERR_LEAD_TIME_VIOLATED.'
    """

    def test_lead_time_violated_rejected(self, api):
        """PRD §2.7: 'if the gap is shorter the request is rejected with
        ERR_LEAD_TIME_VIOLATED'."""
        s = setup_basic_scenario(lead_time_hours=24)
        # Clock at 2026-05-12T00:00; start_at one hour out → 1 hour < 24h.
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T01:00:00.000Z",
                end_at="2026-05-12T02:00:00.000Z",
            ),
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LEAD_TIME_VIOLATED.value)


# ===========================================================================
# Duration limit (PRD §2.7 / §3.3)
# ===========================================================================
class TestDurationLimit:
    """PRD §2.7: 'The reservation duration, measured in full hours as
    end_at minus start_at, must not exceed the equipment's
    single_user_duration_limit_hours; otherwise the request is rejected
    with ERR_DURATION_LIMIT_EXCEEDED.'
    """

    def test_duration_over_limit_rejected(self, api):
        """PRD §2.7: 'must not exceed the equipment's
        single_user_duration_limit_hours; otherwise ...
        ERR_DURATION_LIMIT_EXCEEDED'."""
        s = setup_basic_scenario(
            slot_granularity="HOUR", single_user_duration_limit_hours=2,
        )
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T09:00:00.000Z",
                end_at="2026-05-12T12:00:00.000Z",  # 3h > 2h
            ),
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DURATION_LIMIT_EXCEEDED.value)


# ===========================================================================
# Reservation overlap (PRD §3.3)
# ===========================================================================
class TestReservationOverlap:
    """PRD §3.3: 'It must not overlap any existing BOOKED or CHECKED_IN
    reservation on the same equipment — intersection uses half-open
    semantics, so a new reservation whose start_at exactly equals an
    existing reservation's end_at is permitted — and an overlap yields
    ERR_RESERVATION_OVERLAP.'
    """

    def test_half_open_overlap_rejected(self, api):
        """PRD §3.3: 'an overlap yields ERR_RESERVATION_OVERLAP'.

        U1 holds [09:00, 10:00); U2 attempts [09:00, 11:00). Both
        timestamps are on the HOUR slot grid (PRD §2.7) so the grid
        check passes and the §3.3 overlap rule actually fires.
        """
        s = setup_overlap_scenario_with_two_users()
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user2"]["id"],
                authorization_id=s["authorization2"]["id"],
                start_at="2026-05-12T09:00:00.000Z",
                end_at="2026-05-12T11:00:00.000Z",
            ),
            make_user_headers(s["user2"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RESERVATION_OVERLAP.value)

    def test_adjacent_endpoints_permitted(self, api):
        """PRD §3.3: 'a new reservation whose start_at exactly equals an
        existing reservation's end_at is permitted'."""
        s = setup_overlap_scenario_with_two_users()
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user2"]["id"],
                authorization_id=s["authorization2"]["id"],
                start_at="2026-05-12T10:00:00.000Z",
                end_at="2026-05-12T11:00:00.000Z",
            ),
            make_user_headers(s["user2"]["id"]),
        )
        reservation = validate_success(res, 201)
        assert_reservation(reservation)


# ===========================================================================
# Maintenance block (PRD §3.3)
# ===========================================================================
class TestMaintenanceBlock:
    """PRD §3.3: 'The requested half-open interval [start_at, end_at) must
    not intersect any MaintenanceWindow whose status is SCHEDULED or
    IN_PROGRESS for this equipment; if it does, the request is rejected
    with ERR_MAINTENANCE_BLOCK.'
    """

    def test_reservation_inside_maintenance_rejected(self, api):
        """PRD §3.3: 'if it does, the request is rejected with
        ERR_MAINTENANCE_BLOCK'.

        Maintenance window is [10:00, 12:00). Reservation [11:00, 12:00)
        lies fully inside it. Both endpoints are on the HOUR slot grid
        (PRD §2.7) so the grid check passes and the §3.3 maintenance
        block rule actually fires.
        """
        s = setup_maintenance_overlap_scenario()
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T11:00:00.000Z",
                end_at="2026-05-12T12:00:00.000Z",
            ),
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MAINTENANCE_BLOCK.value)

    def test_reservation_containing_maintenance_rejected(self, api):
        """PRD §3.3: 'The requested half-open interval [start_at, end_at)
        must not intersect any MaintenanceWindow whose status is
        SCHEDULED or IN_PROGRESS'. A reservation that fully contains the
        window also intersects it."""
        s = setup_maintenance_overlap_scenario()
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T09:00:00.000Z",
                end_at="2026-05-12T13:00:00.000Z",
            ),
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MAINTENANCE_BLOCK.value)

    def test_reservation_adjacent_to_maintenance_permitted(self, api):
        """PRD §3.3: half-open semantics — a reservation starting exactly
        at the maintenance window's end_at does not intersect."""
        s = setup_maintenance_overlap_scenario()
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T12:00:00.000Z",
                end_at="2026-05-12T13:00:00.000Z",
            ),
            make_user_headers(s["user"]["id"]),
        )
        reservation = validate_success(res, 201)
        assert_reservation(reservation)


# ===========================================================================
# Authorization referential check (PRD §3.3 / priority 7)
# ===========================================================================
class TestAuthorizationReferential:
    """PRD §3.3: 'The cross-entity authorization check enforces that the
    supplied authorization_id resolves to a row whose status is APPROVED,
    whose expires_at is strictly greater than the server clock, and
    whose equipment_id and user_id both match the reservation's context —
    any deviation yields ERR_AUTHORIZATION_INVALID.'
    """

    def test_revoked_authorization_rejected(self, api):
        """PRD §3.3: 'whose status is APPROVED ... any deviation yields
        ERR_AUTHORIZATION_INVALID'."""
        s = setup_basic_scenario()
        revoke_authorization(
            authorization=s["authorization"],
            owner_user=s["owner_user"],
        )
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T09:00:00.000Z",
                end_at="2026-05-12T10:00:00.000Z",
            ),
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_AUTHORIZATION_INVALID.value)

    def test_authorization_for_different_user_rejected(self, api):
        """PRD §3.3: 'whose ... user_id [matches] the reservation's
        context'."""
        from test_helpers import (
            create_verified_user, request_and_approve_authorization,
        )
        s = setup_basic_scenario()
        other_user = create_verified_user(
            affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
        )
        # s.authorization is bound to s.user, not other_user.
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=other_user["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-12T09:00:00.000Z",
                end_at="2026-05-12T10:00:00.000Z",
            ),
            make_user_headers(other_user["id"]),
        )
        validate_error(res, ApiErrorId.ERR_AUTHORIZATION_INVALID.value)


# ===========================================================================
# Equipment unavailable (PRD §3.3 / priority 6)
# ===========================================================================
class TestEquipmentUnavailable:
    """PRD §3.3: 'Equipment must be in status AVAILABLE; if it is in
    MAINTENANCE or RETIRED the system returns ERR_EQUIPMENT_UNAVAILABLE.'
    """

    def test_reservation_when_equipment_in_maintenance_rejected(self, api):
        """PRD §3.3: 'if it is in MAINTENANCE or RETIRED the system
        returns ERR_EQUIPMENT_UNAVAILABLE'."""
        s = setup_basic_scenario()
        # Spawn an immediate AD_HOC maintenance window so the equipment
        # flips to MAINTENANCE.
        schedule_maintenance(
            equipment=s["equipment"], owner_user=s["owner_user"],
            start_at="2026-05-12T00:00:00.000Z",
            end_at="2026-05-13T00:00:00.000Z",
            kind="AD_HOC",
        )
        res = api.create_reservation(
            s["equipment"]["id"],
            create_reservation_payload(
                user_id=s["user"]["id"],
                authorization_id=s["authorization"]["id"],
                start_at="2026-05-13T09:00:00.000Z",
                end_at="2026-05-13T10:00:00.000Z",
            ),
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value)


# ===========================================================================
# Peak preemption (PRD §3.3)
# ===========================================================================
class TestPeakPreemption:
    """PRD §3.3: 'When the candidate is PEAK and the only conflicting
    reservation is an OFF_PEAK reservation in BOOKED status that overlaps
    the requested slot, the conflicting reservation is preempted: it is
    cancelled with cancellation_refund_bps of 10000 (full refund) and a
    CANCEL audit row is written for it, and the new PEAK reservation is
    then admitted.'
    """

    def test_peak_candidate_preempts_off_peak_booking(self, api):
        """PRD §3.3: 'When the candidate is PEAK and the only conflicting
        reservation is an OFF_PEAK reservation in BOOKED status that
        overlaps the requested slot, the conflicting reservation is
        preempted: it is cancelled with cancellation_refund_bps of 10000
        (full refund) ... and the new PEAK reservation is then admitted.'

        Setup: equipment with a wide peak window 20-24. U1 books an
        OFF_PEAK reservation [12:00,13:00) (zero peak overlap). U2 then
        books [21:00, 23:00) which would be PEAK in this geometry — but
        that doesn't overlap U1's slot. So construct it differently:
        peak window is 09-12, U1 books OFF_PEAK [12:00, 14:00) and U2
        books PEAK [10:00, 13:00) which overlaps U1's window across
        [12:00, 13:00) AND the candidate's peak overlap is in [10:00,
        12:00) → PEAK. The existing OFF_PEAK reservation gets preempted.
        """
        from test_helpers import (
            cancel_reservation, get_equipment, get_reservation,
            make_reservation,
        )
        s = setup_overlap_scenario_with_two_users()
        # Cancel U1's default [09:00,10:00) reservation.
        cancel_reservation(reservation=s["reservation1"], user=s["user1"])
        # Update equipment peak window to 09-12 for this scenario.
        from test_helpers import (
            make_lab_owner_headers, update_equipment_payload,
        )
        # Re-fetch the equipment so we use its current version (it may
        # have been version-bumped by intervening publish / cascade ops).
        current_eq = get_equipment(s["equipment"]["id"])
        eq = validate_success(api.update_equipment(
            current_eq["id"],
            update_equipment_payload(
                peak_window_start_hour=9, peak_window_end_hour=12,
                version=current_eq["version"],
            ),
            make_lab_owner_headers(s["owner_user"]["id"]),
        ), 200)
        # U1 books OFF_PEAK [12:00,14:00) — no overlap with [09,12).
        off_peak = make_reservation(
            equipment=eq, user=s["user1"],
            authorization=s["authorization1"],
            start_at="2026-05-12T12:00:00.000Z",
            end_at="2026-05-12T14:00:00.000Z",
        )
        assert off_peak["priority_tier"] == "OFF_PEAK"
        # U2 books PEAK [10:00, 13:00): peak overlap [10,12) = 120 min >0.
        peak_candidate = make_reservation(
            equipment=eq, user=s["user2"],
            authorization=s["authorization2"],
            start_at="2026-05-12T10:00:00.000Z",
            end_at="2026-05-12T13:00:00.000Z",
        )
        assert peak_candidate["priority_tier"] == "PEAK"
        # The OFF_PEAK reservation must have been preempted with full
        # refund.
        preempted = get_reservation(off_peak["id"])
        assert preempted["status"] == "CANCELLED"
        assert preempted["cancellation_refund_bps"] == 10000
