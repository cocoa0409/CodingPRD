"""Bulk tank reorder projections, fuel-quality water bottoms, stock posture
gating of shop parts, and the computed operations dashboard."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_fuel_sale_payload,
    create_parking_reservation,
    post_fuel_price,
    set_clock,
    setup_shift_site,
    setup_work_order_in_progress,
    validate_error,
    validate_success,
    api_client,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.factories import (
    create_bulk_tank_payload,
    create_service_ticket_payload,
    issue_part_payload,
    parking_check_in_payload,
    stick_reading_payload,
    tank_delivery_payload,
)
from test_helpers.fixtures import (
    CASH_1,
    FDL,
    GM,
    SM_2,
    create_member_with_plate,
    create_parking_space,
    create_pump,
    create_register,
    create_service_ticket,
    create_site,
    create_stock_item,
    make_maintenance_tech_headers,
    open_shift,
    receive_stock_via_po,
    reload_stock_item,
)


def _suggestion_values(data):
    """Extract the suggested-gallon figure from each suggestion row. The PRD
    pins the computation and the emission rule; each row is matched by its
    numeric payload."""
    rows = data["suggestions"] if isinstance(data, dict) else data
    values = []
    for row in rows:
        if isinstance(row, dict) and "suggested_gallons" in row:
            values.append(row["suggested_gallons"])
        elif isinstance(row, dict):
            numerics = [v for v in row.values()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)]
            values.append(max(numerics) if numerics else None)
        else:
            values.append(row)
    return values


class TestReorderSuggestions:
    def test_reorder_suggestions_three_products(self, api):
        """PRD section 3.9: "the projected level is `current_gallons` minus
        `daily_usage_gallons` multiplied by `lead_time_days`; the target fill
        is ninety percent of `capacity_gallons`; and the suggestion is the
        target minus the projection plus the safety stock, floored at zero,
        emitted only for tanks whose current level is at or below the reorder
        threshold." and "For `OIL` product with a matching `PACKAGED_OIL`
        stock item carrying `case_pack_gallons`, the suggestion is rounded up
        to whole case packs".

        Design: Corner/calculations/calc_reorder_suggestions_three_products
        """
        site = create_site("Site C2")
        api_call = api.create_bulk_tank
        validate_success(api_call(
            site["id"],
            create_bulk_tank_payload(
                product_type="DIESEL", capacity_gallons=20000,
                reorder_threshold_gallons=9000, safety_stock_gallons=1500,
                daily_usage_gallons=950, lead_time_days=4,
                initial_gallons=8500, rack_price_cents_per_gallon_4dp=2.7000),
            GM), 201)
        validate_success(api_call(
            site["id"],
            create_bulk_tank_payload(
                product_type="DEF", capacity_gallons=550,
                reorder_threshold_gallons=400, safety_stock_gallons=60,
                daily_usage_gallons=18, lead_time_days=2, initial_gallons=320),
            GM), 201)
        validate_success(api_call(
            site["id"],
            create_bulk_tank_payload(
                product_type="OIL", capacity_gallons=120,
                reorder_threshold_gallons=60, safety_stock_gallons=10,
                daily_usage_gallons=2, lead_time_days=2, initial_gallons=54),
            GM), 201)
        create_stock_item(
            site["id"], sku="OIL-5W30", name="5W30 case",
            category="PACKAGED_OIL", unit="case", unit_price_cents=2400,
            reorder_point=3, initial_on_hand_quantity=12, case_pack_gallons=4,
        )

        data = validate_success(api.get_reorder_suggestions(site["id"], FDL))
        values = _suggestion_values(data)
        assert len(values) == 3, "all three tanks sit at/below threshold"
        # DIESEL: 0.90x20000 - (8500 - 950x4) + 1500 = 18000 - 4700 + 1500
        # DEF: 495 - 284 + 60; OIL: raw 108 - 50 + 10 = 68 -> ceil(68/4)=17 cases
        for expected in (14800.0, 271.0, 68.0):
            assert any(v == pytest.approx(expected) for v in values), (
                f"expected a suggestion of {expected} gallons, got {values}"
            )


class TestWaterBottomQualityGate:
    def test_water_bottom_exceeded_delivery_and_stick(self, api):
        """PRD section 3.9: "Fuel quality gates both paths: a reported water
        bottom above 1.0 inches is rejected with `ERR_WATER_BOTTOM_EXCEEDED`
        (HTTP 422)."

        Design: Corner/validations/validation_water_bottom_over_limit_delivery_and_stick
        """
        site = create_site("Site V11")
        tank = validate_success(
            api.create_bulk_tank(
                site["id"],
                create_bulk_tank_payload(
                    product_type="DEF", capacity_gallons=550,
                    reorder_threshold_gallons=150, safety_stock_gallons=60,
                    daily_usage_gallons=18, lead_time_days=2,
                    initial_gallons=320),
                GM),
            201,
        )

        delivery = api.tank_delivery(
            tank["id"],
            tank_delivery_payload(100.0, water_bottom_inches=1.5),
            FDL,
        )
        validate_error(delivery, ApiErrorId.ERR_WATER_BOTTOM_EXCEEDED)

        stick = api.tank_stick_reading(
            tank["id"],
            stick_reading_payload(300.0, water_bottom_inches=1.2),
            FDL,
        )
        validate_error(stick, ApiErrorId.ERR_WATER_BOTTOM_EXCEEDED)

        tank_now = validate_success(api.get_bulk_tank(tank["id"], FDL))
        assert tank_now["current_gallons"] == pytest.approx(320)


class TestPartIssueGatedByStockPosture:
    def _setup_low_stock_work_order(self):
        site = create_site("Site N")
        set_clock(TEST_CLOCK_ISO)
        item = create_stock_item(
            site["id"], sku="FILTER-X", name="Filter X", category="SHOP_PART",
            unit_price_cents=4599, reorder_point=10, initial_on_hand_quantity=5,
        )
        shop = setup_work_order_in_progress(site=site)
        return site, item, shop

    def test_part_issue_blocked_while_low_stock(self, api):
        """PRD section 3.7: "it is blocked outright while the item's
        `is_low_stock` is true — replenish first, the rejection being
        `ERR_LOW_STOCK_APPROVAL_REQUIRED` (HTTP 422)".
        PRD section 3.6: "`is_low_stock` is true exactly when
        `on_hand_quantity` is at or below `reorder_point`, recomputed on
        every mutation."

        Design: Difficulty/cross_entity_state_dependency/part_issue_gated_by_stock_posture
        """
        _, item, shop = self._setup_low_stock_work_order()
        assert item["is_low_stock"] is True  # on_hand 5 <= reorder_point 10

        resp = api.work_order_issue_part(
            shop.wo["id"], issue_part_payload(item["id"], 3), shop.tech_headers
        )
        validate_error(resp, ApiErrorId.ERR_LOW_STOCK_APPROVAL_REQUIRED)

    def test_part_issue_succeeds_after_replenishment(self, api):
        """PRD section 3.6: "Each receipt grows the matched stock item's
        `on_hand_quantity` by the received quantity with `is_low_stock`
        recomputed" and "An issue decrements `on_hand_quantity`, recomputes
        `is_low_stock`, and writes a `WorkOrderPart` bound to its order by
        `work_order_id`, in status `ISSUED`".

        Design: Difficulty/cross_entity_state_dependency/part_issue_gated_by_stock_posture
        """
        site, item, shop = self._setup_low_stock_work_order()
        po = receive_stock_via_po(site["id"], "FILTER-X", 20, 3000)
        assert po["status"] == "RECEIVED"

        replenished = reload_stock_item(item["id"])
        assert replenished["on_hand_quantity"] == 25
        assert replenished["is_low_stock"] is False

        part = validate_success(
            api.work_order_issue_part(
                shop.wo["id"], issue_part_payload(item["id"], 3),
                shop.tech_headers,
            ),
            201,
        )
        assert part["quantity"] == 3
        assert part["status"] == "ISSUED"
        assert reload_stock_item(item["id"])["on_hand_quantity"] == 22


class TestDashboard:
    def test_dashboard_computed_read(self, api):
        """PRD section 3.1: "a computed operations dashboard returns
        `pumps_total`, `pumps_in_use`, `parking_active_count`,
        `shower_queue_depth`, `laundry_queue_depth`, and `low_stock_count`
        for managers and the fuel desk."
        PRD section 3.5: "The space selector draws from the pool of spaces at
        the site whose `space_type` matches the reservation, whose status is
        `ACTIVE`, whose `is_reservable` is true, and to which no other
        `ACTIVE` reservation is currently assigned, ranked by `space_number`
        ascending".

        Design: Corner/endpoints/endpoint_dashboard_computed_read
        """
        site = create_site("Site E2", parking_total_spaces=10,
                           parking_paid_capacity=2, shower_units_count=1,
                           laundry_machines_count=1)
        post_fuel_price(site["id"], "DIESEL", 385)
        set_clock(TEST_CLOCK_ISO)
        pump1 = create_pump(site["id"], 1, ("DIESEL",))
        create_pump(site["id"], 2, ("DIESEL",))
        space = create_parking_space(site["id"], "A1", "STANDARD", True)
        register = create_register(site["id"])
        shift = open_shift(site["id"], register["id"])
        owner = create_member_with_plate("AAA111")
        reservation = create_parking_reservation(
            site["id"], owner.member["id"], "AAA111")
        create_service_ticket(site["id"], "SHOWER", shift_id=shift["id"])
        create_stock_item(
            site["id"], sku="SNACK-A", name="Snack A", category="RETAIL",
            unit_price_cents=999, reorder_point=10, initial_on_hand_quantity=5,
        )
        # An authorized sale holds pump 1 IN_USE.
        validate_success(
            api.create_fuel_sale(
                site["id"],
                create_fuel_sale_payload(
                    pump1["id"], shift["id"], pricing_mode="RETAIL",
                    fuel_type="DIESEL", tender_type="CARD", max_gallons=10.0),
                CASH_1),
            201,
        )

        set_clock("2026-08-12T22:30:00Z")
        checked_in = validate_success(
            api.parking_reservation_check_in(
                reservation["id"],
                parking_check_in_payload("CARD", shift["id"]),
                CASH_1,
            )
        )
        assert checked_in["assigned_space_id"] == space["id"]

        dashboard = validate_success(api.get_site_dashboard(site["id"], SM_2))
        assert dashboard["pumps_total"] == 2
        assert dashboard["pumps_in_use"] == 1
        assert dashboard["parking_active_count"] == 1
        assert dashboard["shower_queue_depth"] == 1
        assert dashboard["laundry_queue_depth"] == 0
        assert dashboard["low_stock_count"] == 1
