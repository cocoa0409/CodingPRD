"""Reservation creation: temporal validations, eligibility, walk-in.

Covers PRD §3.3 (reservation lifecycle).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    RESERVATION_SLOT_MINUTES,
    add_charging_slot,
    advance_clock_to,
    assert_reservation,
    book_reservation,
    create_battery,
    create_compatibility,
    create_member,
    create_reservation_payload,
    create_station,
    create_vehicle,
    iso_plus,
    make_admin_headers,
    make_member_headers,
    make_operator_headers,
    now_iso,
    reservation_at,
    setup_basic_scene,
    setup_models_and_compat,
    validate_error,
    validate_success,
)


class TestReservationTemporalValidations:
    def test_create_reservation_pins_held_battery(self, api):
        """PRD §3.3: "If the set is non-empty, the highest-ranked battery
        is selected and the reservation's held_battery_id is pinned to
        that battery's id".

        Claim: a successful POST /reservations returns a reservation with
        a non-null held_battery_id pointing at an IDLE compatible battery.
        """
        scene = setup_basic_scene(total_slots=2, num_idle_batteries=1)
        res = book_reservation(scene)
        assert_reservation(res)
        assert res["held_battery_id"] == scene["idle_batteries"][0]["id"]
        assert res["status"] == "BOOKED"

    def test_slot_must_be_fifteen_minutes(self, api):
        """PRD §3.3: "The slot must be exactly fifteen minutes long:
        slot_end_at must equal slot_start_at plus fifteen minutes,
        otherwise ERR_INVALID_TIME_SLOT and HTTP 422."

        Claim: slot of 10 minutes → ERR_INVALID_TIME_SLOT 422.
        """
        scene = setup_basic_scene()
        base = now_iso()
        slot_start = iso_plus(base, minutes=10)
        slot_end = iso_plus(slot_start, minutes=10)  # 10, not 15
        payload = create_reservation_payload(
            member_id=scene["member"]["id"],
            vehicle_id=scene["vehicle"]["id"],
            station_id=scene["station"]["id"],
            slot_start_at=slot_start,
            slot_end_at=slot_end,
        )
        resp = api.create_reservation(
            payload, make_member_headers(scene["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_SLOT.value)

    def test_slot_start_must_be_in_future(self, api):
        """PRD §3.3: "slot_start_at must fall at least five minutes after
        the current server time, otherwise ERR_INVALID_TIME_SLOT."

        Claim: slot_start 1 minute from now → ERR_INVALID_TIME_SLOT.
        """
        scene = setup_basic_scene()
        base = now_iso()
        slot_start = iso_plus(base, minutes=1)
        slot_end = iso_plus(slot_start, minutes=RESERVATION_SLOT_MINUTES)
        payload = create_reservation_payload(
            member_id=scene["member"]["id"],
            vehicle_id=scene["vehicle"]["id"],
            station_id=scene["station"]["id"],
            slot_start_at=slot_start,
            slot_end_at=slot_end,
        )
        resp = api.create_reservation(
            payload, make_member_headers(scene["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_SLOT.value)

    def test_member_overlap_rejected(self, api):
        """PRD §3.3: "The slot must not overlap, in a half-open
        [slot_start_at, slot_end_at) sense, any other BOOKED reservation
        already held by the same member ... any strictly-interior overlap
        returns ERR_RESERVATION_OVERLAP_MEMBER and HTTP 409."

        Claim: a second reservation for the same member with strict
        interior overlap → ERR_RESERVATION_OVERLAP_MEMBER.
        """
        scene = setup_basic_scene(num_idle_batteries=2)
        base = now_iso()
        advance_clock_to(base)
        s1 = iso_plus(base, minutes=10)
        e1 = iso_plus(s1, minutes=15)
        reservation_at(scene, slot_start_iso=s1, slot_end_iso=e1)
        s2 = iso_plus(base, minutes=15)  # strict overlap with [10,25)
        e2 = iso_plus(s2, minutes=15)
        payload = create_reservation_payload(
            member_id=scene["member"]["id"],
            vehicle_id=scene["vehicle"]["id"],
            station_id=scene["station"]["id"],
            slot_start_at=s2,
            slot_end_at=e2,
        )
        resp = api.create_reservation(
            payload, make_member_headers(scene["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_OVERLAP_MEMBER.value)

    def test_member_touching_boundary_allowed(self, api):
        """PRD §3.3: "two reservations that meet exactly at a boundary
        instant do not overlap".

        Claim: a second reservation starting exactly when the first ends
        is accepted.
        """
        scene = setup_basic_scene(num_idle_batteries=2)
        base = now_iso()
        advance_clock_to(base)
        s1 = iso_plus(base, minutes=10)
        e1 = iso_plus(s1, minutes=15)
        reservation_at(scene, slot_start_iso=s1, slot_end_iso=e1)
        s2 = e1
        e2 = iso_plus(s2, minutes=15)
        payload = create_reservation_payload(
            member_id=scene["member"]["id"],
            vehicle_id=scene["vehicle"]["id"],
            station_id=scene["station"]["id"],
            slot_start_at=s2,
            slot_end_at=e2,
        )
        resp = api.create_reservation(
            payload, make_member_headers(scene["member"]["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_reservation(data)


class TestEligibilityFilter:
    def test_no_compatible_battery_rejected(self, api):
        """PRD §3.3: "If the set is empty after eligibility filtering, the
        reservation is rejected with ERR_NO_COMPATIBLE_BATTERY and HTTP
        409".

        Claim: station has no IDLE compatible battery → 409
        ERR_NO_COMPATIBLE_BATTERY.
        """
        # Build a scene where the only available battery has been
        # marked FAULT (so no IDLE compatible candidates remain).
        scene = setup_basic_scene(num_idle_batteries=1)
        from test_helpers import report_battery_fault
        report_battery_fault(scene, scene["idle_batteries"][0]["id"])
        base = now_iso()
        s1 = iso_plus(base, minutes=10)
        e1 = iso_plus(s1, minutes=15)
        payload = create_reservation_payload(
            member_id=scene["member"]["id"],
            vehicle_id=scene["vehicle"]["id"],
            station_id=scene["station"]["id"],
            slot_start_at=s1,
            slot_end_at=e1,
        )
        resp = api.create_reservation(
            payload, make_member_headers(scene["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_COMPATIBLE_BATTERY.value)

    def test_ranking_picks_highest_soh(self, api):
        """PRD §3.3: "The eligible set is then ranked by soh_pct in
        descending order".

        Claim: with two IDLE compatible batteries (soh 90 and 100), the
        held_battery_id is the one with the higher soh_pct.
        """
        scene = setup_basic_scene(num_idle_batteries=0)
        # Mint two batteries with explicit soh_pct.
        from test_helpers import create_battery
        b_low = create_battery(
            station_id=scene["station"]["id"],
            battery_model_code=scene["battery_model"]["code"],
            soh_pct=90.0,
        )
        b_high = create_battery(
            station_id=scene["station"]["id"],
            battery_model_code=scene["battery_model"]["code"],
            soh_pct=100.0,
        )
        scene["idle_batteries"] = [b_low, b_high]
        res = book_reservation(scene)
        assert res["held_battery_id"] == b_high["id"]


class TestWalkIn:
    def test_walk_in_first_is_position_one(self, api):
        """PRD §3.3: "computes queue_position as one plus the count of
        BOOKED and CHECKED_IN walk-in reservations already at the station".

        Claim: first walk-in at a station → queue_position == 1.
        """
        scene = setup_basic_scene(num_idle_batteries=1)
        payload = {
            "member_id": scene["member"]["id"],
            "vehicle_id": scene["vehicle"]["id"],
            "station_id": scene["station"]["id"],
        }
        resp = api.create_walk_in_reservation(
            payload, make_operator_headers(scene["station"]["id"]),
        )
        res = validate_success(resp, expected_status=201)
        assert_reservation(res)
        assert res["queue_position"] == 1

    def test_walk_in_slot_offset_is_five_minutes(self, api):
        """PRD §3.3: "derives slot_start_at as the current server time
        plus five minutes multiplied by queue_position (so the first
        walk-in slots five minutes from now ... and so on)".

        Claim: first walk-in's slot_start is approximately now + 5 min,
        and slot_end equals slot_start + 15 min.
        """
        scene = setup_basic_scene(num_idle_batteries=1)
        base = now_iso()
        advance_clock_to(base)
        payload = {
            "member_id": scene["member"]["id"],
            "vehicle_id": scene["vehicle"]["id"],
            "station_id": scene["station"]["id"],
        }
        resp = api.create_walk_in_reservation(
            payload, make_operator_headers(scene["station"]["id"]),
        )
        res = validate_success(resp, expected_status=201)
        from datetime import datetime
        start = datetime.fromisoformat(
            res["slot_start_at"].replace("Z", "+00:00")
        )
        end = datetime.fromisoformat(
            res["slot_end_at"].replace("Z", "+00:00")
        )
        delta_min = (end - start).total_seconds() / 60.0
        assert delta_min == 15, (
            "PRD §3.3: slot_end_at = slot_start_at + 15 minutes"
        )
        base_dt = datetime.fromisoformat(base.replace("Z", "+00:00"))
        offset_min = (start - base_dt).total_seconds() / 60.0
        assert abs(offset_min - 5.0) < 0.5, (
            "PRD §3.3 walk-in queue_position 1 slots 5 min from now; "
            f"got offset {offset_min} min"
        )
