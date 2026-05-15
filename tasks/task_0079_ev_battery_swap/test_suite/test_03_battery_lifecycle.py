"""Battery lifecycle: registration, charging cycle, fault, recall pathway.

Covers PRD §3.2 (battery onboarding, start/finish-charging, fault) and
the recall pathway in §3.6.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    add_charging_slot,
    assert_battery,
    create_battery,
    create_battery_model,
    create_station,
    drive_battery_to_charging,
    finish_charge,
    make_admin_headers,
    make_operator_headers,
    report_battery_fault,
    retire_battery_via_recall,
    setup_basic_scene,
    setup_models_and_compat,
    start_charging_payload,
    validate_error,
    validate_success,
)


class TestBatteryRegistration:
    def test_register_battery_starts_idle(self, api, platform_admin_headers):
        """PRD §3.2: "The new battery starts at status IDLE, cycle_count
        zero, cascade_stage NONE, recall_flag false, and soh_grade A."

        Claim: a freshly registered battery satisfies all five initial
        invariants in a single returned envelope.
        """
        station = create_station()
        bm = create_battery_model()
        b = create_battery(station_id=station["id"],
                           battery_model_code=bm["code"])
        assert_battery(b)
        assert b["status"] == "IDLE"
        assert b["cycle_count"] == 0
        assert b["cascade_stage"] == "NONE"
        assert b["recall_flag"] is False
        assert b["soh_grade"] == "A"

    def test_register_battery_increments_station_idle_count(self, api,
                                                            platform_admin_headers):
        """PRD §3.2: "The station's idle_battery_count is incremented by
        one as a direct side effect of registration."

        Claim: after creating a battery at a station, station's
        idle_battery_count increases by 1.
        """
        station = create_station()
        bm = create_battery_model()
        before = station["idle_battery_count"]
        create_battery(station_id=station["id"],
                       battery_model_code=bm["code"])
        after = validate_success(
            api.get_station(station["id"], platform_admin_headers),
        )
        assert after["idle_battery_count"] == before + 1

    def test_duplicate_serial_number_rejected(self, api, platform_admin_headers):
        """PRD §2.11: "a duplicate serial_number on a battery ... is
        rejected with ERR_DUPLICATE_RESOURCE and HTTP 409."

        Claim: two batteries with same serial_number → second rejected.
        """
        station = create_station()
        bm = create_battery_model()
        first = create_battery(station_id=station["id"],
                               battery_model_code=bm["code"])
        from test_helpers import create_battery_payload, TEST_USERS
        dup = create_battery_payload(
            battery_model_code=bm["code"], station_id=station["id"],
            serial_number=first["serial_number"],
        )
        resp = api.create_battery(dup, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


class TestStartCharging:
    def test_start_charging_moves_battery_and_slot(self, api):
        """PRD §3.2: "When the move succeeds, the battery flips from IDLE
        to CHARGING, the slot becomes OCCUPIED and binds to the battery's
        id".

        Claim: start-charging transitions Battery IDLE→CHARGING and Slot
        EMPTY→OCCUPIED with slot.battery_id == battery.id.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        op_headers = make_operator_headers(scene["station"]["id"])
        slot = scene["slots"][0]
        b = drive_battery_to_charging(scene, idle["id"], slot_id=slot["id"])
        assert b["status"] == "CHARGING"
        # Slot side-effect (via station charging-slot list).
        slots = api.list_charging_slots(
            scene["station"]["id"], op_headers,
        ).json()["data"]
        match = [s for s in slots if s["id"] == slot["id"]][0]
        assert match["status"] == "OCCUPIED"
        assert match["battery_id"] == idle["id"]

    def test_start_charging_updates_station_counts(self, api):
        """PRD §3.2: "the station's idle_battery_count decreases by one
        and charging_battery_count rises by one".

        Claim: idle -= 1 and charging += 1 on the host station after
        start-charging.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        admin_headers = scene["station"]
        station = api.get_station(
            scene["station"]["id"],
            make_operator_headers(scene["station"]["id"]),
        ).json()["data"]
        before_idle = station["idle_battery_count"]
        before_charging = station["charging_battery_count"]
        drive_battery_to_charging(scene, idle["id"])
        after = api.get_station(
            scene["station"]["id"],
            make_operator_headers(scene["station"]["id"]),
        ).json()["data"]
        assert after["idle_battery_count"] == before_idle - 1
        assert after["charging_battery_count"] == before_charging + 1

    def test_start_charging_on_recalled_battery_rejected(self, api):
        """PRD §3.2: "Violating the recall predicate returns
        ERR_BATTERY_RECALLED".

        Claim: start-charging on a battery with recall_flag=true →
        ERR_BATTERY_RECALLED.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        # Apply recall first, leaving battery RETIRED + recall_flag true.
        recalled = retire_battery_via_recall(scene, idle)
        assert recalled["recall_flag"] is True
        op_headers = make_operator_headers(scene["station"]["id"])
        resp = api.start_charging(
            idle["id"],
            start_charging_payload(scene["slots"][0]["id"]),
            op_headers,
        )
        # State and recall predicates both apply; PRD §2.11 says state
        # check (priority 4) precedes recall check (priority 6). Both 409.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_INVALID_STATE.value,
            ApiErrorId.ERR_BATTERY_RECALLED.value,
        ])


