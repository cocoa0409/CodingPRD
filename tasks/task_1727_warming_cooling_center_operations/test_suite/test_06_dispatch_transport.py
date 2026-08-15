"""Transport dispatch assignment gates, vehicle turnaround conflicts, the
terminal ARRIVED state, reservation stay linkage, and bed-pool conservation
(PRD §2.6, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_bed_conservation,
    assert_transport_dispatch,
    get_dispatch,
    get_site_activation,
    get_stay,
    list_stays,
    setup_arrived_dispatch_scene,
    setup_assigned_dispatch_scene,
    setup_dispatch_capacity_scene,
    setup_dispatch_seats_beds_scene,
    setup_requested_dispatch_scene,
    setup_vehicle_buffer_scene,
    validate_error,
    validate_success,
    INTAKE_HEADERS,
    TC_HEADERS,
)


class TestDispatchCapacityCombinatorics:
    def test_dispatch_assign_rejects_when_combined_pets_exceed_slots(self, api):
        """PRD §3.5: "Finally the destination's capacity must absorb the whole
        party, all-or-nothing, checked in the pinned order: free beds at least
        the rider count, else `ERR_INSUFFICIENT_BEDS_FOR_DISPATCH`; when
        `has_pets` is set, the riders' combined `pet_count` within
        `pet_slots_free`, else `ERR_PET_CAPACITY_EXCEEDED`; and the riders'
        combined locker demand — each guest's `bag_count` divided by two and
        rounded up, summed — within `lockers_free`, else
        `ERR_LOCKER_CAPACITY_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/dispatch_assign_nested_min_with_conditional_pet_branch
        """
        ws = setup_dispatch_capacity_scene()
        # Beds pass (4 free >= 4 riders) but the combined pet_count 3 exceeds
        # pet_slots_free 2 — the conditional pet branch rejects.
        resp = api.assign_transport_dispatch(
            ws["dispatch_pets"]["id"], {"vehicle_id": ws["vehicle"]["id"]},
            TC_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PET_CAPACITY_EXCEEDED,
                       expected_status=409)
        # All-or-nothing: no reservation stays were created.
        assert list_stays({"transport_dispatch_id": ws["dispatch_pets"]["id"]}) == []

    def test_dispatch_assign_without_pets_succeeds_and_reserves_beds(self, api):
        """PRD §3.5: "On success the dispatch moves from `REQUESTED` to
        `ASSIGNED`, `vehicle_id` is set, `reserved_bed_count` becomes the
        rider count, and one `RESERVED` stay per rider is created at the
        destination with intake-style pinned `pet_slots_used` and
        `lockers_used` and the stay's `transport_dispatch_id` pointing back at
        the dispatch."

        Design: Difficulty/combinatorial_formula/dispatch_assign_nested_min_with_conditional_pet_branch
        """
        ws = setup_dispatch_capacity_scene()
        # The pet-flagged party is rejected first and holds nothing.
        validate_error(
            api.assign_transport_dispatch(
                ws["dispatch_pets"]["id"], {"vehicle_id": ws["vehicle"]["id"]},
                TC_HEADERS),
            ApiErrorId.ERR_PET_CAPACITY_EXCEEDED)
        resp = api.assign_transport_dispatch(
            ws["dispatch_plain"]["id"], {"vehicle_id": ws["vehicle"]["id"]},
            TC_HEADERS)
        data = validate_success(resp, 200)
        assert_transport_dispatch(data)
        assert data["status"] == "ASSIGNED"
        assert data["reserved_bed_count"] == 2

        reserved = list_stays(
            {"transport_dispatch_id": ws["dispatch_plain"]["id"]})
        assert len(reserved) == 2
        assert all(s["status"] == "RESERVED" for s in reserved)

        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["occupied_beds"] == 0
        assert sa["reserved_beds"] == 2
        assert sa["beds_free"] == 2


class TestVehicleTurnaroundBuffer:
    def test_back_to_back_dispatch_inside_turnaround_buffer_rejected(self, api):
        """PRD §3.5: "The vehicle must have no window conflict: if it is
        already assigned to another dispatch whose pickup window, expanded by
        `turnaround_minutes` on both sides, intersects the new window, the
        assignment is rejected with `ERR_VEHICLE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/vehicle_window_turnaround_buffer_blocks_adjacent_dispatch
        """
        ws = setup_vehicle_buffer_scene()
        # D1 [14:00, 15:00) ASSIGNED with a 30-minute turnaround fattens to
        # [13:30, 15:30); D2 starting at 15:00 lands inside the buffer.
        resp = api.assign_transport_dispatch(
            ws["d2"]["id"], {"vehicle_id": ws["vehicle"]["id"]}, TC_HEADERS)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT,
                       expected_status=409)
        assert get_dispatch(ws["d2"]["id"])["status"] == "REQUESTED"

    def test_dispatch_starting_exactly_one_turnaround_after_assigns(self, api):
        """PRD §3.5: the conflict test is the assigned window "expanded by
        `turnaround_minutes` on both sides" — and PRD §2.4: "Time-window
        fields throughout the API are half-open intervals: the start instant
        is inclusive and the end instant is exclusive", so a window starting
        exactly at the expanded window's end merely touches it.

        Design: Difficulty/resource_temporal_overlap/vehicle_window_turnaround_buffer_blocks_adjacent_dispatch
        """
        ws = setup_vehicle_buffer_scene()
        # D2 still conflicts and stays REQUESTED; D3 at 15:30 exactly clears
        # the [13:30, 15:30) buffer and assigns.
        validate_error(
            api.assign_transport_dispatch(
                ws["d2"]["id"], {"vehicle_id": ws["vehicle"]["id"]}, TC_HEADERS),
            ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT)
        resp = api.assign_transport_dispatch(
            ws["d3"]["id"], {"vehicle_id": ws["vehicle"]["id"]}, TC_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "ASSIGNED"
        assert data["reserved_bed_count"] == 1


class TestAssignGateOrder:
    def test_dispatch_assign_capacity_gates_beds_and_seats(self, api):
        """PRD §3.5: "The vehicle's `seats` must be at least the rider count,
        else `ERR_VEHICLE_TOO_SMALL`." and, only after the vehicle checks,
        "Finally the destination's capacity must absorb the whole party,
        all-or-nothing, checked in the pinned order: free beds at least the
        rider count, else `ERR_INSUFFICIENT_BEDS_FOR_DISPATCH`; ..."

        Design: Corner/validations/dispatch_assign_capacity_gates_beds_and_seats
        """
        ws = setup_dispatch_seats_beds_scene()
        disp_id = ws["dispatch"]["id"]

        # Seats gate fires first: 1 seat < 2 riders.
        resp_small = api.assign_transport_dispatch(
            disp_id, {"vehicle_id": ws["vehicle_small"]["id"]}, TC_HEADERS)
        validate_error(resp_small, ApiErrorId.ERR_VEHICLE_TOO_SMALL,
                       expected_status=409)

        # With seats satisfied, the bed pool rejects: 1 free bed < 2 riders.
        resp_large = api.assign_transport_dispatch(
            disp_id, {"vehicle_id": ws["vehicle_large"]["id"]}, TC_HEADERS)
        validate_error(resp_large, ApiErrorId.ERR_INSUFFICIENT_BEDS_FOR_DISPATCH,
                       expected_status=409)

        dispatch = get_dispatch(disp_id)
        assert dispatch["status"] == "REQUESTED"
        assert dispatch["reserved_bed_count"] == 0
        assert list_stays({"transport_dispatch_id": disp_id}) == []


class TestTerminalArrived:
    def test_terminal_dispatch_arrived_locks_all_transitions(self, api):
        """PRD §3.5: "Arrival moves an `ASSIGNED` dispatch to `ARRIVED`:
        `arrived_at` is stamped from the logical clock, the vehicle's window
        occupation ends, and the reserved stays become eligible for check-in.
        Arrival is the terminal success state; ..."
        PRD §2.9: "Fifth are state guards, evaluated parents-first — episode
        before site activation before stay or dispatch — yielding the
        transition-specific codes (`ERR_INVALID_STATE`, ...)".

        Design: Corner/state_machines/terminal_dispatch_arrived_locks_all_transitions
        """
        ws = setup_arrived_dispatch_scene(rider_aliases=("rider",))
        disp_id = ws["dispatch"]["id"]
        assert get_dispatch(disp_id)["status"] == "ARRIVED"

        resp_arrive = api.arrive_transport_dispatch(disp_id, TC_HEADERS)
        validate_error(resp_arrive, ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)
        resp_cancel = api.cancel_transport_dispatch(disp_id, TC_HEADERS)
        validate_error(resp_cancel, ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)

        after = get_dispatch(disp_id)
        assert after["status"] == "ARRIVED"
        assert after["reserved_bed_count"] == 1


class TestReservedStayGuards:
    def test_checkin_reserved_stay_before_dispatch_arrival_rejected(self, api):
        """PRD §3.4: "Check-in moves a `RESERVED` stay to `CHECKED_IN`. The
        linked dispatch must have arrived, else `ERR_DISPATCH_NOT_ARRIVED`,
        and the medical-hold gate applies again."

        Design: Corner/state_machines/checkin_reserved_stay_before_dispatch_arrival_rejected
        """
        ws = setup_assigned_dispatch_scene(rider_aliases=("rider",))
        stay = list_stays({"transport_dispatch_id": ws["dispatch"]["id"]})[0]
        assert stay["status"] == "RESERVED"

        resp = api.check_in_stay(stay["id"], INTAKE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_NOT_ARRIVED,
                       expected_status=409)
        assert get_stay(stay["id"])["status"] == "RESERVED"

    def test_checkout_of_reserved_stay_rejected(self, api):
        """PRD §3.4: "Check-out moves a `CHECKED_IN` stay to `CHECKED_OUT`,
        stamps `checked_out_at`, computes the final bed-night figure, and
        releases the bed, pet and locker usage back to the pools." — a
        `RESERVED` stay is not in the transition's source state.
        PRD §2.9: "Fifth are state guards, evaluated parents-first — episode
        before site activation before stay or dispatch — yielding the
        transition-specific codes (`ERR_INVALID_STATE`, ...)".

        Design: Corner/state_machines/checkout_of_reserved_stay_rejected
        """
        ws = setup_assigned_dispatch_scene(rider_aliases=("rider",))
        stay = list_stays({"transport_dispatch_id": ws["dispatch"]["id"]})[0]

        resp = api.check_out_stay(stay["id"], INTAKE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        assert get_stay(stay["id"])["status"] == "RESERVED"
        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["reserved_beds"] == 1
        assert sa["beds_free"] == 3


class TestDispatchCancel:
    def test_outreach_worker_cancels_own_requested_dispatch(self, api):
        """PRD §3.5: "Cancellation is available to both the `OutreachWorker`
        and the `TransportCoordinator`. Cancelling a still-`REQUESTED`
        dispatch has no further effect."

        Design: Corner/rbac/outreach_worker_cancels_own_requested_dispatch
        """
        ws = setup_requested_dispatch_scene()
        resp = api.cancel_transport_dispatch(ws["dispatch"]["id"],
                                             ws["outreach_headers"])
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"
        assert list_stays({"transport_dispatch_id": ws["dispatch"]["id"]}) == []


class TestBedPoolConservation:
    def test_bed_pool_conserved_while_reservation_held(self, api):
        """PRD §2.6: "The bed-conservation invariant — `beds_effective` always
        equals `occupied_beds` plus `reserved_beds` plus `beds_free` — holds
        at all times."

        Design: Difficulty/compensating_invariant/bed_pool_conserved_through_reserve_cancel_cycle
        """
        ws = setup_assigned_dispatch_scene(rider_aliases=("rider-1", "rider-2"))
        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["occupied_beds"] == 0
        assert sa["reserved_beds"] == 2
        assert sa["beds_free"] == 2
        assert_bed_conservation(sa)
        assert sa["beds_effective"] == 4

    def test_bed_pool_restored_after_dispatch_cancel(self, api):
        """PRD §3.5: "Cancelling an `ASSIGNED` dispatch cancels every linked
        stay still in `RESERVED` — releasing its bed, pet and locker usage —
        and drops `reserved_bed_count` to zero."
        PRD §2.6: "The bed-conservation invariant — `beds_effective` always
        equals `occupied_beds` plus `reserved_beds` plus `beds_free` — holds
        at all times."

        Design: Difficulty/compensating_invariant/bed_pool_conserved_through_reserve_cancel_cycle
        """
        ws = setup_assigned_dispatch_scene(rider_aliases=("rider-1", "rider-2"))
        resp = api.cancel_transport_dispatch(ws["dispatch"]["id"], TC_HEADERS)
        assert validate_success(resp, 200)["reserved_bed_count"] == 0

        stays = list_stays({"transport_dispatch_id": ws["dispatch"]["id"]})
        assert len(stays) == 2
        assert all(s["status"] == "CANCELLED" for s in stays)

        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["occupied_beds"] == 0
        assert sa["reserved_beds"] == 0
        assert sa["beds_free"] == 4
        assert_bed_conservation(sa)
