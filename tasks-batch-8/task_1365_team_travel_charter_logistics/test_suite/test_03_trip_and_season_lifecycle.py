"""Trip lifecycle states, season close-out, and budget conservation (PRD §3.1, §3.2, §3.9, §2.12)."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_season_budget_invariants,
    add_member, create_and_book_leg, create_contingency_payload, create_hotel_block,
    create_trip_payload, lock_trip, setup_closed_trip, setup_disrupted_trip,
    setup_lockable_trip, setup_locked_trip, setup_team_season, setup_team_season_trip,
    validate_error, validate_success, get_success_data,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
FIN = TEST_USERS["finance_headers"]


def _season(api, team_id, season_id):
    return get_success_data(api.get_season(team_id, season_id, ANY))


class TestTripLockStates:
    def test_relock_of_locked_trip_rejected(self, api, manager_headers):
        """PRD §3.2: "Locking converts the trip from `DRAFT` to `LOCKED`"; a
        second lock no longer satisfies §2.6: "an operation requiring a `DRAFT`
        trip is rejected with `ERR_TRIP_NOT_DRAFT`".

        Design: Corner/state_machines/trip_lock_from_locked_rejected
        """
        ctx = setup_locked_trip()
        fresh = get_success_data(
            api.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
        res = api.lock_trip(ctx["team"]["id"], ctx["trip"]["id"],
                            fresh["version"], manager_headers)
        validate_error(res, "ERR_TRIP_NOT_DRAFT", expected_status=409)

    def test_cancel_of_closed_trip_rejected(self, api, manager_headers):
        """PRD §3.2: "any mutation against a terminal trip with
        `ERR_TRIP_ALREADY_TERMINAL`".

        Design: Corner/state_machines/terminal_trip_cancel_rejected
        """
        ctx = setup_closed_trip()
        assert ctx["trip"]["posture"] == "CLOSED"
        res = api.cancel_trip(ctx["team"]["id"], ctx["trip"]["id"], manager_headers)
        validate_error(res, "ERR_TRIP_ALREADY_TERMINAL", expected_status=409)


class TestCompoundPosture:
    def test_contingency_flips_locked_trip_to_disrupted(self, api, manager_headers):
        """PRD §3.9: "The event opens in `OPEN` status; the trip's
        `disruption_seq` increments; and if the trip was `LOCKED` or `IN_FLIGHT`,
        its posture becomes `DISRUPTED`." and "opening an event against a booked
        leg of a `LOCKED` trip also pushes the affected leg into `REBOOKING`".

        Design: Corner/state_machines/compound_trip_posture_derived_from_children
        """
        ctx = setup_locked_trip()
        event = validate_success(
            api.create_contingency(ctx["team"]["id"], ctx["trip"]["id"],
                                   create_contingency_payload(ctx["leg"]["id"]),
                                   manager_headers), 201)
        assert event["status"] == "OPEN"

        trip = get_success_data(api.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
        assert trip["posture"] == "DISRUPTED"
        assert trip["disruption_seq"] == 1
        leg = get_success_data(
            api.get_flight_leg(ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"], ANY))
        assert leg["status"] == "REBOOKING"


class TestSeasonClose:
    def test_season_close_blocked_by_locked_trip(self, api, finance_headers):
        """PRD §3.1: "Closing a season is the finance lead's final act and is
        allowed only when every trip in the season has reached `CLOSED` or
        `CANCELLED`". A season with a LOCKED trip violates this state
        precondition (§2.6 item 6, `ERR_INVALID_STATE`).

        Design: Corner/endpoints/season_close_with_open_trips_rejected
        """
        ctx = setup_locked_trip()
        res = api.close_season(ctx["team"]["id"], ctx["season"]["id"], finance_headers)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestSeasonCommittedConservation:
    def test_lock_then_cancel_restores_committed_to_zero(self, api):
        """PRD §3.2: "On a successful lock the season's `committed_cost_cents`
        increases by the trip's `estimated_cost_cents`". PRD §3.9: "the season's
        `committed_cost_cents` is reduced by the trip's `estimated_cost_cents`
        less whatever actual costs have already been incurred."

        Design: Difficulty/compensating_invariant/season_committed_cost_conservation
        """
        ctx = setup_disrupted_trip(
            hotel_overrides={"room_count": 1, "rate_cents_per_night": 20000,
                             "night_count": 1})
        season_at_lock = _season(api, ctx["team"]["id"], ctx["season"]["id"])
        assert season_at_lock["committed_cost_cents"] == 20000, \
            "lock commits the hotel-only estimate of 20000"

        validate_success(
            api.cancel_trip(ctx["team"]["id"], ctx["trip"]["id"], MGR), 200)
        trip = get_success_data(api.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
        assert trip["posture"] == "CANCELLED"

        season_final = _season(api, ctx["team"]["id"], ctx["season"]["id"])
        assert season_final["committed_cost_cents"] == 0, \
            "no actual costs were incurred, so committed returns to the pre-lock value"
        assert season_final["travel_budget_cents"] == season_at_lock["travel_budget_cents"]
        assert_season_budget_invariants(season_final)

    def test_conservation_with_two_trips_one_cancelled(self, api):
        """PRD §2.12: "The season tracks `committed_cost_cents` — the sum of
        `estimated_cost_cents` across the season's trips in `LOCKED`,
        `IN_FLIGHT`, `DISRUPTED`, or `RECOVERING` posture, plus the sum of
        `actual_cost_cents` across trips in `CLOSED`". Cancelling one disrupted
        trip removes exactly its estimate from the committed sum.

        Design: Difficulty/compensating_invariant/season_committed_cost_conservation
        """
        ctx_a = setup_lockable_trip(
            budget_cents=100000000,
            hotel_overrides={"room_count": 1, "rate_cents_per_night": 20000,
                             "night_count": 1})
        team, season = ctx_a["team"], ctx_a["season"]
        # Trip B in the same season with a 30000-cent hotel block.
        trip_b = get_success_data(
            api.create_trip(team["id"], create_trip_payload(
                season["id"], destination_code="PHX",
                game_tipoff_utc="2027-03-05T00:00:00Z",
                return_arrival_utc="2027-03-06T08:00:00Z"), MGR))
        add_member(team["id"], trip_b["id"], member_ref="B01")
        create_and_book_leg(team["id"], trip_b["id"], origin_code="PDX",
                            destination_code="PHX")
        create_hotel_block(team["id"], trip_b["id"],
                           hotel_code="HPHX", room_count=1,
                           rate_cents_per_night=30000, night_count=1)

        ctx_a["trip"] = lock_trip(ctx_a)
        locked_b = lock_trip({"team": team, "trip": trip_b})
        season_mid = _season(api, team["id"], season["id"])
        assert season_mid["committed_cost_cents"] == 20000 + 30000

        # Disrupt A, then cancel A: committed must drop by exactly A's estimate.
        ctx_a = setup_disrupted_trip(ctx_a)
        validate_success(api.cancel_trip(team["id"], ctx_a["trip"]["id"], MGR), 200)

        season_final = _season(api, team["id"], season["id"])
        assert season_final["committed_cost_cents"] == 30000, \
            "only trip B's estimate remains committed after A's cancellation"
        assert_season_budget_invariants(season_final)
