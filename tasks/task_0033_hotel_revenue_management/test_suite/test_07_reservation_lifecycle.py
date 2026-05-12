"""Reservation creation, confirmation gating, and modification (PRD §3.5).

Covers:
- Initial-state contract on Reservation create
- ERR_RATE_PLAN_NOT_DISTRIBUTED on create / modify
- Confirm gating: per-channel inventory share, overbooking ceiling
- booked_total_cents calculation against base rate AND APPROVED override
- Modification timing rules (24h cutoff vs DIRECT carve-out)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    assert_reservation,
    confirm_reservation,
    create_channel,
    create_confirmed_reservation,
    create_mapping,
    create_pending_reservation,
    create_rate_plan,
    create_rate_plan_payload,
    create_reservation_payload,
    create_room,
    create_room_type,
    date_plus_days,
    fill_reservations_to_count,
    modify_reservation_payload,
    setup_basic_distribution,
    setup_room_type_at_overbooking_boundary,
    setup_with_n_confirmed_for_date,
    setup_channel_share_boundary,
    submit_and_approve_rate_override,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Reservation create — initial state
# ===========================================================================
class TestReservationCreate:
    def test_create_reservation_initial_state(self, api):
        """PRD §3.5: 'On creation, the reservation is born in
        booking_status of PENDING and payment_status of UNPAID.'

        PRD §3.5: 'Several derived fields begin at known initial values:
        assigned_room_id is null ... booked_total_cents is zero ...
        refund_amount_cents is zero, no_show_charge_cents is zero,
        walkout_compensation_cents is zero, cancelled_at is null, and
        dispute_status is NONE.'
        """
        scaffold = setup_basic_distribution(n_rooms=2)
        res = create_pending_reservation(
            scaffold,
            check_in_date="2028-04-01", check_out_date="2028-04-03",
        )
        assert_reservation(res)
        assert res["booking_status"] == "PENDING"
        assert res["payment_status"] == "UNPAID"
        assert res.get("assigned_room_id") is None
        assert res["nights"] == 2
        assert res["booked_total_cents"] == 0
        assert res["refund_amount_cents"] == 0
        assert res["no_show_charge_cents"] == 0
        assert res["walkout_compensation_cents"] == 0
        assert res.get("cancelled_at") is None
        assert res["dispute_status"] == "NONE"

    def test_check_out_must_be_strictly_after_check_in(
        self, api, agent_headers,
    ):
        """PRD §3.5: 'check_out_date MUST be strictly later than
        check_in_date.'"""
        scaffold = setup_basic_distribution(n_rooms=1)
        bad = api.create_reservation(
            create_reservation_payload(
                room_type_id=scaffold["room_type"]["id"],
                rate_plan_id=scaffold["rate_plan"]["id"],
                channel_id=scaffold["channel"]["id"],
                check_in_date="2028-04-10",
                check_out_date="2028-04-10",
            ),
            agent_headers,
        )
        validate_error(bad, "ERR_INVALID_INPUT")


