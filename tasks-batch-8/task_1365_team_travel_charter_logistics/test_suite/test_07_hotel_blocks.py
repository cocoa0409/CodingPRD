"""Hotel block cutoff windows, attrition penalties, room lifecycle (PRD §3.6, §2.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_member, create_hotel_block, create_room_assignment_payload,
    set_clock, setup_team_season_trip,
    validate_error, validate_error_is_one_of, validate_success, get_success_data,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestCutoffWindow:
    def test_room_create_before_cutoff_succeeds(self, api):
        """PRD §3.6: "and once `cutoff_date` has passed, room-name changes —
        creating or confirming assignments — and locking are all rejected with
        `ERR_CUTOFF_PASSED`." Before the cutoff, creation is accepted.

        Design: Difficulty/resource_temporal_overlap/hotel_block_cutoff_date_exclusion
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-03-15T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="O01")
        block = create_hotel_block(team["id"], trip["id"], room_count=3,
                                   check_in_date="2027-03-14", night_count=1,
                                   cutoff_date="2027-03-10")
        set_clock("2027-03-09T23:59:59Z")  # clearly before the cutoff date
        room = validate_success(
            api.create_room_assignment(
                team["id"], trip["id"], block["id"],
                create_room_assignment_payload(member["id"], room_label="801"), COORD), 201)
        assert room["status"] == "RESERVED"

    def test_room_create_after_cutoff_rejected(self, api):
        """PRD §3.6: "and once `cutoff_date` has passed, room-name changes —
        creating or confirming assignments — and locking are all rejected with
        `ERR_CUTOFF_PASSED`."

        Design: Difficulty/resource_temporal_overlap/hotel_block_cutoff_date_exclusion
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-03-15T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="O02")
        block = create_hotel_block(team["id"], trip["id"], room_count=3,
                                   check_in_date="2027-03-14", night_count=1,
                                   cutoff_date="2027-03-10")
        set_clock("2027-03-11T00:00:00Z")  # clearly past the cutoff date
        res = api.create_room_assignment(
            team["id"], trip["id"], block["id"],
            create_room_assignment_payload(member["id"], room_label="802"), COORD)
        validate_error(res, "ERR_CUTOFF_PASSED", expected_status=409)


class TestAttritionPenalty:
    def test_attrition_exposed_penalty_added_to_estimate(self, api, any_headers):
        """PRD §3.6: "If the clock reaches `cutoff_date` with occupancy below the
        attrition allowance, the block becomes `ATTRITION_EXPOSED` and a penalty
        lands on the trip's `estimated_cost_cents`." and "The attrition
        arithmetic: allowed slippage is `room_count` multiplied by
        `attrition_allowance_pct` and divided by 100, rounded down to whole rooms;
        occupied rooms are the assignments in `CONFIRMED`, `CHECKED_IN`, or
        `CHECKED_OUT`; penalty rooms are `room_count` minus `rooms_released`
        minus occupied rooms minus allowed slippage, floored at zero; and each
        penalty room costs `rate_cents_per_night` multiplied by `night_count`."

        Design: Corner/calculations/hotel_attrition_penalty_below_allowance
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-04-20T00:00:00Z"})
        block = create_hotel_block(
            team["id"], trip["id"], room_count=10, rate_cents_per_night=20000,
            check_in_date="2027-04-19", night_count=2, cutoff_date="2027-04-05",
            attrition_allowance_pct=20)
        est_before = get_success_data(
            api.get_trip(team["id"], trip["id"], ANY))["estimated_cost_cents"]

        set_clock("2027-04-06T00:00:00Z")  # past cutoff_date with zero occupancy
        block_after = get_success_data(
            api.get_hotel_block(team["id"], trip["id"], block["id"], ANY))
        assert block_after["posture"] == "ATTRITION_EXPOSED"

        est_after = get_success_data(
            api.get_trip(team["id"], trip["id"], ANY))["estimated_cost_cents"]
        # penalty_rooms = 10 - 0 released - 0 occupied - floor(10*20/100)=2 -> 8
        # penalty = 8 * 20000 * 2 = 320000
        assert est_after - est_before == 320000, \
            "attrition penalty of 320000 cents must land on the trip estimate"


class TestRoomLifecycleGuards:
    def test_checkin_requires_locked_block(self, api):
        """PRD §3.6: "Check-in moves a `CONFIRMED` assignment to `CHECKED_IN`
        and is only possible once the block is `LOCKED`". The PRD does not name
        a specialized error for this guard, so any state-machine rejection of
        §2.6 items 5-6 is acceptable.

        Design: Corner/state_machines/room_checkin_requires_block_locked
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-04-10T00:00:00Z"})
        member = add_member(team["id"], trip["id"], member_ref="N01",
                            requires_single_room=True)
        block = create_hotel_block(team["id"], trip["id"], room_count=2,
                                   check_in_date="2027-04-09", night_count=1,
                                   cutoff_date="2027-04-05")
        room = validate_success(
            api.create_room_assignment(
                team["id"], trip["id"], block["id"],
                create_room_assignment_payload(member["id"], room_label="701"), COORD), 201)
        confirmed = validate_success(
            api.confirm_room_assignment(team["id"], trip["id"], block["id"],
                                        room["id"], COORD), 200)
        assert confirmed["status"] == "CONFIRMED"

        # Block is still HOLDING: check-in must be rejected with a 409 state error.
        res = api.checkin_room(team["id"], trip["id"], block["id"], room["id"], COORD)
        assert res.status_code == 409
        validate_error_is_one_of(res, ["ERR_INVALID_STATE", "ERR_BLOCK_NOT_NAME_LIST_DUE"])


class TestHotelBlockOcc:
    def test_block_lock_with_stale_version_rejected(self, api, coordinator_headers):
        """PRD §2.7: "locking a hotel block requires `expected_block_version`
        matching the block's current `version`" and "If the supplied value does
        not match the parent resource's current `version` ... the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and no mutation occurs."
        PRD §2.4: "Any mutation described in §3 — including system-driven
        transitions such as a trip being nudged into `DISRUPTED` by an opened
        contingency, or a cascade touching child resources — refreshes
        `updated_at` and increments `version` on every resource it modifies."

        Design: Corner/cross_cutting_layers/occ_hotel_block_lock_stale_version
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-07-05T00:00:00Z"})
        block = create_hotel_block(team["id"], trip["id"], room_count=2,
                                   rate_cents_per_night=35000,
                                   check_in_date="2027-07-04", night_count=1,
                                   cutoff_date="2027-07-08")
        stale_version = get_success_data(
            api.get_hotel_block(team["id"], trip["id"], block["id"], ANY))["version"]
        # Clock crosses cutoff_date - 7d: HOLDING -> NAME_LIST_DUE is a
        # system-driven mutation that increments the block's version.
        set_clock("2027-07-02T00:00:00Z")
        res = api.lock_hotel_block(team["id"], trip["id"], block["id"],
                                   stale_version, coordinator_headers)
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)
