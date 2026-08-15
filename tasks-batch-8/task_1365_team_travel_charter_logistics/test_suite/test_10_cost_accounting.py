"""Provisional vs chronological cost accounting divergence (PRD §2.10, §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_member, create_and_book_leg, create_hotel_block, create_per_diem,
    create_room_assignment_payload, make_team_member_headers, set_clock,
    setup_team_season_trip,
    validate_success, get_success_data,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
FIN = TEST_USERS["finance_headers"]
COORD = TEST_USERS["coordinator_headers"]

HOTEL_CENTS = 30000 * 1 * 2          # 1 room x 30000/night x 2 nights = 60000
GAME_DAY_BASE_A = 15000              # TIER_A GAME_DAY base rate


def _base_trip(api):
    """Trip (game 2026-10-15) with one TIER_A member, a booked commercial leg,
    and a 1-room hotel block (60000 cents). Returns ctx dict."""
    team, season, trip = setup_team_season_trip(
        trip_overrides={"destination_code": "LAX",
                        "game_tipoff_utc": "2026-10-15T02:00:00Z",
                        "return_arrival_utc": "2026-10-16T08:00:00Z"})
    member = add_member(team["id"], trip["id"], member_ref="P01",
                        party_role="PLAYER", per_diem_tier="TIER_A")
    block = create_hotel_block(team["id"], trip["id"], hotel_code="HLAX",
                               room_count=1, rate_cents_per_night=30000,
                               check_in_date="2026-10-14", night_count=2,
                               cutoff_date="2026-10-10")
    leg = create_and_book_leg(team["id"], trip["id"], leg_seq=1,
                              origin_code="PDX", destination_code="LAX",
                              scheduled_depart_utc="2026-10-14T18:00:00Z",
                              scheduled_arrive_utc="2026-10-14T21:00:00Z")
    return {"team": team, "season": season, "trip": trip,
            "member": member, "block": block, "leg": leg}


class TestProvisionalVersusChronological:
    def test_lock_estimate_counts_draft_ledger_at_base_regardless_of_meals(self, api):
        """PRD §3.9: "The forward-looking `estimated_cost_cents` at lock time
        counts every `DRAFT` per-diem row at its full `base_amount_cents`
        regardless of `meals_provided_count` — a deliberately conservative
        assumption of zero team-provided meals — while the close-out replay uses
        the actual meal counts."

        Design: Difficulty/dual_variant_calc/trip_cost_provisional_vs_chronological_diverge
        """
        ctx = _base_trip(api)
        team_id, trip_id = ctx["team"]["id"], ctx["trip"]["id"]
        ledger = create_per_diem(team_id, trip_id, ctx["member"]["id"],
                                 service_date="2026-10-15", day_kind="GAME_DAY",
                                 meals_provided_count=2)
        assert ledger["net_amount_cents"] == 10000  # 15000 - 2*2500

        fresh = get_success_data(api.get_trip(team_id, trip_id, ANY))
        locked = validate_success(
            api.lock_trip(team_id, trip_id, fresh["version"], MGR), 200)
        assert locked["posture"] == "LOCKED"
        assert locked["estimated_cost_cents"] == HOTEL_CENTS + GAME_DAY_BASE_A, \
            ("provisional estimate counts the DRAFT ledger at its 15000 base, "
             "not its 10000 net: 60000 hotel + 15000 = 75000")

    def test_close_out_replay_diverges_by_actual_meal_deduction(self, api):
        """PRD §3.9: "Closing computes the trip's `actual_cost_cents` as a
        chronological ledger replay: ... each hotel block lock contributing the
        un-released rooms' rate times nights; ... each per-diem payment
        contributing the `net_amount_cents` as of pay time". PRD §2.10: "Because
        the two rollups use different inclusion rules, they legitimately
        diverge".

        Design: Difficulty/dual_variant_calc/trip_cost_provisional_vs_chronological_diverge
        """
        ctx = _base_trip(api)
        team_id, trip_id = ctx["team"]["id"], ctx["trip"]["id"]
        member_id = ctx["member"]["id"]
        ledger = create_per_diem(team_id, trip_id, member_id,
                                 service_date="2026-10-15", day_kind="GAME_DAY",
                                 meals_provided_count=0)

        # Lock the hotel block first (NAME_LIST_DUE at cutoff-7d) so the
        # chronological replay has a hotel-lock event to pick up.
        set_clock("2026-10-04T00:00:00Z")
        validate_success(
            api.create_room_assignment(
                team_id, trip_id, ctx["block"]["id"],
                create_room_assignment_payload(member_id, room_label="501"), COORD), 201)
        block_fresh = get_success_data(
            api.get_hotel_block(team_id, trip_id, ctx["block"]["id"], ANY))
        locked_block = validate_success(
            api.lock_hotel_block(team_id, trip_id, ctx["block"]["id"],
                                 block_fresh["version"], COORD), 200)
        assert locked_block["posture"] == "LOCKED"

        fresh = get_success_data(api.get_trip(team_id, trip_id, ANY))
        locked = validate_success(
            api.lock_trip(team_id, trip_id, fresh["version"], MGR), 200)
        estimated_at_lock = locked["estimated_cost_cents"]
        assert estimated_at_lock == HOTEL_CENTS + GAME_DAY_BASE_A, \
            "60000 hotel + DRAFT ledger at base 15000 = 75000"

        # Correct the meal count through the dispute channel, then pay.
        validate_success(api.approve_per_diem(team_id, trip_id, member_id,
                                              ledger["id"], FIN), 200)
        validate_success(api.dispute_per_diem(team_id, trip_id, member_id,
                                              ledger["id"],
                                              make_team_member_headers(member_id)), 200)
        resolved = validate_success(
            api.resolve_per_diem(team_id, trip_id, member_id, ledger["id"], 2, FIN), 200)
        assert resolved["net_amount_cents"] == 10000
        validate_success(api.pay_per_diem(team_id, trip_id, member_id,
                                          ledger["id"], FIN), 200)

        # Fly the single leg so the trip reaches RECOVERING, then close.
        set_clock("2026-10-15T01:00:00Z")
        validate_success(api.depart_leg(team_id, trip_id, ctx["leg"]["id"], COORD), 200)
        validate_success(api.arrive_leg(team_id, trip_id, ctx["leg"]["id"], COORD), 200)

        closed = validate_success(api.close_trip(team_id, trip_id, FIN), 200)
        assert closed["posture"] == "CLOSED"
        # Chronological replay: hotel block lock (+60000) then per-diem pay at
        # net as of pay time (+10000) -> 70000.
        assert closed["actual_cost_cents"] == HOTEL_CENTS + 10000
        assert estimated_at_lock - closed["actual_cost_cents"] == 5000, \
            "the two lenses diverge by exactly the 2 x 2500 meal deduction"
