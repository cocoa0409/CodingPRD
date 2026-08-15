"""Charter contracting: execution gates, cancellation penalties, cascades (PRD §3.3, §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_manifest_entry, create_contract, create_executed_contract, create_leg,
    set_clock, setup_charter_leg_booked, setup_disrupted_charter_trip,
    setup_team_season_trip, setup_trip_with_executed_contract,
    validate_error, validate_success, get_success_data,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
FIN = TEST_USERS["finance_headers"]
VENDOR = TEST_USERS["vendor_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestExecutionGate:
    def test_execute_submitted_contract_rejected(self, api, finance_headers):
        """PRD §3.3: "Execution requires the contract to be
        `VENDOR_COUNTERSIGNED` (otherwise `ERR_CONTRACT_NOT_VENDOR_COUNTERSIGNED`)".

        Design: Corner/state_machines/charter_execute_requires_countersigned
        """
        team, season, trip = setup_team_season_trip(
            budget_cents=1000000000,
            trip_overrides={"game_tipoff_utc": "2027-04-01T00:00:00Z"})
        contract = create_contract(team["id"], trip["id"])
        submitted = validate_success(
            api.submit_contract(team["id"], trip["id"], contract["id"], MGR), 200)
        res = api.execute_contract(team["id"], trip["id"], contract["id"],
                                   submitted["version"], finance_headers)
        validate_error(res, "ERR_CONTRACT_NOT_VENDOR_COUNTERSIGNED", expected_status=409)

    def test_execute_establishes_team_executed_and_estimate(self, api):
        """PRD §3.3: "On execution the contract reaches `TEAM_EXECUTED`, its
        `executed_at` timestamp is set to the current clock time, the trip's
        `estimated_cost_cents` increases by the base price plus the fuel
        surcharge cap, and the trip's `version` increments."

        Design: Corner/consistency_model/trip_estimated_visible_immediately_after_charter_execute
        """
        team, season, trip = setup_team_season_trip(
            budget_cents=1000000000,
            trip_overrides={"game_tipoff_utc": "2027-07-15T00:00:00Z"})
        contract = create_contract(team["id"], trip["id"], base_price_cents=6000000,
                                   fuel_surcharge_cap_cents=600000)
        validate_success(api.submit_contract(team["id"], trip["id"], contract["id"], MGR), 200)
        countersigned = validate_success(
            api.countersign_contract(team["id"], trip["id"], contract["id"], VENDOR), 200)
        executed = validate_success(
            api.execute_contract(team["id"], trip["id"], contract["id"],
                                 countersigned["version"], FIN), 200)
        assert executed["status"] == "TEAM_EXECUTED"
        assert executed["executed_at"] is not None

        # Immediate consistency: the very next read reflects the rollup.
        trip_after = get_success_data(api.get_trip(team["id"], trip["id"], ANY))
        assert trip_after["estimated_cost_cents"] == 6600000, \
            "base 6000000 + fuel cap 600000 must be visible immediately"


class TestBookRequiresExecutableContract:
    def test_book_with_vendor_countersigned_contract_rejected(self, api):
        """PRD §3.4: "First, a charter leg's contract must be in `TEAM_EXECUTED`
        or `ACTIVE` (otherwise `ERR_CONTRACT_NOT_EXECUTABLE`...)".

        Design: Difficulty/cross_entity_state_dependency/flight_leg_book_requires_contract_team_executed
        """
        team, season, trip = setup_team_season_trip(
            budget_cents=1000000000,
            trip_overrides={"game_tipoff_utc": "2027-01-15T00:00:00Z"})
        contract = create_contract(team["id"], trip["id"], seat_capacity=25,
                                   cargo_capacity_lb=8000)
        validate_success(api.submit_contract(team["id"], trip["id"], contract["id"], MGR), 200)
        validate_success(
            api.countersign_contract(team["id"], trip["id"], contract["id"], VENDOR), 200)
        leg = create_leg(team["id"], trip["id"], is_charter=True,
                         contract_id=contract["id"],
                         scheduled_depart_utc="2027-01-14T18:00:00Z",
                         scheduled_arrive_utc="2027-01-14T19:00:00Z")

        res = api.book_leg(team["id"], trip["id"], leg["id"], COORD)
        validate_error(res, "ERR_CONTRACT_NOT_EXECUTABLE", expected_status=409)

        leg_after = get_success_data(
            api.get_flight_leg(team["id"], trip["id"], leg["id"], ANY))
        assert leg_after["status"] == "PLANNED", "rejected book must not mutate the leg"
        contract_after = get_success_data(
            api.get_charter_contract(team["id"], trip["id"], contract["id"], ANY))
        assert contract_after["status"] == "VENDOR_COUNTERSIGNED"

    def test_book_with_submitted_contract_rejected(self, api):
        """PRD §3.4: "First, a charter leg's contract must be in `TEAM_EXECUTED`
        or `ACTIVE` (otherwise `ERR_CONTRACT_NOT_EXECUTABLE`...)". A SUBMITTED
        contract is likewise not yet executable.

        Design: Difficulty/cross_entity_state_dependency/flight_leg_book_requires_contract_team_executed
        """
        team, season, trip = setup_team_season_trip(
            budget_cents=1000000000,
            trip_overrides={"game_tipoff_utc": "2027-01-15T00:00:00Z"})
        contract = create_contract(team["id"], trip["id"], seat_capacity=25)
        validate_success(api.submit_contract(team["id"], trip["id"], contract["id"], MGR), 200)
        leg = create_leg(team["id"], trip["id"], is_charter=True,
                         contract_id=contract["id"],
                         scheduled_depart_utc="2027-01-14T18:00:00Z",
                         scheduled_arrive_utc="2027-01-14T19:00:00Z")

        res = api.book_leg(team["id"], trip["id"], leg["id"], COORD)
        validate_error(res, "ERR_CONTRACT_NOT_EXECUTABLE", expected_status=409)
        leg_after = get_success_data(
            api.get_flight_leg(team["id"], trip["id"], leg["id"], ANY))
        assert leg_after["status"] == "PLANNED"


class TestCancellationPenaltyBands:
    def test_band_selection_twenty_days_out(self, api):
        """PRD §3.3: "take the whole days remaining until tipoff — the difference
        between `game_tipoff_utc` and the current clock time, discarding any
        partial day — and select the first band in the descending `days_before`
        ordering whose threshold has been reached (the band's `days_before` is
        less than or equal to the days remaining)." and "The
        `cancellation_penalty_cents` is that percentage of the sum of
        `base_price_cents` and `fuel_surcharge_cap_cents`, rounded half up to a
        whole cent."

        Design: Corner/calculations/charter_cancellation_penalty_band_selection
        """
        # Execute while the clock is far outside the 30-day execution window.
        team, season, trip = setup_team_season_trip(
            budget_cents=1000000000,
            trip_overrides={"game_tipoff_utc": "2027-04-21T00:00:00Z"})
        contract = create_executed_contract(
            team["id"], trip["id"],
            base_price_cents=8000000, fuel_surcharge_cap_cents=800000,
            seat_capacity=30, cargo_capacity_lb=10000,
            penalty_bands=[{"days_before": 30, "penalty_pct": 10},
                           {"days_before": 7, "penalty_pct": 50}])
        # Advance to exactly 20 days before tipoff -> 7-day band (50%) applies.
        set_clock("2027-04-01T00:00:00Z")
        cancelled = validate_success(
            api.cancel_contract(team["id"], trip["id"], contract["id"], MGR), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_penalty_cents"] == 4400000, \
            "20 days out selects the days_before=7 band: 50% of 8800000"
        assert cancelled["cancelled_at"] is not None


class TestTripCancelCascade:
    def test_disrupted_trip_cancel_cascades_depth3(self, api):
        """PRD §3.9: "From `DISRUPTED`, cancellation is permitted only while no
        leg has `DEPARTED`, and it unwinds the whole trip: every charter contract
        in `SUBMITTED`, `VENDOR_COUNTERSIGNED`, `TEAM_EXECUTED`, or `ACTIVE` is
        cancelled with its `cancellation_penalty_cents` computed from the penalty
        bands as in §3.3". PRD §3.3: "Cancelling stamps `cancelled_at`, ... ,
        cancels every flight leg bound to the contract, and bumps every manifest
        entry on those legs with `bump_reason` `OVERBOOK`."

        Design: Difficulty/transitive_cascade/trip_cancel_cascade_depth3
        """
        ctx = setup_disrupted_charter_trip(
            num_members=2, base_price_cents=8000000, fuel_surcharge_cap_cents=800000,
            penalty_bands=[{"days_before": 30, "penalty_pct": 10}],
            game_tipoff_utc="2026-12-20T00:00:00Z")
        assert ctx["trip"]["posture"] == "DISRUPTED"
        team_id, trip_id = ctx["team"]["id"], ctx["trip"]["id"]

        cancelled_trip = validate_success(api.cancel_trip(team_id, trip_id, MGR), 200)
        assert cancelled_trip["posture"] == "CANCELLED"

        # Depth 1: contract cancelled with band-computed penalty.
        contract = get_success_data(
            api.get_charter_contract(team_id, trip_id, ctx["contract"]["id"], ANY))
        assert contract["status"] == "CANCELLED"
        # Clock is 2026-08-01, tipoff 2026-12-20: 141 whole days -> 30-day band, 10%.
        assert contract["cancellation_penalty_cents"] == 880000

        # Depth 2: the leg on the contract is cancelled.
        leg = get_success_data(api.get_flight_leg(team_id, trip_id, ctx["leg"]["id"], ANY))
        assert leg["status"] == "CANCELLED"

        # Depth 3: manifest entries on that leg are bumped OVERBOOK.
        for entry in ctx["entries"]:
            after = get_success_data(
                api.get_manifest_entry(team_id, trip_id, ctx["leg"]["id"], entry["id"], ANY))
            assert after["status"] == "BUMPED"
            assert after["bump_reason"] == "OVERBOOK"

    def test_disrupted_trip_cancel_increments_all_versions(self, api):
        """PRD §3.9: "The trip, the season, and every cancelled child each
        increment their `version`."

        Design: Difficulty/transitive_cascade/trip_cancel_cascade_depth3
        """
        ctx = setup_disrupted_charter_trip(num_members=1)
        team_id, trip_id = ctx["team"]["id"], ctx["trip"]["id"]

        before = {
            "trip": get_success_data(api.get_trip(team_id, trip_id, ANY))["version"],
            "season": get_success_data(
                api.get_season(team_id, ctx["season"]["id"], ANY))["version"],
            "contract": get_success_data(
                api.get_charter_contract(team_id, trip_id, ctx["contract"]["id"], ANY)
            )["version"],
            "leg": get_success_data(
                api.get_flight_leg(team_id, trip_id, ctx["leg"]["id"], ANY))["version"],
        }

        validate_success(api.cancel_trip(team_id, trip_id, MGR), 200)

        after = {
            "trip": get_success_data(api.get_trip(team_id, trip_id, ANY))["version"],
            "season": get_success_data(
                api.get_season(team_id, ctx["season"]["id"], ANY))["version"],
            "contract": get_success_data(
                api.get_charter_contract(team_id, trip_id, ctx["contract"]["id"], ANY)
            )["version"],
            "leg": get_success_data(
                api.get_flight_leg(team_id, trip_id, ctx["leg"]["id"], ANY))["version"],
        }
        for name in before:
            assert after[name] > before[name], \
                f"{name}.version must increment under the cancel cascade " \
                f"({before[name]} -> {after[name]})"
