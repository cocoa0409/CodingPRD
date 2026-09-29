"""Exact-boundary behaviour on two different metrics.

Gallons since the last filter change are tested one hundredth below and exactly
at the derated interval; the brand-mix apportionment is tested at its zero-volume
edge.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    activate_agreement,
    add_telemetry,
    create_agreement,
    create_outlet,
    create_supply_item,
    create_task,
    create_unit,
    pin_clock,
    read_outlet,
    read_task,
    read_unit,
    TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]


def _hard_water_filter_task():
    """A 4000-gallon filter interval derated to 2800.00 by 25 gpg feed water."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Harbor Fish Shack",
        account_code="ACCT-BP-A",
        region_code="R11",
        throughput_tier="MEDIUM",
        water_hardness_gpg=25,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    unit = create_unit(
        outlet["id"], agreement["id"], serial_number="SN-BP-A-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    item = create_supply_item(
        sku_code="COKE_BIB_BP",
        brand_name="Coca-Cola",
        supply_form="BAG_IN_BOX",
        case_pack_units=2,
        ounces_per_unit=640,
        promotional=False,
        national_allocation_units=500,
    )
    task = create_task(
        unit["id"], "FILTER_CHANGE", "2027-06-01T00:00:00Z", gallon_interval=4000
    )
    return outlet, unit, item, task


def _outlet_with_two_skus_and_no_telemetry():
    """One in-window promotional SKU, one plain SKU, and not a single reading."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Museum Atrium Bar",
        account_code="ACCT-BP-B",
        region_code="R12",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    create_unit(
        outlet["id"], agreement["id"], serial_number="SN-BP-B-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    create_supply_item(
        sku_code="FREESTYLE_PEACH",
        brand_name="Coca-Cola Peach",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=True,
        promo_window_start="2026-07-15T00:00:00Z",
        promo_window_end="2026-08-15T00:00:00Z",
        national_allocation_units=200,
    )
    create_supply_item(
        sku_code="COKE_CART_BM",
        brand_name="Coca-Cola",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=False,
        national_allocation_units=1000,
    )
    return outlet


class TestFilterChangeGallonBoundary:
    def test_one_hundredth_of_a_gallon_short_of_the_interval_does_not_breach(self, api):
        """PRD §3.5: "Otherwise nothing has been breached: `breach_kind` stays null,
        the task's `status` is left exactly where it was, and because nothing was
        mutated the task's `version` does not advance."

        Design: Difficulty/boundary_precision_check/filter_change_gallon_interval_exact_threshold_hit
        """
        outlet, unit, item, task = _hard_water_filter_task()
        assert read_task(task["id"])["effective_gallon_interval"] == pytest.approx(
            2800.00, abs=0.01
        )

        add_telemetry(unit["id"], item["id"], 358398.72, "2026-08-01T00:00:00Z",
                      window_days=30)

        assert read_unit(unit["id"])["lifetime_dispensed_gallons"] == pytest.approx(
            2799.99, abs=0.001
        )
        after = read_task(task["id"])
        assert after["status"] == "SCHEDULED"
        assert after["breach_kind"] is None

        outlet_state = read_outlet(outlet["id"])
        assert outlet_state["overdue_task_count"] == 0
        assert outlet_state["service_posture"] == "OPEN"

    def test_sitting_exactly_on_the_interval_breaches_with_gallon(self, api):
        """PRD §3.5: "If the task has a non-null `effective_gallon_interval` and the
        machine's gallons since its last filter change — that is
        `lifetime_dispensed_gallons` less `gallons_at_last_filter_change` — have
        reached or exceeded that effective interval, the task's `breach_kind`
        becomes `GALLON` and it goes straight to `OVERDUE`, with no grace band. A
        machine sitting exactly at the effective interval has breached it."

        Design: Difficulty/boundary_precision_check/filter_change_gallon_interval_exact_threshold_hit
        """
        outlet, unit, item, task = _hard_water_filter_task()

        add_telemetry(unit["id"], item["id"], 358398.72, "2026-08-01T00:00:00Z",
                      window_days=30)
        add_telemetry(unit["id"], item["id"], 1.28, "2026-08-01T00:00:00Z",
                      window_days=30)

        machine = read_unit(unit["id"])
        assert machine["lifetime_dispensed_gallons"] == pytest.approx(2800.00, abs=0.001)
        assert machine["gallons_at_last_filter_change"] == pytest.approx(0.00, abs=0.001)
        assert machine["version"] == 3

        breached = read_task(task["id"])
        assert breached["status"] == "OVERDUE"
        assert breached["breach_kind"] == "GALLON"
        assert breached["version"] == 2

        outlet_state = read_outlet(outlet["id"])
        assert outlet_state["overdue_task_count"] == 1
        assert outlet_state["service_posture"] == "RESTRICTED"


class TestBrandMixZeroVolumeEdge:
    def test_no_qualifying_volume_emits_no_lines_and_a_null_top_brand(self, api):
        """PRD §3.9: "Where the period contains no qualifying volume at all,
        `total_ounces` is 0, `lines` is an empty array with no `share_pct` emitted
        anywhere, and `top_brand_name` is null."

        Design: Difficulty/boundary_precision_check/brand_mix_report_zero_telemetry_empty_line_set
        """
        outlet = _outlet_with_two_skus_and_no_telemetry()

        report = validate_success(api.get_brand_mix_report(outlet["id"], PLANNER))

        assert report["outlet_id"] == outlet["id"]
        assert report["total_ounces"] == 0
        assert report["lines"] == []
        assert report["top_brand_name"] is None

    def test_the_thirty_day_period_and_the_in_window_promotion_still_report(self, api):
        """PRD §3.9: "`promo_available_skus` lists the `sku_code` of every supply
        item that is `promotional`, whose promotional window currently contains the
        logical clock — at or after `promo_window_start` and strictly before
        `promo_window_end` — and only while the outlet's `service_posture` is not
        `FROZEN`, ordered by the supply item's `created_at` ascending".

        Design: Difficulty/boundary_precision_check/brand_mix_report_zero_telemetry_empty_line_set
        """
        outlet = _outlet_with_two_skus_and_no_telemetry()

        report = validate_success(api.get_brand_mix_report(outlet["id"], PLANNER))

        assert report["promo_available_skus"] == ["FREESTYLE_PEACH"]
        assert report["period_start"].startswith("2026-07-02T00:00:00")
        assert report["period_end"].startswith("2026-08-01T00:00:00")