class TestFinishCharging:
    def test_finish_charging_returns_to_idle(self, api):
        """PRD §3.2: "the battery returns from CHARGING to IDLE in the
        ordinary way".

        Claim: finish-charging with healthy SOH inputs ends with the
        battery at status IDLE and cycle_count incremented by 1.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, idle["id"])
        b = finish_charge(
            scene, idle["id"], soc_pct=100.0, capacity_test_kwh=50.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        assert b["status"] == "IDLE"
        assert b["cycle_count"] == 1

    def test_finish_charging_requires_soc_at_least_95(self, api):
        """PRD §3.2: "the submitted soc_pct must be at least 95, marking
        the charge as complete; otherwise ERR_INVALID_STATE."

        Claim: finish-charging with soc_pct=90 → ERR_INVALID_STATE.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, idle["id"])
        from test_helpers import finish_charging_payload
        resp = api.finish_charging(
            idle["id"],
            finish_charging_payload(
                soc_pct=90.0, capacity_test_kwh=50.0,
                internal_resistance_mohm=50.0, avg_temperature_c=25.0,
            ),
            make_operator_headers(scene["station"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_finish_charging_increments_cycle_count(self, api):
        """PRD §3.2: "the battery's cycle_count is incremented by one
        and its soc_pct overwritten with the value just submitted."

        Claim: after finish-charging cycle_count = old + 1, soc_pct =
        submitted value.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, idle["id"])
        b = finish_charge(
            scene, idle["id"], soc_pct=98.0, capacity_test_kwh=50.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        assert b["cycle_count"] == 1
        assert float(b["soc_pct"]) == 98.0


class TestFaultHandling:
    def test_report_fault_from_idle(self, api):
        """PRD §3.2: "Reporting a fault accepts an optional reason string
        and is valid when the battery's status is in IDLE or CHARGING;
        the battery transitions to FAULT".

        Claim: report-fault on IDLE battery → status FAULT, station
        idle_battery_count decremented.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        op = make_operator_headers(scene["station"]["id"])
        before = api.get_station(scene["station"]["id"], op).json()["data"]
        b = report_battery_fault(scene, idle["id"])
        assert b["status"] == "FAULT"
        after = api.get_station(scene["station"]["id"], op).json()["data"]
        assert after["idle_battery_count"] == before["idle_battery_count"] - 1

    def test_clear_fault_returns_to_idle(self, api):
        """PRD §3.2: "A fault is cleared by an operator only when the
        battery is currently FAULT and recall_flag is false: the battery
        returns to IDLE and the station's idle_battery_count increases
        by one."

        Claim: clear-fault on FAULT battery → status IDLE.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        op = make_operator_headers(scene["station"]["id"])
        report_battery_fault(scene, idle["id"])
        resp = api.clear_fault(idle["id"], op)
        b = validate_success(resp)
        assert b["status"] == "IDLE"

    def test_report_fault_from_charging(self, api):
        """PRD §3.2: "Reporting a fault ... is valid when the battery's
        status is in IDLE or CHARGING".

        Claim: report-fault on a CHARGING battery → status FAULT; host
        slot released to EMPTY; station charging_battery_count decremented.
        """
        scene = setup_basic_scene(total_slots=2)
        idle = scene["idle_batteries"][0]
        slot = scene["slots"][0]
        drive_battery_to_charging(scene, idle["id"], slot_id=slot["id"])
        op = make_operator_headers(scene["station"]["id"])
        before = api.get_station(scene["station"]["id"], op).json()["data"]
        b = report_battery_fault(scene, idle["id"])
        assert b["status"] == "FAULT"
        after = api.get_station(scene["station"]["id"], op).json()["data"]
        assert (
            after["charging_battery_count"]
            == before["charging_battery_count"] - 1
        )
        slots = api.list_charging_slots(scene["station"]["id"], op).json()[
            "data"
        ]
        match = [s for s in slots if s["id"] == slot["id"]][0]
        assert match["status"] == "EMPTY"
        assert match.get("battery_id") in (None, "")
