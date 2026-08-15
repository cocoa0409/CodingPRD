"""Crew legality (training, duty time), release gating on services, and
leg completion gating on the logical clock."""
from test_helpers import (
    ApiErrorId,
    add_catering,
    add_leg,
    add_ground_transport,
    approve_trip,
    assign_aircraft,
    assign_crew,
    confirm_catering,
    create_aircraft,
    create_crew,
    create_trip,
    get_success_data,
    make_dispatcher_headers,
    release_leg,
    reset_clock,
    setup_approved_trip,
    setup_assigned_trip,
    setup_bu_and_passenger,
    setup_crewed_trip,
    setup_dispatched_trip,
    setup_released_trip,
    submit_trip,
    validate_error,
    validate_success,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestTrainingExpiryBoundary:
    def test_departure_equal_to_training_expiry_rejected(self, api):
        """PRD §3.4: "must each have `training_valid_until` strictly later than
        the leg's `scheduled_departure_utc` — a pilot whose recurrent training
        expires at or before departure is illegal for that leg. Crew-legality
        failures are rejected with `ERR_CREW_ILLEGAL` (HTTP 422)"

        Design: Difficulty/boundary_precision_check/training_expiry_strict_less_than_boundary
        """
        reset_clock()
        create_aircraft()
        pic = create_crew("PIC", ("LIGHT_JET",),
                          training_valid_until="2026-08-10T12:00:00Z")
        sic = create_crew("SIC", ("LIGHT_JET",))
        _bu, _pax, trip, legs = setup_approved_trip()
        assign_aircraft(trip["id"])
        resp = api.assign_crew(legs[0]["id"], pic["id"], sic["id"],
                               make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_CREW_ILLEGAL)

    def test_departure_one_second_before_expiry_permitted(self, api):
        """PRD §3.4: "must each have `training_valid_until` strictly later than
        the leg's `scheduled_departure_utc` — a pilot whose recurrent training
        expires at or before departure is illegal for that leg."
        PRD §3.4: "A successful pairing sets `pic_crew_id` and `sic_crew_id` on
        the leg and moves it from `AIRCRAFT_ASSIGNED` to `CREWED`."

        Design: Difficulty/boundary_precision_check/training_expiry_strict_less_than_boundary
        """
        reset_clock()
        create_aircraft()
        pic = create_crew("PIC", ("LIGHT_JET",),
                          training_valid_until="2026-08-10T12:00:01Z")
        sic = create_crew("SIC", ("LIGHT_JET",))
        _bu, _pax, trip, legs = setup_approved_trip()
        assign_aircraft(trip["id"])
        resp = api.assign_crew(legs[0]["id"], pic["id"], sic["id"],
                               make_dispatcher_headers("disp-1"))
        crewed = validate_success(resp, 200)
        assert crewed["status"] == "CREWED", (
            "departure strictly before training expiry is legal"
        )


class TestDutyLimitBoundary:
    def _setup_preloaded_pic(self, api, first_block_minutes=600):
        """Charge `first_block_minutes` of duty to a PIC/SIC pair via a
        dispatched long leg, then return the crew plus a second assigned leg
        whose duration the caller controls."""
        reset_clock()
        bu, pax = setup_bu_and_passenger()
        aircraft = create_aircraft(aircraft_type="HEAVY_JET", passenger_capacity=12)
        pic = create_crew("PIC", ("HEAVY_JET",))
        sic = create_crew("SIC", ("HEAVY_JET",))
        # Trip 1: a 10-hour (600-minute) leg, dispatched so duty time posts.
        trip1 = create_trip(pax, bu["id"],
                            requested_departure_utc="2026-08-10T00:00:00Z",
                            requested_return_utc="2026-08-10T10:00:00Z")
        leg1 = add_leg(trip1, pax,
                       scheduled_departure_utc="2026-08-10T00:00:00Z",
                       scheduled_arrival_utc="2026-08-10T10:00:00Z",
                       distance_statute_miles=2400)
        trip1 = submit_trip(trip1, pax)
        approve_trip(trip1)
        assign_aircraft(trip1["id"])
        assign_crew(leg1["id"], pic["id"], sic["id"])
        release_leg(leg1["id"])
        get_success_data(api.dispatch_trip(trip1["id"], make_dispatcher_headers("disp-1")))
        pic_after = get_success_data(api.get_crew_member(pic["id"], DISPATCHER))
        assert pic_after["duty_minutes_used"] == first_block_minutes
        return bu, pax, aircraft, pic, sic

    def _second_assigned_leg(self, api, pax, bu_id, dep, arr):
        trip2 = create_trip(pax, bu_id, requested_departure_utc=dep,
                            requested_return_utc=arr)
        leg2 = add_leg(trip2, pax, scheduled_departure_utc=dep,
                       scheduled_arrival_utc=arr, distance_statute_miles=1000)
        trip2 = submit_trip(trip2, pax)
        approve_trip(trip2)
        assign_aircraft(trip2["id"])
        return leg2

    def test_duty_total_exactly_840_permitted(self, api):
        """PRD §3.4: "The pairing is legal only when the minutes already used in
        the window plus the leg's `block_minutes` total at most 840 minutes —
        fourteen hours — and a total landing exactly on the limit is permitted."

        Design: Difficulty/boundary_precision_check/duty_limit_inclusive_equality_boundary
        """
        bu, pax, _ac, pic, sic = self._setup_preloaded_pic(api, 600)
        # 600 + 240 == 840 exactly: permitted. The 13:00 departure also keeps
        # the second leg outside the first leg's 90-minute aircraft turn buffer.
        leg2 = self._second_assigned_leg(api, pax, bu["id"],
                                         "2026-08-10T13:00:00Z", "2026-08-10T17:00:00Z")
        resp = api.assign_crew(leg2["id"], pic["id"], sic["id"],
                               make_dispatcher_headers("disp-1"))
        crewed = validate_success(resp, 200)
        assert crewed["status"] == "CREWED", "600 + 240 == 840 is permitted (inclusive)"

    def test_duty_total_841_rejected(self, api):
        """PRD §3.4: "The pairing is legal only when the minutes already used in
        the window plus the leg's `block_minutes` total at most 840 minutes —
        fourteen hours"
        PRD §3.4: "Crew-legality failures are rejected with `ERR_CREW_ILLEGAL`
        (HTTP 422)"

        Design: Difficulty/boundary_precision_check/duty_limit_inclusive_equality_boundary
        """
        bu, pax, _ac, pic, sic = self._setup_preloaded_pic(api, 600)
        # 600 + 241 == 841 > 840: rejected.
        leg2 = self._second_assigned_leg(api, pax, bu["id"],
                                         "2026-08-10T13:00:00Z", "2026-08-10T17:01:00Z")
        resp = api.assign_crew(leg2["id"], pic["id"], sic["id"],
                               make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_CREW_ILLEGAL)


class TestReleaseGating:
    def test_release_blocked_by_requested_catering(self, api):
        """PRD §3.4: "an attempt to release while a catering order or ground
        transport is still in `REQUESTED` is rejected with
        `ERR_SERVICE_NOT_READY` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/flight_leg_release_depends_on_catering_state
        """
        _bu, _pax, _trip, legs, _ac, _pic, _sic = setup_crewed_trip()
        add_catering(legs[0]["id"])  # left in REQUESTED
        resp = api.release_leg(legs[0]["id"], make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_SERVICE_NOT_READY)

    def test_release_blocked_by_requested_ground_transport(self, api):
        """PRD §3.4: "Release requires the parent trip's `approval_status` to be
        `APPROVED`, every catering order on the leg to be in `CONFIRMED` or
        `CANCELLED`, and every ground transport to be in `CONFIRMED` or
        `CANCELLED`; an attempt to release while a catering order or ground
        transport is still in `REQUESTED` is rejected with
        `ERR_SERVICE_NOT_READY` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/flight_leg_release_depends_on_catering_state
        """
        _bu, _pax, _trip, legs, _ac, _pic, _sic = setup_crewed_trip()
        confirm_catering(add_catering(legs[0]["id"])["id"])
        add_ground_transport(legs[0]["id"])  # left in REQUESTED
        resp = api.release_leg(legs[0]["id"], make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_SERVICE_NOT_READY)


class TestCompletionGating:
    def test_complete_before_arrival_rejected(self, api):
        """PRD §3.4: "A released leg completes once the logical clock has reached
        its `scheduled_arrival_utc`; completing a leg that is not in `RELEASED`
        fails with `ERR_LEG_NOT_RELEASED` (HTTP 422), and an early completion
        ahead of the arrival instant is likewise rejected."

        Design: Corner/state_machines/flight_leg_complete_before_arrival_rejected
        """
        # Clock stays at 2026-08-01 while the leg arrives 2026-08-10T14:00.
        _bu, _pax, _trip, legs, _ac, _pic, _sic = setup_released_trip()
        resp = api.complete_leg(legs[0]["id"], make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDutyAccumulationInvariant:
    def test_dispatch_posts_duty_minutes(self, api):
        """PRD §3.5: "A successful dispatch moves `assignment_status` from
        `ASSIGNED` to `DISPATCHED`, records the acting dispatcher in
        `dispatched_by_user_id`, and charges duty time: each leg's
        `block_minutes` are summed across the trip and added to
        `duty_minutes_used` for both the `PIC` and the `SIC` on each leg"

        Design: Difficulty/compensating_invariant/pass_seats_and_wallet_invariant_analogous_via_duty_minutes
        """
        legs_spec = (("2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z", 200),
                     ("2026-08-10T13:00:00Z", "2026-08-10T16:00:00Z", 400))
        _bu, _pax, _trip, _legs, _ac, pic, sic = setup_dispatched_trip(legs=legs_spec)
        pic_after = get_success_data(api.get_crew_member(pic["id"], DISPATCHER))
        sic_after = get_success_data(api.get_crew_member(sic["id"], DISPATCHER))
        assert pic_after["duty_minutes_used"] == 300, "120 + 180 block minutes"
        assert sic_after["duty_minutes_used"] == 300, "both seats are charged"

    def test_cancel_after_dispatch_rejected_and_duty_unchanged(self, api):
        """PRD §3.2: "a `Dispatcher`, the originating `ExecutiveRequester`, or a
        `FlightDeptManager` can cancel a trip whose `assignment_status` is
        `UNASSIGNED` or `ASSIGNED`, moving it to the terminal `CANCELLED`."

        Design: Difficulty/compensating_invariant/pass_seats_and_wallet_invariant_analogous_via_duty_minutes
        """
        legs_spec = (("2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z", 200),
                     ("2026-08-10T13:00:00Z", "2026-08-10T16:00:00Z", 400))
        _bu, _pax, trip, _legs, _ac, pic, _sic = setup_dispatched_trip(legs=legs_spec)
        before = get_success_data(api.get_crew_member(pic["id"], DISPATCHER))
        assert before["duty_minutes_used"] == 300
        resp = api.cancel_trip(trip["id"], make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_crew_member(pic["id"], DISPATCHER))
        assert after["duty_minutes_used"] == 300, (
            "rejected compensation leaves the duty total unchanged"
        )
