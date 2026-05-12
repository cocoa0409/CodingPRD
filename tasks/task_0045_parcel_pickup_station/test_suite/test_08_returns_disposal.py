"""Returns workflow and disposal of unclaimed parcels.

PRD §3.7 (Returns and Disposal of Unclaimed Parcels).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_hours,
    courier_responds,
    drive_parcel_to_awaiting_return,
    find_audit_entries,
    find_system_events,
    is_iso8601_timestamp,
    list_audit_events,
    list_system_events,
    register_shelved_parcel,
    request_return_shipment,
    setup_station_with_staff,
    ship_return,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestReturnShipmentLifecycle:
    def test_request_return_creates_requested(self, api):
        """PRD §3.7: "Once a parcel is in AWAITING_RETURN, a Manager
        may request that the courier reclaim it. ... the request is
        recorded as a new ReturnShipment ... whose status is REQUESTED,
        whose courier_company_id mirrors the parcel's at request time,
        and whose requested_at is stamped server-side."

        Claim: POST /parcels/{id}/return-shipments returns a record
        with status=REQUESTED, courier_company_id mirroring the
        parcel's, and an ISO 8601 requested_at.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        rs = request_return_shipment(ctx, parcel)
        assert rs["status"] == "REQUESTED"
        assert rs["courier_company_id"] == parcel["courier_company_id"]
        assert is_iso8601_timestamp(rs["requested_at"])

    def test_courier_accept_flips_to_courier_accepted(self, api):
        """PRD §3.7: "acceptance flips the return's status from
        REQUESTED to COURIER_ACCEPTED and stamps courier_response_at."

        Claim: POST /return-shipments/{id}/courier-response with
        decision=accept yields status=COURIER_ACCEPTED with stamped
        courier_response_at.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        rs = request_return_shipment(ctx, parcel)
        accepted = courier_responds(rs["id"], "accept")
        assert accepted["status"] == "COURIER_ACCEPTED"
        assert is_iso8601_timestamp(accepted["courier_response_at"])

    def test_courier_decline_flips_to_courier_declined(self, api):
        """PRD §3.7: "declination flips it to COURIER_DECLINED and
        likewise stamps courier_response_at."

        Claim: courier-response with decision=decline yields
        status=COURIER_DECLINED.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        rs = request_return_shipment(ctx, parcel)
        declined = courier_responds(rs["id"], "decline")
        assert declined["status"] == "COURIER_DECLINED"
        assert is_iso8601_timestamp(declined["courier_response_at"])

    def test_ship_return_cascades_parcel_to_returned(self, api):
        """PRD §3.7: "A subsequent ship action — accepting
        courier_tracking_return if not yet recorded — flips the
        return from COURIER_ACCEPTED to SHIPPED, stamps shipped_at, and
        cascades the parent parcel from AWAITING_RETURN to RETURNED;
        on the cascade the parcel's returned_at is stamped, its
        storage_fee_total is finalized and storage_fee_locked is set
        to true, both occupancy counters decrement, an AuditEvent of
        action RETURNED is appended, and a COURIER-targeted
        RETURN_SHIPPED event is queued."

        Claim: after ship, the return is SHIPPED and the parcel is
        RETURNED with stamped returned_at, storage_fee_locked=true,
        and a RETURN_SHIPPED outbox event on the COURIER target.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        rs = request_return_shipment(ctx, parcel)
        courier_responds(rs["id"], "accept")
        shipped = ship_return(rs["id"])
        assert shipped["status"] == "SHIPPED"
        assert is_iso8601_timestamp(shipped["shipped_at"])
        # Re-read the parcel.
        parcel_after = validate_success(
            api.get_parcel(parcel["id"], ctx["clerk_headers"])
        )
        assert parcel_after["status"] == "RETURNED"
        assert is_iso8601_timestamp(parcel_after["returned_at"])
        assert parcel_after["storage_fee_locked"] is True
        # RETURN_SHIPPED outbox event on COURIER target.
        events = list_system_events(subject_id=rs["id"]) +\
                 list_system_events(subject_id=parcel["id"])
        match = find_system_events(
            events, event_name="RETURN_SHIPPED", target_system="COURIER",
        )
        assert len(match) >= 1


class TestDisposal:
    def test_disposal_before_grace_returns_too_early(self, api):
        """PRD §3.7: "Disposal is permitted only when
        long_stay_flagged_at is non-null and the current server time is
        at or after long_stay_flagged_at plus 240 hours, and only when
        no ReturnShipment for the parcel is currently in
        COURIER_ACCEPTED or SHIPPED. A premature disposal attempt is
        refused with ERR_DISPOSAL_TOO_EARLY (HTTP 422)."

        Claim: dispose called immediately after long_stay_flagged_at
        was set (well before the 240h grace) yields
        ERR_DISPOSAL_TOO_EARLY.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        # Immediately attempt disposal (well before 240h grace).
        resp = api.dispose_parcel(parcel["id"], ctx["manager_headers"])
        validate_error(resp, ApiErrorId.ERR_DISPOSAL_TOO_EARLY)

    def test_disposal_after_grace_succeeds(self, api):
        """PRD §3.7: "On success, the parcel transitions from
        AWAITING_RETURN to DISPOSED, storage_fee_locked becomes true,
        both occupancy counters decrement, and an audit event of
        action DISPOSED is appended."

        Claim: after long_stay_flagged_at + 240h, dispose succeeds:
        parcel.status=DISPOSED, storage_fee_locked=true,
        Station.current_occupancy=0, and audit event DISPOSED present.
        """
        ctx = setup_station_with_staff(storage_capacity=5)
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        advance_clock_hours(241)  # > DISPOSAL_GRACE_HOURS=240
        resp = api.dispose_parcel(parcel["id"], ctx["manager_headers"])
        disposed = validate_success(resp)
        assert disposed["status"] == "DISPOSED"
        assert disposed["storage_fee_locked"] is True
        station = validate_success(
            api.get_station(ctx["station"]["id"],
                            TEST_USERS["platform_admin_headers"])
        )
        assert station["current_occupancy"] == 0
        rows = list_audit_events(
            TEST_USERS["platform_admin_headers"],
            subject_kind="Parcel", subject_id=parcel["id"],
        )
        assert find_audit_entries(rows, action="DISPOSED")
