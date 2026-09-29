"""Corner behaviour of the two asset-fitness numbers: the three-legged element life with its floored
age leg and its reversible throughput leg, and the reliability score with its twice-applied cap."""
import pytest

from test_helpers import (
    assert_same_instant,
    validate_success, get_success_data, validate_paginated, fixtures as fx,
)

BIG_CREDIT = 100_000_000_000


def _asset_at_full_element_life():
    """A FUELING truck order carrying one 4,200,000.00-litre ticket, so the throughput leg is 105 %."""
    env = fx.setup_truck_order(
        # PRD §3.6 gates TRUCK assignment on the source tank's `available_volume_liters`
        # being at least the requested volume, and PRD §3.6 has already subtracted that same
        # volume as the authorisation reservation, so the baseline needs twice the headroom.
        target_state="FUELING", requested_uplift_liters=4_200_000.0,
        max_authorized_liters=4_200_000.0, opening_volume_liters=8_500_000.0,
        tank_overrides={"capacity_liters": 10_000_000.0, "safe_fill_liters": 9_000_000.0},
        asset_overrides={"tank_capacity_liters": 40_000.0, "turnaround_buffer_minutes": 15,
                         "differential_pressure_kpa": 10.0},
        account_overrides={"base_price_cents_per_liter": 62.00,
                           "credit_limit_cents": BIG_CREDIT},
        permit_overrides={"max_daily_throughput_liters": 5_000_000.0})
    env["uplift"] = fx.post_uplift(env["order"]["id"], meter_start_liters=0.0,
                                   meter_end_liters=4_200_000.0, temperature_c=15.0)
    return env


