"""Workshop scheduling, delivery driver overlap, and subscription boundaries."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, get_success_data,
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order,
    TEST_USERS, make_customer_headers,
)


# -----------------------------------------------------------------------------
# Difficulty Rule 6 (instance 2): subscription selector empty set → MISSING_STOCK
# -----------------------------------------------------------------------------

class TestSubscriptionSelectorEmptyCandidateSet:

    def test_scheduler_flips_subscription_to_missing_stock_when_no_match(self, api):
        """PRD §3.6: "On a miss, an ACTIVE subscription flips to MISSING_STOCK
        while next_fulfillment_at is left unchanged so the scheduler retries on
        the next tick; the subscription's version bumps."
        PRD §3.6: "The candidate set is every StockUnit whose sale_status is
        FOR_SALE, whose health_status is HEALTHY, whose parent plant's care_tag
        equals the subscription's care_tag_preference, whose parent plant's
        light_tag equals the subscription's light_tag_preference".

        Design: Difficulty/boundary_precision_check/subscription_stock_selector_empty_candidate_set_flips_missing_stock
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="quinn@example.com", delivery_zone="ZONE_A")
        # A plant that mismatches the subscription's care/light preferences.
        plant = create_plant(
            name="Mismatched", light_tag="DIRECT", care_tag="EXPERT",
            weight_class="LIGHT", unit_price_cents=2500, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        sub = get_success_data(api.create_subscription(
            {
                "customer_id": customer["id"], "plan_tier": "STARTER",
                "care_tag_preference": "EASY", "light_tag_preference": "MEDIUM",
            },
            make_customer_headers(customer["id"]),
        ))
        set_clock("2026-05-05T00:00:00Z")
        summary = validate_success(api.scheduler_fulfill_subscriptions(TEST_USERS["manager_headers"]))
        assert summary["missed_count"] == 1
        after = get_success_data(api.get_subscription(sub["id"], make_customer_headers(customer["id"])))
        assert after["status"] == "MISSING_STOCK"

    def test_scheduler_missing_stock_leaves_next_fulfillment_unchanged(self, api):
        """PRD §3.6: "On a miss, an ACTIVE subscription flips to MISSING_STOCK
        while next_fulfillment_at is left unchanged so the scheduler retries on
        the next tick; the subscription's version bumps."

        Design: Difficulty/boundary_precision_check/subscription_stock_selector_empty_candidate_set_flips_missing_stock
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="quinn2@example.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Mismatched2", light_tag="DIRECT", care_tag="EXPERT",
            weight_class="LIGHT", unit_price_cents=2500, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        sub = get_success_data(api.create_subscription(
            {
                "customer_id": customer["id"], "plan_tier": "STARTER",
                "care_tag_preference": "EASY", "light_tag_preference": "MEDIUM",
            },
            make_customer_headers(customer["id"]),
        ))
        # next_fulfillment_at is set to 30 days after clock at create → 2026-05-01T00:00:00Z.
        original_next = sub["next_fulfillment_at"]
        set_clock("2026-05-05T00:00:00Z")
        validate_success(api.scheduler_fulfill_subscriptions(TEST_USERS["manager_headers"]))
        after = get_success_data(api.get_subscription(sub["id"], make_customer_headers(customer["id"])))
        # next_fulfillment_at should NOT have advanced on the miss.
        assert after["next_fulfillment_at"] == original_next


# -----------------------------------------------------------------------------
# Difficulty Rule 8: Resource temporal-overlap conflicts
# -----------------------------------------------------------------------------

class TestWorkshopRoomOverlapWithBuffer:

    def test_workshop_within_15min_buffer_rejected(self, api):
        """PRD §3.7: "The overlap check treats each workshop's window as the
        half-open interval from start_at inclusive to end_at exclusive, then
        extends by a 15-minute buffer on either side: a proposed workshop is
        rejected if its buffered window intersects the buffered window of any
        existing workshop sharing the room, whether or not the workshops belong
        to the same manager. The rejection carries ERR_WORKSHOP_OVERLAP (HTTP
        409)."

        Design: Difficulty/resource_temporal_overlap/workshop_room_half_open_with_15min_buffer
        """
        set_clock("2026-04-01T00:00:00Z")
        get_success_data(api.create_workshop(
            {
                "title": "Repot 101", "topic": "REPOTTING", "room_id": "STUDIO_A",
                "start_at": "2026-05-01T10:00:00Z", "end_at": "2026-05-01T12:00:00Z",
                "capacity": 10,
            },
            TEST_USERS["manager_headers"],
        ))
        # Second workshop starts 12:05Z — 5 min after prior end, inside 15-min buffer.
        r = api.create_workshop(
            {
                "title": "Light 101", "topic": "LIGHT_101", "room_id": "STUDIO_A",
                "start_at": "2026-05-01T12:05:00Z", "end_at": "2026-05-01T13:00:00Z",
                "capacity": 5,
            },
            TEST_USERS["manager_headers"],
        )
        validate_error(r, ApiErrorId.ERR_WORKSHOP_OVERLAP.value)


class TestDeliveryDriverDailyCapacity:

    def test_third_dispatch_exceeding_daily_capacity_rejected(self, api):
        """PRD §3.3: "the sum of the driver's total scheduled minutes on the UTC
        calendar day of window_start_at (across all SCHEDULED and DELIVERED
        assignments for that driver, plus the proposed window) must not exceed
        the driver's daily_capacity_minutes. Either failure raises
        ERR_DELIVERY_OVERLAP (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/delivery_driver_closed_interval_and_daily_capacity_aggregate
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="uma@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Ulla", daily_capacity_minutes=179)
        plant = create_plant(
            name="Palm", light_tag="BRIGHT_INDIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"], acquisition_date="2026-03-25T00:00:00Z")
        intake_stock_unit(plant["id"], acquisition_date="2026-03-26T00:00:00Z")
        intake_stock_unit(plant["id"], acquisition_date="2026-03-27T00:00:00Z")
        # Two dispatches at 60min each = 120 total scheduled.
        o1 = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(o1["id"], customer["id"])
        dispatch_order(o1["id"], driver["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z")
        o2 = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(o2["id"], customer["id"])
        dispatch_order(o2["id"], driver["id"], "2026-04-02T14:00:00Z", "2026-04-02T15:00:00Z")
        # Third dispatch: disjoint window but 120+60=180 > 179 → capacity breach.
        o3 = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(o3["id"], customer["id"])
        r = api.dispatch_order(
            o3["id"],
            {"driver_id": driver["id"],
             "window_start_at": "2026-04-02T16:00:00Z",
             "window_end_at": "2026-04-02T17:00:00Z"},
            TEST_USERS["shop_staff_headers"],
        )
        validate_error(r, ApiErrorId.ERR_DELIVERY_OVERLAP.value)


# -----------------------------------------------------------------------------
# Corner: workshop capacity + too-late
# -----------------------------------------------------------------------------

class TestWorkshopCapacityAndTiming:

    def test_workshop_registration_capacity_full_rejected(self, api):
        """PRD §3.7: "the count of existing WorkshopRegistration rows under this
        workshop whose status is either REGISTERED or ATTENDED must be strictly
        less than Workshop.capacity, otherwise the request is rejected with
        ERR_WORKSHOP_FULL (HTTP 409)."

        Design: Corner/validations/workshop_register_capacity_reached_returns_workshop_full
        """
        set_clock("2026-04-01T00:00:00Z")
        cust_a = register_customer(email="c9@x.com", delivery_zone="ZONE_A")
        cust_b = register_customer(email="c10@x.com", delivery_zone="ZONE_A")
        w = get_success_data(api.create_workshop(
            {
                "title": "Small", "topic": "REPOTTING", "room_id": "STUDIO_A",
                "start_at": "2026-05-01T10:00:00Z", "end_at": "2026-05-01T12:00:00Z",
                "capacity": 1,
            },
            TEST_USERS["manager_headers"],
        ))
        get_success_data(api.register_workshop(
            w["id"], {"customer_id": cust_a["id"]}, make_customer_headers(cust_a["id"])
        ))
        r = api.register_workshop(
            w["id"], {"customer_id": cust_b["id"]}, make_customer_headers(cust_b["id"])
        )
        validate_error(r, ApiErrorId.ERR_WORKSHOP_FULL.value)

    def test_workshop_registration_too_late_rejected(self, api):
        """PRD §3.7: "registration must occur strictly earlier than 24 hours
        before the workshop's start_at. A registration attempt when the logical
        clock is at or after 24 hours before start_at is rejected with
        ERR_WORKSHOP_TOO_LATE (HTTP 422)."

        Design: Corner/validations/workshop_register_too_late_returns_workshop_too_late
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c11@x.com", delivery_zone="ZONE_A")
        w = get_success_data(api.create_workshop(
            {
                "title": "Late", "topic": "REPOTTING", "room_id": "STUDIO_A",
                "start_at": "2026-05-01T10:00:00Z", "end_at": "2026-05-01T12:00:00Z",
                "capacity": 10,
            },
            TEST_USERS["manager_headers"],
        ))
        # start_at - 12h = 2026-04-30T22:00Z, well inside the 24h cutoff.
        set_clock("2026-04-30T22:00:00Z")
        r = api.register_workshop(
            w["id"], {"customer_id": customer["id"]}, make_customer_headers(customer["id"])
        )
        validate_error(r, ApiErrorId.ERR_WORKSHOP_TOO_LATE.value)
