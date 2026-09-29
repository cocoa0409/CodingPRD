"""The five ordered steps of a demand forecast, one arithmetic edge at a time.

Trailing-window membership, the outlet scope of the telemetry sum, the tier factor,
the net-requirement rounding, the upward request rounding, promotional suppression,
and the exact boundaries of the three alert bands.
"""

import pytest

from test_helpers import (
    add_telemetry,
    create_agreement,
    create_outlet,
    create_position,
    create_supply_item,
    create_unit,
    pin_clock,
    read_position,
    run_forecast,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet_unit_and_item(outlet_overrides=None, **item_overrides):
    """One IN_SERVICE machine at Riverside Diner plus the SKU it dispenses."""
    pin_clock(CLOCK)
    outlet = create_outlet(
        name="Riverside Diner",
        account_code="OUT-1001",
        region_code="R-WEST",
        **(outlet_overrides or {}),
    )
    agreement = create_agreement(
        outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    catalogue_entry = {
        "sku_code": "SKU-COLA",
        "brand_name": "Cola Classic",
        "supply_form": "CARTRIDGE",
        "case_pack_units": 4,
        "ounces_per_unit": 1000,
        "national_allocation_units": 100,
    }
    catalogue_entry.update(item_overrides)
    item = create_supply_item(**catalogue_entry)
    return outlet, unit, item


def _position_after_one_weekly_reading(on_hand_units, outlet_overrides=None,
                                       **item_overrides):
    """7000 ounces booked at 2026-07-28 against a position holding `on_hand_units`."""
    outlet, unit, item = _outlet_unit_and_item(outlet_overrides, **item_overrides)
    add_telemetry(unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
    return create_position(outlet["id"], item["id"], on_hand_units)


class TestNetRequirement:
    def test_a_fractional_requirement_is_kept_to_two_places_and_ordered_up(self, api):
        """PRD §3.6: "The projected ounces are divided by the SKU's `ounces_per_unit`
        to give a raw unit requirement, the position's current `on_hand_units` are
        subtracted, any negative result is clamped up to zero, and the outcome is
        rounded half up to two decimal places and stored as `forecast_units`." The same
        section adds: "`requested_units` is then the `forecast_units` value rounded
        **upward** to the next whole unit, so a suppressed position requests nothing."

        Design: Corner/calculations/forecast_trailing_actual_correct_result_and_requested_units_ceiling
        """
        position = _position_after_one_weekly_reading(
            2, outlet_overrides={"throughput_tier": "MEDIUM"}, ounces_per_unit=3000
        )

        forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert forecast["forecast_units"] == pytest.approx(2.67, abs=0.01)
        assert forecast["requested_units"] == 3
        assert forecast["alert_level"] == "LOW"
        assert forecast["promo_suppressed"] is False
        assert forecast["forecast_variant"] == "TRAILING_ACTUAL"


class TestTelemetryWindowMembership:
    def test_the_window_takes_its_first_instant_and_leaves_out_the_clock_instant(self, api):
        """PRD §3.6: "The run sums `dispensed_ounces` over every telemetry reading that
        reports the position's own SKU, was produced by a dispenser unit belonging to
        the position's outlet whose `status` is `IN_SERVICE` or `SERVICE_HOLD`, and
        whose `reading_at` falls in the half-open window that begins `window_days` days
        before the logical clock and ends at the logical clock exclusive."

        Design: Corner/calculations/forecast_window_includes_lower_bound_and_excludes_the_clock_instant
        """
        outlet, unit, item = _outlet_unit_and_item()
        add_telemetry(unit["id"], item["id"], 3500, "2026-07-25T00:00:00Z", window_days=7)
        add_telemetry(unit["id"], item["id"], 3500, "2026-07-28T00:00:00Z", window_days=7)
        add_telemetry(unit["id"], item["id"], 5000, "2026-08-01T00:00:00Z", window_days=7)
        position = create_position(outlet["id"], item["id"], 3)

        forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert forecast["forecast_units"] == pytest.approx(11.00, abs=0.01)
        assert forecast["requested_units"] == 11
        assert forecast["alert_level"] == "LOW"

    def test_another_outlets_machine_never_feeds_this_positions_forecast(self, api):
        """PRD §3.6: "The run sums `dispensed_ounces` over every telemetry reading that
        reports the position's own SKU, was produced by a dispenser unit belonging to
        the position's outlet whose `status` is `IN_SERVICE` or `SERVICE_HOLD`, and
        whose `reading_at` falls in the half-open window that begins `window_days` days
        before the logical clock and ends at the logical clock exclusive."

        Design: Corner/calculations/forecast_ignores_telemetry_from_units_of_another_outlet
        """
        outlet, unit, item = _outlet_unit_and_item()
        neighbour = create_outlet(
            name="Corner Deli", account_code="OUT-1002", region_code="R-WEST"
        )
        neighbour_agreement = create_agreement(
            neighbour["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
        )
        neighbour_unit = create_unit(
            neighbour["id"], neighbour_agreement["id"],
            serial_number="SN-9002", installed_at="2025-11-01T00:00:00Z",
        )
        add_telemetry(unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
        add_telemetry(
            neighbour_unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7
        )
        position = create_position(outlet["id"], item["id"], 3)

        forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert forecast["forecast_units"] == pytest.approx(11.00, abs=0.01)
        assert forecast["requested_units"] == 11
        assert forecast["alert_level"] == "LOW"


class TestAlertBands:
    def test_three_days_of_cover_exactly_is_low_not_critical(self, api):
        """PRD §3.6: "The resulting `alert_level` is `CRITICAL` when the position has
        zero `on_hand_units` **or** its cover is under 3 days, `LOW` when the cover is
        under 7 days without meeting the critical test, and `NONE` otherwise."

        Design: Corner/calculations/forecast_alert_band_at_exactly_three_days_of_cover_is_low
        """
        position = _position_after_one_weekly_reading(3)

        forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert forecast["alert_level"] == "LOW"
        assert forecast["forecast_units"] == pytest.approx(11.00, abs=0.01)
        assert forecast["requested_units"] == 11

    def test_seven_days_of_cover_exactly_raises_no_alert_at_all(self, api):
        """PRD §3.6: "The resulting `alert_level` is `CRITICAL` when the position has
        zero `on_hand_units` **or** its cover is under 3 days, `LOW` when the cover is
        under 7 days without meeting the critical test, and `NONE` otherwise."

        Design: Corner/calculations/forecast_alert_band_at_exactly_seven_days_of_cover_is_none
        """
        position = _position_after_one_weekly_reading(7)

        forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert forecast["alert_level"] == "NONE"
        assert forecast["forecast_units"] == pytest.approx(7.00, abs=0.01)
        assert forecast["requested_units"] == 7

    def test_an_empty_shelf_is_critical_even_with_unlimited_cover(self, api):
        """PRD §3.6: "If the measured daily ounce rate is zero the position is treated
        as having unlimited cover." The band itself is then decided by the other clause:
        "The resulting `alert_level` is `CRITICAL` when the position has zero
        `on_hand_units` **or** its cover is under 3 days, `LOW` when the cover is under
        7 days without meeting the critical test, and `NONE` otherwise."

        Design: Corner/calculations/forecast_zero_on_hand_without_telemetry_is_critical_with_zero_demand
        """
        outlet, _unit, item = _outlet_unit_and_item()
        position = create_position(outlet["id"], item["id"], 0)

        forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert forecast["forecast_units"] == pytest.approx(0.00, abs=0.01)
        assert forecast["requested_units"] == 0
        assert forecast["alert_level"] == "CRITICAL"


class TestVariantHandling:
    def test_the_medium_tier_factor_lifts_the_projected_horizon(self, api):
        """PRD §3.6: "Under `THROUGHPUT_PROJECTED` the same fourteen-day projection is
        additionally multiplied by the tier factor of the outlet's `throughput_tier`: a
        `SMALL` outlet uses 1.00, a `MEDIUM` outlet 1.15 and a `LARGE` outlet 1.30 — so
        from identical telemetry a large outlet forecasts thirty percent more units than
        a small one."

        Design: Corner/calculations/forecast_medium_tier_factor_applied_under_throughput_projected
        """
        position = _position_after_one_weekly_reading(
            2, outlet_overrides={"throughput_tier": "MEDIUM"}
        )

        forecast = run_forecast(position["id"], "THROUGHPUT_PROJECTED", 7)
        assert forecast["forecast_units"] == pytest.approx(14.10, abs=0.01)
        assert forecast["requested_units"] == 15
        assert forecast["alert_level"] == "CRITICAL"
        assert forecast["forecast_variant"] == "THROUGHPUT_PROJECTED"

    def test_the_position_remembers_the_variant_of_its_latest_run(self, api):
        """PRD §3.6: "A newly opened position answers 201 with `forecast_variant`
        recorded as `TRAILING_ACTUAL`, `forecast_units` at 0, `requested_units` at 0,
        `allocated_units` at 0, `planned_route_stop_id` null, `alert_level` `NONE`,
        `promo_suppressed` false, `alert_acknowledged_by_user_id` null and `version` 1."
        Each run then rewrites that record: "A run writes `forecast_variant`,
        `forecast_units`, `requested_units`, `alert_level` and `promo_suppressed`,
        clears `alert_acknowledged_by_user_id` back to null so that every fresh alert
        must be acknowledged afresh, and increments the position's `version` by one."

        Design: Corner/calculations/forecast_variant_recorded_on_the_position_after_the_run
        """
        position = _position_after_one_weekly_reading(
            2, outlet_overrides={"throughput_tier": "LARGE"}
        )
        assert position["forecast_variant"] == "TRAILING_ACTUAL"
        assert position["forecast_units"] == pytest.approx(0, abs=0.01)

        projected = run_forecast(position["id"], "THROUGHPUT_PROJECTED", 7)
        assert projected["forecast_variant"] == "THROUGHPUT_PROJECTED"

        trailing = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert trailing["forecast_variant"] == "TRAILING_ACTUAL"
        assert trailing["forecast_units"] == pytest.approx(12.00, abs=0.01)
        assert read_position(position["id"])["forecast_variant"] == "TRAILING_ACTUAL"


class TestPromotionalSuppression:
    def test_a_promotion_that_has_already_ended_orders_nothing(self, api):
        """PRD §3.6: "When the SKU is `promotional` and the logical clock does **not**
        sit inside the promotional window — that is, the clock is before
        `promo_window_start` or at or after `promo_window_end` — then `forecast_units`
        is overwritten with 0.00 and `promo_suppressed` is set to true."

        Design: Corner/calculations/forecast_promotional_sku_outside_its_window_is_suppressed_to_zero
        """
        position = _position_after_one_weekly_reading(
            2,
            sku_code="SKU-PROMO",
            brand_name="Summer Splash",
            promotional=True,
            promo_window_start="2026-06-01T00:00:00Z",
            promo_window_end="2026-07-01T00:00:00Z",
        )

        forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert forecast["forecast_units"] == pytest.approx(0.00, abs=0.01)
        assert forecast["requested_units"] == 0
        assert forecast["promo_suppressed"] is True
        assert forecast["alert_level"] == "CRITICAL"

    def test_a_promotion_still_running_keeps_the_units_it_earned(self, api):
        """PRD §3.6: "In every other case, including a non-promotional SKU and a
        promotional SKU inside its window, `promo_suppressed` is set to false and the
        computed `forecast_units` stands."

        Design: Corner/calculations/forecast_promotional_sku_inside_its_window_is_not_suppressed
        """
        position = _position_after_one_weekly_reading(
            2,
            sku_code="SKU-PROMO",
            brand_name="Summer Splash",
            promotional=True,
            promo_window_start="2026-07-15T00:00:00Z",
            promo_window_end="2026-09-01T00:00:00Z",
        )

        forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert forecast["forecast_units"] == pytest.approx(12.00, abs=0.01)
        assert forecast["requested_units"] == 12
        assert forecast["promo_suppressed"] is False
        assert forecast["alert_level"] == "CRITICAL"
