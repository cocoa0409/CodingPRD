"""Corner behaviour of the static picture: farm identity and posture, permit governance and
reinstatement, and the tank's ledger and isolation edges."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F,
)


class TestFuelFarmCorners:
    def test_a_second_farm_cannot_reuse_an_iata_code(self, api):
        """PRD §3.1: "Registering a farm requires the airport's `iata_code` — exactly three uppercase
        letters, unique across all farms — and a consortium `name`."

        Design: Corner/entities/farm_iata_code_uniqueness_is_global
        """
        first = fx.create_farm(iata_code="SFO", name="SFO Fuel Consortium")

        validate_error(api.create_fuel_farm(
            F.create_fuel_farm_payload(iata_code="SFO", name="Second Consortium"), fx.ADMIN),
            ApiErrorId.ERR_DUPLICATE_KEY, 409)

        assert fx.read_farm(first["id"])["name"] == "SFO Fuel Consortium"

    def test_advancing_the_clock_past_permit_validity_freezes_the_farm_alone(self, api):
        """PRD §2.5: "Two lifecycle transitions are purely time-driven and are evaluated lazily: a
        fuel authorization moves from `ISSUED` to `EXPIRED` once the clock has reached or passed its
        `expires_at_utc`, and an environmental permit moves from `ACTIVE` to `EXPIRED` once the clock
        has reached or passed its `valid_until_utc`."
        PRD §2.5: "Each such auto-transition raises the affected row's `version` by 1, and a permit
        expiry additionally recomputes the farm's posture — which will land on `FROZEN`, because a
        farm without an active permit covering the clock is frozen by definition."

        Design: Corner/entities/posture_recomputed_by_clock_advance_alone
        """
        env = fx.setup_fuel_farm(permit_overrides={"valid_until_utc": "2026-08-10T12:00:00Z"})
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        before = fx.read_farm(env["farm"]["id"])
        assert before["posture"] == "OPEN"
        assert before["in_service_asset_count"] == 1

        fx.set_clock("2026-08-10T12:00:00Z")

        permits, _meta = validate_paginated(
            api.list_environmental_permits(env["farm"]["id"], fx.ADMIN))
        assert [p["status"] for p in permits] == ["EXPIRED"]
        after = fx.read_farm(env["farm"]["id"])
        assert after["posture"] == "FROZEN"
        assert after["in_service_asset_count"] == 1, \
            "the freeze came from the clock alone, with no child write"


class TestEnvironmentalPermitCorners:
    def test_the_latest_valid_from_governs_and_ties_break_on_created_at(self, api):
        """PRD §2.7: "First, the **governing permit** is identified: among the farm's environmental
        permits, the one with the latest `valid_from_utc` governs; if two permits share the same
        `valid_from_utc`, the tie is broken by `created_at` ascending, so the earliest-created of the
        tied permits wins."
        PRD §2.7: "the farm's `active_permit_throughput_used_liters` has reached or exceeded 90 percent
        of the governing permit's `max_daily_throughput_liters`"

        Design: Corner/entities/latest_valid_from_permit_governs_with_created_at_tiebreak
        """
        fx.set_clock()
        farm = fx.create_farm()
        fx.issue_permit(farm["id"], valid_from_utc="2026-01-01T00:00:00Z",
                        valid_until_utc="2027-01-01T00:00:00Z",
                        max_daily_throughput_liters=400000.0)
        fx.issue_permit(farm["id"], valid_from_utc="2026-06-01T00:00:00Z",
                        valid_until_utc="2027-01-01T00:00:00Z",
                        max_daily_throughput_liters=33000.0)
        fx.issue_permit(farm["id"], valid_from_utc="2026-06-01T00:00:00Z",
                        valid_until_utc="2027-01-01T00:00:00Z",
                        max_daily_throughput_liters=400000.0)
        fx.register_truck(farm["id"], tank_capacity_liters=40_000.0)
        tank = fx.make_released_tank(farm["id"], capacity_liters=5_000_000.0,
                                     safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                     opening_volume_liters=0.0)

        fx.make_released_receipt(
            tank["id"], metrics={"particulate_mg_per_l": 0.4, "conductivity_ps_per_m": 150.0,
                                 "flash_point_c": 41.0},
            delivery_mode="PIPELINE", supplier_name="Refinery One",
            meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
            tank_closing_gauge_liters=29700.0, temperature_c=15.0,
            certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)

        assert fx.read_farm(farm["id"])["posture"] == "RESTRICTED", \
            "the second permit's 33000.0-liter cap governs, so 29700.00 liters is 90 percent"

    def test_reinstatement_after_the_validity_window_closed_is_refused(self, api):
        """PRD §3.1: "The reverse, `SUSPENDED → ACTIVE`, is permitted only while the logical clock is
        still strictly before the permit's `valid_until_utc`, and it recomputes posture."
        PRD §2.7: "The permit is considered satisfactory when it exists, its `status` is `ACTIVE`, and
        the logical clock is at or after its `valid_from_utc` and strictly before its
        `valid_until_utc`."

        Design: Corner/entities/reinstate_after_validity_window_closed
        """
        env = fx.setup_fuel_farm(permit_overrides={"valid_until_utc": "2026-08-10T12:00:00Z"})
        validate_success(api.suspend_permit(
            env["permit"]["id"], {"suspension_reason": "regulator audit"}, fx.ENVIRO))
        fx.set_clock("2026-08-10T13:00:00Z")

        validate_error(api.reinstate_permit(env["permit"]["id"], fx.ENVIRO),
                       ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

        assert fx.read_farm(env["farm"]["id"])["posture"] == "FROZEN"


class TestStorageTankCorners:
    def test_a_gauge_reporting_exactly_twenty_five_millimetres_quarantines_the_tank(self, api):
        """PRD §3.4: "When the reported water depth reaches 25.0 millimetres the gauge itself forces
        the quality quarantine and its two downstream hops; posture is recomputed in every case."
        PRD §3.4: "Quarantining a tank, `RELEASED → QUARANTINED`, arrives by three different routes: a
        direct request by a `QualityInspector` carrying an optional `reason`, the cascade hop from a
        receipt quarantine described above, or a gauge measurement reporting free water at or above
        25.0 millimetres."

        Design: Corner/entities/gauge_with_water_bottom_at_25mm_quarantines_the_tank
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        tank_id = env["tank"]["id"]

        below = fx.gauge_tank(tank_id, 1_000_000.0, water_bottom_mm=24.99)
        assert below["quality_status"] == "RELEASED", "24.99 millimetres is below the trigger"

        at_the_line = fx.gauge_tank(tank_id, 1_000_000.0, water_bottom_mm=25.0)
        assert at_the_line["quality_status"] == "QUARANTINED"
        assert at_the_line["water_bottom_mm"] == pytest.approx(25.0, abs=0.005)
        assert fx.read_farm(env["farm"]["id"])["posture"] == "RESTRICTED"

    def test_a_release_landing_exactly_on_safe_fill_is_allowed(self, api):
        """PRD §3.3: "The destination tank's current `book_volume_liters` plus the receipt's
        `net_volume_liters` must not exceed the tank's `safe_fill_liters`, or the release is refused
        with `ERR_SAFE_FILL_EXCEEDED`."

        Design: Corner/entities/safe_fill_reached_exactly_is_allowed
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_daily_throughput_liters": 400000.0})
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        tank = fx.make_released_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                     safe_fill_liters=29_700.0, density_kg_per_m3=795.0,
                                     opening_volume_liters=0.0)

        released = fx.make_released_receipt(
            tank["id"], metrics={"particulate_mg_per_l": 0.4, "conductivity_ps_per_m": 150.0,
                                 "flash_point_c": 41.0},
            delivery_mode="PIPELINE", supplier_name="Refinery One",
            meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
            tank_closing_gauge_liters=29700.0, temperature_c=15.0,
            certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)
        assert released["status"] == "RELEASED"
        assert fx.read_tank(tank["id"])["book_volume_liters"] == \
            pytest.approx(29700.00, abs=0.005), "book volume may reach safe fill exactly"

    def test_only_intersecting_isolation_windows_conflict(self, api):
        """PRD §3.4: "Isolating a tank, `IN_SERVICE → ISOLATED`, requires an isolation window supplied
        as `isolation_window_start_utc` and `isolation_window_end_utc`, and it competes for a scarce
        resource: **a farm may have at most one tank isolated over any given instant.**"
        PRD §3.4: "No order drawing on the tank may be `ASSIGNED` or `FUELING`, and the requested
        half-open window must not intersect the isolation window of any other tank at the same farm
        whose `service_status` is already `ISOLATED`; a conflict is `ERR_TANK_ISOLATION_CONFLICT`."

        Design: Corner/entities/isolation_slot_capacity_one_per_farm
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        farm_id = env["farm"]["id"]
        fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        second = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                  safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                  opening_volume_liters=0.0)
        third = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                 safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                 opening_volume_liters=0.0)

        fx.isolate_tank(env["tank"]["id"], "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")

        validate_error(api.change_tank_service_status(
            second["id"], {"to_status": "ISOLATED",
                           "isolation_window_start_utc": "2026-08-10T09:00:00Z",
                           "isolation_window_end_utc": "2026-08-10T11:00:00Z"}, fx.OPERATOR),
            ApiErrorId.ERR_TANK_ISOLATION_CONFLICT, 409)
        assert fx.read_tank(second["id"])["service_status"] == "IN_SERVICE"

        clear = validate_success(api.change_tank_service_status(
            third["id"], {"to_status": "ISOLATED",
                          "isolation_window_start_utc": "2026-08-10T10:00:00Z",
                          "isolation_window_end_utc": "2026-08-10T11:00:00Z"}, fx.OPERATOR))
        assert clear["service_status"] == "ISOLATED", \
            "the constraint is on window intersection, not on how many tanks are isolated"
