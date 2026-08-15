"""Reconciliation: pinned cost rounding order and the strict waste-ratio
threshold."""
import pytest

from test_helpers import (
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    allocate,
    confirm_item,
    create_accepted_batch,
    create_food_batch,
    create_guest,
    create_menu_day,
    create_menu_item,
    create_order,
    create_service,
    create_shift,
    create_site,
    create_volunteer,
    create_waste_log,
    get_menu_day,
    inspect_batch,
    lock_forecast,
    open_service,
    prep_order_to_ready,
    set_clock,
    start_production,
)
from test_helpers.test_users import make_volunteer_headers


def _build_rounding_scenario(api):
    """Two PURCHASE batches at 33.335 cents/serving, each feeding an item of
    planned 3; two orders served (3 + 1) so served_count is 4; day
    reconciled.  PRD 3.8 pins the arithmetic for exactly this shape."""
    set_clock("2026-08-10T08:00:00Z")
    site = create_site(name="Round Kitchen", dine_in_capacity=50,
                       togo_capacity_per_window=20, delivery_radius_km=8)
    b1 = create_food_batch(
        site["id"], source_type="PURCHASE", item_description="apples",
        quantity_servings=4, received_at="2026-08-10T07:00:00Z",
        use_by="2026-08-12T00:00:00Z", unit_cost_cents_per_serving=33.335,
    )
    inspect_batch(b1["id"], "PASSED")
    b2 = create_food_batch(
        site["id"], source_type="PURCHASE", item_description="bread",
        quantity_servings=4, received_at="2026-08-10T07:05:00Z",
        use_by="2026-08-12T00:00:00Z", unit_cost_cents_per_serving=33.335,
    )
    inspect_batch(b2["id"], "PASSED")
    menu_day = create_menu_day(site["id"], "2026-08-10")
    i1 = create_menu_item(menu_day["id"], name="Apple Cup", planned_servings=3)
    allocate(i1["id"], b1["id"], 3)
    confirm_item(i1["id"])
    i2 = create_menu_item(menu_day["id"], name="Bread Cup", planned_servings=3)
    allocate(i2["id"], b2["id"], 3)
    confirm_item(i2["id"])
    guest = create_guest(full_name="G Four", household_size=4)
    volunteer = create_volunteer(full_name="Vol R")
    lock_forecast(menu_day["id"])
    start_production(menu_day["id"])
    service = create_service(
        menu_day["id"], service_model="DINE_IN",
        window_start="2026-08-10T11:00:00Z",
        window_end="2026-08-10T13:00:00Z", capacity=10,
    )
    # PREP role: start-prep requires a CHECKED_IN PREP or COOK shift covering
    # the current instant (PRD 3.7); serve carries no role requirement.
    shift = create_shift(
        site["id"], volunteer["id"], menu_day["id"], role_on_shift="PREP",
        starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T14:00:00Z",
    )
    set_clock("2026-08-10T10:30:00Z")
    vol_headers = make_volunteer_headers(volunteer["id"])
    get_success_data(api.check_in_shift(shift["id"], vol_headers))
    open_service(service["id"])

    o1 = create_order(service["id"], guest["id"], i1["id"], quantity=3)
    get_success_data(api.start_prep(o1["id"], vol_headers))
    get_success_data(api.mark_ready(o1["id"], vol_headers))
    get_success_data(api.serve_order(o1["id"], vol_headers))
    o2 = create_order(service["id"], guest["id"], i2["id"], quantity=1)
    get_success_data(api.start_prep(o2["id"], vol_headers))
    get_success_data(api.mark_ready(o2["id"], vol_headers))
    get_success_data(api.serve_order(o2["id"], vol_headers))

    get_success_data(api.close_service(service["id"], MANAGER))
    menu_day = get_success_data(api.reconcile_menu_day(menu_day["id"], MANAGER))
    return menu_day


