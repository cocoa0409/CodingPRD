"""Validation priority ordering, OCC stale versions, version increments
(PRD §2.4, §2.6, §2.7, §2.12)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_member, create_contingency_payload, create_leg, create_hotel_block,
    create_trip_payload, lock_trip, set_clock, setup_disrupted_trip,
    setup_lockable_trip, setup_locked_trip, setup_team_season,
    setup_team_season_trip, setup_charter_leg_booked, create_executed_contract,
    add_manifest_entry, confirm_manifest_entry,
    validate_error, validate_success, get_success_data,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]


class TestStateBeatsFiscalOnTripLock:
    def test_relock_reports_not_draft_not_budget(self, api, manager_headers):
        """PRD §2.6: "When several checks guard the same endpoint, the server
        applies them in a fixed global order, and the first failing check
        determines the error returned." — parent aggregate state (item 5:
        "an operation requiring a `DRAFT` trip is rejected with
        `ERR_TRIP_NOT_DRAFT`") precedes item 16 ("Season budget sufficiency
        (`ERR_BUDGET_EXCEEDED`)").

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_trip_lock
        """
        # Budget 60000; hotel block estimate 50000. After the first lock the
        # remaining budget (10000) is itself insufficient, so the fiscal check
        # would also fail if it were ever reached.
        ctx = setup_locked_trip(
            budget_cents=60000,
            hotel_overrides={"room_count": 1, "rate_cents_per_night": 50000,
                             "night_count": 1})
        fresh = get_success_data(api.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
        res = api.lock_trip(ctx["team"]["id"], ctx["trip"]["id"],
                            fresh["version"], manager_headers)
        validate_error(res, "ERR_TRIP_NOT_DRAFT", expected_status=409)

    def test_lock_on_disrupted_trip_reports_not_draft_not_budget(self, api,
                                                                 manager_headers):
        """PRD §2.6: "an operation requiring a `DRAFT` trip is rejected with
        `ERR_TRIP_NOT_DRAFT`" (item 5) is evaluated ahead of "Season budget
        sufficiency (`ERR_BUDGET_EXCEEDED`)" (item 16); a DISRUPTED trip is no
        longer DRAFT, and the depleted remaining budget must not change the
        reported error.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_trip_lock
        """
        ctx = setup_disrupted_trip(
            budget_cents=60000,
            hotel_overrides={"room_count": 1, "rate_cents_per_night": 50000,
                             "night_count": 1})
        assert ctx["trip"]["posture"] == "DISRUPTED"
        fresh = get_success_data(api.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
        res = api.lock_trip(ctx["team"]["id"], ctx["trip"]["id"],
                            fresh["version"], manager_headers)
        validate_error(res, "ERR_TRIP_NOT_DRAFT", expected_status=409)


class TestRestFloorBeatsManifestCapacity:
    def test_rebook_from_delayed_violating_rest_and_capacity(self, api):
        """PRD §2.6: item 7 ("The league rest floor (`ERR_REST_FLOOR_VIOLATION`)
        on leg booking and rebooking") precedes item 11 ("Manifest capacity
        (`ERR_MANIFEST_FULL`)"). PRD §3.4: "the new departure must again satisfy
        the rest floor against the prior leg, and when rebooking from `DELAYED`
        the charter contract must still have seat capacity for the `IN` members."
        Here both fail; the safety error must win.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_rest_vs_capacity
        """
        ctx = setup_charter_leg_booked(
            contract_overrides={"seat_capacity": 1, "cargo_capacity_lb": 5000},
            num_members=1,
            trip_overrides={"game_tipoff_utc": "2026-12-26T00:00:00Z"},
            leg_overrides={"origin_code": "SAT", "destination_code": "HOU",
                           "scheduled_depart_utc": "2026-12-25T14:00:00Z",
                           "scheduled_arrive_utc": "2026-12-25T15:00:00Z"})
        team_id, trip_id = ctx["team"]["id"], ctx["trip"]["id"]
        leg1 = ctx["leg"]
        # Second leg departs 660 minutes after leg 1 arrival (satisfies 600).
        leg2 = create_leg(team_id, trip_id, leg_seq=2,
                          origin_code="HOU", destination_code="DAL",
                          scheduled_depart_utc="2026-12-26T02:00:00Z",
                          scheduled_arrive_utc="2026-12-26T03:00:00Z",
                          is_charter=True, contract_id=ctx["contract"]["id"])
        validate_success(api.book_leg(team_id, trip_id, leg2["id"], COORD), 200)
        # Roster grows past the single seat after booking.
        add_member(team_id, trip_id, member_ref="S02", party_role="COACH")
        validate_success(api.delay_leg(team_id, trip_id, leg2["id"], 30, COORD), 200)

        # New departure (20:00) is inside the floor (prior arrive 15:00 + 600min
        # = 01:00 next day) AND the contract can no longer seat 2 IN members.
        res = api.rebook_leg(team_id, trip_id, leg2["id"],
                             "2026-12-25T20:00:00Z", "2026-12-25T21:00:00Z", COORD)
        validate_error(res, "ERR_REST_FLOOR_VIOLATION", expected_status=409)

    def test_rebook_from_rebooking_violating_rest_floor(self, api):
        """PRD §3.4: delay "forces every downstream leg whose scheduled
        departure now falls before the new arrival plus the rest floor into
        `REBOOKING`" and rebooking requires that "the new departure must again
        satisfy the rest floor against the prior leg", failing with
        `ERR_REST_FLOOR_VIOLATION` (§2.6 item 7).

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_rest_vs_capacity
        """
        team, season, trip = setup_team_season_trip(
            budget_cents=1000000000,
            trip_overrides={"game_tipoff_utc": "2026-12-26T00:00:00Z"})
        leg1 = create_leg(team["id"], trip["id"], leg_seq=1,
                          origin_code="SAT", destination_code="HOU",
                          scheduled_depart_utc="2026-12-25T14:00:00Z",
                          scheduled_arrive_utc="2026-12-25T15:00:00Z")
        leg2 = create_leg(team["id"], trip["id"], leg_seq=2,
                          origin_code="HOU", destination_code="DAL",
                          scheduled_depart_utc="2026-12-26T02:00:00Z",
                          scheduled_arrive_utc="2026-12-26T03:00:00Z")
        validate_success(api.book_leg(team["id"], trip["id"], leg1["id"], COORD), 200)
        validate_success(api.book_leg(team["id"], trip["id"], leg2["id"], COORD), 200)
        # 300-minute delay: new arrival 20:00; leg 2's 02:00 departure falls
        # before 20:00 + 600min = 06:00 -> REBOOKING.
        validate_success(api.delay_leg(team["id"], trip["id"], leg1["id"], 300, COORD), 200)
        assert get_success_data(
            api.get_flight_leg(team["id"], trip["id"], leg2["id"], ANY)
        )["status"] == "REBOOKING"

        res = api.rebook_leg(team["id"], trip["id"], leg2["id"],
                             "2026-12-26T01:00:00Z", "2026-12-26T02:00:00Z", COORD)
        validate_error(res, "ERR_REST_FLOOR_VIOLATION", expected_status=409)
        assert get_success_data(
            api.get_flight_leg(team["id"], trip["id"], leg2["id"], ANY)
        )["status"] == "REBOOKING", "rejected rebook must leave the leg REBOOKING"


class TestBudgetExceeded:
    def test_trip_lock_over_budget_rejected(self, api, manager_headers):
        """PRD §3.2: "A trip whose estimate exceeds the remaining budget is
        refused with `ERR_BUDGET_EXCEEDED`." PRD §2.12: "Any operation whose
        proposed change would push committed spend past the ceiling — locking a
        trip, executing a charter contract, or resolving a contingency with a
        recovery cost — is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/budget_exceeded_on_trip_lock
        """
        ctx = setup_lockable_trip(
            budget_cents=100000,
            hotel_overrides={"room_count": 4, "rate_cents_per_night": 50000,
                             "night_count": 1})
        fresh = get_success_data(api.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
        res = api.lock_trip(ctx["team"]["id"], ctx["trip"]["id"],
                            fresh["version"], manager_headers)
        validate_error(res, "ERR_BUDGET_EXCEEDED", expected_status=402)


class TestOptimisticConcurrency:
    def test_trip_lock_with_stale_version_rejected(self, api, manager_headers):
        """PRD §2.7: "Locking a trip requires `expected_trip_version` matching
        the trip's current `version`" and "If the supplied value does not match
        the parent resource's current `version` — because another writer has
        advanced the resource since the client last read it (a party member
        added, a leg edited, a vendor counter-signature applied, rooms
        released) — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and no mutation occurs."

        Design: Corner/cross_cutting_layers/occ_trip_lock_stale_version
        """
        ctx = setup_lockable_trip()
        stale_version = ctx["trip"]["version"]
        # Another writer adds a roster member, advancing the trip's version.
        add_member(ctx["team"]["id"], ctx["trip"]["id"], member_ref="I02",
                   party_role="COACH")
        res = api.lock_trip(ctx["team"]["id"], ctx["trip"]["id"],
                            stale_version, manager_headers)
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)
        trip_after = get_success_data(
            api.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
        assert trip_after["posture"] == "DRAFT", "no mutation occurs on a stale write"


class TestVersionIncrements:
    def test_member_add_increments_trip_version(self, api, manager_headers):
        """PRD §3.2: "The trip's `party_size` is the count of its `IN` members
        and is recomputed as the roster changes — each roster change also
        increments the trip's `version`." PRD §2.4: "`updated_at` (string): an
        ISO 8601 UTC timestamp refreshed on every modification of the resource."

        Design: Corner/cross_cutting_layers/version_increments_on_mutation
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-07-10T00:00:00Z"})
        v0 = trip["version"]
        created_at = trip["created_at"]
        set_clock("2026-08-02T00:00:00Z")
        add_member(team["id"], trip["id"], member_ref="M03", party_role="STAFF")
        after = get_success_data(api.get_trip(team["id"], trip["id"], ANY))
        assert after["version"] == v0 + 1, "a roster change increments version by exactly 1"
        assert after["updated_at"] > created_at, \
            "a modification refreshes updated_at (clock advanced between writes)"
        assert after["party_size"] == 1
