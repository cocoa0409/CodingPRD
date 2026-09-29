"""Corner behaviour of the farm's derived posture and of the permit stack: a thaw that lands straight
on OPEN, a suspension that touches nothing because the permit does not govern, and a permit that is
ACTIVE without covering the clock."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F,
)

PIPELINE_PARCEL = dict(delivery_mode="PIPELINE", supplier_name="Refinery One",
                       meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
                       tank_closing_gauge_liters=29700.0, temperature_c=15.0,
                       certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)
PASSING_METRICS = {"particulate_mg_per_l": 0.4, "conductivity_ps_per_m": 150.0,
                   "flash_point_c": 41.0}


class TestFuelFarmPostureCorners:
    def test_a_thaw_lands_straight_on_open_when_no_other_cause_is_live(self, api):
        """PRD §2.7: "The resulting posture is `FROZEN` when the frozen condition holds, otherwise
        `RESTRICTED` when any restricted condition holds, otherwise `OPEN`."
        PRD §3.8: "That recomputation is how a farm thaws: the farm leaves `FROZEN` once no escalated
        incident remains at it and its permit is `ACTIVE` and unexpired, landing on `RESTRICTED` while
        any incident is still merely `REPORTED`."
        PRD §2.7: "Third, the farm is **restricted** if any of four conditions holds: at least one
        storage tank at the farm has `quality_status` `QUARANTINED`; at least one spill incident at the
        farm has `status` `REPORTED`; the farm's `active_permit_throughput_used_liters` has reached or
        exceeded 90 percent of the governing permit's `max_daily_throughput_liters`; or the farm's
        `in_service_asset_count` is zero."

        Design: Corner/state_machines/frozen_to_open_skips_restricted
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_reportable_spill_liters": 20.0,
                                                   "max_daily_throughput_liters": 400000.0})
        farm_id = env["farm"]["id"]
        fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        assert fx.read_farm(farm_id)["posture"] == "OPEN"

        spill = fx.report_spill(farm_id, spilled_volume_liters=25.0, surface="APRON")
        fx.escalate_spill(spill["id"], regulator_reference="REG-2026-0041")
        assert fx.read_farm(farm_id)["posture"] == "FROZEN"

        replacement = fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        assert replacement["status"] == "IN_SERVICE"
        frozen = fx.read_farm(farm_id)
        assert frozen["posture"] == "FROZEN", "a frozen farm stays frozen however healthy the rest is"
        assert frozen["in_service_asset_count"] == 1

        contained = fx.contain_spill(spill["id"], 25.0)
        assert contained["status"] == "CONTAINED"

        thawed = fx.read_farm(farm_id)
        assert thawed["open_spill_count"] == 0
        assert thawed["in_service_asset_count"] == 1
        assert thawed["posture"] == "OPEN", \
            "one recompute, and none of the four restricted causes is live"


class TestEnvironmentalPermitCorners:
    def test_only_the_governing_permit_freezes_the_farm_and_caps_its_receipts(self, api):
        """PRD §2.7: "First, the **governing permit** is identified: among the farm's environmental
        permits, the one with the latest `valid_from_utc` governs; if two permits share the same
        `valid_from_utc`, the tie is broken by `created_at` ascending, so the earliest-created of the tied
        permits wins."
        PRD §3.1: "An `EnvironmentalOfficer` may later drive `ACTIVE → SUSPENDED`, which requires a
        non-empty `suspension_reason` recorded on the permit and immediately drives the farm to `FROZEN`
        because it no longer has an active permit — the full freeze cascade described in §3.7 fires on
        that same request."
        PRD §3.3: "The farm's `active_permit_throughput_used_liters` plus the receipt's net volume must
        not exceed the governing permit's `max_daily_throughput_liters`, or the release is refused with
        `ERR_PERMIT_THROUGHPUT_EXCEEDED`."

        Design: Corner/state_machines/suspension_of_a_non_governing_permit_does_not_freeze_the_farm
        """
        env = fx.setup_farm_with_released_tank(
            opening_volume_liters=0.0, density_kg_per_m3=795.0,
            permit_overrides={"valid_from_utc": "2026-01-01T00:00:00Z",
                              "valid_until_utc": "2027-01-01T00:00:00Z",
                              "max_daily_throughput_liters": 1000.0})
        farm_id, tank_id, superseded = env["farm"]["id"], env["tank"]["id"], env["permit"]["id"]
        fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        governing = fx.issue_permit(farm_id, valid_from_utc="2026-06-01T00:00:00Z",
                                    valid_until_utc="2027-01-01T00:00:00Z",
                                    max_daily_throughput_liters=400000.0)
        assert fx.read_farm(farm_id)["posture"] == "OPEN"

        suspended = validate_success(api.suspend_permit(
            superseded, {"suspension_reason": "superseded by the 2026 renewal"}, fx.ENVIRO))
        assert suspended["status"] == "SUSPENDED"

        farm = fx.read_farm(farm_id)
        assert farm["posture"] == "OPEN", "the suspended permit was not the one that governs"
        permits, _meta = validate_paginated(api.list_environmental_permits(farm_id, fx.ADMIN))
        assert {p["id"]: p["status"] for p in permits} == {superseded: "SUSPENDED",
                                                          governing["id"]: "ACTIVE"}

        receipt = fx.make_released_receipt(tank_id, metrics=dict(PASSING_METRICS),
                                           **PIPELINE_PARCEL)
        assert receipt["status"] == "RELEASED", \
            "29,700 liters would breach the suspended permit's 1,000 litre day but not the governing one"
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(29700.00, abs=0.005)

    def test_a_permit_that_starts_next_month_governs_today_and_freezes_the_farm(self, api):
        """PRD §2.7: "The permit is considered satisfactory when it exists, its `status` is `ACTIVE`, and
        the logical clock is at or after its `valid_from_utc` and strictly before its `valid_until_utc`."
        PRD §2.7: "Operations that a `FROZEN` posture blocks are rejected with `ERR_FARM_FROZEN`, and
        when the block is specifically the absence of a satisfactory permit the rejection is
        `ERR_PERMIT_NOT_ACTIVE`."
        PRD §3.1: "A permit begins life with `status` `ACTIVE`, and issuing it recomputes the farm's
        posture, which typically leaves `FROZEN` at that moment."

        Design: Corner/state_machines/valid_from_in_the_future_is_active_but_not_covering
        """
        env = fx.setup_farm_with_released_tank(
            opening_volume_liters=0.0, density_kg_per_m3=795.0,
            permit_overrides={"valid_from_utc": "2026-01-01T00:00:00Z",
                              "valid_until_utc": "2027-01-01T00:00:00Z",
                              "max_daily_throughput_liters": 400000.0})
        farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]
        fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        assert fx.read_farm(farm_id)["posture"] == "OPEN"

        future = fx.issue_permit(farm_id, valid_from_utc="2026-09-01T00:00:00Z",
                                 valid_until_utc="2027-09-01T00:00:00Z",
                                 max_daily_throughput_liters=400000.0)
        assert future["status"] == "ACTIVE", "nothing about issuance looks at the clock"

        assert fx.read_farm(farm_id)["posture"] == "FROZEN", \
            "the latest valid_from_utc governs even though it does not cover the clock"

        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank_id, **PIPELINE_PARCEL), fx.OPERATOR),
            ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)

        receipts, _meta = validate_paginated(api.list_fuel_receipts(fx.OPERATOR))
        assert receipts == []
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(0.00, abs=0.005)
