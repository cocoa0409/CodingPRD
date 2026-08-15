"""Flight leg booking, the league rest floor, delays and rebooking (PRD §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_manifest_entry, add_member, assert_same_instant, create_leg,
    confirm_manifest_entry, set_clock, setup_team_season_trip,
    validate_error, validate_success, get_success_data,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _leg(api, team_id, trip_id, leg_id):
    return get_success_data(api.get_flight_leg(team_id, trip_id, leg_id, ANY))


class TestRestFloorBoundary:
    def test_exactly_600_minute_gap_allowed(self, api):
        """PRD §3.4: "for any leg with `leg_seq` greater than 1, the planned
        `scheduled_depart_utc` must be no earlier than the prior leg's
        `scheduled_arrive_utc` plus the required rest minutes." With a STANDARD
        policy and no delay the floor is 600 minutes, and a departure at exactly
        the floor is not earlier than it.

        Design: Difficulty/resource_temporal_overlap/flight_leg_rest_interval_buffer
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-02-02T00:00:00Z"})
        leg1 = create_leg(team["id"], trip["id"], leg_seq=1,
                          origin_code="ATL", destination_code="CHA",
                          scheduled_depart_utc="2027-02-01T18:00:00Z",
                          scheduled_arrive_utc="2027-02-01T20:00:00Z")
        leg2 = create_leg(team["id"], trip["id"], leg_seq=2,
                          origin_code="CHA", destination_code="ORL",
                          scheduled_depart_utc="2027-02-02T06:00:00Z",
                          scheduled_arrive_utc="2027-02-02T08:00:00Z")
        validate_success(api.book_leg(team["id"], trip["id"], leg1["id"], COORD), 200)
        booked2 = validate_success(api.book_leg(team["id"], trip["id"], leg2["id"], COORD), 200)
        assert booked2["status"] == "BOOKED", \
            "gap exactly equal to the 600-minute rest floor is allowed (boundary inclusive)"

    def test_one_minute_short_of_floor_rejected(self, api):
        """PRD §3.4: "A departure inside the floor is rejected with
        `ERR_REST_FLOOR_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/flight_leg_rest_interval_buffer
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-02-02T00:00:00Z"})
        leg1 = create_leg(team["id"], trip["id"], leg_seq=1,
                          origin_code="ATL", destination_code="CHA",
                          scheduled_depart_utc="2027-02-01T18:00:00Z",
                          scheduled_arrive_utc="2027-02-01T20:00:00Z")
        leg2 = create_leg(team["id"], trip["id"], leg_seq=2,
                          origin_code="CHA", destination_code="ORL",
                          scheduled_depart_utc="2027-02-02T05:59:00Z",
                          scheduled_arrive_utc="2027-02-02T07:00:00Z")
        validate_success(api.book_leg(team["id"], trip["id"], leg1["id"], COORD), 200)
        res = api.book_leg(team["id"], trip["id"], leg2["id"], COORD)
        validate_error(res, "ERR_REST_FLOOR_VIOLATION", expected_status=409)
        assert _leg(api, team["id"], trip["id"], leg2["id"])["status"] == "PLANNED"


class TestCompoundDelay:
    def test_compound_term_applies_after_prior_leg_arrives_late(self, api):
        """PRD §3.4: "The required rest is a base of 600 minutes under a
        `STANDARD` `league_rest_policy` ..., plus a delay compounding term — for
        every full sixty minutes by which the prior leg's `delay_minutes` exceeds
        its first hour, an additional 60 minutes under `STANDARD`". After leg 1
        arrives 130 minutes late (delay_minutes = 130), the floor is 660 minutes.

        Design: Difficulty/combinatorial_formula/rest_floor_compound_delay_circular
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2026-12-05T02:00:00Z"})
        leg1 = create_leg(team["id"], trip["id"], leg_seq=1,
                          origin_code="DAL", destination_code="DEN",
                          scheduled_depart_utc="2026-12-04T18:00:00Z",
                          scheduled_arrive_utc="2026-12-04T20:00:00Z")
        # Leg 2 departs 630 minutes after leg 1's scheduled arrival: clear of the
        # 600-minute base but inside the 660-minute compounded floor.
        leg2 = create_leg(team["id"], trip["id"], leg_seq=2,
                          origin_code="DEN", destination_code="PHX",
                          scheduled_depart_utc="2026-12-05T06:30:00Z",
                          scheduled_arrive_utc="2026-12-05T08:00:00Z")
        validate_success(api.book_leg(team["id"], trip["id"], leg1["id"], COORD), 200)
        set_clock("2026-12-04T22:10:00Z")
        validate_success(api.depart_leg(team["id"], trip["id"], leg1["id"], COORD), 200)
        arrived1 = validate_success(
            api.arrive_leg(team["id"], trip["id"], leg1["id"], COORD), 200)
        # PRD §3.4: arrival "computes `delay_minutes` as the difference between
        # actual and scheduled arrival in minutes".
        assert arrived1["delay_minutes"] == 130

        res = api.book_leg(team["id"], trip["id"], leg2["id"], COORD)
        validate_error(res, "ERR_REST_FLOOR_VIOLATION", expected_status=409)

    def test_delay_pushes_downstream_leg_into_rebooking(self, api):
        """PRD §3.4: "Reporting a delay on a `BOOKED` leg ... moves it to
        `DELAYED`, pushes `scheduled_arrive_utc` later by the delay, and forces
        every downstream leg whose scheduled departure now falls before the new
        arrival plus the rest floor into `REBOOKING`."

        Design: Difficulty/combinatorial_formula/rest_floor_compound_delay_circular
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2026-12-05T02:00:00Z"})
        leg1 = create_leg(team["id"], trip["id"], leg_seq=1,
                          origin_code="DAL", destination_code="DEN",
                          scheduled_depart_utc="2026-12-04T18:00:00Z",
                          scheduled_arrive_utc="2026-12-04T20:00:00Z")
        # 600-minute gap: satisfies the base rest floor before any delay.
        leg2 = create_leg(team["id"], trip["id"], leg_seq=2,
                          origin_code="DEN", destination_code="PHX",
                          scheduled_depart_utc="2026-12-05T06:00:00Z",
                          scheduled_arrive_utc="2026-12-05T08:00:00Z")
        validate_success(api.book_leg(team["id"], trip["id"], leg1["id"], COORD), 200)
        validate_success(api.book_leg(team["id"], trip["id"], leg2["id"], COORD), 200)

        delayed1 = validate_success(
            api.delay_leg(team["id"], trip["id"], leg1["id"], 60, COORD), 200)
        assert delayed1["status"] == "DELAYED"
        # PRD §3.4 pins the instant shift ("pushes scheduled_arrive_utc later
        # by the delay"), not a single string serialization.
        assert_same_instant(delayed1["scheduled_arrive_utc"], "2026-12-04T21:00:00Z")

        leg2_after = _leg(api, team["id"], trip["id"], leg2["id"])
        assert leg2_after["status"] == "REBOOKING", \
            "540-minute gap after the delay falls inside the 600-minute floor"


class TestRebookingLoop:
    def test_delay_rebook_cycles_increment_generation(self, api):
        """PRD §3.4: "Rebooking — from either `DELAYED` or `REBOOKING` — returns
        the leg to `BOOKED` with a rewritten `scheduled_depart_utc` and
        `scheduled_arrive_utc`" and "Each rebooking increments the leg's
        `rebook_generation`".

        Design: Difficulty/non_linear_state_machine/flight_leg_cyclic_rebooking_loop
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2026-12-10T00:00:00Z"})
        leg = create_leg(team["id"], trip["id"], leg_seq=1,
                         origin_code="ORD", destination_code="JFK",
                         scheduled_depart_utc="2026-12-09T14:00:00Z",
                         scheduled_arrive_utc="2026-12-09T17:00:00Z")
        validate_success(api.book_leg(team["id"], trip["id"], leg["id"], COORD), 200)

        validate_success(api.delay_leg(team["id"], trip["id"], leg["id"], 60, COORD), 200)
        rebooked = validate_success(
            api.rebook_leg(team["id"], trip["id"], leg["id"],
                           "2026-12-09T16:00:00Z", "2026-12-09T19:00:00Z", COORD), 200)
        assert rebooked["status"] == "BOOKED"
        assert rebooked["rebook_generation"] == 1

        validate_success(api.delay_leg(team["id"], trip["id"], leg["id"], 45, COORD), 200)
        rebooked2 = validate_success(
            api.rebook_leg(team["id"], trip["id"], leg["id"],
                           "2026-12-09T18:00:00Z", "2026-12-09T21:00:00Z", COORD), 200)
        assert rebooked2["status"] == "BOOKED"
        assert rebooked2["rebook_generation"] == 2, \
            "two DELAYED -> BOOKED cycles must accumulate two generations"
        # PRD §3.4 pins the rewritten instant, not a single string serialization.
        assert_same_instant(rebooked2["scheduled_depart_utc"], "2026-12-09T18:00:00Z")

    def test_rebook_keeps_entries_but_resets_ticketing(self, api):
        """PRD §3.4: "Each rebooking increments the leg's `rebook_generation`
        (used to tie-break manifest reconciliation), keeps the manifest entries
        in place, and resets every entry's `is_ticketed` to false".

        Design: Difficulty/non_linear_state_machine/flight_leg_cyclic_rebooking_loop
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2026-12-10T00:00:00Z"})
        member = add_member(team["id"], trip["id"])
        leg = create_leg(team["id"], trip["id"], leg_seq=1,
                         origin_code="ORD", destination_code="JFK",
                         scheduled_depart_utc="2026-12-09T14:00:00Z",
                         scheduled_arrive_utc="2026-12-09T17:00:00Z")
        validate_success(api.book_leg(team["id"], trip["id"], leg["id"], COORD), 200)
        entry = add_manifest_entry(team["id"], trip["id"], leg["id"], member["id"])
        confirmed = confirm_manifest_entry(team["id"], trip["id"], leg["id"], entry["id"])
        assert confirmed["is_ticketed"] is True

        validate_success(api.delay_leg(team["id"], trip["id"], leg["id"], 30, COORD), 200)
        validate_success(
            api.rebook_leg(team["id"], trip["id"], leg["id"],
                           "2026-12-09T16:00:00Z", "2026-12-09T19:00:00Z", COORD), 200)

        entry_after = get_success_data(
            api.get_manifest_entry(team["id"], trip["id"], leg["id"], entry["id"], ANY))
        assert entry_after["status"] == "CONFIRMED", "entries stay in place across rebook"
        assert entry_after["is_ticketed"] is False, "rebook resets ticketing"