class TestFilterElementLifeCorners:
    def test_the_age_leg_counts_whole_days_and_ignores_the_odd_hour(self, api):
        """PRD §3.7: "The **age leg** takes the whole days elapsed from the asset's
        `last_filter_change_at_utc` to the current logical clock — floored to whole days, so a partial day
        does not count — compares that against a nominal element life of one year, taken as 365 days, and
        expresses the result as a percentage rounded half up to four decimals."
        PRD §3.7: "Reaching 100.0 percent element life moves the asset `IN_SERVICE → FILTER_DUE`
        automatically — the comparison is inclusive, so exactly 100.0 triggers it — provided the
        differential pressure leg has not itself passed the 103.0 kilopascal threshold."
        PRD §3.1: "On registration the asset's `last_filter_change_at_utc` is stamped with the current
        logical clock, `liters_since_filter_change` starts at 0.0, `element_life_pct` is computed from
        those counters, `reliability_score` starts at 100, `onboard_volume_liters` is 0.0, and `status` is
        `IN_SERVICE`."

        Design: Corner/calculations/days_leg_floors_to_whole_days
        """
        env = fx.setup_fuel_farm(
            clock="2025-08-10T06:00:00Z",
            permit_overrides={"valid_from_utc": "2025-01-01T00:00:00Z",
                              "valid_until_utc": "2028-01-01T00:00:00Z"})
        truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  differential_pressure_kpa=10.0)
        assert_same_instant(truck["last_filter_change_at_utc"], "2025-08-10T06:00:00Z",
                            "last_filter_change_at_utc")
        assert truck["element_life_pct"] == pytest.approx(9.7087, abs=0.00005), \
            "only the pressure leg has anything to say on day zero"

        fx.set_clock("2026-08-10T05:00:00Z")
        nearly = fx.read_asset(truck["id"])
        assert nearly["element_life_pct"] == pytest.approx(99.7260, abs=0.00005), \
            "364 whole days and 23 hours count as 364 days"
        assert nearly["status"] == "IN_SERVICE"

        fx.set_clock("2026-08-10T06:00:00Z")
        due = fx.read_asset(truck["id"])
        assert due["element_life_pct"] == pytest.approx(100.0000, abs=0.00005)
        assert due["status"] == "FILTER_DUE", \
            "one more hour completes the 365th day, with no uplift anywhere in sight"
        assert fx.read_farm(env["farm"]["id"])["in_service_asset_count"] == 0

    def test_a_filter_change_resets_the_two_legs_it_owns_and_no_others(self, api):
        """PRD §3.7: "On the asset itself, `liters_since_filter_change` resets to 0.0,
        `differential_pressure_kpa` is set to the posted post-change reading, `last_filter_change_at_utc`
        is set to the current logical clock, and `element_life_pct` is recomputed from the reset
        counters."
        PRD §3.7: "The change record captures the pre-change state for audit: `liters_at_change` is the
        value of the asset's `liters_since_filter_change` immediately before it was reset, and
        `differential_pressure_before_kpa` is the value of the asset's `differential_pressure_kpa`
        immediately before it was overwritten."
        PRD §3.7: "The **pressure leg** compares the asset's `differential_pressure_kpa` against a
        maximum permitted differential of 103.0 kilopascals and expresses that as a percentage rounded
        half up to four decimals."

        Design: Corner/calculations/filter_change_resets_only_the_legs_it_owns
        """
        env = _asset_at_full_element_life()
        asset_id = env["truck"]["id"]
        spent = fx.read_asset(asset_id)
        assert spent["liters_since_filter_change"] == pytest.approx(4200000.00, abs=0.005)
        assert spent["element_life_pct"] == pytest.approx(105.0000, abs=0.00005)
        assert spent["status"] == "FILTER_DUE"
        assert spent["reliability_score"] == 100

        fx.complete_order(env["order"]["id"])
        validate_success(api.change_asset_status(asset_id, {"to_status": "DOWN_FOR_FILTER"},
                                                fx.OPERATOR))
        record = get_success_data(api.create_filter_change(
            asset_id, {"element_lot_number": "LOT-4200", "element_count": 4,
                       "post_change_differential_pressure_kpa": 8.0}, fx.INSPECTOR_A))

        assert record["liters_at_change"] == pytest.approx(4200000.00, abs=0.005)
        assert record["differential_pressure_before_kpa"] == pytest.approx(10.0, abs=0.005)

        fresh = fx.read_asset(asset_id)
        assert fresh["liters_since_filter_change"] == pytest.approx(0.00, abs=0.005)
        assert fresh["differential_pressure_kpa"] == pytest.approx(8.0, abs=0.005)
        assert_same_instant(fresh["last_filter_change_at_utc"], "2026-08-10T06:00:00Z",
                            "last_filter_change_at_utc")
        assert fresh["element_life_pct"] == pytest.approx(7.7670, abs=0.00005), \
            "8.0 against 103.0 is all that is left of the three legs"
        assert fresh["status"] == "IN_SERVICE"
        assert fresh["reliability_score"] == 100, \
            "reliability is a spill story and a filter change is not part of it"

    def test_voiding_the_ticket_takes_its_litres_back_out_of_the_throughput_leg(self, api):
        """PRD §3.7: "The counter that feeds the throughput leg accumulates the `net_liters` of `POSTED`
        and `BILLED` tickets metered by the asset since its last filter change, and a ticket that is later
        voided is subtracted back out."
        PRD §3.7: "The **throughput leg** compares the asset's `liters_since_filter_change` against a
        nominal element life of four million liters and expresses the result as a percentage, rounded half
        up to four decimals."
        PRD §3.7: "The asset's `element_life_pct` is the largest of those three percentages."

        Design: Corner/calculations/voided_ticket_volume_is_subtracted_back_out
        """
        env = _asset_at_full_element_life()
        asset_id = env["truck"]["id"]
        assert fx.read_asset(asset_id)["element_life_pct"] == pytest.approx(105.0000,
                                                                           abs=0.00005)

        fx.abort_order(env["order"]["id"], abort_reason="EQUIPMENT_FAILURE")

        assert fx.read_uplift(env["uplift"]["id"])["status"] == "VOIDED"
        healed = fx.read_asset(asset_id)
        assert healed["liters_since_filter_change"] == pytest.approx(0.00, abs=0.005), \
            "the whole 4,200,000.00 litres left the counter with the ticket"
        assert healed["element_life_pct"] == pytest.approx(9.7087, abs=0.00005), \
            "with the throughput leg back at zero the pressure leg is the worst of the three"


