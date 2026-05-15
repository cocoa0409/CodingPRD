"""Concurrency serialisation points.

Covers PRD §2.10 (five concurrency rules where PRD explicitly defines
the outcome of concurrent operations).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_exactly_one_succeeds,
    book_reservation,
    create_dispatch,
    create_reservation_payload,
    create_vehicle,
    drive_swap_to_completed,
    find_billing_record_for_swap,
    iso_plus,
    make_admin_headers,
    make_member_headers,
    make_operator_headers,
    now_iso,
    run_race,
    setup_basic_scene,
    setup_two_station_scene,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import TEST_USERS


class TestConcurrentReservationHold:
    def test_only_one_reservation_pins_single_idle_battery(self, api):
        """PRD §2.10: "Two reservations that attempt to soft-hold the
        same compatible IDLE battery at overlapping time windows on the
        same station are resolved first-writer-wins on held_battery_id.
        The loser receives `ERR_NO_COMPATIBLE_BATTERY` and HTTP 409,
        because by the time it evaluates eligibility the only compatible
        idle battery has already been pinned to the earlier reservation."

        Claim: with exactly 1 IDLE compatible battery and 2 concurrent
        reservation requests from two different members, exactly one
        succeeds and the other gets ERR_NO_COMPATIBLE_BATTERY.
        """
        from test_helpers import (
            create_station, add_charging_slot, create_battery_model,
            create_vehicle_model, create_compatibility, create_battery,
            create_member, create_vehicle,
        )
        st = create_station(total_slots=4)
        for i in range(1, 5):
            add_charging_slot(st["id"], i)
        bm = create_battery_model(rated_capacity_kwh=50.0)
        vm = create_vehicle_model()
        create_compatibility(vm["code"], bm["code"])
        # Single IDLE battery — both reservations compete for it.
        create_battery(station_id=st["id"], battery_model_code=bm["code"])
        m1 = create_member()
        m2 = create_member()
        v1 = create_vehicle(
            vehicle_model_code=vm["code"], owner_member_id=m1["id"],
        )
        v2 = create_vehicle(
            vehicle_model_code=vm["code"], owner_member_id=m2["id"],
        )
        base = now_iso()
        advance_clock_to(base)
        s1 = iso_plus(base, minutes=10)
        e1 = iso_plus(s1, minutes=15)

        def attempt(member_id, vehicle_id):
            return api.create_reservation(
                create_reservation_payload(
                    member_id=member_id, vehicle_id=vehicle_id,
                    station_id=st["id"],
                    slot_start_at=s1, slot_end_at=e1,
                ),
                make_member_headers(member_id),
            )

        results = run_race(
            lambda: attempt(m1["id"], v1["id"]),
            lambda: attempt(m2["id"], v2["id"]),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_NO_COMPATIBLE_BATTERY.value


class TestConcurrentBillingPayment:
    def test_pay_and_mark_failed_race_only_one_wins(self, api,
                                                   platform_admin_headers):
        """PRD §2.10: "On a PENDING billing record, a payment and an
        admin mark-failed racing each other are serialised on
        payment_status. Exactly one terminal outcome wins; the other is
        rejected with ERR_INVALID_STATE and HTTP 409."

        Claim: concurrent pay + mark-failed on a PENDING BillingRecord
        → exactly one succeeds, the other returns ERR_INVALID_STATE.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        results = run_race(
            lambda: api.pay_billing_record(
                br["id"], make_member_headers(scene["member"]["id"]),
            ),
            lambda: api.mark_failed_billing_record(
                br["id"], platform_admin_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


class TestConcurrentDispatchSameBattery:
    def test_two_dispatch_orders_same_battery(self, api, platform_admin_headers):
        """PRD §2.10: "Two dispatch orders that try to move the same
        IDLE battery are serialised on Battery.status. The first
        transitions the battery to IN_TRANSIT; the second receives
        ERR_BATTERY_NOT_IDLE and HTTP 409."

        Claim: two parallel /dispatch on the same battery → exactly one
        succeeds, loser gets ERR_BATTERY_NOT_IDLE.
        """
        # Two dispatch orders, same battery, different destinations.
        scene = setup_two_station_scene(idle_at_source=1)
        battery = scene["idle_batteries"][0]
        # Third station to give two non-equal destinations.
        from test_helpers import create_station, add_charging_slot
        st3 = create_station(total_slots=2)
        add_charging_slot(st3["id"], 1)
        o1 = create_dispatch(
            scene["source"]["id"], scene["dest"]["id"], battery["id"],
        )
        o2 = create_dispatch(
            scene["source"]["id"], st3["id"], battery["id"],
        )
        results = run_race(
            lambda: api.dispatch_dispatch_order(o1["id"], platform_admin_headers),
            lambda: api.dispatch_dispatch_order(o2["id"], platform_admin_headers),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_BATTERY_NOT_IDLE.value
