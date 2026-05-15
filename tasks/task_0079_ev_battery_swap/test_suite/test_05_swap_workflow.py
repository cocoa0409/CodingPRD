"""Swap workflow phases: check-in → inspect → uninstall → install →
complete, plus abort with compensating action.

Covers PRD §3.4 (six phases) and the abort compensating action.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_swap_event,
    book_reservation,
    drive_swap_to_inspected,
    drive_swap_to_installed,
    drive_swap_to_uninstalled,
    drive_swap_to_completed,
    find_billing_record_for_swap,
    inspect_payload,
    install_payload,
    iso_plus,
    make_member_headers,
    make_operator_headers,
    now_iso,
    perform_check_in_and_fetch_swap_event,
    setup_basic_scene,
    validate_error,
    validate_success,
)


class TestCheckIn:
    def test_check_in_creates_swap_event(self, api):
        """PRD §3.4: "The reservation moves to CHECKED_IN, a fresh
        SwapEvent is created with phase set to CHECKED_IN".

        Claim: check-in returns/produces a SwapEvent with phase
        'CHECKED_IN' and reservation_id matching the originating
        reservation.
        """
        scene = setup_basic_scene()
        res = book_reservation(scene)
        _, se = perform_check_in_and_fetch_swap_event(scene, res)
        assert_swap_event(se)
        assert se["phase"] == "CHECKED_IN"
        assert se["reservation_id"] == res["id"]

    def test_check_in_records_outgoing_battery_id(self, api):
        """PRD §3.4: "its outgoing_battery_id initialised to the vehicle's
        currently installed_battery_id".

        Claim: SwapEvent.outgoing_battery_id == vehicle's installed
        battery at the time of check-in.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        _, se = perform_check_in_and_fetch_swap_event(scene, res)
        assert se["outgoing_battery_id"] == scene["outgoing_battery"]["id"]


