"""Stations, charging slots, and reference-data CRUD.

Covers PRD §3.1 (station, slot, member, vehicle, reference-data
registration).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    add_charging_slot,
    assert_battery_model,
    assert_charging_slot,
    assert_compatibility_rule,
    assert_station,
    assert_vehicle_model,
    create_battery_model,
    create_battery_model_payload,
    create_station,
    create_station_payload,
    create_vehicle_model,
    create_vehicle_model_payload,
    setup_models_and_compat,
    validate_error,
    validate_success,
)


class TestStationRegistration:
    def test_register_station_returns_open_status(self, api, platform_admin_headers):
        """PRD §3.1: "it begins life as OPEN".

        Claim: a freshly created station has status == 'OPEN'.
        """
        resp = api.create_station(
            create_station_payload(), platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_station(data)
        assert data["status"] == "OPEN"

    def test_register_station_zero_counters(self, api, platform_admin_headers):
        """PRD §3.1: "Two counters, idle_battery_count and
        charging_battery_count ... both default to zero on registration."

        Claim: idle_battery_count and charging_battery_count both 0 at
        registration.
        """
        resp = api.create_station(
            create_station_payload(), platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["idle_battery_count"] == 0
        assert data["charging_battery_count"] == 0

    @pytest.mark.parametrize("total_slots", [0, 65, -1])
    def test_total_slots_bounds(self, api, platform_admin_headers, total_slots):
        """PRD §3.1: "A station must have at least one slot and at most
        sixty-four."

        Claim: total_slots = 0/65/-1 → ERR_INVALID_INPUT 422.
        """
        resp = api.create_station(
            create_station_payload(total_slots=total_slots),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    @pytest.mark.parametrize("lat", [-90.5, 90.5])
    def test_latitude_out_of_range(self, api, platform_admin_headers, lat):
        """PRD §3.1: "latitude between -90.0 and 90.0 inclusive".

        Claim: latitude outside [-90, 90] → ERR_INVALID_INPUT.
        """
        resp = api.create_station(
            create_station_payload(latitude=lat), platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


class TestChargingSlotRegistration:
    def test_slot_defaults_to_empty(self, api, platform_admin_headers):
        """PRD §3.1: "A slot's status is EMPTY on creation".

        Claim: fresh slot has status == 'EMPTY' and battery_id == null.
        """
        station = create_station()
        resp = api.create_charging_slot(
            station["id"], {"slot_number": 1}, platform_admin_headers,
        )
        slot = validate_success(resp, expected_status=201)
        assert_charging_slot(slot)
        assert slot["status"] == "EMPTY"
        assert slot.get("battery_id") in (None, "")

    def test_tou_zone_default_shoulder(self, api, platform_admin_headers):
        """PRD §3.1: "the zone defaults to SHOULDER when the operator
        does not supply one."

        Claim: slot created without tou_zone → tou_zone == 'SHOULDER'.
        """
        station = create_station()
        resp = api.create_charging_slot(
            station["id"], {"slot_number": 1}, platform_admin_headers,
        )
        slot = validate_success(resp, expected_status=201)
        assert slot["tou_zone"] == "SHOULDER"


class TestReferenceDataRegistration:
    def test_battery_model_default_ev_floor(self, api, platform_admin_headers):
        """PRD §3.1: "ev_soh_floor_pct ... defaults to 80.0 when the
        admin omits it."

        Claim: BatteryModel created without ev_soh_floor_pct → 80.0.
        """
        resp = api.create_battery_model(
            create_battery_model_payload(),  # omits ev_soh_floor_pct
            platform_admin_headers,
        )
        bm = validate_success(resp, expected_status=201)
        assert_battery_model(bm)
        assert float(bm["ev_soh_floor_pct"]) == 80.0

    def test_battery_model_no_updated_at(self, api, platform_admin_headers):
        """PRD §2.4: "BatteryModel, VehicleModel, CompatibilityRule,
        SOHAssessment, and AuditLog. updated_at and version are absent".

        Claim: BatteryModel response has no updated_at and no version field.
        """
        resp = api.create_battery_model(
            create_battery_model_payload(), platform_admin_headers,
        )
        bm = validate_success(resp, expected_status=201)
        assert "updated_at" not in bm, (
            "PRD §2.4: BatteryModel has no updated_at"
        )
        assert "version" not in bm, (
            "PRD §2.4: BatteryModel has no version"
        )

    def test_duplicate_battery_model_code_rejected(self, api, platform_admin_headers):
        """PRD §2.11: "a duplicate model code ... is rejected with
        ERR_DUPLICATE_RESOURCE and HTTP 409."

        Claim: creating two BatteryModels with the same code →
        ERR_DUPLICATE_RESOURCE on the second.
        """
        first = create_battery_model()
        resp = api.create_battery_model(
            create_battery_model_payload(code=first["code"]),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    def test_vehicle_model_voltage_constraint(self, api, platform_admin_headers):
        """PRD §3.1: "two voltages — pack_voltage_min (at least zero)
        and pack_voltage_max (strictly greater than pack_voltage_min)."

        Claim: pack_voltage_max <= pack_voltage_min → ERR_INVALID_INPUT.
        """
        resp = api.create_vehicle_model(
            create_vehicle_model_payload(
                pack_voltage_min=400.0, pack_voltage_max=400.0,
            ),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_compatibility_flags_default_true(self, api, platform_admin_headers):
        """PRD §3.1: "both flags default to true when omitted at creation."

        Claim: CompatibilityRule created without flags → connector_match
        and bms_handshake_supported both True.
        """
        bm = create_battery_model()
        vm = create_vehicle_model()
        resp = api.create_compatibility_rule(
            {
                "vehicle_model_code": vm["code"],
                "battery_model_code": bm["code"],
            },
            platform_admin_headers,
        )
        rule = validate_success(resp, expected_status=201)
        assert_compatibility_rule(rule)
        assert rule["connector_match"] is True
        assert rule["bms_handshake_supported"] is True
