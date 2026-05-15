"""Cross-station dispatch and manufacturer recall.

Covers PRD §3.6 (dispatch lifecycle + recall pathway).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    create_dispatch,
    create_dispatch_order_payload,
    report_battery_fault,
    retire_battery_via_recall,
    setup_basic_scene,
    setup_two_station_scene,
    validate_error,
    validate_success,
)


class TestDispatchValidation:
    def test_source_equals_dest_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "The source and destination must differ; submitting
        the same station for both fields is rejected with
        ERR_INVALID_DISPATCH."

        Claim: source_station_id == dest_station_id → ERR_INVALID_DISPATCH.
        """
        scene = setup_two_station_scene(idle_at_source=1)
        battery = scene["idle_batteries"][0]
        resp = api.create_dispatch_order(
            create_dispatch_order_payload(
                source_station_id=scene["source"]["id"],
                dest_station_id=scene["source"]["id"],
                battery_id=battery["id"],
            ),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DISPATCH.value)


class TestDispatchLifecycle:
    def test_dispatch_transitions_battery_in_transit(self, api,
                                                    platform_admin_headers):
        """PRD §3.6: "Beginning transit advances the order from REQUESTED
        to IN_TRANSIT. The battery transitions from IDLE to IN_TRANSIT,
        its station_id is cleared to null while in flight".

        Claim: after dispatch, order.status=IN_TRANSIT, battery.status=
        IN_TRANSIT, battery.station_id is null.
        """
        scene = setup_two_station_scene(idle_at_source=1)
        battery = scene["idle_batteries"][0]
        order = create_dispatch(
            scene["source"]["id"], scene["dest"]["id"], battery["id"],
        )
        resp = api.dispatch_dispatch_order(order["id"], platform_admin_headers)
        order2 = validate_success(resp)
        assert order2["status"] == "IN_TRANSIT"
        b = api.get_battery(battery["id"], platform_admin_headers).json()["data"]
        assert b["status"] == "IN_TRANSIT"
        assert b.get("station_id") in (None, "")

    def test_deliver_settles_at_destination(self, api, platform_admin_headers):
        """PRD §3.6: "Delivery advances the order from IN_TRANSIT to
        DELIVERED: the battery returns to IDLE, its station_id is set to
        dest_station_id".

        Claim: after deliver, battery is IDLE at dest_station.
        """
        scene = setup_two_station_scene(idle_at_source=1)
        battery = scene["idle_batteries"][0]
        order = create_dispatch(
            scene["source"]["id"], scene["dest"]["id"], battery["id"],
        )
        api.dispatch_dispatch_order(order["id"], platform_admin_headers)
        resp = api.deliver_dispatch_order(order["id"], platform_admin_headers)
        order3 = validate_success(resp)
        assert order3["status"] == "DELIVERED"
        b = api.get_battery(battery["id"], platform_admin_headers).json()["data"]
        assert b["status"] == "IDLE"
        assert b["station_id"] == scene["dest"]["id"]

    def test_dispatch_non_idle_battery_rejected(self, api,
                                                platform_admin_headers):
        """PRD §3.6: "The battery must be IDLE at the source station for
        the order to begin transit; otherwise ERR_BATTERY_NOT_IDLE is
        returned."

        Claim: a FAULT battery cannot start dispatch → ERR_BATTERY_NOT_IDLE.
        """
        scene = setup_two_station_scene(idle_at_source=1)
        battery = scene["idle_batteries"][0]
        # Create the order, then mark battery FAULT before dispatch.
        order = create_dispatch(
            scene["source"]["id"], scene["dest"]["id"], battery["id"],
        )
        # Mark fault via the source-station operator.
        from test_helpers import make_operator_headers, report_fault_payload
        api.report_fault(
            battery["id"], report_fault_payload(),
            make_operator_headers(scene["source"]["id"]),
        )
        resp = api.dispatch_dispatch_order(order["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BATTERY_NOT_IDLE.value)


class TestRecallPathway:
    def test_recall_idle_battery_retires_it(self, api, platform_admin_headers):
        """PRD §3.6: "For each matching battery currently in IDLE or
        CHARGING, the platform sets recall_flag to true, transitions the
        battery to RETIRED, sets cascade_stage directly to END_OF_LIFE".

        Claim: recall on an IDLE battery → recall_flag=true, status=
        RETIRED, cascade_stage=END_OF_LIFE.
        """
        scene = setup_basic_scene()
        b = scene["idle_batteries"][0]
        recalled = retire_battery_via_recall(scene, b)
        assert recalled["recall_flag"] is True
        assert recalled["status"] == "RETIRED"
        assert recalled["cascade_stage"] == "END_OF_LIFE"

    def test_recall_on_in_use_battery_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "A recall targeting a battery already in IN_USE
        cannot succeed — the install pathway wins the race and the
        recall is rejected with ERR_BATTERY_RECALLED."

        Claim: applying a recall to a battery currently IN_USE (held
        & installed via a swap workflow) → ERR_BATTERY_RECALLED.
        """
        from test_helpers import (
            book_reservation, drive_swap_to_installed,
        )
        scene = setup_basic_scene(member_existing_installed=True)
        held = scene["idle_batteries"][0]
        res = book_reservation(scene)
        # Drive to INSTALLED so the held battery is now IN_USE.
        drive_swap_to_installed(scene, res, outgoing_soc_pct=20.0)
        # Now recall it.
        resp = api.create_recall(
            {
                "battery_model_code": held["battery_model_code"],
                "serial_numbers": [held["serial_number"]],
            },
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BATTERY_RECALLED.value)
