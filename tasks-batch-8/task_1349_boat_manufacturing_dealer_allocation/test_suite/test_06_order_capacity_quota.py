"""Booking gates: slot hours capacity (equality allowed) and dealer allocation
quota (equality rejected) — boundary precision on two metrics (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dealer_order,
    book_order,
    book_order_no_options,
    book_order_tower_ballast,
    create_dealer_order_payload,
    create_option,
    create_run,
    create_slot,
    create_model,
    create_dealer,
    get_dealer,
    get_slot,
    make_dealer_principal_headers,
    setup_bookable_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestSlotCapacityBoundary:
    def test_slot_capacity_equality_allows_booking(self, api):
        """PRD §3.4: "the fit check then requires the slot's `reserved_hours`
        plus the order's `production_hours` to be no greater than
        `capacity_hours` — landing exactly at capacity is allowed, exceeding it
        draws `ERR_SLOT_CAPACITY_EXCEEDED`."

        Model 40h + WAKE-TOWER 6h + BALLAST 4h = 50 hours on a 50-hour slot:
        equality is allowed.

        Design: Difficulty/boundary_precision_check/slot_capacity_equality_allows_booking
        """
        world = setup_bookable_world(api, capacity_hours=50)
        order = book_order_tower_ballast(
            api, world["dealer"], world["model"], world["tower"],
            world["ballast"], slot_id=world["slot"]["id"],
        )
        assert order["status"] == "ALLOCATED"
        assert order["production_hours"] == 50
        slot = get_slot(api, world["slot"]["id"])
        assert slot["reserved_hours"] == 50, (
            f"reserved_hours must reach exactly capacity, got {slot['reserved_hours']}"
        )

    def test_slot_capacity_exceeded_by_one_hour_rejected(self, api):
        """PRD §3.4: "the fit check then requires the slot's `reserved_hours`
        plus the order's `production_hours` to be no greater than
        `capacity_hours` — landing exactly at capacity is allowed, exceeding it
        draws `ERR_SLOT_CAPACITY_EXCEEDED`."

        51 hours on a 50-hour slot: one hour over the boundary rejects.

        Design: Difficulty/boundary_precision_check/slot_capacity_equality_allows_booking
        """
        world = setup_bookable_world(api, capacity_hours=50)
        trim = create_option(
            api, world["model"]["id"], option_code="TRIM",
            price_cents=100000, production_hours=5,
        )
        # 40 + 6 + 5 = 51 production hours > 50 capacity.
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                world["dealer"]["id"], world["model"]["id"],
                deposit_paid_cents=301533,
                option_package_ids=[world["tower"]["id"], trim["id"]],
                slot_id=world["slot"]["id"],
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)


class TestQuotaBoundary:
    def test_quota_equality_blocks_second_booking(self, api):
        """PRD §3.4: "Either way, the dealer must have quota headroom:
        `allocation_used` must be strictly below `annual_allocation_quota`, with
        equality rejecting as `ERR_QUOTA_EXCEEDED` — a dealer one below quota
        books successfully and lands exactly at quota."

        Quota 1: the first ALLOCATED booking lands used == 1 == quota; the
        second booking hits equality and is rejected.

        Design: Difficulty/boundary_precision_check/quota_equality_blocks_second_booking
        """
        world = setup_bookable_world(api, with_options=False, quota=1)
        slot2 = create_slot(api, world["run"]["id"], slot_code="S2",
                            capacity_hours=200)
        o1 = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        assert o1["status"] == "ALLOCATED"
        assert get_dealer(api, world["dealer"]["id"])["allocation_used"] == 1
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                world["dealer"]["id"], world["model"]["id"],
                deposit_paid_cents=257500, slot_id=slot2["id"],
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUOTA_EXCEEDED)
        # The rejected booking is not persisted; only the first order exists.
        data, meta = validate_paginated(
            api.list_dealer_orders(ANY, params={"dealer_id": world["dealer"]["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == o1["id"]
        assert data[0]["status"] == "ALLOCATED"

    def test_waitlisted_entry_does_not_consume_quota(self, api):
        """PRD §3.4: "When no slot fits, the order lands in `WAITLISTED` with
        `slot_id` null — the quota gate does not apply to waitlisted entries,
        which by definition hold no committed production."
        PRD §3.4: "`allocation_used` must be strictly below
        `annual_allocation_quota`, with equality rejecting as
        `ERR_QUOTA_EXCEEDED` — a dealer one below quota books successfully and
        lands exactly at quota."

        Quota 1 with a WAITLISTED order already held: the waitlisted entry is
        not counted, so a subsequent slot-securing booking still succeeds and
        lands the dealer exactly at quota.

        Design: Difficulty/boundary_precision_check/quota_equality_blocks_second_booking
        """
        model = create_model(api)
        dealer = create_dealer(api, annual_allocation_quota=1)
        # No slots exist -> WAITLISTED, and no allocation consumed.
        o_wait = book_order_no_options(api, dealer, model)
        assert o_wait["status"] == "WAITLISTED"
        assert get_dealer(api, dealer["id"])["allocation_used"] == 0
        # Open capacity; booking secures the slot (used 0 < quota 1).
        run = create_run(api)
        slot = create_slot(api, run["id"], slot_code="S1", capacity_hours=200)
        o2 = book_order_no_options(api, dealer, model, slot_id=slot["id"])
        assert o2["status"] == "ALLOCATED"
        assert get_dealer(api, dealer["id"])["allocation_used"] == 1
