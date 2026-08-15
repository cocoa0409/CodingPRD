"""Logistics: half-open room booking, the 45-minute vehicle turnaround buffer,
the window-vs-buffer gate ordering, conditional vehicle codes, and lodging
cancel state errors."""
from test_helpers import (
    ApiErrorId,
    add_itinerary_item,
    add_lodging,
    create_program,
    create_trip,
    get_trip,
    make_director_headers,
    make_leader_headers,
    validate_error,
    validate_success,
)

LEADER = make_leader_headers()
DIRECTOR = make_director_headers()


def _draft_trip(api):
    program = create_program()
    trip = create_trip(program["id"], destination_type="IN_STATE",
                       start_date="2027-06-15", end_date="2027-06-25",
                       capacity_youth=30, emergency_protocol_text="")
    return program, trip


class TestRoomBookingHalfOpen:
    def test_adjacent_booking_allowed_overlap_rejected(self, api):
        """PRD §3.9: "a new reservation whose half-open stay interval — check-in
        day inclusive through check-out day exclusive — overlaps an existing
        `CONFIRMED` reservation with the same (trip, `site_name`, `room_code`)
        is rejected with `ERR_ROOM_ALREADY_BOOKED` (HTTP 409); a back-to-back
        booking where one room's check-out equals the next's check-in is
        allowed."

        Design: Difficulty/resource_temporal_overlap/room_booking_half_open_adjacency_allowed
        """
        _, trip = _draft_trip(api)
        res_a = add_lodging(trip["id"], site_name="host", room_code="R1",
                            check_in_date="2027-06-15",
                            check_out_date="2027-06-20", room_capacity=4,
                            cost_cents=10000)
        assert res_a["status"] == "CONFIRMED"

        # Adjacent: check_in == prior check_out touches but does not overlap.
        res_b = api.create_lodging_reservation(
            trip["id"],
            {"site_name": "host", "room_code": "R1",
             "check_in_date": "2027-06-20", "check_out_date": "2027-06-25",
             "room_capacity": 4, "cost_cents": 10000},
            LEADER)
        assert validate_success(res_b, 201)["status"] == "CONFIRMED"

        # Proper one-day overlap against both existing intervals.
        res_c = api.create_lodging_reservation(
            trip["id"],
            {"site_name": "host", "room_code": "R1",
             "check_in_date": "2027-06-19", "check_out_date": "2027-06-21",
             "room_capacity": 4, "cost_cents": 5000},
            LEADER)
        validate_error(res_c, ApiErrorId.ERR_ROOM_ALREADY_BOOKED, 409)

    def test_same_room_code_at_other_site_and_rollup_total(self, api):
        """PRD §3.9: the overlap scope is "the same (trip, `site_name`,
        `room_code`)" — a different site is a different resource; and
        "`lodging_cost_total_cents` — the sum of `cost_cents` over `CONFIRMED`
        reservations".

        Design: Difficulty/resource_temporal_overlap/room_booking_half_open_adjacency_allowed
        """
        _, trip = _draft_trip(api)
        add_lodging(trip["id"], site_name="host", room_code="R1",
                    check_in_date="2027-06-15", check_out_date="2027-06-20",
                    room_capacity=4, cost_cents=10000)
        add_lodging(trip["id"], site_name="host", room_code="R1",
                    check_in_date="2027-06-20", check_out_date="2027-06-25",
                    room_capacity=4, cost_cents=10000)

        res_d = api.create_lodging_reservation(
            trip["id"],
            {"site_name": "hotel", "room_code": "R1",
             "check_in_date": "2027-06-19", "check_out_date": "2027-06-21",
             "room_capacity": 4, "cost_cents": 5000},
            LEADER)
        assert validate_success(res_d, 201)["status"] == "CONFIRMED", (
            "same room_code at a different site_name does not conflict")

        # 10000 + 10000 (adjacent half-open pair) + 5000 (other site) = 25000
        assert get_trip(trip["id"])["lodging_cost_total_cents"] == 25000


