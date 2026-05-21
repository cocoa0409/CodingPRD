"""Keeper declarations, revoke, and the eager round/price computations.

Covers PRD §3.2: keeper_snake_round formula, keeper_auction_price
formula, keeper_cap check, REVOKE state machine, lock at start-draft,
auction balance debit at start-draft.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    COMMISSIONER,
    create_league,
    create_league_with_teams,
    create_player,
    declare_keeper,
    fetch_team,
    make_manager_headers,
    manager_uid,
    revoke_keeper,
    setup_prior_season_auction_pick,
    setup_prior_season_snake_pick,
    validate_error,
    validate_success,
)


# ===========================================================================
# Keeper cap — PRD §3.2
# ===========================================================================
class TestKeeperCap:
    def test_declaration_exceeding_keeper_cap_rejected(self, api):
        """PRD §3.2: "Each team's outstanding declarations may not exceed League.keeper_cap; a declaration that would push the team above the cap is rejected with ERR_KEEPER_CAP_EXCEEDED."

        Claim: a team that already has keeper_cap declarations is
        rejected when it tries to declare one more.
        """
        # keeper_cap=1, declare two keepers.
        league, teams = create_league_with_teams(
            team_count=4, keeper_mode="DYNASTY", keeper_cap=1,
        )
        t0 = teams[0]
        p1 = create_player(position="RB")
        p2 = create_player(position="WR")
        # First declaration succeeds.
        declare_keeper(team=t0, player_id=p1["id"], season_year=league["season_year"])
        # Second exceeds cap.
        from test_helpers import create_keeper_payload
        payload = create_keeper_payload(player_id=p2["id"], season_year=league["season_year"])
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.create_keeper(t0["id"], payload, h0)
        validate_error(res, ApiErrorId.ERR_KEEPER_CAP_EXCEEDED.value)


# ===========================================================================
# Revoke — PRD §3.2
# ===========================================================================
class TestKeeperRevoke:
    def test_revoke_pending_keeper(self, api):
        """PRD §3.2: "While the league remains in DRAFT_PENDING, the owning Manager may revoke a DECLARED keeper, transitioning it to REVOKED".

        Claim: a DECLARED keeper revoked by its owning manager moves
        to REVOKED.
        """
        league, teams = create_league_with_teams(
            team_count=4, keeper_mode="DYNASTY", keeper_cap=2,
        )
        t0 = teams[0]
        p = create_player(position="RB")
        keeper = declare_keeper(
            team=t0, player_id=p["id"], season_year=league["season_year"],
        )
        assert keeper["status"] == "DECLARED"
        revoked = revoke_keeper(team=t0, keeper_id=keeper["id"])
        assert revoked["status"] == "REVOKED"


# ===========================================================================
# keeper_snake_round — PRD §3.2 (difficulty Rule 1 instance 2 split)
# ===========================================================================
class TestKeeperSnakeRound:
    def test_undrafted_free_agent_keeper_assigned_late_round(self, api):
        """PRD §3.2: "treats an undrafted free-agent keeper as if they had been picked in round number regular_season_weeks + 5 (effectively the last round), subtracts 1 from that prior round, and then takes the larger of that result and 1 (so a first-round prior pick still costs at least round 1)."

        Claim: an undrafted keeper has assigned_round =
        max(1, (regular_season_weeks + 5) - 1) = regular_season_weeks + 4
        in the prior-season fallback path. With regular_season_weeks=14
        that is 18. The difficulty design names 19 — but PRD prose
        says the substitution is "in round number regular_season_weeks
        + 5" and then "subtracts 1 from that prior round". 14 + 5 = 19,
        then -1 = 18.

        We test the PRD-derivable value 18 (regular_season_weeks +
        5 - 1).

        # difficulty: dual_variant_calc/keeper_round_drafted_vs_undrafted_on_keeper_designation
        """
        league = create_league(
            name="No-prior-season",
            season_year=2026, draft_mode="SNAKE",
            team_count=4, roster_size=12, starter_count=7, ir_slots=1,
            regular_season_weeks=14, keeper_mode="DYNASTY", keeper_cap=2,
        )
        # Create teams.
        teams_h = []
        for i in range(4):
            from test_helpers import create_team_payload
            res = api.create_team(
                league["id"],
                create_team_payload(manager_user_id=manager_uid(f"snake-{i}")),
                COMMISSIONER,
            )
            teams_h.append(validate_success(res, 201))
        t0 = teams_h[0]
        # The team's manager_user_id was minted by manager_uid; ensure
        # it's present on the returned record (the create endpoint
        # echoes its input).
        if "manager_user_id" not in t0:
            t0["manager_user_id"] = manager_uid(f"snake-0-recover")
        p_new = create_player(position="RB")
        # Use the manager_user_id we sent at create time.
        # Re-read team to get the canonical manager_user_id from the server.
        t0_canon = fetch_team(league["id"], t0["id"])
        keeper = declare_keeper(
            team=t0_canon, player_id=p_new["id"], season_year=2026,
        )
        # PRD-derived expected: max(1, (14+5)-1) = 18.
        assert keeper["assigned_round"] == 18, \
            f"PRD §3.2: undrafted keeper assigned_round = max(1, regular_season_weeks+5 - 1) = 18, got {keeper.get('assigned_round')}"
        # SNAKE mode → assigned_price_dollars is null.
        assert keeper.get("assigned_price_dollars") is None, \
            "PRD §3.2: AUCTION-only assigned_price_dollars is null for SNAKE keepers"

    # DELETED — test_drafted_last_year_keeper_assigned_one_round_earlier.
    # PRD §3.2 wording "looks up the prior-season DraftPick.round_number
    # for this team_id and player_id pairing" is literal team_id. Since
    # Team rows are recreated each season with new ids, a strict PRD
    # reading yields no cross-season match (assigned_round = 18 = the
    # undrafted default), while a charitable manager-identity reading
    # yields 4. UNIQUE DERIVABILITY is broken. PRD-silent on cross-
    # season identity model.
    def _removed_test_drafted_last_year_keeper_assigned_one_round_earlier(self, api):
        """REMOVED — see note above."""
        pass


# ===========================================================================
# keeper_auction_price — PRD §3.2 (difficulty Rule 2 instance 3)
# ===========================================================================
class TestKeeperAuctionPrice:
    # DELETED — test_auction_inflation_multiply_then_ceiling.
    # Same PRD-silence as the SNAKE cross-season keeper test: PRD §3.2
    # says "looks up the prior-season auction price_dollars for the
    # same pairing" (where 'pairing' is team_id+player_id). Team rows
    # are per-season, so strict reading finds no match (price=1) while
    # charitable manager-identity reading yields 22/6. UNIQUE
    # DERIVABILITY broken — deleted.
    def _removed_test_auction_inflation_multiply_then_ceiling(self, api):
        """REMOVED — see note above."""
        uid = manager_uid("auction-cross")
        prior, prior_team, target_players = setup_prior_season_auction_pick(
            manager_user_id=uid,
            season_year=2025,
            target_player_prices=[20, 5],
        )
        # Current season league.
        cur = create_league(
            name="Cur-auction",
            season_year=2026, draft_mode="AUCTION", team_count=4,
            roster_size=12, starter_count=7, ir_slots=1,
            regular_season_weeks=14, keeper_mode="DYNASTY", keeper_cap=2,
            auction_budget_dollars=200,
        )
        from test_helpers import create_team_payload
        team_res = api.create_team(
            cur["id"],
            create_team_payload(manager_user_id=uid),
            COMMISSIONER,
        )
        cur_team = validate_success(team_res, 201)
        if "manager_user_id" not in cur_team:
            cur_team["manager_user_id"] = uid
        for i in range(3):
            api.create_team(
                cur["id"],
                create_team_payload(manager_user_id=manager_uid(f"auction-cross-filler-{i}")),
                COMMISSIONER,
            )
        k1 = declare_keeper(
            team=cur_team, player_id=target_players[0]["id"], season_year=2026,
        )
        k2 = declare_keeper(
            team=cur_team, player_id=target_players[1]["id"], season_year=2026,
        )
        assert k1["assigned_price_dollars"] == 22, \
            f"PRD §3.2: ceil(20*1.10)=22, got {k1.get('assigned_price_dollars')}"
        assert k2["assigned_price_dollars"] == 6, \
            f"PRD §3.2: ceil(5*1.10)=ceil(5.5)=6, got {k2.get('assigned_price_dollars')}"

    def test_undrafted_or_zero_prior_floors_at_one_dollar(self, api):
        """PRD §3.2: "defaults to 1 if no prior price exists or the prior price was 0 ... and takes the larger of that result and 1."

        Claim: a keeper with no prior auction pick gets
        assigned_price_dollars = 1.

        # difficulty: combinatorial_formula/keeper_auction_inflation_circular_evaluation_mode_c
        """
        uid = manager_uid("no-prior-auction")
        league = create_league(
            name="No-prior-auction",
            season_year=2026, draft_mode="AUCTION", team_count=4,
            roster_size=12, starter_count=7, ir_slots=1,
            regular_season_weeks=14, keeper_mode="DYNASTY", keeper_cap=2,
            auction_budget_dollars=200,
        )
        from test_helpers import create_team_payload
        t_res = api.create_team(
            league["id"], create_team_payload(manager_user_id=uid), COMMISSIONER,
        )
        cur_team = validate_success(t_res, 201)
        if "manager_user_id" not in cur_team:
            cur_team["manager_user_id"] = uid
        for i in range(3):
            api.create_team(
                league["id"],
                create_team_payload(manager_user_id=manager_uid(f"nopf-{i+2}")),
                COMMISSIONER,
            )
        new_player = create_player(position="RB")
        keeper = declare_keeper(
            team=cur_team, player_id=new_player["id"], season_year=2026,
        )
        assert keeper["assigned_price_dollars"] == 1, \
            f"PRD §3.2: undrafted keeper assigned_price_dollars = 1, got {keeper.get('assigned_price_dollars')}"
        # AUCTION mode → assigned_round is null.
        assert keeper.get("assigned_round") is None
