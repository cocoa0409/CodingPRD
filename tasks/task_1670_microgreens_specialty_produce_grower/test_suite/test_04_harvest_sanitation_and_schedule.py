"""Harvest gating (batch state + sanitation record), the sow-to-harvest
schedule driven by the logical clock, and the harvest allocation waterfall."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_crop_plan,
    create_approved_food_safety_plan,
    create_crop_plan,
    create_customer,
    create_listed_variety,
    create_released_seed_lot,
    create_standing_order,
    add_order_line,
    confirm_standing_order,
    get_plan_batch,
    get_tray_batch,
    log_sanitation,
    setup_ready_batch,
    setup_sown_batch,
    sow_crop_plan,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import GROWER, OPS


class TestHarvestSanitationGate:
    def test_harvest_without_sanitation_log_rejected(self, api):
        """PRD §3.4: "the sanitation gate must pass: if no `SanitationLog`
        exists for the batch at all, the rejection is `ERR_SANITATION_NOT_LOGGED`"

        Design: Difficulty/cross_entity_state_dependency/harvest_requires_sanitation_log_passing
        """
        ws = setup_ready_batch(name="Tatsoi")
        batch = ws["tray_batch"]
        assert batch["status"] == "READY"

        resp = api.harvest_tray_batch(batch["id"], 18.0, GROWER)
        validate_error(resp, ApiErrorId.ERR_SANITATION_NOT_LOGGED)

        after = get_tray_batch(batch["id"])
        assert after["status"] == "READY", "A rejected harvest leaves the batch READY"

    def test_harvest_with_failed_swab_rejected(self, api):
        """PRD §3.4: "if a log exists but shows `surface_swab_passed` false or a
        `wash_water_ppm` outside the inclusive band of 50 to 200 parts per
        million, the rejection is `ERR_SANITATION_FAILED`."

        Design: Difficulty/cross_entity_state_dependency/harvest_requires_sanitation_log_passing
        """
        ws = setup_ready_batch(name="Tatsoi")
        batch = ws["tray_batch"]
        log_sanitation(batch["id"], surface_swab_passed=False, wash_water_ppm=100)

        resp = api.harvest_tray_batch(batch["id"], 18.0, GROWER)
        validate_error(resp, ApiErrorId.ERR_SANITATION_FAILED)

    def test_harvest_with_wash_water_ppm_out_of_range_rejected(self, api):
        """PRD §3.4: "if a log exists but shows `surface_swab_passed` false or a
        `wash_water_ppm` outside the inclusive band of 50 to 200 parts per
        million, the rejection is `ERR_SANITATION_FAILED`."

        Design: Corner/validations/sanitation_failed_ppm_out_of_range
        """
        ws = setup_ready_batch(name="Carrot")
        batch = ws["tray_batch"]
        log_sanitation(batch["id"], surface_swab_passed=True, wash_water_ppm=300)

        resp = api.harvest_tray_batch(batch["id"], 18.0, GROWER)
        validate_error(resp, ApiErrorId.ERR_SANITATION_FAILED)


class TestHarvestBatchState:
    def test_harvest_from_sown_batch_rejected_not_ready(self, api):
        """PRD §3.4: "The batch must be `READY` — harvesting in any other state
        is rejected with `ERR_BATCH_NOT_READY`"

        Design: Corner/state_machines/harvest_from_sown_returns_batch_not_ready
        """
        ws = setup_sown_batch(name="Pea")
        batch = ws["tray_batch"]
        assert batch["status"] == "SOWN"
        log_sanitation(batch["id"])  # passing log present; state gate is what fires

        resp = api.harvest_tray_batch(batch["id"], 18.0, GROWER)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_READY)

        after = get_tray_batch(batch["id"])
        assert after["status"] == "SOWN", "A rejected harvest leaves the batch unchanged"


class TestSowToHarvestSchedule:
    def test_sown_batch_dates_follow_logical_clock_default(self, api):
        """PRD §2.5: "At startup the clock reads exactly 2026-08-01T00:00:00Z,
        and it must never silently fall back to wall-clock time"
        PRD §3.3: "The batch's `sown_at` is stamped from the logical clock, and
        its `expected_harvest_date` falls out as the date of `sown_at` plus the
        variety's `days_to_harvest` days."

        Design: Difficulty/resource_temporal_overlap/tray_rack_sow_harvest_interval_overlap
        """
        ws = setup_sown_batch(name="Fennel", days_to_harvest=14)
        batch = ws["tray_batch"]
        assert batch["sown_at"].startswith("2026-08-01"), (
            "sown_at is stamped from the startup logical clock 2026-08-01T00:00:00Z")
        assert str(batch["expected_harvest_date"])[:10] == "2026-08-15", (
            "expected_harvest_date = date(sown_at) 2026-08-01 + 14 days")

    def test_sown_batch_dates_follow_shifted_logical_clock(self, api):
        """PRD §2.5: "the only way it advances is through the `OpsManager`-only
        capability `POST /grow/_clock/set_current_utc`, which moves the clock to
        a supplied `to_iso8601` instant."
        PRD §3.3: "The batch's `sown_at` is stamped from the logical clock, and
        its `expected_harvest_date` falls out as the date of `sown_at` plus the
        variety's `days_to_harvest` days."

        Design: Difficulty/resource_temporal_overlap/tray_rack_sow_harvest_interval_overlap
        """
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Fennel", days_to_harvest=14)
        lot = create_released_seed_lot(variety["id"])
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=10)

        validate_success(api.set_clock("2026-08-03T00:00:00Z", OPS))
        sow_crop_plan(plan["id"], plan["version"], lot["id"])
        batch = get_plan_batch(plan["id"])

        assert batch["sown_at"].startswith("2026-08-03"), (
            "sown_at follows the advanced logical clock")
        assert str(batch["expected_harvest_date"])[:10] == "2026-08-17", (
            "expected_harvest_date = date(sown_at) 2026-08-03 + 14 days")

    def test_expected_harvest_date_and_base_harvest_fixed_at_creation(self, api):
        """PRD §3.3: "the system fixes its `base_harvest_kg` at creation as the
        planned tray count multiplied by the variety's
        `expected_yield_grams_per_tray` and divided by 1000 — this figure is
        frozen at plan creation and is not recomputed if the variety's yield
        estimate is edited later."
        PRD §3.3: "The batch's `sown_at` is stamped from the logical clock, and
        its `expected_harvest_date` falls out as the date of `sown_at` plus the
        variety's `days_to_harvest` days."

        Design: Corner/calculations/sow_to_harvest_expected_date_computation
        """
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Corn Shoots", days_to_harvest=10,
                                        expected_yield_grams_per_tray=20000)
        lot = create_released_seed_lot(variety["id"])
        plan = create_crop_plan(variety["id"], planned_tray_count=4,
                                seed_grams_required=20)
        assert_crop_plan(plan)
        assert plan["base_harvest_kg"] == pytest.approx(80.0), (
            "base_harvest_kg = 4 trays * 20000 g/tray / 1000, fixed at creation")

        validate_success(api.set_clock("2026-08-03T00:00:00Z", OPS))
        sow_crop_plan(plan["id"], plan["version"], lot["id"])
        batch = get_plan_batch(plan["id"])
        assert str(batch["expected_harvest_date"])[:10] == "2026-08-13", (
            "sown 2026-08-03 + 10 days_to_harvest")


class TestHarvestAllocationWaterfall:
    def test_harvest_allocation_fills_earliest_week_first(self, api):
        """PRD §3.4: "The freshly harvested kilograms are offered to order lines
        whose `fulfillment` is `PLANNED` for the same variety, taken in order of
        the standing order's `effective_week_start`, earliest first, with ties
        broken by the standing order's `created_at`, earliest first — never by
        identifier. Each line is filled against its `qty_kg` in turn: a line
        that can be fully covered becomes `ALLOCATED`, and when supply runs out
        mid-line that line is partially allocated with its unfilled remainder
        marked `SHORTED`."

        Design: Corner/calculations/harvest_allocation_waterfall_ordering
        """
        ws = setup_ready_batch(name="Watercress", listed_price_cents_per_kg=1000)
        batch = ws["tray_batch"]

        customer1 = create_customer(business_name="First")
        order1 = create_standing_order(customer1, effective_week_start="2026-08-03")
        item1 = add_order_line(order1["id"], customer1, ws["variety"]["id"], 3.0)
        confirm_standing_order(order1["id"], customer1)

        customer2 = create_customer(business_name="Second")
        order2 = create_standing_order(customer2, effective_week_start="2026-08-10")
        item2 = add_order_line(order2["id"], customer2, ws["variety"]["id"], 3.0)
        confirm_standing_order(order2["id"], customer2)

        log_sanitation(batch["id"])
        # Only 4.0 kg against 6.0 kg of open demand.
        harvested = validate_success(api.harvest_tray_batch(batch["id"], 4.0, GROWER))
        assert harvested["status"] == "HARVESTED"
        assert harvested["harvested_kg"] == pytest.approx(4.0)

        item1_after = validate_success(api.get_order_item(item1["id"], OPS))
        assert item1_after["fulfillment"] == "ALLOCATED", (
            "Earliest effective_week_start fills first: 3.0 kg of the 4.0 kg harvest")

        item2_after = validate_success(api.get_order_item(item2["id"], OPS))
        assert item2_after["fulfillment"] == "SHORTED", (
            "Supply runs out mid-line: only 1.0 kg remains for a 3.0 kg line")
