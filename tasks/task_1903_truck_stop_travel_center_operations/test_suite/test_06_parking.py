"""Paid parking: aggregate capacity boundary, half-open windows, plate
referential checks, window shape, charge computation, and no-show grace."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_member,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.fixtures import (
    CASH_1,
    GM,
    create_member_with_plate,
    create_parking_reservation,
    create_site,
)
from test_helpers.test_users import make_loyalty_member_headers


def _setup_parking_site(parking_paid_capacity=2, parking_total_spaces=10):
    site = create_site("Parking Site", parking_total_spaces=parking_total_spaces,
                       parking_paid_capacity=parking_paid_capacity)
    set_clock(TEST_CLOCK_ISO)
    return site


class TestCapacityBoundary:
    def _setup_three_members(self):
        site = _setup_parking_site(parking_paid_capacity=2)
        members = [
            create_member_with_plate("AAA111", full_name="Driver One",
                                     email="one@x.com"),
            create_member_with_plate("BBB222", full_name="Driver Two",
                                     email="two@x.com"),
            create_member_with_plate("CCC333", vehicle_type="BOX_TRUCK",
                                     full_name="Driver Three",
                                     email="three@x.com"),
        ]
        return site, members

    def test_second_reservation_at_capacity_admitted(self, api):
        """PRD section 3.5: "Aggregate capacity is then enforced at every
        instant of the requested window: the count of overlapping
        reservations in `CONFIRMED` or `ACTIVE`, windows compared half-open,
        must stay strictly below the site's `parking_paid_capacity`, else
        `ERR_PARKING_CAPACITY_FULL` (HTTP 422)." — with capacity 2, the
        second reservation sees an existing count of 1, still below 2.

        Design: Difficulty/boundary_precision_check/parking_capacity_at_exact_limit
        """
        site, members = self._setup_three_members()
        r1 = create_parking_reservation(site["id"], members[0].member["id"],
                                        "AAA111")
        r2 = create_parking_reservation(site["id"], members[1].member["id"],
                                        "BBB222")
        assert r1["status"] == "CONFIRMED"
        assert r2["status"] == "CONFIRMED"

    def test_third_reservation_beyond_capacity_rejected(self, api):
        """PRD section 3.5: "the count of overlapping reservations in
        `CONFIRMED` or `ACTIVE`, windows compared half-open, must stay
        strictly below the site's `parking_paid_capacity`, else
        `ERR_PARKING_CAPACITY_FULL` (HTTP 422)" — the third reservation sees
        an existing count of 2, which is not below 2.

        Design: Difficulty/boundary_precision_check/parking_capacity_at_exact_limit
        """
        site, members = self._setup_three_members()
        create_parking_reservation(site["id"], members[0].member["id"], "AAA111")
        create_parking_reservation(site["id"], members[1].member["id"], "BBB222")

        from test_helpers.factories import create_parking_reservation_payload
        resp = api.create_parking_reservation(
            site["id"],
            create_parking_reservation_payload(members[2].member["id"], "CCC333"),
            CASH_1,
        )
        validate_error(resp, ApiErrorId.ERR_PARKING_CAPACITY_FULL)


class TestHalfOpenWindows:
    def _setup_single_capacity(self):
        site = _setup_parking_site(parking_paid_capacity=1)
        owner = create_member_with_plate("AAA111")
        return site, owner.member["id"]

    def test_adjacent_half_open_windows_do_not_overlap(self, api):
        """PRD section 2.5: "Time windows are half-open unless explicitly
        stated otherwise: a window runs from its start instant inclusive to
        its end instant exclusive."
        PRD section 3.5: "the count of overlapping reservations in
        `CONFIRMED` or `ACTIVE`, windows compared half-open, must stay
        strictly below the site's `parking_paid_capacity`".

        Design: Difficulty/resource_temporal_overlap/parking_half_open_windows_vs_aggregate_capacity
        """
        site, member_id = self._setup_single_capacity()
        r1 = create_parking_reservation(
            site["id"], member_id, "AAA111",
            reserved_from="2026-08-12T22:00:00Z",
            reserved_to="2026-08-13T06:00:00Z")
        r2 = create_parking_reservation(
            site["id"], member_id, "AAA111",
            reserved_from="2026-08-13T06:00:00Z",
            reserved_to="2026-08-13T10:00:00Z")
        assert r1["status"] == "CONFIRMED"
        assert r2["status"] == "CONFIRMED", (
            "a window starting exactly at another's reserved_to does not "
            "overlap under half-open semantics"
        )

    def test_tail_overlap_rejected(self, api):
        """PRD section 3.5: "the count of overlapping reservations in
        `CONFIRMED` or `ACTIVE`, windows compared half-open, must stay
        strictly below the site's `parking_paid_capacity`, else
        `ERR_PARKING_CAPACITY_FULL` (HTTP 422)".

        Design: Difficulty/resource_temporal_overlap/parking_half_open_windows_vs_aggregate_capacity
        """
        site, member_id = self._setup_single_capacity()
        create_parking_reservation(
            site["id"], member_id, "AAA111",
            reserved_from="2026-08-12T22:00:00Z",
            reserved_to="2026-08-13T06:00:00Z")
        create_parking_reservation(
            site["id"], member_id, "AAA111",
            reserved_from="2026-08-13T06:00:00Z",
            reserved_to="2026-08-13T10:00:00Z")

        from test_helpers.factories import create_parking_reservation_payload
        resp = api.create_parking_reservation(
            site["id"],
            create_parking_reservation_payload(
                member_id, "AAA111",
                reserved_from="2026-08-13T05:00:00Z",
                reserved_to="2026-08-13T07:00:00Z"),
            CASH_1,
        )
        validate_error(resp, ApiErrorId.ERR_PARKING_CAPACITY_FULL)


class TestPlateReferentialBeatsCapacity:
    def _setup_plate_conflict(self):
        site = _setup_parking_site(parking_paid_capacity=1)
        m1 = create_member_with_plate("AAA111", full_name="Driver One",
                                      email="one@x.com")
        m2 = create_member(full_name="Driver Two", email="two@x.com")
        r1 = create_parking_reservation(site["id"], m1.member["id"], "AAA111")
        return site, m1, m2, r1

    def test_dual_failure_returns_plate_not_registered(self, api):
        """PRD section 2.10: "Business rules evaluate last among the semantic
        checks, in the order safety (water bottoms), referential integrity of
        the commercial payload (pricing-mode shape, plate registration,
        contract fuel types), temporal windows (parking, price, bay
        schedule), capacity and stock constraints, and finally fiscal rules".
        PRD section 3.5: "The plate must belong to a `RegisteredVehicle`
        owned by that same member, else `ERR_PLATE_NOT_REGISTERED`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/plate_referential_beats_capacity_constraint
        """
        site, _, m2, _ = self._setup_plate_conflict()
        from test_helpers.factories import create_parking_reservation_payload
        resp = api.create_parking_reservation(
            site["id"],
            create_parking_reservation_payload(
                m2["id"], "AAA111",
                reserved_from="2026-08-12T23:00:00Z",
                reserved_to="2026-08-13T07:00:00Z"),
            CASH_1,
        )
        validate_error(resp, ApiErrorId.ERR_PLATE_NOT_REGISTERED)

    def test_rejected_reservation_not_persisted(self, api):
        """PRD section 3.5: "The plate must belong to a `RegisteredVehicle`
        owned by that same member, else `ERR_PLATE_NOT_REGISTERED`
        (HTTP 422)." — a rejected create leaves no reservation behind.

        Design: Difficulty/priority_pair_validation_conflict/plate_referential_beats_capacity_constraint
        """
        site, _, m2, r1 = self._setup_plate_conflict()
        from test_helpers.factories import create_parking_reservation_payload
        validate_error(
            api.create_parking_reservation(
                site["id"],
                create_parking_reservation_payload(
                    m2["id"], "AAA111",
                    reserved_from="2026-08-12T23:00:00Z",
                    reserved_to="2026-08-13T07:00:00Z"),
                CASH_1,
            ),
            ApiErrorId.ERR_PLATE_NOT_REGISTERED,
        )
        rows, meta = validate_paginated(
            api.list_parking_reservations(site["id"], GM)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == r1["id"]


class TestWindowShapeAndCharge:
    def test_parking_window_shape_violations(self, api):
        """PRD section 3.5: "The window must be well-formed: `reserved_from`
        at or after the current clock, `reserved_to` strictly after
        `reserved_from`, and the whole window no longer than 336 hours — two
        weeks — else `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/validation_parking_window_shape_errors
        """
        from test_helpers.factories import create_parking_reservation_payload

        site = _setup_parking_site(parking_paid_capacity=2)
        owner = create_member_with_plate("AAA111")

        cases = [
            # reserved_from in the past (clock is 2026-08-12T10:00:00Z)
            ("2026-08-12T09:00:00Z", "2026-08-12T17:00:00Z"),
            # reserved_to not strictly after reserved_from
            ("2026-08-12T22:00:00Z", "2026-08-12T21:00:00Z"),
            # 360-hour window exceeds the 336-hour maximum
            ("2026-08-12T22:00:00Z", "2026-08-27T22:00:00Z"),
        ]
        for reserved_from, reserved_to in cases:
            resp = api.create_parking_reservation(
                site["id"],
                create_parking_reservation_payload(
                    owner.member["id"], "AAA111",
                    reserved_from=reserved_from, reserved_to=reserved_to),
                CASH_1,
            )
            validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_parking_amount_grace_ceil_oversize_points(self, api):
        """PRD section 3.5: "the first 15 minutes are a grace allowance, so
        `paid_minutes` is the total minus 15, floored at zero. `billed_hours`
        is the paid minutes divided by 60 rounded up to the next whole hour,
        and the base charge is those hours at 300 cents each. An `OVERSIZED`
        reservation adds a flat 800-cent `oversize_fee_cents`" and "the
        redemption count is the smaller of `requested_redeem_points` and the
        member's `stack_cap_points`, worth half a cent each rounded half up,
        recorded as `points_discount_cents`, and the final `amount_cents` is
        base plus oversize minus the points value, floored at zero."

        Design: Corner/calculations/calc_parking_amount_grace_ceil_oversize_points
        """
        site = _setup_parking_site(parking_paid_capacity=10,
                                   parking_total_spaces=20)
        owner = create_member_with_plate("STD-1", points=500)
        from test_helpers.fixtures import create_member_vehicle_payload
        get = api.create_member_vehicle(
            owner.member["id"],
            create_member_vehicle_payload("OVR-2", "RV"),
            CASH_1,
        )
        validate_success(get, 201)

        r1 = create_parking_reservation(
            site["id"], owner.member["id"], "STD-1", "STANDARD",
            reserved_from="2026-08-12T22:15:00Z",
            reserved_to="2026-08-13T06:45:00Z")
        # 510 total minutes - 15 grace = 495 paid; ceil(495/60) = 9 hours
        assert r1["billed_hours"] == 9
        assert r1["paid_minutes"] == 495
        assert r1["amount_cents"] == 2700

        r2 = create_parking_reservation(
            site["id"], owner.member["id"], "OVR-2", "OVERSIZED",
            reserved_from="2026-08-12T22:15:00Z",
            reserved_to="2026-08-13T06:45:00Z")
        assert r2["oversize_fee_cents"] == 800
        assert r2["amount_cents"] == 3500

        r3 = create_parking_reservation(
            site["id"], owner.member["id"], "STD-1", "STANDARD",
            reserved_from="2026-08-13T22:15:00Z",
            reserved_to="2026-08-14T06:45:00Z",
            redeem_points=100)
        assert r3["points_discount_cents"] == 50
        assert r3["amount_cents"] == 2650

        from test_helpers.fixtures import reload_member
        member = reload_member(owner.member["id"])
        assert member["points_balance"] == 400  # 500 - 100 burned at creation

    def test_parking_no_show_grace_window(self, api):
        """PRD section 3.5: "When a driver simply never arrives, a cashier or
        shift manager marks the reservation `CONFIRMED → NO_SHOW` once the
        current clock has passed two hours after `reserved_from`; capacity is
        released and nothing else moves."
        PRD section 2.10: "the generic rule that the target entity must be in
        a state from which the requested transition exists fails with
        `ERR_INVALID_STATE` (HTTP 409)" — before the grace elapses the
        transition is not yet available.

        Design: Corner/state_machines/sm_parking_no_show_grace
        """
        site = _setup_parking_site(parking_paid_capacity=2)
        owner = create_member_with_plate("AAA111")
        reservation = create_parking_reservation(
            site["id"], owner.member["id"], "AAA111")

        set_clock("2026-08-12T23:30:00Z")  # within reserved_from + 2h
        early = api.parking_reservation_no_show(reservation["id"], CASH_1)
        validate_error(early, ApiErrorId.ERR_INVALID_STATE)

        set_clock("2026-08-13T00:31:00Z")  # past reserved_from + 2h
        marked = validate_success(
            api.parking_reservation_no_show(reservation["id"], CASH_1)
        )
        assert marked["status"] == "NO_SHOW"


class TestMemberSelfScope:
    def test_loyalty_member_self_scope(self, api):
        """PRD section 2.1: "When `X-User-Role` is `LoyaltyMember`,
        `X-User-ID` is the `id` of the acting `LoyaltyMember`; the caller may
        touch only resources whose `loyalty_member_id` equals `X-User-ID`"
        and "Violations of these entity-backed scoping rules are rejected
        with `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 3.5: "From `CONFIRMED` — by a cashier or the member
        themselves, while still `UNPAID` — the reservation moves to
        `CANCELLED`".

        Design: Corner/rbac/rbac_loyalty_member_self_scope
        """
        site = _setup_parking_site(parking_paid_capacity=2)
        member_a = create_member(full_name="Driver A", email="a@x.com")
        member_b = create_member(full_name="Driver B", email="b@x.com")
        a_headers = make_loyalty_member_headers(member_a["id"])

        from test_helpers.factories import create_member_vehicle_payload
        validate_success(
            api.create_member_vehicle(
                member_a["id"],
                create_member_vehicle_payload("AAA111", "TRACTOR"),
                a_headers,
            ),
            201,
        )
        reservation = create_parking_reservation(
            site["id"], member_a["id"], "AAA111", headers=a_headers)

        peek = api.get_loyalty_member(member_b["id"], a_headers)
        validate_error(peek, ApiErrorId.ERR_FORBIDDEN)

        cancelled = validate_success(
            api.parking_reservation_cancel(reservation["id"], a_headers)
        )
        assert cancelled["status"] == "CANCELLED"