# ===========================================================================
# RATE_PLAN_NOT_DISTRIBUTED gating
# ===========================================================================
class TestRatePlanDistribution:
    def test_create_with_unmapped_channel_rejected(self, api, agent_headers):
        """PRD §3.5: 'a ChannelRatePlanMapping exists between the chosen
        channel_id and rate_plan_id whose enabled flag is true; failure
        of either is rejected with ERR_RATE_PLAN_NOT_DISTRIBUTED.'"""
        rt = create_room_type()
        # Plan and channel exist but no mapping between them.
        plan = create_rate_plan(room_type_id=rt["id"])
        unmapped_channel = create_channel(channel_type="DIRECT")
        # We still need a real Room to satisfy upstream checks.
        create_room(room_type_id=rt["id"])
        res = api.create_reservation(
            create_reservation_payload(
                room_type_id=rt["id"],
                rate_plan_id=plan["id"],
                channel_id=unmapped_channel["id"],
                check_in_date="2028-05-01",
                check_out_date="2028-05-02",
            ),
            agent_headers,
        )
        validate_error(res, "ERR_RATE_PLAN_NOT_DISTRIBUTED")

    def test_create_with_rate_plan_room_type_mismatch_rejected(
        self, api, agent_headers,
    ):
        """PRD §3.5: 'enforces that the RatePlan's room_type_id equals the
        reservation's room_type_id ... failure of either is rejected with
        ERR_RATE_PLAN_NOT_DISTRIBUTED.'"""
        rt_a = create_room_type()
        rt_b = create_room_type()
        plan_a = create_rate_plan(room_type_id=rt_a["id"])
        channel = create_channel()
        # Map plan_a (which is for rt_a) to channel.
        create_mapping(
            channel_id=channel["id"], rate_plan_id=plan_a["id"],
            inventory_share_basis_points=10000,
        )
        create_room(room_type_id=rt_b["id"])
        # Try a reservation that references rt_b but plan_a — mismatch.
        res = api.create_reservation(
            create_reservation_payload(
                room_type_id=rt_b["id"],
                rate_plan_id=plan_a["id"],
                channel_id=channel["id"],
                check_in_date="2028-05-10",
                check_out_date="2028-05-11",
            ),
            agent_headers,
        )
        validate_error(res, "ERR_RATE_PLAN_NOT_DISTRIBUTED")


# ===========================================================================
# Confirm: rate locking (booked_total_cents)
# ===========================================================================
class TestConfirmLockRate:
    def test_confirm_locks_booked_total_using_base_rate(self, api):
        """PRD §3.5: 'for each date, if a RateOverride for this room type
        and this stay_date exists with status of APPROVED, the per-night
        rate is its applied_rate_cents; otherwise, it is the room type's
        base_rate_cents. The booked total is the sum of those per-night
        cents amounts'."""
        scaffold = setup_basic_distribution(
            base_rate_cents=15000, n_rooms=2, channel_type="DIRECT",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2028-06-01", check_out_date="2028-06-04",
        )
        # 3 nights * 15000 = 45000
        assert res["booking_status"] == "CONFIRMED"
        assert res["booked_total_cents"] == 45000
        assert res["payment_status"] == "AUTHORIZED"

    def test_confirm_uses_approved_rate_override(self, api):
        """PRD §3.5: 'if a RateOverride for this room type and this
        stay_date exists with status of APPROVED, the per-night rate is
        its applied_rate_cents'.

        Setup: 2-night stay; an APPROVED RateOverride sets night 1's
        rate to 30000 cents; night 2 falls back to base_rate=15000.
        Total = 30000 + 15000 = 45000.
        """
        scaffold = setup_basic_distribution(
            base_rate_cents=15000, n_rooms=2, channel_type="DIRECT",
        )
        # Approve an override for night 1 only.
        submit_and_approve_rate_override(
            room_type_id=scaffold["room_type"]["id"],
            stay_date="2028-07-01",
            proposed_rate_cents=30000,
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2028-07-01", check_out_date="2028-07-03",
        )
        assert res["booked_total_cents"] == 30000 + 15000


# ===========================================================================
# Confirm: per-channel inventory exhaustion
# ===========================================================================
class TestPerChannelInventory:
    def test_confirm_rejected_when_channel_share_exhausted(self, api):
        """PRD §3.5: 'if the minimum remaining across all nights is not
        greater than zero, the confirm is rejected with
        ERR_INVENTORY_EXHAUSTED.'

        Setup: 4 rooms, channel share 2500bp → channel_share = floor(4 *
        0.25) = 1. After confirming 1 reservation through this channel,
        the next confirm must fail.
        """
        scaffold = setup_channel_share_boundary(
            physical_capacity=4, inventory_share_basis_points=2500,
        )
        ci = "2028-08-01"
        co = date_plus_days(ci, 1)
        # First confirm uses the only allotted slot.
        first = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        # Second confirm via the same channel — should fail.
        second_pending = create_pending_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        res = api.confirm_reservation(
            second_pending["id"], TEST_USERS["agent_headers"],
        )
        validate_error(res, "ERR_INVENTORY_EXHAUSTED")


