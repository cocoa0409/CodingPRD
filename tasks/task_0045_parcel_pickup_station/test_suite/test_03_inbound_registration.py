"""Inbound parcel registration: accept-and-shelve vs. exception path.

PRD §3.2 (Inbound Registration), §2.11 (Validation Priority Order).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_parcel,
    fetch_active_pickup_code,
    find_audit_entries,
    find_reminders,
    find_system_events,
    list_all_pickup_codes,
    list_all_reminders,
    list_audit_events,
    list_system_events,
    register_parcel_payload,
    register_rejected_parcel,
    register_shelved_parcel,
    setup_station_with_staff,
    TEST_USERS,
    unique_courier_company_id,
    unique_tracking_number,
    validate_error,
    validate_success,
)


# ===========================================================================
# Accept-and-shelve cascade
# ===========================================================================
class TestAcceptAndShelveCascade:
    def test_accept_increments_station_occupancy_and_zone_slots(self, api):
        """PRD §3.2: "Acceptance pins the parcel to its shelf_zone_id
        and shelf_position, sets shelved_at to the current server time,
        computes free_storage_deadline as shelved_at plus the parent
        station's free_storage_hours worth of hours (immutable once
        set), increments the station's current_occupancy and the zone's
        occupied_slots by one each."

        Claim: after one accept-and-shelve call, Station.current_occupancy
        == 1 and ShelfZone.occupied_slots == 1.
        """
        ctx = setup_station_with_staff(storage_capacity=5,
                                       zone_row_count=1, zone_col_count=2)
        parcel = register_shelved_parcel(ctx)
        assert parcel["status"] == "SHELVED"
        assert parcel["shelf_zone_id"] == ctx["zone"]["id"]
        assert parcel["shelf_position"] == "R01-C01"
        # Re-read station and zone.
        station = validate_success(
            api.get_station(ctx["station"]["id"],
                            TEST_USERS["platform_admin_headers"])
        )
        zones, _meta = (
            validate_success(api.list_shelf_zones(ctx["station"]["id"],
                                                  ctx["manager_headers"])),
            None,
        )  # validate_success returns the data envelope's "data" array
        # (it's a list endpoint, so unwrap manually).
        # Use list endpoint helper instead:
        from test_helpers import validate_paginated
        zone_list, _ = validate_paginated(
            api.list_shelf_zones(ctx["station"]["id"], ctx["manager_headers"])
        )
        zone = next(z for z in zone_list if z["id"] == ctx["zone"]["id"])
        assert station["current_occupancy"] == 1
        assert zone["occupied_slots"] == 1

    def test_accept_mints_initial_active_pickup_code(self, api):
        """PRD §3.3: "Inbound acceptance mints the first pickup code
        automatically. ... The newly minted row records code, sets
        status to ACTIVE, stamps issued_at to the current time, sets
        issue_reason to INITIAL."

        Claim: after accept-and-shelve, exactly one ACTIVE PickupCode
        exists for the parcel with issue_reason=INITIAL and a 6-digit
        code.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        active = fetch_active_pickup_code(parcel["id"], ctx["clerk_headers"])
        assert active["status"] == "ACTIVE"
        assert active["issue_reason"] == "INITIAL"
        assert active["code"].isdigit() and len(active["code"]) == 6

    def test_accept_emits_t1_initial_sms_reminder(self, api):
        """PRD §3.2: "emits the first reminder record (tier T1_INITIAL,
        channel SMS, triggered_by INBOUND)."

        Claim: GET /parcels/{id}/reminders lists exactly one
        T1_INITIAL row over SMS triggered_by INBOUND.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        reminders = list_all_reminders(parcel["id"], ctx["clerk_headers"])
        t1 = find_reminders(reminders, tier="T1_INITIAL")
        assert len(t1) == 1
        assert t1[0]["channel"] == "SMS"
        assert t1[0]["triggered_by"] == "INBOUND"

    def test_accept_appends_inbound_accepted_audit(self, api):
        """PRD §3.2: "appends an AuditEvent whose action is INBOUND_ACCEPTED, and queues an IM-targeted PICKUP_CODE_SENT event into the outbox."

        Claim: GET /audit-events filtered to the parcel includes one
        action=INBOUND_ACCEPTED row.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        rows = list_audit_events(
            TEST_USERS["platform_admin_headers"],
            subject_kind="Parcel", subject_id=parcel["id"],
        )
        accepted = find_audit_entries(rows, action="INBOUND_ACCEPTED")
        assert len(accepted) == 1

    def test_accept_queues_pickup_code_sent_im_event(self, api):
        """PRD §3.2: "queues an IM-targeted PICKUP_CODE_SENT event into
        the outbox."

        Claim: GET /system-events includes one event_name=PICKUP_CODE_SENT
        row whose target_system is IM and whose payload references this
        parcel. (PRD §2.10 does not pin which entity is the event's
        subject — implementers may key the event by PickupCode.id or by
        Parcel.id — so we identify the event via payload, not subject_id.)
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        events = list_system_events()
        pcs = [
            e for e in find_system_events(
                events, event_name="PICKUP_CODE_SENT", target_system="IM",
            )
            if e.get("payload", {}).get("parcel_id") == parcel["id"]
            or e.get("subject_id") == parcel["id"]
        ]
        assert len(pcs) >= 1


# ===========================================================================
# Exception path (REJECTED)
# ===========================================================================
class TestExceptionPath:
    @pytest.mark.parametrize("exc", ["DAMAGED", "WRONG_DELIVERY"])
    def test_exception_parcel_does_not_consume_capacity(self, api, exc):
        """PRD §3.2: "It does not consume capacity, does not occupy a
        shelf slot, leaves shelf_zone_id and shelf_position null, sets
        the parcel's status to REJECTED with exception_type preserved."

        Claim: a DAMAGED / WRONG_DELIVERY registration ends in
        status=REJECTED with null shelf_zone_id / null shelf_position
        and the station's current_occupancy unchanged.
        """
        ctx = setup_station_with_staff(storage_capacity=3)
        parcel = register_rejected_parcel(ctx, exception_type=exc)
        assert parcel["status"] == "REJECTED"
        assert parcel["exception_type"] == exc
        assert parcel.get("shelf_zone_id") is None
        assert parcel.get("shelf_position") is None
        station = validate_success(
            api.get_station(ctx["station"]["id"],
                            TEST_USERS["platform_admin_headers"])
        )
        assert station["current_occupancy"] == 0

    def test_exception_with_shelf_assignment_yields_safety_error(self, api):
        """PRD §3.2: "If a request both names a non-NONE exception_type
        and asks for a shelf assignment, the safety rule fires before
        any capacity or referential check and the request is refused
        with ERR_EXCEPTION_PARCEL_CANNOT_SHELVE."

        Claim: payload with exception_type=DAMAGED and shelf_zone_id +
        shelf_position yields ERR_EXCEPTION_PARCEL_CANNOT_SHELVE.
        """
        ctx = setup_station_with_staff()
        payload = register_parcel_payload(
            exception_type="DAMAGED",
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EXCEPTION_PARCEL_CANNOT_SHELVE)


# ===========================================================================
# Negative validations on the accept path
# ===========================================================================
class TestAcceptNegativeValidations:
    def test_shelf_zone_from_different_station_yields_mismatch(self, api):
        """PRD §3.2: "a referential check that the targeted shelf
        zone's station_id matches the path station — a mismatch
        raises ERR_SHELF_ZONE_STATION_MISMATCH."

        Claim: POST /stations/{S1}/parcels with shelf_zone_id pointing
        to a zone under S2 yields ERR_SHELF_ZONE_STATION_MISMATCH.
        """
        ctx1 = setup_station_with_staff()
        ctx2 = setup_station_with_staff()
        payload = register_parcel_payload(
            shelf_zone_id=ctx2["zone"]["id"],  # zone under station2
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx1["station"]["id"], payload, ctx1["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_ZONE_STATION_MISMATCH)

    def test_shelf_position_already_occupied_yields_conflict(self, api):
        """PRD §3.2: "an occupancy check that no other parcel currently
        in SHELVED, OVERTIME, or AWAITING_RETURN already holds the
        target shelf_position in that zone (otherwise
        ERR_SHELF_POSITION_OCCUPIED)."

        Claim: registering a second parcel onto the same
        (shelf_zone_id, shelf_position) yields ERR_SHELF_POSITION_OCCUPIED.
        """
        ctx = setup_station_with_staff(zone_row_count=1, zone_col_count=1)
        register_shelved_parcel(ctx)
        payload = register_parcel_payload(
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_POSITION_OCCUPIED)

    def test_zone_full_yields_err_shelf_zone_full(self, api):
        """PRD §3.2: "the targeted shelf zone's occupied_slots must be
        strictly less than its capacity (otherwise ERR_SHELF_ZONE_FULL)."

        Claim: when the zone is at capacity, a new accept-and-shelve
        targeting that zone (on a free position label) yields
        ERR_SHELF_ZONE_FULL.
        """
        # A 1x1 zone is full after one shelving.
        ctx = setup_station_with_staff(storage_capacity=10,
                                       zone_row_count=1, zone_col_count=1)
        register_shelved_parcel(ctx)
        # Same position would surface POSITION_OCCUPIED (priority 10);
        # a different position label in the same 1x1 zone surfaces
        # ZONE_FULL because the zone has only one slot in total.
        payload = register_parcel_payload(
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R02-C01",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_ZONE_FULL)

    def test_station_capacity_exceeded(self, api):
        """PRD §3.2: "the station's current_occupancy must be strictly
        less than its storage_capacity (otherwise
        ERR_STATION_CAPACITY_EXCEEDED)."

        Claim: when current_occupancy == storage_capacity, a new
        accept-and-shelve yields ERR_STATION_CAPACITY_EXCEEDED.
        """
        # Capacity 1 + 1x2 zone -> one shelving fills the station.
        ctx = setup_station_with_staff(storage_capacity=1,
                                       zone_row_count=1, zone_col_count=2)
        register_shelved_parcel(ctx, slot_index=0)
        payload = register_parcel_payload(
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R01-C02",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STATION_CAPACITY_EXCEEDED)

    def test_duplicate_courier_tracking_number_yields_conflict(self, api):
        """PRD §3.2: "no other ACTIVE-lifecycle parcel may share this
        courier company's tracking_number."

        Claim: a second accept-and-shelve with the same
        (courier_company_id, tracking_number) yields
        ERR_DUPLICATE_TRACKING_NUMBER.
        """
        ctx = setup_station_with_staff(zone_row_count=2, zone_col_count=2)
        courier = unique_courier_company_id()
        tracking = unique_tracking_number()
        register_shelved_parcel(
            ctx, slot_index=0,
            courier_company_id=courier, tracking_number=tracking,
        )
        # Second attempt: same courier+tracking, different position.
        payload = register_parcel_payload(
            courier_company_id=courier, tracking_number=tracking,
            shelf_zone_id=ctx["zone"]["id"], shelf_position="R01-C02",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRACKING_NUMBER)

    def test_re_present_after_rejection_succeeds(self, api):
        """PRD §3.2: "A parcel that was rejected can be re-presented;
        a fresh registration after a REJECTED row simply produces a new
        parcel row from UNREGISTERED. Because the duplicate-tracking
        rule applies only to active-lifecycle rows (those whose status
        is not in the REJECTED set), the re-presentation is not blocked
        by the first attempt."

        Claim: after rejecting tracking T1, a fresh registration with
        the same (courier_company_id, tracking_number) succeeds.
        """
        ctx = setup_station_with_staff()
        courier = unique_courier_company_id()
        tracking = unique_tracking_number()
        register_rejected_parcel(
            ctx, courier_company_id=courier, tracking_number=tracking,
        )
        # Second attempt as accept-and-shelve: same courier+tracking.
        new_parcel = register_shelved_parcel(
            ctx, courier_company_id=courier, tracking_number=tracking,
        )
        assert new_parcel["status"] == "SHELVED"