class TestCostPerServedMealRounding:
    """Queue A: combinatorial_formula / cost_per_served_meal_rounding_order_mode_b."""

    def test_total_cost_rounded_per_line_then_summed(self, api):
        """PRD 3.8: "The day's total cost is the sum of those already-rounded
        lines — the rounding order is pinned, per line first and only then
        summed, because summing raw unrounded values and rounding once
        produces different cents and is not compliant: two lines of raw
        100.005 sum to 200.01 under sum-then-round, but to 100.01 + 100.01 =
        200.02 under the pinned order."

        Design: Difficulty/combinatorial_formula/cost_per_served_meal_rounding_order_mode_b
        """
        menu_day = _build_rounding_scenario(api)
        summary = get_success_data(api.get_menu_day_summary(menu_day["id"], MANAGER))
        assert summary["served_count"] == 4, (
            f"served_count must be 4, got {summary.get('served_count')}"
        )
        total = float(summary["total_cost_cents"])
        assert total == pytest.approx(200.02, abs=1e-9), (
            f"pinned round-per-line total must be 200.02 cents (not the "
            f"sum-then-round 200.01), got {total}"
        )

    def test_cost_per_served_uses_round_half_up(self, api):
        """PRD 3.8: "The cost per served meal is that total divided by the
        day's `served_count` — or by 1 when no guest was served, so the
        divisor is never zero — rounded half up to two decimal places."
        PRD 2.10: "Money is accounted in cents carried to two decimal places
        (hundredths of a cent): per-line costs and the final per-meal division
        are rounded half up to two decimal places".

        Design: Difficulty/combinatorial_formula/cost_per_served_meal_rounding_order_mode_b
        """
        menu_day = _build_rounding_scenario(api)
        summary = get_success_data(api.get_menu_day_summary(menu_day["id"], MANAGER))
        # round_half_up(200.02 / 4, 2dp) = round_half_up(50.005) = 50.01.
        per_served = float(summary["cost_per_served_cents"])
        assert per_served == pytest.approx(50.01, abs=1e-9), (
            f"cost per served must be 50.01 cents under round-half-up "
            f"(round-half-even would give 50.00), got {per_served}"
        )


class TestWasteRatioThreshold:
    def _reconciled_day_with_waste(self, api, site_name, waste_servings):
        """One site, committed 100, zero orders served, one DISCARD waste log,
        reconciled.  Returns the menu day id."""
        site = create_site(name=site_name, dine_in_capacity=200,
                           togo_capacity_per_window=100, delivery_radius_km=10)
        batch = create_accepted_batch(
            site["id"], item_description="stock", quantity_servings=150,
            unit_cost_cents_per_serving=50,
        )
        menu_day = create_menu_day(site["id"], "2026-08-10")
        item = create_menu_item(menu_day["id"], name="Meal", planned_servings=100)
        allocate(item["id"], batch["id"], 100)
        confirm_item(item["id"])
        lock_forecast(menu_day["id"])
        start_production(menu_day["id"])
        service = create_service(
            menu_day["id"], service_model="DINE_IN",
            window_start="2026-08-10T11:00:00Z",
            window_end="2026-08-10T13:00:00Z", capacity=200,
        )
        set_clock("2026-08-10T10:30:00Z")
        open_service(service["id"])
        get_success_data(api.close_service(service["id"], MANAGER))
        create_waste_log(menu_day["id"], batch["id"],
                         servings_wasted=waste_servings,
                         reason="OVERPRODUCTION", disposition="DISCARD")
        get_success_data(api.reconcile_menu_day(menu_day["id"], MANAGER))
        return menu_day["id"]

    def test_waste_ratio_threshold_strict_greater(self, api):
        """PRD 3.8: "Reconciliation computes the day's waste ratio: the
        numerator is the sum of `servings_wasted` over the day's waste logs
        with disposition `DISCARD` or `COMPOST`, and the denominator is the
        day's `committed_servings` at reconcile time. The ratio is carried to
        four decimal places with round-half-up."
        PRD 3.8: "Otherwise, a ratio strictly greater than 0.15 raises the
        day's overproduction alert flag, surfaced on subsequent reads of the
        menu day; a ratio exactly equal to 0.15 does not alert."

        Design: Corner/calculations/waste_ratio_threshold_strict_greater
        """
        set_clock("2026-08-10T08:00:00Z")
        da = self._reconciled_day_with_waste(api, "Waste A", 15)
        db = self._reconciled_day_with_waste(api, "Waste B", 16)

        summary_a = get_success_data(api.get_menu_day_summary(da, MANAGER))
        ratio_a = float(summary_a["waste_ratio"])
        assert ratio_a == pytest.approx(0.15, abs=1e-9), (
            f"15 / 100 must give waste_ratio 0.15, got {ratio_a}"
        )

        summary_b = get_success_data(api.get_menu_day_summary(db, MANAGER))
        ratio_b = float(summary_b["waste_ratio"])
        assert ratio_b == pytest.approx(0.16, abs=1e-9), (
            f"16 / 100 must give waste_ratio 0.16, got {ratio_b}"
        )