class TestAssetReliabilityCorners:
    def test_the_forty_point_cap_binds_after_the_doubling_as_well_as_before_it(self, api):
        """PRD §3.7: "The severity component counts the spilled volume in whole 10-litre steps, rounding
        the number of steps up, and charges 5 points per step, with the severity component itself capped
        at 40 points **before** anything else happens."
        PRD §3.7: "A surface multiplier of 2 then applies when the product landed on a `STORM_DRAIN` or
        on `UNSEALED_GROUND`, and of 1 for an `APRON` or a `TANK_BUND`. The product of severity and
        multiplier is capped at 40 again **after** the multiplication, and that capped figure is the
        penalty."
        PRD §3.7: "Once the score falls **below 60** the asset is driven `IN_SERVICE →
        DOWN_MAINTENANCE`; that move is also reachable from `FILTER_DUE`, by an explicit status change,
        and by the farm freeze cascade."

        Design: Corner/calculations/surface_multiplier_applies_before_the_per_incident_cap
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_reportable_spill_liters": 500.0})
        farm_id = env["farm"]["id"]
        truck = fx.register_truck(farm_id, tank_capacity_liters=40_000.0)

        spill = fx.report_spill(farm_id, spilled_volume_liters=200.0, surface="STORM_DRAIN",
                                fueling_asset_id=truck["id"])
        assert fx.read_asset(truck["id"])["reliability_score"] == 100, \
            "a merely reported incident has had no effect on the score yet"

        contained = fx.contain_spill(spill["id"], 200.0)
        assert contained["status"] == "CONTAINED"

        penalised = fx.read_asset(truck["id"])
        assert penalised["reliability_score"] == 60, \
            "20 steps at 5 points caps to 40, doubles to 80, and caps to 40 all over again"
        assert penalised["status"] == "IN_SERVICE", "exactly 60 is not below 60"
        assert fx.read_farm(farm_id)["in_service_asset_count"] == 1

    def test_a_single_litre_on_the_apron_still_costs_a_whole_step(self, api):
        """PRD §3.7: "The severity component counts the spilled volume in whole 10-litre steps, rounding
        the number of steps up, and charges 5 points per step, with the severity component itself capped
        at 40 points **before** anything else happens."
        PRD §3.7: "Every asset starts with a `reliability_score` of 100."
        PRD §3.8: "Its effects are correspondingly narrow — the reliability penalty is applied to the
        attributed asset when a `fueling_asset_id` was recorded, which may itself drive that asset
        `IN_SERVICE → DOWN_MAINTENANCE`; the farm's `open_spill_count` and posture are recomputed; and the
        incident's, the farm's and (when attributed) the asset's `version` each rise by one."

        Design: Corner/calculations/small_spill_on_sealed_ground_costs_five_points
        """
        env = fx.setup_fuel_farm()
        farm_id = env["farm"]["id"]
        truck = fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        assert truck["reliability_score"] == 100

        spill = fx.report_spill(farm_id, spilled_volume_liters=1.0, surface="APRON",
                                fueling_asset_id=truck["id"])
        contained = fx.contain_spill(spill["id"], 1.0)
        assert contained["status"] == "CONTAINED"

        penalised = fx.read_asset(truck["id"])
        assert penalised["reliability_score"] == 95, \
            "one litre rounds up to a single 10-litre step, and the apron carries no multiplier"
        assert penalised["status"] == "IN_SERVICE"
        assert fx.read_farm(farm_id)["open_spill_count"] == 0

    def test_an_unattributed_release_restricts_the_farm_and_charges_nobody(self, api):
        """PRD §3.8: "Attribution is optional and may name either a `fueling_asset_id`, a
        `storage_tank_id`, or neither."
        PRD §3.8: "Reporting alone recomputes the farm's `open_spill_count` and posture, and an open
        incident makes the farm `RESTRICTED` — never `FROZEN`."
        PRD §3.7: "When a spill attributed to the asset reaches containment, a penalty is computed and
        subtracted."

        Design: Corner/calculations/unattributed_spill_penalises_nothing
        """
        env = fx.setup_fuel_farm()
        farm_id = env["farm"]["id"]
        first = fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        second = fx.register_truck(farm_id, tank_capacity_liters=40_000.0)

        spill = fx.report_spill(farm_id, spilled_volume_liters=5.0, surface="UNSEALED_GROUND")
        assert spill["fueling_asset_id"] is None
        assert spill["storage_tank_id"] is None

        reported = fx.read_farm(farm_id)
        assert reported["posture"] == "RESTRICTED"
        assert reported["open_spill_count"] == 1
        assert reported["in_service_asset_count"] == 2

        fx.contain_spill(spill["id"], 5.0)

        assets, _meta = validate_paginated(api.list_fueling_assets(fx.ADMIN))
        assert {a["id"]: a["reliability_score"] for a in assets} == {first["id"]: 100,
                                                                    second["id"]: 100}
        assert all(a["status"] == "IN_SERVICE" for a in assets), \
            "an unattributed release is an environmental fact and nothing more"
        assert fx.read_farm(farm_id)["posture"] == "OPEN"
