"""Aircraft selector ranking, capacity shortfall, and buffered/unbuffered
interval-overlap semantics."""
from test_helpers import (
    ApiErrorId,
    add_leg,
    approve_trip,
    assign_crew,
    create_aircraft,
    create_crew,
    create_trip,
    get_success_data,
    make_dispatcher_headers,
    make_executive_requester_headers,
    reset_clock,
    setup_bu_and_passenger,
    setup_approved_trip,
    submit_trip,
    validate_error,
    validate_success,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _assign(api, trip_id, dispatcher_id="disp-1"):
    version = get_success_data(api.get_trip_request(trip_id, MANAGER))["version"]
    return api.assign_aircraft(trip_id, version, make_dispatcher_headers(dispatcher_id))


def _approved_trip_with_leg(api, pax, bu_id, dep, arr, dist=200, seq_purpose="X"):
    trip = create_trip(pax, bu_id, requested_departure_utc=dep, requested_return_utc=arr,
                       purpose=seq_purpose)
    leg = add_leg(trip, pax, scheduled_departure_utc=dep, scheduled_arrival_utc=arr,
                  distance_statute_miles=dist)
    trip = submit_trip(trip, pax)
    trip = approve_trip(trip)
    return trip, leg


class TestSelectorRanking:
    def test_selector_picks_smallest_sufficient_aircraft(self, api):
        """PRD §3.3: "Eligible tails are ranked smallest-sufficient-first:
        ascending `passenger_capacity`, then preferring a tail whose
        `home_base_icao` equals the leg's `origin_icao`, with `created_at`
        ascending as the deterministic final tie-break."

        Design: Corner/calculations/selector_picks_smallest_sufficient_aircraft
        """
        from test_helpers import create_passenger
        reset_clock()
        bu, pax1 = setup_bu_and_passenger()
        pax2 = create_passenger(bu["id"], priority_tier="TIER_2")
        pax3 = create_passenger(bu["id"], priority_tier="TIER_2")
        pax4 = create_passenger(bu["id"], priority_tier="TIER_3")
        # HEAVY created first so the created_at tie-break would favor it if
        # capacity ordering did not dominate.
        create_aircraft(aircraft_type="HEAVY_JET", passenger_capacity=12,
                        tail_number="N4003HV")
        light = create_aircraft(aircraft_type="LIGHT_JET", passenger_capacity=6,
                                tail_number="N4004LJ")
        trip = create_trip(pax1, bu["id"],
                           passenger_ids=[pax1["id"], pax2["id"], pax3["id"], pax4["id"]])
        leg = add_leg(trip, pax1)
        trip = submit_trip(trip, pax1)
        approve_trip(trip)
        resp = _assign(api, trip["id"])
        validate_success(resp, 200)
        chosen = get_success_data(api.get_flight_leg(leg["id"], DISPATCHER))["aircraft_id"]
        assert chosen == light["id"], (
            "smallest sufficient capacity wins over created_at ordering"
        )


class TestCapacityShortfall:
    def test_no_candidate_when_passengers_exceed_seats(self, api):
        """PRD §3.3: "A candidate aircraft must be `ACTIVE` with posture
        `AVAILABLE`, must offer a `passenger_capacity` at least equal to the
        number of passengers on the trip roster"
        PRD §3.3: "When the candidate pool comes up empty, the leg is left in
        `PLANNED`, the attempt reports `ERR_NO_CANDIDATE_AIRCRAFT` (HTTP 422), and
        the trip becomes charter-eligible"

        Design: Corner/validations/capacity_violation_more_passengers_than_seats
        """
        from test_helpers import create_passenger
        reset_clock()
        bu, pax1 = setup_bu_and_passenger()
        others = [create_passenger(bu["id"], priority_tier="TIER_3") for _ in range(6)]
        create_aircraft(passenger_capacity=6)
        roster = [pax1["id"]] + [p["id"] for p in others]
        trip = create_trip(pax1, bu["id"], passenger_ids=roster)
        add_leg(trip, pax1)
        trip = submit_trip(trip, pax1)
        approve_trip(trip)
        resp = _assign(api, trip["id"])
        validate_error(resp, ApiErrorId.ERR_NO_CANDIDATE_AIRCRAFT)


class TestAircraftBufferedInterval:
    def test_ninety_minute_gap_permitted(self, api):
        """PRD §3.3: "Each leg's buffered interval opens ninety minutes before its
        `scheduled_departure_utc` and closes ninety minutes after its
        `scheduled_arrival_utc` — a turn-buffer of an hour and a half on each side
        — and the comparison is half-open, so a back-to-back pairing in which one
        leg's buffered start exactly equals another leg's buffered end does *not*
        count as an overlap."

        Design: Difficulty/resource_temporal_overlap/aircraft_buffered_half_open_interval
        """
        reset_clock()
        bu, pax = setup_bu_and_passenger()
        create_aircraft(tail_number="N1101CF")
        # Trip1 occupies 10:00-12:00; buffered interval [08:30, 13:30).
        trip1, _leg1 = _approved_trip_with_leg(
            api, pax, bu["id"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        validate_success(_assign(api, trip1["id"]), 200)
        # Trip2 departs 15:00, so its buffered start is exactly 13:30 — equal to
        # trip1's buffered end. Half-open adjacency is NOT an overlap: permitted.
        trip2, leg2 = _approved_trip_with_leg(
            api, pax, bu["id"], "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
        data = validate_success(_assign(api, trip2["id"]), 200)
        assert data["assignment_status"] == "ASSIGNED", (
            "buffered start == prior buffered end is permitted (half-open)"
        )

    def test_eighty_nine_minute_gap_rejected(self, api):
        """PRD §3.3: "any existing leg on the same tail in `AIRCRAFT_ASSIGNED`,
        `CREWED`, or `RELEASED` whose buffered interval intersects the candidate
        leg's buffered interval disqualifies the tail."
        PRD §3.3: "a buffered-interval collision on the tail is
        `ERR_AIRCRAFT_INTERVAL_CONFLICT` (HTTP 422)"

        Design: Difficulty/resource_temporal_overlap/aircraft_buffered_half_open_interval
        """
        reset_clock()
        bu, pax = setup_bu_and_passenger()
        create_aircraft(tail_number="N1101CF")
        trip1, _leg1 = _approved_trip_with_leg(
            api, pax, bu["id"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        validate_success(_assign(api, trip1["id"]), 200)
        # Trip3 departs 14:59: buffered start 13:29 is one minute inside trip1's
        # buffered end (13:30) — a true intersection; rejected.
        trip3, _leg3 = _approved_trip_with_leg(
            api, pax, bu["id"], "2026-08-10T14:59:00Z", "2026-08-10T16:00:00Z")
        resp = _assign(api, trip3["id"])
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_INTERVAL_CONFLICT)


class TestCrewUnbufferedInterval:
    def test_back_to_back_legs_permitted_for_crew(self, api):
        """PRD §3.4: "Unlike the aircraft rule, no turn buffer is added for crew,
        so adjacent legs that share an endpoint are permitted."

        Design: Difficulty/resource_temporal_overlap/crew_unbuffered_half_open_interval
        """
        reset_clock()
        bu, pax = setup_bu_and_passenger()
        create_aircraft(tail_number="N1102CF")
        create_aircraft(tail_number="N1103CF")
        pic = create_crew("PIC", ("LIGHT_JET",))
        sic = create_crew("SIC", ("LIGHT_JET",))
        # Trip1: 10:00-12:00, crewed.
        trip1, leg1 = _approved_trip_with_leg(
            api, pax, bu["id"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        validate_success(_assign(api, trip1["id"]), 200)
        assign_crew(leg1["id"], pic["id"], sic["id"])
        # Trip2 departs exactly when trip1 arrives (12:00); buffered aircraft
        # interval pushes the selector to the second tail, crew adjacency is fine.
        trip2, leg2 = _approved_trip_with_leg(
            api, pax, bu["id"], "2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z", dist=400)
        validate_success(_assign(api, trip2["id"]), 200)
        resp = api.assign_crew(leg2["id"], pic["id"], sic["id"],
                               make_dispatcher_headers("disp-1"))
        crewed = validate_success(resp, 200)
        assert crewed["status"] == "CREWED", (
            "crew legs sharing an endpoint do not overlap (no turn buffer)"
        )

    def test_overlapping_crew_leg_rejected(self, api):
        """PRD §3.4: "a crew member already committed, as either `PIC` or `SIC`,
        to another leg in `CREWED` or `RELEASED` whose scheduled interval
        intersects the new leg's scheduled interval triggers
        `ERR_CREW_INTERVAL_CONFLICT` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/crew_unbuffered_half_open_interval
        """
        reset_clock()
        bu, pax = setup_bu_and_passenger()
        create_aircraft(tail_number="N1104CF")
        create_aircraft(tail_number="N1105CF")
        pic = create_crew("PIC", ("LIGHT_JET",))
        sic = create_crew("SIC", ("LIGHT_JET",))
        trip1, leg1 = _approved_trip_with_leg(
            api, pax, bu["id"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        validate_success(_assign(api, trip1["id"]), 200)
        assign_crew(leg1["id"], pic["id"], sic["id"])
        # Trip2 departs 11:00 — strictly inside trip1's crewed interval.
        trip2, leg2 = _approved_trip_with_leg(
            api, pax, bu["id"], "2026-08-10T11:00:00Z", "2026-08-10T14:00:00Z", dist=400)
        validate_success(_assign(api, trip2["id"]), 200)
        resp = api.assign_crew(leg2["id"], pic["id"], sic["id"],
                               make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_CREW_INTERVAL_CONFLICT)