# ===========================================================================
# Confirm: overbooking ceiling boundary
# ===========================================================================
class TestOverbookingCeiling:
    def test_confirm_at_ceiling_boundary_allowed(self, api):
        """PRD §3.5: 'The boundary is strict: a count equal to the
        ceiling is full but legal; only counts strictly exceeding the
        ceiling are forbidden.'

        capacity=4, ratio=2500bp → ceiling=5. Confirm 5 reservations.
        """
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=4, overbook_ratio_basis_points=2500,
            stay_date="2028-09-15", initial_confirmed=4,
        )
        # 5th confirm should succeed (cumulative == ceiling).
        fifth_pending = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
        )
        res = api.confirm_reservation(
            fifth_pending["id"], TEST_USERS["agent_headers"],
        )
        confirmed = validate_success(res, expected_status=200)
        assert confirmed["booking_status"] == "CONFIRMED"

    def test_confirm_above_ceiling_rejected(self, api):
        """PRD §3.5: 'if the resulting count is strictly greater than the
        ceiling, the confirm is rejected with
        ERR_OVERBOOKING_LIMIT_EXCEEDED.'

        capacity=4, ratio=2500bp → ceiling=5. The 6th confirm fails.
        """
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=4, overbook_ratio_basis_points=2500,
            stay_date="2028-09-16", initial_confirmed=5,
        )
        # 6th confirm should fail.
        sixth_pending = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
        )
        res = api.confirm_reservation(
            sixth_pending["id"], TEST_USERS["agent_headers"],
        )
        validate_error(res, "ERR_OVERBOOKING_LIMIT_EXCEEDED")


# ===========================================================================
# Confirm side effect: OVERBOOKING_ACCEPTED audit when ceiling binds
# ===========================================================================
class TestOverbookingAcceptedAudit:
    def test_overbooking_accepted_audit_emitted_inside_overbook_zone(
        self, api,
    ):
        """PRD §3.5: 'If the confirm landed inside the overbooking
        allowance — i.e., the cumulative count exceeded physical capacity
        but stayed at or below the ceiling — the system writes an
        OVERBOOKING_ACCEPTED audit event.'

        capacity=4, ratio=2500bp → ceiling=5. 5th confirm is inside
        the overbook zone (count > capacity, count <= ceiling).
        """
        from test_helpers import list_audit_logs
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=4, overbook_ratio_basis_points=2500,
            stay_date="2028-09-17", initial_confirmed=4,
        )
        fifth_pending = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
        )
        res = api.confirm_reservation(
            fifth_pending["id"], TEST_USERS["agent_headers"],
        )
        confirmed = validate_success(res, expected_status=200)
        logs = list_audit_logs(
            event_type="OVERBOOKING_ACCEPTED",
            subject_id=confirmed["id"],
        )
        assert len(logs) >= 1, (
            "expected OVERBOOKING_ACCEPTED audit when 5th confirm "
            "(count > capacity, count <= ceiling) lands"
        )


