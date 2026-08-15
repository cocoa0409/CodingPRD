"""Telemetry ledger, tank guards, and fuel projection variants (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    arrive_visit,
    assert_telemetry_event,
    complete_visit,
    create_equipment_unit,
    create_visit,
    dispatch_visit,
    get_site,
    get_unit,
    off_hire_contract,
    post_telemetry,
    set_logical_clock,
    setup_on_rent_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]
TEST_DEPOT = TEST_USERS["depot_manager_headers"]
TEST_TECH = TEST_USERS["field_technician_headers"]


def _projection(api, unit_id, method):
    data = validate_success(
        api.get_fuel_projection(unit_id, TEST_DEPOT, params={"method": method}), 200
    )
    return data


class TestFuelProjectionDualVariant:
    def _setup_deployed_unit_with_telemetry(self, api):
        """200 kW unit deployed; tank filled to 3000 L; 10 runtime hours and 500
        burn liters metered inside the trailing window (clock 2026-09-05)."""
        bundle = setup_on_rent_contract(clock_after_start="2026-09-05T00:00:00Z")
        cid = bundle["contract"]["id"]
        uid = bundle["unit"]["id"]
        post_telemetry(cid, "FUEL_DELIVERY", 3000, recorded_at="2026-09-02T08:00:00Z")
        post_telemetry(cid, "RUNTIME", 10, unit_id=uid, recorded_at="2026-09-04T10:00:00Z")
        post_telemetry(cid, "FUEL_BURN", 500, unit_id=uid, recorded_at="2026-09-04T12:00:00Z")
        return bundle

    def test_rated_curve_projection(self, api):
        """PRD §3.6: "The rated-curve variant computes the hourly burn as the unit's
        `capacity_kw` multiplied by a load factor of 0.75 and a specific consumption
        of 0.28 liters per kilowatt-hour, independent of any telemetry."
        PRD §3.6: "Either way, the projected daily burn is the hourly rate multiplied
        by twenty-four, and the next-refuel estimate is the current
        `tank_level_liters` of the unit's site — resolved through `current_site_id` —
        divided by the hourly rate."

        Design: Difficulty/dual_variant_calc/fuel_projection_rated_vs_metered
        """
        bundle = self._setup_deployed_unit_with_telemetry(api)
        rated = _projection(api, bundle["unit"]["id"], "RATED_CURVE")
        # 200 * 0.75 * 0.28 = 42.0 L/h; 42 * 24 = 1008 L/day; 3000 / 42 = 71.43 h
        assert rated["liters_per_hour"] == pytest.approx(42.0, abs=0.005)
        assert rated["projected_liters_per_day"] == pytest.approx(1008.0, abs=0.005)
        assert rated["next_refuel_eta_hours"] == pytest.approx(71.43, abs=0.005)

    def test_metered_avg_projection_diverges_from_rated(self, api):
        """PRD §3.6: "The metered-average variant considers the unit's telemetry
        inside the trailing seven-day window — from seven days before the logical now
        through the logical now, both ends inclusive — and divides the total fuel-burn
        liters in that window by the total runtime hours in that window".
        PRD §3.6: "the two methods yield identical answers for an unrun unit and
        diverge exactly when the metered rate differs from the nameplate curve."

        Design: Difficulty/dual_variant_calc/fuel_projection_rated_vs_metered
        """
        bundle = self._setup_deployed_unit_with_telemetry(api)
        rated = _projection(api, bundle["unit"]["id"], "RATED_CURVE")
        metered = _projection(api, bundle["unit"]["id"], "METERED_AVG")
        # 500 L / 10 h = 50.0 L/h; 50 * 24 = 1200 L/day; 3000 / 50 = 60.0 h
        assert metered["liters_per_hour"] == pytest.approx(50.0, abs=0.005)
        assert metered["projected_liters_per_day"] == pytest.approx(1200.0, abs=0.005)
        assert metered["next_refuel_eta_hours"] == pytest.approx(60.0, abs=0.005)
        assert metered["telemetry_event_count"] == 2
        assert rated["liters_per_hour"] != metered["liters_per_hour"]


class TestMeteredWindowBoundaries:
    def test_metered_window_inclusive_boundary(self, api):
        """PRD §3.6: "The metered-average variant considers the unit's telemetry
        inside the trailing seven-day window — from seven days before the logical now
        through the logical now, both ends inclusive".

        Design: Corner/calculations/metered_window_inclusive_boundary
        """
        bundle = setup_on_rent_contract(
            contract_overrides={"expected_offhire_date": "2026-09-15T00:00:00Z"},
            clock_after_start="2026-09-08T00:00:00Z",
        )
        cid = bundle["contract"]["id"]
        uid = bundle["unit"]["id"]
        # Exactly at now-7d: inside the inclusive window.
        post_telemetry(cid, "RUNTIME", 4, unit_id=uid, recorded_at="2026-09-01T00:00:00Z")
        post_telemetry(cid, "FUEL_BURN", 160, unit_id=uid, recorded_at="2026-09-01T00:00:00Z")
        # One hour before the window opens: excluded.
        post_telemetry(cid, "RUNTIME", 10, unit_id=uid, recorded_at="2026-08-31T23:00:00Z")
        post_telemetry(cid, "FUEL_BURN", 600, unit_id=uid, recorded_at="2026-08-31T23:00:00Z")

        metered = _projection(api, uid, "METERED_AVG")
        # Only the boundary pair counts: 160 / 4 = 40.0; wrong inclusion -> 54.29.
        assert metered["liters_per_hour"] == pytest.approx(40.0, abs=0.005)
        assert metered["projected_liters_per_day"] == pytest.approx(960.0, abs=0.005)
        assert metered["telemetry_event_count"] == 2

    def test_metered_fallback_to_rated_on_empty_window(self, api):
        """PRD §3.6: "when the window holds zero runtime hours, the variant falls back
        to the rated-curve result, so the two methods yield identical answers for an
        unrun unit and diverge exactly when the metered rate differs from the
        nameplate curve."

        Design: Corner/calculations/metered_fallback_to_rated_on_empty_window
        """
        bundle = setup_on_rent_contract()
        uid = bundle["unit"]["id"]
        metered = _projection(api, uid, "METERED_AVG")
        # No telemetry at all: the fallback answer equals the rated curve.
        assert metered["liters_per_hour"] == pytest.approx(42.0, abs=0.005)
        assert metered["projected_liters_per_day"] == pytest.approx(1008.0, abs=0.005)
        assert metered["telemetry_event_count"] == 0


class TestTelemetryLedger:
    def test_telemetry_event_append_only_and_filterable(self, api):
        """PRD §2.4: "An accessory kit catalog entry and a telemetry event each carry
        only `id` and `created_at`: both `updated_at` and `version` are absent from
        these two resources, because both are immutable once created — a catalog entry
        is never edited after publication, and a telemetry event is an append-only
        record that is never modified after it is written."
        PRD §3.6: "The telemetry list may be filtered by `equipment_unit_id`,
        `contract_id`, or `event_type`."

        Design: Corner/entities/telemetry_event_append_only_and_filterable
        """
        bundle = setup_on_rent_contract(clock_after_start="2026-09-03T00:00:00Z")
        cid = bundle["contract"]["id"]
        uid = bundle["unit"]["id"]

        event = post_telemetry(cid, "RUNTIME", 4, unit_id=uid)
        assert_telemetry_event(event)

        fetched = validate_success(api.get_telemetry_event(event["id"], TEST_TECH), 200)
        assert fetched["value"] == 4
        assert "version" not in fetched
        assert "updated_at" not in fetched

        data, meta = validate_paginated(
            api.list_telemetry_events(
                TEST_TECH, params={"contract_id": cid, "event_type": "RUNTIME"}
            )
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == event["id"]

    def test_telemetry_unit_contract_mismatch(self, api):
        """PRD §3.6: "Where a unit is named, it must sit on an equipment line in
        `PENDING` or `ON_RENT` status of the same contract, or the event is rejected
        with `ERR_UNIT_CONTRACT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/telemetry_unit_contract_mismatch
        """
        bundle = setup_on_rent_contract()
        stranger = create_equipment_unit(
            capacity_kw=100, nox_g_per_kwh=2.5, day_rate_cents=8000,
            week_rate_cents=40000, month_rate_cents=130000, demob_fee_cents=20000,
        )
        res = api.create_telemetry_event(
            {
                "equipment_unit_id": stranger["id"],
                "contract_id": bundle["contract"]["id"],
                "event_type": "RUNTIME",
                "value": 3,
            },
            TEST_TECH,
        )
        validate_error(res, ApiErrorId.ERR_UNIT_CONTRACT_MISMATCH, expected_status=422)
        assert get_unit(stranger["id"])["runtime_hours_total"] == 0


class TestTankGuards:
    def test_tank_capacity_boundary_equality_allowed(self, api):
        """PRD §3.6: "A delivery — whether posted directly as telemetry or generated
        by a completed fuel-delivery visit in §3.7 — must not raise the site level
        above its `fuel_tank_capacity_liters`, though landing exactly at capacity is
        allowed; an over-capacity delivery is rejected with
        `ERR_TANK_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/tank_capacity_boundary_equality_allowed
        """
        bundle = setup_on_rent_contract()
        cid = bundle["contract"]["id"]
        site_id = bundle["site"]["id"]

        post_telemetry(cid, "FUEL_DELIVERY", 4000)
        # Landing exactly at the 5000 L capacity is allowed.
        post_telemetry(cid, "FUEL_DELIVERY", 1000)

        over = api.create_telemetry_event(
            {"contract_id": cid, "event_type": "FUEL_DELIVERY", "value": 1},
            TEST_TECH,
        )
        validate_error(over, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED, expected_status=422)
        assert get_site(site_id)["tank_level_liters"] == 5000

    def test_pumpout_exceeds_tank_level(self, api):
        """PRD §3.6: "A pump-out may not draw more than the current tank level; an
        overdraw is rejected with `ERR_INSUFFICIENT_TANK_FUEL` (HTTP 422)."

        Design: Corner/validations/pumpout_exceeds_tank_level
        """
        bundle = setup_on_rent_contract(clock_after_start="2026-09-03T00:00:00Z")
        cid = bundle["contract"]["id"]
        site_id = bundle["site"]["id"]
        post_telemetry(cid, "FUEL_DELIVERY", 50)

        set_logical_clock("2026-09-06T00:00:00Z")
        off_hire_contract(cid)

        res = api.create_telemetry_event(
            {"contract_id": cid, "event_type": "FUEL_PUMP_OUT", "value": 100},
            TEST_TECH,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_TANK_FUEL, expected_status=422)
        assert get_site(site_id)["tank_level_liters"] == 50


class TestTankLevelInvariant:
    def test_fuel_delivery_raises_tank_level(self, api):
        """PRD §3.6: "Once accepted, an event applies its effect immediately and
        immutably: runtime adds `value` to the unit's `runtime_hours_total`, fuel burn
        adds to `fuel_consumed_liters_total`, delivery raises the site's
        `tank_level_liters`, and pump-out lowers it."

        Design: Difficulty/compensating_invariant/fuel_delivery_then_pumpout_restores_tank_level
        """
        bundle = setup_on_rent_contract(clock_after_start="2026-09-03T00:00:00Z")
        assert get_site(bundle["site"]["id"])["tank_level_liters"] == 0

        post_telemetry(bundle["contract"]["id"], "FUEL_DELIVERY", 2000)
        assert get_site(bundle["site"]["id"])["tank_level_liters"] == 2000

    def test_pumpout_restores_tank_level_exactly(self, api):
        """PRD §3.1: "A site's `tank_level_liters` is never written directly: it is a
        computed figure that starts at zero and thereafter equals the sum of all
        fuel-delivery telemetry minus all pump-out telemetry recorded over every
        contract at that site."

        Design: Difficulty/compensating_invariant/fuel_delivery_then_pumpout_restores_tank_level
        """
        bundle = setup_on_rent_contract(clock_after_start="2026-09-03T00:00:00Z")
        cid = bundle["contract"]["id"]
        site_id = bundle["site"]["id"]

        post_telemetry(cid, "FUEL_DELIVERY", 2000)
        assert get_site(site_id)["tank_level_liters"] == 2000

        set_logical_clock("2026-09-06T00:00:00Z")
        off_hire_contract(cid)

        post_telemetry(cid, "FUEL_PUMP_OUT", 2000)
        assert get_site(site_id)["tank_level_liters"] == 0, (
            "an equal pump-out restores the tank to its pre-pair level"
        )


class TestFuelDeliveryVisit:
    def test_fuel_delivery_visit_complete_creates_telemetry(self, api):
        """PRD §3.7: "Completion of a fuel-delivery visit has a physical side effect:
        the system appends a `FUEL_DELIVERY` telemetry event whose `value` is the
        visit's `fuel_quantity_liters`, raising the site tank level under the same
        capacity guard as any other delivery".

        Design: Corner/endpoints/fuel_delivery_visit_complete_creates_telemetry
        """
        bundle = setup_on_rent_contract()
        cid = bundle["contract"]["id"]
        visit = create_visit(
            cid, "FUEL_DELIVERY",
            scheduled_start="2026-08-02T10:00:00Z",
            scheduled_end="2026-08-02T11:00:00Z",
            fuel_quantity_liters=1500,
        )
        dispatch_visit(visit["id"], "tech-3")
        arrive_visit(visit["id"], "tech-3")

        completed = complete_visit(visit["id"], "tech-3")
        assert completed["status"] == "COMPLETED"

        data, meta = validate_paginated(
            api.list_telemetry_events(
                TEST_TECH, params={"contract_id": cid, "event_type": "FUEL_DELIVERY"}
            )
        )
        assert meta["total_count"] == 1
        assert data[0]["value"] == 1500
        assert get_site(bundle["site"]["id"])["tank_level_liters"] == 1500
