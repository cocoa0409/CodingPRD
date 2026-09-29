"""A transition is gated by state two or three entities away: a permit suspension freezing the farm
underneath a receipt, and a spill history decaying the assigned truck's reliability."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, fixtures as fx,
)

RECEIPT_MEASUREMENTS = dict(
    delivery_mode="TRUCK", supplier_name="Refinery One", meter_ticket_gross_liters=30120.0,
    tank_opening_gauge_liters=100.0, tank_closing_gauge_liters=30100.0, temperature_c=25.0,
    certificate_density_kg_per_m3=795.0, measured_water_liters=200.0)


def _farm_with_two_recorded_receipts():
    env = fx.setup_farm_with_released_tank(
        opening_volume_liters=1_000_000.0,
        permit_overrides={"max_daily_throughput_liters": 400000.0})
    fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                      turnaround_buffer_minutes=15, differential_pressure_kpa=10.0)
    env["r1"] = fx.record_receipt(env["tank"]["id"], **RECEIPT_MEASUREMENTS)
    env["r2"] = fx.record_receipt(env["tank"]["id"], **RECEIPT_MEASUREMENTS)
    return env


class TestPermitStateGatesReceiptSampling:
    def test_suspending_the_permit_freezes_the_farm_and_blocks_receipt_sampling(self, api):
        """PRD §3.1: "An `EnvironmentalOfficer` may later drive `ACTIVE → SUSPENDED`, which requires a
        non-empty `suspension_reason` recorded on the permit and immediately drives the farm to
        `FROZEN` because it no longer has an active permit — the full freeze cascade described in §3.7
        fires on that same request."
        PRD §3.2: "Drawing the receipt QC sample moves it `RECORDED → SAMPLED`; this is a
        `QualityInspector` action and requires that the farm of the receipt's tank is not `FROZEN` and
        that the destination tank's `service_status` is not `OUT_OF_SERVICE`."
        PRD §2.10: "The frozen-farm guard (`ERR_FARM_FROZEN`) is evaluated before anything else in
        this band, so a mid-flight freeze surfaces as a freeze rather than being masked by a later
        check."

        Design: Difficulty/cross_entity_state_dependency/receipt_sampling_gated_by_environmental_permit_state_two_hops_away
        """
        env = _farm_with_two_recorded_receipts()
        assert fx.read_farm(env["farm"]["id"])["posture"] == "OPEN"

        first = fx.draw_receipt_sample(env["r1"]["id"], fx.INSPECTOR_A)
        assert validate_success(
            api.get_fuel_receipt(env["r1"]["id"], fx.OPERATOR))["status"] == "SAMPLED"

        suspended = validate_success(api.suspend_permit(
            env["permit"]["id"],
            {"suspension_reason": "regulator audit of the bund drainage system"}, fx.ENVIRO))
        assert suspended["status"] == "SUSPENDED"
        assert fx.read_farm(env["farm"]["id"])["posture"] == "FROZEN"

        validate_error(api.create_receipt_sample(env["r2"]["id"], fx.INSPECTOR_A),
                       ApiErrorId.ERR_FARM_FROZEN, 409)

        blocked = validate_success(api.get_fuel_receipt(env["r2"]["id"], fx.OPERATOR))
        assert blocked["status"] == "RECORDED", \
            "the receipt itself never changed; only the permit two hops away did"
        samples, _meta = validate_paginated(api.list_quality_samples(
            fx.INSPECTOR_A, {"fuel_receipt_id": env["r2"]["id"]}))
        assert samples == []

    def test_reinstating_the_permit_lets_the_identical_request_through(self, api):
        """PRD §3.1: "The reverse, `SUSPENDED → ACTIVE`, is permitted only while the logical clock is
        still strictly before the permit's `valid_until_utc`, and it recomputes posture."
        PRD §3.2: "It creates a quality sample whose `sample_purpose` is `RECEIPT_QC`, whose `status`
        is `DRAWN`, and whose `fuel_receipt_id` points back at this receipt, stamps the receipt's
        `sampled_by_user_id` with the acting identifier, and raises the receipt's `version` by one."
        PRD §3.2: "A newly recorded receipt sits in `RECORDED` and has added nothing to any tank. Its
        `sampled_by_user_id`, `released_by_user_id` and `released_at_utc` are null and its
        `retest_round` is zero."

        Design: Difficulty/cross_entity_state_dependency/receipt_sampling_gated_by_environmental_permit_state_two_hops_away
        """
        env = _farm_with_two_recorded_receipts()
        validate_success(api.suspend_permit(
            env["permit"]["id"],
            {"suspension_reason": "regulator audit of the bund drainage system"}, fx.ENVIRO))
        validate_error(api.create_receipt_sample(env["r2"]["id"], fx.INSPECTOR_A),
                       ApiErrorId.ERR_FARM_FROZEN, 409)

        reinstated = validate_success(api.reinstate_permit(env["permit"]["id"], fx.ENVIRO))
        assert reinstated["status"] == "ACTIVE"
        # The suspension fired the full freeze cascade, and PRD §2.9 keeps its asymmetry:
        # "assets driven to `DOWN_MAINTENANCE` by a farm freeze are **not** automatically
        # restored when the farm unfreezes." With the farm's only truck still down, PRD §2.7's
        # fourth restricted cause — "the farm's `in_service_asset_count` is zero" — holds, so
        # the recompute lands on RESTRICTED rather than OPEN. RESTRICTED does not gate receipt
        # sampling, which is what the rest of this test exercises.
        assert fx.read_farm(env["farm"]["id"])["posture"] == "RESTRICTED"

        sample = fx.draw_receipt_sample(env["r2"]["id"], fx.INSPECTOR_A)
        assert sample["sample_purpose"] == "RECEIPT_QC"
        assert sample["status"] == "DRAWN"
        assert sample["fuel_receipt_id"] == env["r2"]["id"]

        receipt = validate_success(api.get_fuel_receipt(env["r2"]["id"], fx.OPERATOR))
        assert receipt["status"] == "SAMPLED"
        assert receipt["retest_round"] == 0, \
            "only a re-test round out of QUARANTINED raises the counter"
        assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
            pytest.approx(1000000.00, abs=0.005)


class TestSpillHistoryGatesFuellingStart:
    @staticmethod
    def _assigned_order_with_two_contained_spills():
        env = fx.setup_truck_order(
            target_state="ASSIGNED", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000},
            permit_overrides={"max_daily_throughput_liters": 400000.0,
                              "max_reportable_spill_liters": 20.0})
        env["truck2"] = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                          turnaround_buffer_minutes=15,
                                          differential_pressure_kpa=10.0)
        for _ in range(2):
            spill = fx.report_spill(env["farm"]["id"], spilled_volume_liters=15.0,
                                    surface="STORM_DRAIN",
                                    fueling_asset_id=env["truck"]["id"])
            fx.contain_spill(spill["id"], 15.0)
        return env

    def test_reliability_decays_in_steps_and_sixty_exactly_stays_in_service(self, api):
        """PRD §3.7: "The severity component counts the spilled volume in whole 10-litre steps,
        rounding the number of steps up, and charges 5 points per step, with the severity component
        itself capped at 40 points **before** anything else happens. A surface multiplier of 2 then
        applies when the product landed on a `STORM_DRAIN` or on `UNSEALED_GROUND`, and of 1 for an
        `APRON` or a `TANK_BUND`."
        PRD §3.7: "Once the score falls **below 60** the asset is driven
        `IN_SERVICE → DOWN_MAINTENANCE`; that move is also reachable from `FILTER_DUE`, by an explicit
        status change, and by the farm freeze cascade."
        PRD §3.8: "**Containment, `REPORTED → CONTAINED`,** is the non-reportable path and skips
        escalation entirely: it is lawful only when the spilled volume is strictly below the governing
        permit's `max_reportable_spill_liters`, and it requires a `contained_volume_liters` no greater
        than the `spilled_volume_liters`."

        Design: Difficulty/cross_entity_state_dependency/order_start_gated_by_asset_reliability_driven_down_by_spill_history
        """
        env = fx.setup_truck_order(
            target_state="ASSIGNED", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000},
            permit_overrides={"max_daily_throughput_liters": 400000.0,
                              "max_reportable_spill_liters": 20.0})
        truck_id = env["truck"]["id"]

        first = fx.report_spill(env["farm"]["id"], spilled_volume_liters=15.0,
                                surface="STORM_DRAIN", fueling_asset_id=truck_id)
        fx.contain_spill(first["id"], 15.0)
        after_one = fx.read_asset(truck_id)
        assert after_one["reliability_score"] == 80
        assert after_one["status"] == "IN_SERVICE"

        second = fx.report_spill(env["farm"]["id"], spilled_volume_liters=15.0,
                                 surface="STORM_DRAIN", fueling_asset_id=truck_id)
        fx.contain_spill(second["id"], 15.0)
        after_two = fx.read_asset(truck_id)
        assert after_two["reliability_score"] == 60
        assert after_two["status"] == "IN_SERVICE", \
            "a score of exactly 60 has not fallen below 60"

        third = fx.report_spill(env["farm"]["id"], spilled_volume_liters=15.0,
                                surface="STORM_DRAIN", fueling_asset_id=truck_id)
        fx.contain_spill(third["id"], 15.0)
        after_three = fx.read_asset(truck_id)
        assert after_three["reliability_score"] == 40
        assert after_three["status"] == "DOWN_MAINTENANCE"

    def test_start_is_refused_because_of_incidents_the_request_never_mentions(self, api):
        """PRD §3.6: "The asset must be `IN_SERVICE` with its `element_life_pct` strictly below
        100.0."
        PRD §2.10: "then asset serviceability (`ERR_ASSET_NOT_SERVICEABLE`) on order assignment,
        fuelling start and uplift posting"
        PRD §3.8: "Its effects are correspondingly narrow — the reliability penalty is applied to the
        attributed asset when a `fueling_asset_id` was recorded, which may itself drive that asset
        `IN_SERVICE → DOWN_MAINTENANCE`; the farm's `open_spill_count` and posture are recomputed; and
        the incident's, the farm's and (when attributed) the asset's `version` each rise by one."

        Design: Difficulty/cross_entity_state_dependency/order_start_gated_by_asset_reliability_driven_down_by_spill_history
        """
        env = self._assigned_order_with_two_contained_spills()
        third = fx.report_spill(env["farm"]["id"], spilled_volume_liters=15.0,
                                surface="STORM_DRAIN", fueling_asset_id=env["truck"]["id"])
        fx.contain_spill(third["id"], 15.0)

        validate_error(api.start_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_ASSET_NOT_SERVICEABLE, 409)

        order = fx.read_order(env["order"]["id"])
        assert order["status"] == "ASSIGNED"
        assert order["fueling_asset_id"] == env["truck"]["id"]

        assert fx.read_asset(env["truck2"]["id"])["status"] == "IN_SERVICE"
        farm = fx.read_farm(env["farm"]["id"])
        assert farm["in_service_asset_count"] == 1
        assert farm["open_spill_count"] == 0, "all three incidents reached CONTAINED"
        assert farm["posture"] == "OPEN"

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["quality_status"] == "RELEASED"
        assert tank["available_volume_liters"] == pytest.approx(979500.00, abs=0.005)