# ===========================================================================
# Modification timing: 24h cutoff vs DIRECT carve-out
# ===========================================================================
class TestReservationModification:
    def test_modify_inside_24h_on_non_direct_channel_rejected(self, api):
        """PRD §3.5: 'modification is rejected with ... ERR_MODIFICATION_
        TOO_LATE if the original check_in_date is at or within 24 hours
        of the moment of modification AND the originating channel's
        channel_type is not DIRECT'."""
        # Build OTA channel scaffold.
        rt = create_room_type(base_rate_cents=20000)
        create_room(room_type_id=rt["id"])
        plan = create_rate_plan(room_type_id=rt["id"], modification_allowed=True)
        ota = create_channel(channel_type="OTA", commission_basis_points=1000)
        create_mapping(
            channel_id=ota["id"], rate_plan_id=plan["id"],
            inventory_share_basis_points=10000,
        )
        scaffold = {
            "room_type": rt, "rooms": [], "rate_plan": plan,
            "channel": ota, "mapping": None,
        }
        # Set clock to 2028-10-01 09:00; create+confirm a stay starting
        # 2028-10-01 (today). Check_in is within 24h.
        advance_clock("2028-10-01T09:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2028-10-02", check_out_date="2028-10-04",
        )
        # Now modify at clock=2028-10-01T13:00 (still within 24h of
        # 2028-10-02 midnight). Should fail because OTA.
        advance_clock("2028-10-01T13:00:00.000Z")
        bad = api.modify_reservation(
            res["id"],
            modify_reservation_payload(
                check_in_date="2028-10-03", check_out_date="2028-10-05",
            ),
            TEST_USERS["agent_headers"],
        )
        validate_error(bad, "ERR_MODIFICATION_TOO_LATE")

    def test_modify_inside_24h_on_direct_channel_allowed(self, api):
        """PRD §3.5: 'direct bookings retain modification rights inside
        the 24-hour window'."""
        scaffold = setup_basic_distribution(
            n_rooms=4, channel_type="DIRECT", commission_basis_points=0,
        )
        advance_clock("2028-11-01T09:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2028-11-02", check_out_date="2028-11-04",
        )
        advance_clock("2028-11-01T20:00:00.000Z")  # within 24h
        ok = api.modify_reservation(
            res["id"],
            modify_reservation_payload(
                check_in_date="2028-11-03", check_out_date="2028-11-05",
            ),
            TEST_USERS["agent_headers"],
        )
        modified = validate_success(ok, expected_status=200)
        assert modified["check_in_date"].startswith("2028-11-03")

    def test_modify_when_modification_disallowed_rejected(self, api):
        """PRD §3.5: 'Modification of a CONFIRMED reservation ... is
        rejected with ... ERR_MODIFICATION_NOT_ALLOWED if the rate plan's
        modification_allowed is false'."""
        rt = create_room_type(base_rate_cents=20000)
        create_room(room_type_id=rt["id"])
        plan = create_rate_plan(room_type_id=rt["id"], modification_allowed=False)
        ch = create_channel(channel_type="DIRECT")
        create_mapping(
            channel_id=ch["id"], rate_plan_id=plan["id"],
            inventory_share_basis_points=10000,
        )
        scaffold = {
            "room_type": rt, "rooms": [], "rate_plan": plan,
            "channel": ch, "mapping": None,
        }
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-01-10", check_out_date="2029-01-12",
        )
        bad = api.modify_reservation(
            res["id"],
            modify_reservation_payload(
                check_in_date="2029-01-11", check_out_date="2029-01-13",
            ),
            TEST_USERS["agent_headers"],
        )
        validate_error(bad, "ERR_MODIFICATION_NOT_ALLOWED")


# ===========================================================================
# Reservation list endpoint filters
# ===========================================================================
class TestReservationListFilters:
    def test_list_filter_by_booking_status(self, api, admin_headers):
        """PRD §4: 'GET /hotel/reservations ... filter by booking_status,
        channel_id, room_type_id, check_in_date_from, check_in_date_to'."""
        scaffold = setup_basic_distribution(n_rooms=2)
        # Create two reservations: one PENDING, one CONFIRMED.
        pending = create_pending_reservation(
            scaffold,
            check_in_date="2029-02-01", check_out_date="2029-02-02",
        )
        confirmed = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-02-05", check_out_date="2029-02-06",
        )
        res = api.list_reservations(
            admin_headers,
            params={"booking_status": "CONFIRMED",
                    "room_type_id": scaffold["room_type"]["id"]},
        )
        data, _ = validate_paginated(res)
        ids = {r["id"] for r in data}
        assert confirmed["id"] in ids
        assert pending["id"] not in ids