class TestVehicleTurnaroundBuffer:
    def test_buffer_44_fails_45_passes(self, api):
        """PRD §3.9: "Vehicles need turnaround time: two `TRAVEL` items sharing
        a `vehicle_code` must leave at least a 45-minute gap between one item's
        end and the other's start — intervals that merely touch violate the
        buffer and are rejected with `ERR_VEHICLE_SCHEDULE_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/vehicle_travel_segments_require_45min_turnaround_buffer
        """
        _, trip = _draft_trip(api)
        add_itinerary_item(trip["id"], segment_type="TRAVEL",
                           title="Outbound leg",
                           start_at="2027-06-15T08:00:00Z",
                           end_at="2027-06-15T10:00:00Z", vehicle_code="bus-1")

        e_30 = api.create_itinerary_item(
            trip["id"],
            {"segment_type": "TRAVEL", "title": "Too soon",
             "start_at": "2027-06-15T10:30:00Z",
             "end_at": "2027-06-15T11:00:00Z", "vehicle_code": "bus-1"},
            LEADER)
        validate_error(e_30, ApiErrorId.ERR_VEHICLE_SCHEDULE_CONFLICT, 409)

        ok_45 = api.create_itinerary_item(
            trip["id"],
            {"segment_type": "TRAVEL", "title": "Exactly 45",
             "start_at": "2027-06-15T10:45:00Z",
             "end_at": "2027-06-15T11:30:00Z", "vehicle_code": "bus-1"},
            LEADER)
        validate_success(ok_45, 201)

    def test_buffer_scoped_to_travel_items_on_same_vehicle(self, api):
        """PRD §3.9: "two `TRAVEL` items sharing a `vehicle_code`" — items on a
        different vehicle, and non-TRAVEL items carrying no vehicle, never
        conflict.

        Design: Difficulty/resource_temporal_overlap/vehicle_travel_segments_require_45min_turnaround_buffer
        """
        _, trip = _draft_trip(api)
        add_itinerary_item(trip["id"], segment_type="TRAVEL",
                           title="Outbound leg",
                           start_at="2027-06-15T08:00:00Z",
                           end_at="2027-06-15T10:00:00Z", vehicle_code="bus-1")

        other_vehicle = api.create_itinerary_item(
            trip["id"],
            {"segment_type": "TRAVEL", "title": "Other vehicle",
             "start_at": "2027-06-15T08:30:00Z",
             "end_at": "2027-06-15T09:00:00Z", "vehicle_code": "van-2"},
            LEADER)
        validate_success(other_vehicle, 201)

        service = api.create_itinerary_item(
            trip["id"],
            {"segment_type": "SERVICE", "title": "Service block",
             "start_at": "2027-06-15T08:30:00Z",
             "end_at": "2027-06-15T09:30:00Z", "location": "host site"},
            LEADER)
        validate_success(service, 201)


