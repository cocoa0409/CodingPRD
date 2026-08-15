"""Team enrollment, season opening, trip creation, and roster basics (PRD §3.1-3.2)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS,
    assert_member, assert_same_instant, assert_season, assert_team, assert_trip,
    create_team_payload, create_trip_payload, create_member_payload,
    reset_clock, setup_team_season, setup_team_season_trip, add_member,
    validate_error, validate_paginated, validate_success,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
FIN = TEST_USERS["finance_headers"]
OPS = TEST_USERS["ops_admin_headers"]


class TestTeamEnrollment:
    def test_team_creation_applies_rest_policy_default(self, api, ops_admin_headers):
        """PRD §3.1: "an optional `league_rest_policy` of `STANDARD` or `STRINGENT`
        that establishes the team's baseline rest rules; when omitted, the policy
        defaults to `STANDARD`."

        Design: Corner/entities/team_creation_required_fields
        """
        reset_clock()
        payload = create_team_payload(team_code="GSW", display_name="Golden State")
        del payload["league_rest_policy"]
        team = validate_success(api.create_team(payload, ops_admin_headers), 201)
        assert_team(team)
        assert team["team_code"] == "GSW"
        assert team["league_rest_policy"] == "STANDARD", \
            "omitted league_rest_policy must default to STANDARD"

    def test_get_team_not_found(self, api, any_headers):
        """PRD §2.5: "rejects the request with a 404 the moment an identifier
        fails to resolve within its parent: `ERR_TEAM_NOT_FOUND` for a bad
        `teamId`".

        Design: Corner/entities/team_get_not_found
        """
        reset_clock()
        res = api.get_team(NON_EXISTENT_UUID, any_headers)
        validate_error(res, "ERR_TEAM_NOT_FOUND", expected_status=404)


class TestTripCreation:
    def test_trip_computed_fields_at_creation(self, api):
        """PRD §3.2: "The trip begins in `DRAFT` posture with `disruption_seq`
        at 0" and "The trip's `party_size` is the count of its `IN` members".

        Design: Corner/entities/trip_computed_party_size
        """
        team, season = setup_team_season()
        trip = validate_success(
            api.create_trip(team["id"], create_trip_payload(season["id"]), MGR), 201)
        assert_trip(trip)
        assert trip["posture"] == "DRAFT"
        assert trip["disruption_seq"] == 0
        assert trip["party_size"] == 0, "no members added yet -> party_size 0"
        assert trip["estimated_cost_cents"] == 0


class TestRoster:
    def test_member_party_role_enum_rejected(self, api, manager_headers):
        """PRD §3.2: "a `party_role` drawn from `PLAYER`, `COACH`, `STAFF`,
        `MEDICAL`, `SECURITY`, `EQUIPMENT`, or `EXECUTIVE`". PRD §2.6: "Request
        bodies that fail generic shape validation — missing required fields,
        wrong types — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/member_enum_party_role_validation
        """
        team, season, trip = setup_team_season_trip()
        payload = create_member_payload(party_role="VIP")
        res = api.add_member(team["id"], trip["id"], payload, manager_headers)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_member_list_filtered_by_status(self, api, any_headers):
        """PRD §3.2: "The roster list accepts a `status` filter".

        Design: Corner/entities/member_list_filtered_by_status
        """
        team, season, trip = setup_team_season_trip()
        m1 = add_member(team["id"], trip["id"], member_ref="W1", party_role="PLAYER")
        m2 = add_member(team["id"], trip["id"], member_ref="W2", party_role="COACH")
        m3 = add_member(team["id"], trip["id"], member_ref="W3", party_role="STAFF")
        validate_success(
            api.scratch_member(team["id"], trip["id"], m3["id"], MGR), 200)

        data, meta = validate_paginated(
            api.list_members(team["id"], trip["id"], ANY, params={"status": "IN"}))
        ids = {m["id"] for m in data}
        assert ids == {m1["id"], m2["id"]}, \
            f"status=IN filter must return exactly the two IN members, got {ids}"
        assert m3["id"] not in ids


class TestClockAndPathErrors:
    def test_clock_set_returns_new_now(self, api, ops_admin_headers):
        """PRD §2.8: "A `TravelOpsAdmin` may advance it to a supplied instant
        via the clock-setting capability, passing `to_iso8601`; the capability
        returns the new `now_utc`."

        Design: Corner/endpoints/clock_set_endpoint_default
        """
        res = api.set_clock("2027-01-15T12:00:00Z", ops_admin_headers)
        clock = validate_success(res, 200)
        # PRD pins the returned instant, not a single string serialization.
        assert_same_instant(clock["now_utc"], "2027-01-15T12:00:00Z")

    def test_get_trip_not_found(self, api, any_headers):
        """PRD §2.5: "`ERR_TRIP_NOT_FOUND` for a `tripId` that does not exist
        within the team".

        Design: Corner/errors/error_trip_not_found
        """
        reset_clock()
        team = validate_success(api.create_team(create_team_payload(), OPS), 201)
        res = api.get_trip(team["id"], NON_EXISTENT_UUID, any_headers)
        validate_error(res, "ERR_TRIP_NOT_FOUND", expected_status=404)

    def test_child_creation_under_closed_season_rejected(self, api, manager_headers):
        """PRD §3.1: "Once a season is `CLOSED`, attempts to open new child
        state under it fail with `ERR_SEASON_CLOSED`."

        Design: Corner/errors/error_season_closed
        """
        team, season = setup_team_season()
        # Empty season: every trip (none) is terminal and projected == committed.
        validate_success(api.close_season(team["id"], season["id"], FIN), 200)
        res = api.create_trip(team["id"], create_trip_payload(season["id"]),
                              manager_headers)
        validate_error(res, "ERR_SEASON_CLOSED", expected_status=409)
