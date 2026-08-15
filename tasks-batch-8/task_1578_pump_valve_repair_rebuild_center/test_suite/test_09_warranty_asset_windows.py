"""Repair order intake: closed-interval asset service windows and warranty
eligibility day boundaries."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_repair_order,
    create_asset,
    create_customer,
    create_repair_order,
    create_repair_order_payload,
    get_repair_order,
    get_success_data,
    set_clock,
    setup_closed_shop,
    validate_error,
    validate_paginated,
    validate_success,
)

SM = TEST_USERS["service_manager_headers"]
IC = TEST_USERS["intake_coordinator_headers"]


class TestAssetServiceWindowOverlap:
    def test_closed_interval_touching_endpoints_conflict(self, api):
        """PRD §3.3: "The planned service window runs from `planned_start_date` through `planned_end_date`, both calendar dates, and the window is a closed interval — inclusive at both ends."
        PRD §3.3: "Two non-terminal repair orders for the same asset may not hold overlapping planned windows; because the interval is closed, even touching endpoints conflict, and an overlapping intake is rejected with `ERR_ASSET_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/asset_service_window_closed_interval_overlap
        """
        customer = create_customer(name="Red River Paper", account_number="RR-960",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-9601")
        ro1 = create_repair_order(customer["id"], asset["id"],
                                  planned_start_date="2026-08-10",
                                  planned_end_date="2026-08-20",
                                  estimated_bay_hours=10)
        assert ro1["status"] == "RECEIVED"

        # Touching the end date: 08-20 belongs to both closed intervals.
        touching = api_client.create_repair_order(
            create_repair_order_payload(
                customer["id"], asset["id"], failure_mode="OTHER",
                failure_description="recheck", planned_start_date="2026-08-20",
                planned_end_date="2026-08-25", estimated_bay_hours=4),
            IC)
        validate_error(touching, ApiErrorId.ERR_ASSET_WINDOW_OVERLAP)

        # Starting the day after: no overlap.
        clear = validate_success(api_client.create_repair_order(
            create_repair_order_payload(
                customer["id"], asset["id"], failure_mode="OTHER",
                failure_description="recheck", planned_start_date="2026-08-21",
                planned_end_date="2026-08-25", estimated_bay_hours=4),
            IC), 201)
        assert clear["status"] == "RECEIVED"

        data, meta = validate_paginated(api_client.list_repair_orders(
            SM, params={"asset_id": asset["id"]}))
        assert meta["total_count"] == 2
        assert all(o["status"] == "RECEIVED" for o in data)

    def test_front_touch_conflicts_and_other_asset_is_unaffected(self, api):
        """PRD §3.3: "Two non-terminal repair orders for the same asset may not hold overlapping planned windows; because the interval is closed, even touching endpoints conflict, and an overlapping intake is rejected with `ERR_ASSET_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/asset_service_window_closed_interval_overlap
        """
        customer = create_customer(name="Sabine", account_number="SA-961",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-9611")
        other_asset = create_asset(customer["id"], serial_number="V-9612")
        create_repair_order(customer["id"], asset["id"],
                            planned_start_date="2026-08-10",
                            planned_end_date="2026-08-20", estimated_bay_hours=10)

        # Ending exactly on the existing order's start date conflicts.
        front_touch = api_client.create_repair_order(
            create_repair_order_payload(
                customer["id"], asset["id"], failure_mode="OTHER",
                failure_description="front", planned_start_date="2026-08-01",
                planned_end_date="2026-08-10", estimated_bay_hours=4),
            IC)
        validate_error(front_touch, ApiErrorId.ERR_ASSET_WINDOW_OVERLAP)

        # Ending the day before is clear.
        front_clear = validate_success(api_client.create_repair_order(
            create_repair_order_payload(
                customer["id"], asset["id"], failure_mode="OTHER",
                failure_description="front", planned_start_date="2026-08-01",
                planned_end_date="2026-08-09", estimated_bay_hours=4),
            IC), 201)
        assert front_clear["status"] == "RECEIVED"

        # The overlap rule is per asset: identical dates on another asset pass.
        other = validate_success(api_client.create_repair_order(
            create_repair_order_payload(
                customer["id"], other_asset["id"], failure_mode="OTHER",
                failure_description="other asset", planned_start_date="2026-08-10",
                planned_end_date="2026-08-20", estimated_bay_hours=4),
            IC), 201)
        assert other["status"] == "RECEIVED"

    def test_cancelled_order_frees_its_window(self, api):
        """PRD §3.3: "Two non-terminal repair orders for the same asset may not hold overlapping planned windows; because the interval is closed, even touching endpoints conflict, and an overlapping intake is rejected with `ERR_ASSET_WINDOW_OVERLAP`."

        Design: Corner/calculations/asset_overlap_ignores_terminal_orders
        """
        customer = create_customer(name="Raton", account_number="RA-270",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-2701")
        ro1 = create_repair_order(customer["id"], asset["id"],
                                  planned_start_date="2026-08-10",
                                  planned_end_date="2026-08-20",
                                  estimated_bay_hours=5)
        get_success_data(api_client.cancel_repair_order(ro1["id"], IC))
        assert get_repair_order(ro1["id"])["status"] == "CANCELLED"

        # The cancelled order is terminal: its interval no longer participates.
        ro2 = validate_success(api_client.create_repair_order(
            create_repair_order_payload(
                customer["id"], asset["id"], failure_mode="OTHER",
                failure_description="retry", planned_start_date="2026-08-10",
                planned_end_date="2026-08-20", estimated_bay_hours=5),
            IC), 201)
        assert ro2["status"] == "RECEIVED"


class TestWarrantyEligibility:
    def test_day_boundary_inclusive_and_ineligible_paths(self, api):
        """PRD §3.3: "Eligibility requires every one of the following: the parent order exists and is `CLOSED`; it covers the same `asset_id`; it belongs to the same `customer_id`; and the whole days between the parent's `closed_at` and the current logical clock — elapsed seconds divided by 86,400 and rounded down — do not exceed the customer's `warranty_terms_days`."
        PRD §3.3: "The day boundary is inclusive: an intake exactly `warranty_terms_days` days after the parent's closure still qualifies. Failing any condition rejects the creation with `ERR_WARRANTY_NOT_ELIGIBLE`."
        PRD §3.3: "When eligibility holds, the new order's `warranty_case` is set true — which later forces the `WARRANTY` pricing variant on its quotes — and `repeat_failure_flag` is set true exactly when the parent's `failure_mode` matches the new order's, feeding re-repair analysis."

        Design: Corner/calculations/warranty_window_boundary_and_ineligible_paths
        """
        # Parent order on asset 1 closes at the default clock 2026-08-01.
        shop = setup_closed_shop(
            customer_over={"warranty_terms_days": 30},
            asset_over={"equipment_class": "PUMP", "serial_number": "P-2801"},
            ro_over={"failure_mode": "SEAL_LEAK"})
        parent = shop["ro"]
        assert parent["status"] == "CLOSED"
        asset2 = create_asset(shop["customer"]["id"], serial_number="P-2802",
                              equipment_class="PUMP")

        cust_id = shop["customer"]["id"]
        a1 = shop["asset"]["id"]

        def claim(asset_id, description, start, end):
            return api_client.create_repair_order(
                create_repair_order_payload(
                    cust_id, asset_id, failure_mode="SEAL_LEAK",
                    failure_description=description,
                    planned_start_date=start, planned_end_date=end,
                    estimated_bay_hours=5, warranty_parent_ro_id=parent["id"]),
                IC)

        # Exactly 30 days after closure: still eligible.
        set_clock("2026-08-31T00:00:00Z")
        on_boundary = validate_success(
            claim(a1, "again", "2026-09-05", "2026-09-15"), 201)
        assert_repair_order(on_boundary)
        assert on_boundary["warranty_case"] is True
        assert on_boundary["repeat_failure_flag"] is True

        # 31 days after closure: outside the terms.
        set_clock("2026-09-01T00:00:00Z")
        too_late = claim(a1, "late claim", "2026-09-20", "2026-09-25")
        validate_error(too_late, ApiErrorId.ERR_WARRANTY_NOT_ELIGIBLE)

        # Same window but a different asset than the parent's: ineligible.
        wrong_asset = claim(asset2["id"], "wrong asset claim",
                            "2026-09-20", "2026-09-25")
        validate_error(wrong_asset, ApiErrorId.ERR_WARRANTY_NOT_ELIGIBLE)
