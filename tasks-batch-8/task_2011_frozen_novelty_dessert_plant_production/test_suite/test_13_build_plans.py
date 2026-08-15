"""Seasonal build plans: shelf-life window and zone week capacity
(PRD §3.11)."""
from test_helpers import (
    ApiErrorId,
    create_build_plan,
    create_freezer_zone,
    create_product,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PM
from test_helpers.factories import create_product_payload


class TestShelfLifeWindow:
    def test_shelf_life_window_exact_fit_approved(self, api):
        """PRD §3.11: "The shelf-life window gate requires the number of
        whole days between production_week_start and sale_week_start, plus a
        30-day minimum-remaining-shelf buffer, to be no greater than the
        product's shelf_life_days — the boundary is inclusive, so equality
        passes". 2026-10-05 -> 2027-04-03 is 180 days; 180 + 30 == 210 ==
        shelf_life_days, so approval passes.

        Design: Corner/calculations/shelf_life_window_exact_fit_approved
        """
        product = create_product(**create_product_payload(
            sku_code="SHELF-210", product_name="Short Shelf Bar",
            flavor_family="FRUIT", shelf_life_days=210))
        zone = create_freezer_zone(zone_code="Z-A")
        plan = create_build_plan(product["id"], zone["id"],
                                 plan_code="BP-FIT",
                                 production_week_start="2026-10-05",
                                 sale_week_start="2027-04-03",
                                 target_units=1000)
        assert plan["required_pallets"] == 10  # ceil(1000/100)
        approved = validate_success(api.approve_build_plan(plan["id"], PM))
        assert approved["status"] == "APPROVED"

    def test_shelf_life_window_one_day_over_rejected(self, api):
        """PRD §3.11: "a violation rejects with ERR_SHELF_LIFE_WINDOW
        (HTTP 422)." Same dates but shelf_life_days 209: 180 + 30 == 210 >
        209, so one day of shelf life flips the outcome.

        Design: Corner/calculations/shelf_life_window_one_day_over_rejected
        """
        product = create_product(**create_product_payload(
            sku_code="SHELF-209", product_name="Shorter Shelf Bar",
            flavor_family="FRUIT", shelf_life_days=209))
        zone = create_freezer_zone(zone_code="Z-A")
        plan = create_build_plan(product["id"], zone["id"],
                                 plan_code="BP-OVER",
                                 production_week_start="2026-10-05",
                                 sale_week_start="2027-04-03",
                                 target_units=1000)
        resp = api.approve_build_plan(plan["id"], PM)
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_WINDOW)
        plan_after = get_success_data(api.get_seasonal_build_plan(plan["id"], PM))
        assert plan_after["status"] == "DRAFT"


class TestZoneWeekCapacity:
    def test_plan_week_capacity_bucket_rejected(self, api):
        """PRD §3.11: "The zone week-capacity gate sums required_pallets
        over all APPROVED plans sharing this plan's zone_id and
        production_week_start, adds this plan's required_pallets, and
        requires the total to be no greater than the zone's
        pallet_capacity; a violation rejects with ERR_ZONE_CAPACITY_EXCEEDED
        (HTTP 422)." Zone cap 2; approved plan A takes 2; plan B in the same
        week needs 1 more -> 3 > 2 rejected.

        Design: Corner/calculations/plan_week_capacity_bucket_rejected
        """
        product = create_product()
        zone = create_freezer_zone(zone_code="Z-W", pallet_capacity=2)
        plan_a = create_build_plan(product["id"], zone["id"],
                                   plan_code="BP-W1",
                                   production_week_start="2026-10-05",
                                   sale_week_start="2026-12-28",
                                   target_units=150)
        validate_success(api.approve_build_plan(plan_a["id"], PM))
        plan_b = create_build_plan(product["id"], zone["id"],
                                   plan_code="BP-W2",
                                   production_week_start="2026-10-05",
                                   sale_week_start="2026-12-28",
                                   target_units=100)
        resp = api.approve_build_plan(plan_b["id"], PM)
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)
        plan_b_after = get_success_data(
            api.get_seasonal_build_plan(plan_b["id"], PM))
        assert plan_b_after["status"] == "DRAFT"


class TestPlanTerminalState:
    def test_plan_approve_after_cancel_rejected(self, api):
        """PRD §3.11: "Cancellation moves from DRAFT or APPROVED to
        CANCELED." CANCELED is terminal, so approving a canceled plan fails
        the state gate (§5 ERR_INVALID_STATE: "Target resource's state does
        not allow the requested transition")."

        Design: Corner/state_machines/plan_approve_after_cancel_rejected
        """
        product = create_product()
        zone = create_freezer_zone(zone_code="Z-A")
        plan = create_build_plan(product["id"], zone["id"], plan_code="BP-X",
                                 production_week_start="2026-10-05",
                                 sale_week_start="2027-04-03",
                                 target_units=1000)
        validate_success(api.cancel_build_plan(plan["id"], PM))
        resp = api.approve_build_plan(plan["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
