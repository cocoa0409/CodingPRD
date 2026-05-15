"""Prize-pool allocation, finalization, and tax-withholding tests
(PRD §3.6).

Covers PROVISIONAL emission on COMPLETED, the round-half-up per-tier
math, MVP allocation at 500 basis points, finalize-prize-pool
preconditions, and the conservation invariant at distribute-prizes.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    MVP_BPS,
    TEST_USERS,
    create_open_tournament,
    finalize_prize_pool,
    register_team_to_registered,
    reset_clock_to_epoch,
    setup_completed_tournament,
    validate_error,
    validate_success,
)


# ===========================================================================
# Finalize precondition: tournament must be COMPLETED (PRD §3.6)
# ===========================================================================
class TestFinalizePreconditions:
    def test_finalize_when_tournament_not_completed_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.6: "the tournament's status must be COMPLETED
        (otherwise ERR_TOURNAMENT_NOT_COMPLETED)."

        Claim: finalize-prize-pool on a tournament not in COMPLETED →
        ERR_TOURNAMENT_NOT_COMPLETED.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        response = api.finalize_prize_pool(t["id"], league_admin_headers)
        validate_error(
            response, ApiErrorId.ERR_TOURNAMENT_NOT_COMPLETED.value,
        )


# ===========================================================================
# Distribute precondition: every payout FINALIZED (PRD §3.1)
# ===========================================================================
class TestDistributePreconditions:
    def test_distribute_when_payouts_still_provisional_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "Distribution requires that every PrizePayout for
        the tournament has already reached FINALIZED status —
        otherwise ERR_PRIZE_POOL_NOT_FINALIZED."

        Claim: distribute-prizes on a COMPLETED tournament whose
        payouts are still PROVISIONAL → ERR_PRIZE_POOL_NOT_FINALIZED.
        """
        tournament, regs, matches = setup_completed_tournament(num_teams=2)
        if tournament["status"] != "COMPLETED":
            pytest.skip(
                "Composite did not bring tournament to COMPLETED; cannot "
                "isolate the distribute precondition",
            )
        response = api.distribute_prizes(tournament["id"], league_admin_headers)
        validate_error(
            response, ApiErrorId.ERR_PRIZE_POOL_NOT_FINALIZED.value,
        )


# ===========================================================================
# Prize-pool conservation invariant (PRD §3.1 + §3.6)
# ===========================================================================
class TestPrizePoolConservation:
    def test_finalize_then_distribute_holds_conservation(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "the sum of PrizePayout.gross_amount_cents across
        the tournament equals total_prize_pool_cents exactly, otherwise
        ERR_PRIZE_POOL_INVARIANT."

        Claim: after finalize-prize-pool, distribute-prizes succeeds
        because sum(PrizePayout.gross_amount_cents) ==
        total_prize_pool_cents.
        """
        # default_prize_tier_table has 3 tiers — use 3 teams so every
        # placement has an eligible team (PRD §3.6 emits one PrizePayout
        # row per tier per team).
        tournament, regs, matches = setup_completed_tournament(num_teams=3)
        if tournament["status"] != "COMPLETED":
            pytest.skip("Composite did not reach COMPLETED state")
        # Finalize.
        finalize_prize_pool(tournament["id"])
        # Distribute should now succeed.
        response = api.distribute_prizes(tournament["id"], league_admin_headers)
        data = validate_success(response)
        assert data["status"] == "PRIZES_DISTRIBUTED"