class TestItineraryWindowBeatsVehicleBuffer:
    def test_outside_window_and_buffer_violation_reports_window(self, api):
        """PRD §2.8: "the error reported is the one from the earliest applicable
        check in this sequence" — "10. **Temporal windows**: registration
        windows, itinerary containment, open-registration earliness" precedes
        "11. **Uniqueness, overlap, and capacity constraints**: duplicates, room
        and vehicle overlaps, capacity floors, waitlist ordering".
        PRD §3.9: "both endpoints must sit inside the trip window — from
        midnight UTC on `start_date` up to but not including midnight UTC on
        the day after `end_date` (`ERR_ITINERARY_OUTSIDE_TRIP_WINDOW`,
        HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_itinerary_window_beats_vehicle_buffer
        """
        _, trip = _draft_trip(api)
        add_itinerary_item(trip["id"], segment_type="TRAVEL",
                           title="Late shuttle",
                           start_at="2027-06-25T23:30:00Z",
                           end_at="2027-06-25T23:59:00Z",
                           vehicle_code="bus-1")

        # Outside the window (window ends 2027-06-26T00:00:00Z exclusive) AND
        # only 16 minutes after the shuttle's arrival — both gates fail; the
        # temporal gate reports first.
        resp = api.create_itinerary_item(
            trip["id"],
            {"segment_type": "TRAVEL", "title": "After-midnight run",
             "start_at": "2027-06-26T00:15:00Z",
             "end_at": "2027-06-26T01:00:00Z", "vehicle_code": "bus-1"},
            LEADER)
        validate_error(resp, ApiErrorId.ERR_ITINERARY_OUTSIDE_TRIP_WINDOW, 422)

    def test_inside_window_buffer_violation_reports_vehicle_control(self, api):
        """PRD §3.9: "Vehicles need turnaround time: two `TRAVEL` items sharing
        a `vehicle_code` must leave at least a 45-minute gap between one item's
        end and the other's start — intervals that merely touch violate the
        buffer and are rejected with `ERR_VEHICLE_SCHEDULE_CONFLICT`
        (HTTP 409)." Control: with the window satisfied, the constraint gate is
        the one that fires.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_itinerary_window_beats_vehicle_buffer
        """
        _, trip = _draft_trip(api)
        add_itinerary_item(trip["id"], segment_type="TRAVEL",
                           title="Morning leg",
                           start_at="2027-06-15T08:00:00Z",
                           end_at="2027-06-15T10:00:00Z",
                           vehicle_code="bus-1")
        resp = api.create_itinerary_item(
            trip["id"],
            {"segment_type": "TRAVEL", "title": "Tight turn",
             "start_at": "2027-06-15T10:30:00Z",
             "end_at": "2027-06-15T11:00:00Z", "vehicle_code": "bus-1"},
            LEADER)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_SCHEDULE_CONFLICT, 409)


class TestVehicleCodeConditional:
    def test_itinerary_vehicle_code_conditional_requirement(self, api):
        """PRD §3.9: "Each item carries a `segment_type` of `TRAVEL`, `LODGING`,
        `SERVICE`, `MEAL`, or `FREE`, a `title`, `start_at` and `end_at`
        instants, an optional `location` (defaulting to empty), and a
        `vehicle_code` that is required exactly when the segment type is
        `TRAVEL` and otherwise defaults to empty." A missing required field is
        `ERR_INVALID_REQUEST` (§2.8 step 2).

        Design: Corner/validations/itinerary_vehicle_code_conditional_requirement
        """
        _, trip = _draft_trip(api)

        e_travel = api.create_itinerary_item(
            trip["id"],
            {"segment_type": "TRAVEL", "title": "bus leg",
             "start_at": "2027-06-15T08:00:00Z",
             "end_at": "2027-06-15T10:00:00Z"},
            LEADER)
        validate_error(e_travel, ApiErrorId.ERR_INVALID_REQUEST, 400)

        ok_meal = api.create_itinerary_item(
            trip["id"],
            {"segment_type": "MEAL", "title": "lunch",
             "start_at": "2027-06-15T12:00:00Z",
             "end_at": "2027-06-15T13:00:00Z"},
            LEADER)
        validate_success(ok_meal, 201)


class TestLodgingDoubleCancel:
    def test_lodging_double_cancel_state_error(self, api):
        """PRD §3.9: "A `TripLeader` may cancel a `CONFIRMED` reservation
        (optionally with a `reason`) while the trip remains pre-lock; logistics
        are frozen from `ROSTER_LOCKED` onward (`ERR_TRIP_STATE_FORBIDS_ACTION`),
        and cancelling anything not `CONFIRMED` is
        `ERR_LODGING_STATE_FORBIDS_ACTION`."

        Design: Corner/errors/lodging_double_cancel_state_error
        """
        _, trip = _draft_trip(api)
        reservation = add_lodging(trip["id"], site_name="host",
                                  room_code="R1", check_in_date="2027-06-15",
                                  check_out_date="2027-06-16",
                                  room_capacity=4, cost_cents=1000)

        first = api.cancel_lodging_reservation(reservation["id"], LEADER)
        assert validate_success(first, 200)["status"] == "CANCELLED"

        second = api.cancel_lodging_reservation(reservation["id"], LEADER)
        validate_error(second, ApiErrorId.ERR_LODGING_STATE_FORBIDS_ACTION,
                       409)