class TestPhaseProgression:
    def test_inspect_writes_outgoing_soc(self, api):
        """PRD §3.4: "the platform writes outgoing_soc_pct onto the swap
        event and advances phase to INSPECTED."

        Claim: inspect sets outgoing_soc_pct and phase=INSPECTED.
        """
        scene = setup_basic_scene()
        res = book_reservation(scene)
        se = drive_swap_to_inspected(scene, res, outgoing_soc_pct=42.0)
        assert se["phase"] == "INSPECTED"
        assert float(se["outgoing_soc_pct"]) == 42.0

    def test_uninstall_returns_outgoing_to_idle(self, api):
        """PRD §3.4: "The outgoing battery — whose status was IN_USE —
        transitions to IDLE, has its soc_pct set from the swap event's
        recorded outgoing_soc_pct".

        Claim: after uninstall, the outgoing battery is IDLE with
        soc_pct equal to the recorded outgoing_soc_pct.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        se = drive_swap_to_uninstalled(scene, res, outgoing_soc_pct=22.5)
        assert se["phase"] == "UNINSTALLED"
        # Fetch outgoing battery state.
        op = make_operator_headers(scene["station"]["id"])
        outgoing = api.get_battery(
            scene["outgoing_battery"]["id"], op,
        ).json()["data"]
        assert outgoing["status"] == "IDLE"
        assert float(outgoing["soc_pct"]) == 22.5

    def test_uninstall_clears_vehicle_installed_battery_id(self, api):
        """PRD §3.4: "The vehicle's installed_battery_id is cleared to
        null".

        Claim: after uninstall, Vehicle.installed_battery_id is null.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        drive_swap_to_uninstalled(scene, res)
        op = make_operator_headers(scene["station"]["id"])
        veh = api.get_vehicle(scene["vehicle"]["id"], op).json()["data"]
        assert veh.get("installed_battery_id") in (None, "")

    def test_install_moves_held_to_in_use(self, api):
        """PRD §3.4: "held battery transitions from `IDLE` to `IN_USE`,
        the vehicle's `installed_battery_id` is set to the held
        battery's `id`".

        Claim: install transitions held battery to IN_USE and pins it on
        the vehicle.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        held = scene["idle_batteries"][0]
        res = book_reservation(scene)
        drive_swap_to_installed(scene, res)
        op = make_operator_headers(scene["station"]["id"])
        held_after = api.get_battery(held["id"], op).json()["data"]
        veh = api.get_vehicle(scene["vehicle"]["id"], op).json()["data"]
        assert held_after["status"] == "IN_USE"
        assert veh["installed_battery_id"] == held["id"]

    def test_install_snapshots_incoming_soc(self, api):
        """PRD §3.4: "the swap event's ... incoming_soc_pct is
        snapshotted from the battery's current soc_pct at this moment".

        Claim: SwapEvent.incoming_soc_pct equals held battery's soc_pct
        at install time.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        held = scene["idle_batteries"][0]
        # held was created with soc_pct=80.0 by setup_basic_scene.
        res = book_reservation(scene)
        se = drive_swap_to_installed(scene, res, outgoing_soc_pct=20.0)
        assert se["phase"] == "INSTALLED"
        assert float(se["incoming_soc_pct"]) == float(held["soc_pct"])

    def test_complete_creates_billing_record_and_fulfills(self, api):
        """PRD §3.4: "creates the corresponding BillingRecord linked
        back via swap_event_id, bubbles the reservation up from
        CHECKED_IN to FULFILLED".

        Claim: complete → SwapEvent phase=COMPLETED, Reservation status
        =FULFILLED, BillingRecord created with swap_event_id link.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        assert se["phase"] == "COMPLETED"
        # Reservation upgraded to FULFILLED.
        op = make_operator_headers(scene["station"]["id"])
        ref = api.get_reservation(res["id"], op).json()["data"]
        assert ref["status"] == "FULFILLED"
        # BillingRecord exists, linked.
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        assert br["swap_event_id"] == se["id"]


class TestPhasePreconditionsInvalid:
    def test_inspect_requires_checked_in_phase(self, api):
        """PRD §3.4: "The `SwapEvent.phase` must be `CHECKED_IN`; the
        platform writes `outgoing_soc_pct` onto the swap event and
        advances `phase` to `INSPECTED`."

        Claim: inspect on a SwapEvent already in INSPECTED →
        ERR_INVALID_STATE (precondition violated).
        """
        scene = setup_basic_scene()
        res = book_reservation(scene)
        se = drive_swap_to_inspected(scene, res)
        resp = api.inspect_swap_event(
            se["id"], inspect_payload(50.0),
            make_operator_headers(scene["station"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_install_requires_uninstalled_phase(self, api):
        """PRD §3.4: install precondition "The SwapEvent.phase must be
        UNINSTALLED".

        Claim: install on phase=CHECKED_IN → ERR_INVALID_STATE.
        """
        scene = setup_basic_scene()
        res = book_reservation(scene)
        _, se = perform_check_in_and_fetch_swap_event(scene, res)
        resp = api.install_swap_event(
            se["id"], install_payload(verify=True),
            make_operator_headers(scene["station"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestAbortAndCompensation:
    def test_abort_from_inspected_moves_to_aborted(self, api):
        """PRD §3.4: "An operator may abort while the swap event is in
        CHECKED_IN, INSPECTED, or UNINSTALLED. The swap event transitions
        to ABORTED, the reservation transitions from CHECKED_IN to
        CANCELLED".

        Claim: abort from INSPECTED → SwapEvent.phase=ABORTED and
        Reservation.status=CANCELLED.
        """
        scene = setup_basic_scene()
        res = book_reservation(scene)
        se = drive_swap_to_inspected(scene, res)
        op = make_operator_headers(scene["station"]["id"])
        resp = api.abort_swap_event(se["id"], op)
        out = validate_success(resp)
        assert out["phase"] == "ABORTED"
        ref = api.get_reservation(res["id"], op).json()["data"]
        assert ref["status"] == "CANCELLED"

    def test_abort_from_uninstalled_compensates(self, api):
        """PRD §3.4: "If the abort lands while phase was already
        UNINSTALLED ... the outgoing battery is re-installed into the
        vehicle, transitioning from IDLE back to IN_USE, the vehicle's
        installed_battery_id is restored to the outgoing battery's id".

        Claim: abort from UNINSTALLED restores outgoing battery into the
        vehicle.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        se = drive_swap_to_uninstalled(scene, res, outgoing_soc_pct=25.0)
        op = make_operator_headers(scene["station"]["id"])
        api.abort_swap_event(se["id"], op)
        veh = api.get_vehicle(scene["vehicle"]["id"], op).json()["data"]
        outgoing = api.get_battery(
            scene["outgoing_battery"]["id"], op,
        ).json()["data"]
        assert outgoing["status"] == "IN_USE"
        assert veh["installed_battery_id"] == scene["outgoing_battery"]["id"]
