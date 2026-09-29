"""Corner behaviour of the model graph and of the tank's two parallel status dimensions: the uplift-to-farm
diamond, the polymorphic sample parent, and the independence of quality from service."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F,
)

BIG_CREDIT = 100_000_000_000
LONG_PERMIT = {"valid_from_utc": "2025-01-01T00:00:00Z",
               "valid_until_utc": "2028-01-01T00:00:00Z"}


class TestGraphTopologyCorners:
    def test_the_two_paths_from_a_ticket_to_its_farm_must_agree(self, api):
        """PRD §2.10: "**Existence.** Path identifiers are resolved left to right (`ERR_RESOURCE_NOT_FOUND`)
        on every endpoint carrying a path parameter, then body foreign keys are resolved in the order the
        fields are listed in the endpoint's input (`ERR_REFERENCED_ENTITY_NOT_FOUND`), then aggregate
        agreement is checked (`ERR_CROSS_FARM_REFERENCE`) on fuelling order creation and order assignment —
        specifically that the quoted authorization's flight matches the order's flight, that the hydrant pit
        and the storage tank belong to the same farm, and that the fuelling asset and the storage tank belong
        to the same farm."
        PRD §3.6: "Both branches require the asset's `status` to be `IN_SERVICE` (otherwise
        `ERR_ASSET_NOT_SERVICEABLE`) and the farm not to be `FROZEN`."

        Design: Corner/complexity_layers/an_uplift_reaches_its_farm_by_two_distinct_paths
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        elsewhere = fx.setup_fuel_farm()
        foreign_truck = fx.register_truck(elsewhere["farm"]["id"],
                                          tank_capacity_liters=40_000.0)

        # the diamond could disagree, which is exactly why the aggregate check exists
        validate_error(api.assign_order(env["order"]["id"],
                                        {"fueling_asset_id": foreign_truck["id"]}, fx.AGENT),
                       ApiErrorId.ERR_CROSS_FARM_REFERENCE, 422)

        fx.assign_order(env["order"]["id"], env["truck"]["id"])
        fx.start_order(env["order"]["id"])
        ticket = fx.post_uplift(env["order"]["id"],
                                fx.current_order_version(env["order"]["id"]),
                                meter_start_liters=0.0, meter_end_liters=20_000.0,
                                temperature_c=15.0)

        order = fx.read_order(ticket["fueling_order_id"])
        through_tank = fx.read_tank(order["storage_tank_id"])["fuel_farm_id"]
        through_asset = fx.read_asset(order["fueling_asset_id"])["fuel_farm_id"]
        assert through_tank == env["farm"]["id"]
        assert through_asset == through_tank, \
            "both legs of the diamond land on the same farm once the check has passed"

    def test_a_membrane_sample_hangs_off_the_asset_and_not_off_a_tank(self, api):
        """PRD §3.7: "The same request draws a fresh quality sample with `sample_purpose`
        `POST_FILTER_CHANGE` in `DRAWN` status against the asset, which is the membrane check on the new
        elements — its metrics are later posted and judged by the same all-pass verdict logic, with the
        comparison density taken from the parent tank rather than a receipt certificate."
        PRD §3.7: "Recording a filter change is a `QualityInspector` action, permitted when the asset's
        `status` is either `DOWN_FOR_FILTER` or `FILTER_DUE` and the farm is not `FROZEN`, and it is what
        returns the asset to `IN_SERVICE`."
        PRD §4: "Lists samples, filterable by receipt, tank, asset and status."

        Design: Corner/complexity_layers/polymorphic_sample_parents_do_not_create_a_cycle
        """
        env = fx.setup_fuel_farm(clock="2025-08-10T06:00:00Z", permit_overrides=LONG_PERMIT)
        truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  differential_pressure_kpa=10.0)
        fx.set_clock("2026-08-10T06:00:00Z")
        assert fx.read_asset(truck["id"])["status"] == "FILTER_DUE", \
            "a year of calendar life alone is enough to call the elements due"

        change = validate_success(api.create_filter_change(
            truck["id"], F.create_filter_change_payload(), fx.INSPECTOR_A), 201)
        assert change["fueling_asset_id"] == truck["id"]

        samples, meta = validate_paginated(api.list_quality_samples(
            fx.INSPECTOR_A, {"fueling_asset_id": truck["id"]}))
        assert meta["total_count"] == 1
        membrane = samples[0]
        assert membrane["sample_purpose"] == "POST_FILTER_CHANGE"
        assert membrane["status"] == "DRAWN"
        assert membrane["fueling_asset_id"] == truck["id"]
        assert membrane["fuel_receipt_id"] is None, \
            "the parent slots are alternative edges, so the receipt edge stays empty"
        assert fx.read_asset(truck["id"])["fuel_farm_id"] == env["farm"]["id"], \
            "the asset reaches its farm directly, without passing through a tank"


class TestTheTanksTwoDimensions:
    def test_service_and_quality_move_without_disturbing_each_other(self, api):
        """PRD §3.4: "A storage tank carries two status dimensions that evolve on the same row without
        constraining each other's shape."
        PRD §3.4: "A tank may perfectly well be `RELEASED` on quality while `ISOLATED` on service, and the
        two dimensions must be tracked and reported separately."
        PRD §3.4: "On the quality dimension, a fresh tank starts `ON_TEST` and cannot yet source an order."
        PRD §3.4: "Quarantining a tank, `RELEASED → QUARANTINED`, arrives by three different routes: a direct
        request by a `QualityInspector` carrying an optional `reason`, the cascade hop from a receipt
        quarantine described above, or a gauge measurement reporting free water at or above 25.0
        millimetres."

        Design: Corner/complexity_layers/the_tank_carries_two_independent_status_dimensions
        """
        env = fx.setup_fuel_farm()
        tank = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                opening_volume_liters=100_000.0)
        assert (tank["service_status"], tank["quality_status"]) == ("IN_SERVICE", "ON_TEST")

        sample = fx.draw_tank_sample(tank["id"], fx.INSPECTOR_A)
        drawn_from = fx.read_tank(tank["id"])
        assert (drawn_from["service_status"], drawn_from["quality_status"]) == \
            ("IN_SERVICE", "ON_TEST"), \
            "drawing a quality sample never touches the mechanical dimension"

        fx.post_results(sample["id"])
        fx.release_tank_quality(tank["id"], fx.INSPECTOR_B)
        released = fx.read_tank(tank["id"])
        assert (released["service_status"], released["quality_status"]) == \
            ("IN_SERVICE", "RELEASED")

        fx.isolate_tank(tank["id"], "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
        isolated = fx.read_tank(tank["id"])
        assert (isolated["service_status"], isolated["quality_status"]) == \
            ("ISOLATED", "RELEASED")

        validate_success(api.change_tank_service_status(
            tank["id"], {"to_status": "IN_SERVICE"}, fx.OPERATOR), 200)
        validate_success(api.quarantine_tank(tank["id"], fx.INSPECTOR_B), 200)
        quarantined = fx.read_tank(tank["id"])
        assert (quarantined["service_status"], quarantined["quality_status"]) == \
            ("IN_SERVICE", "QUARANTINED")

        fx.isolate_tank(tank["id"], "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
        both = fx.read_tank(tank["id"])
        assert (both["service_status"], both["quality_status"]) == \
            ("ISOLATED", "QUARANTINED"), \
            "all four combinations are reachable because the dimensions are genuinely parallel"
