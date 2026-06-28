"""Prize payout calculation: cash/annuity divergence, withholding, installments.

Covers difficulty rules dual_variant_calc, combinatorial_formula (payout mode),
non_linear_state_machine (claim fork), and the cash-nonjackpot corner.
"""
from test_helpers import (
    api_client, validate_success, officer_headers,
    setup_adjudicating_claim, setup_game_retailer_terminal,
    sell_and_validate_winner, create_player, open_claim,
)


class TestCashVsAnnuityDivergence:
    def test_cash_jackpot_gross_payout_applies_factor(self, api):
        """PRD 3.7: "For a `CASH` claim on a `JACKPOT` game, the basis is the
        advertised `gross_prize_cents` multiplied by the game's `cash_option_factor`,
        rounded half-up to the nearest cent — this is the discounted lump-sum cash value."

        Design: Difficulty/dual_variant_calc/prize_payout_cash_jackpot_vs_annuity_diverge_on_claim
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="JACKPOT", payout_option="CASH",
            gross_prize_cents=1000000000, clock="2026-01-05T00:00:00Z",
            threshold_cents=600000)
        adj = ctx["adj_headers"]
        data = validate_success(api.approve_claim(ctx["claim"]["id"], adj))
        assert data["gross_payout_cents"] == 600000000, data["gross_payout_cents"]
        assert data["net_payout_cents"] == 426000000, data["net_payout_cents"]

    def test_annuity_jackpot_gross_payout_no_factor(self, api):
        """PRD 3.7: "For an `ANNUITY` claim (which is only ever a jackpot game), the
        basis is the full advertised `gross_prize_cents` with the cash-option factor
        **not** applied."

        Design: Difficulty/dual_variant_calc/prize_payout_cash_jackpot_vs_annuity_diverge_on_claim
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="JACKPOT", payout_option="ANNUITY",
            gross_prize_cents=1000000000, clock="2026-01-05T00:00:00Z",
            threshold_cents=600000)
        adj = ctx["adj_headers"]
        data = validate_success(api.approve_claim(ctx["claim"]["id"], adj))
        assert data["gross_payout_cents"] == 1000000000, data["gross_payout_cents"]
        assert data["net_payout_cents"] == 710000000, data["net_payout_cents"]
        assert data["annual_installment_cents"] == 23666666, data["annual_installment_cents"]


class TestPayoutBranchSelection:
    def test_cash_jackpot_full_withholding_breakdown(self, api):
        """PRD 3.7: "the `federal_withholding_cents` is `gross_payout_cents` multiplied
        by the `federal_withholding_rate`, rounded half-up to the nearest cent, and the
        `state_withholding_cents` is `gross_payout_cents` multiplied by the
        `state_withholding_rate`, rounded half-up to the nearest cent."

        Design: Difficulty/combinatorial_formula/payout_branch_min_max_tiered_jackpot_threshold
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="JACKPOT", payout_option="CASH",
            gross_prize_cents=1000000000, clock="2026-01-05T00:00:00Z",
            threshold_cents=600000)
        adj = ctx["adj_headers"]
        data = validate_success(api.approve_claim(ctx["claim"]["id"], adj))
        assert data["gross_payout_cents"] == 600000000
        assert data["federal_withholding_cents"] == 144000000, data["federal_withholding_cents"]
        assert data["state_withholding_cents"] == 30000000, data["state_withholding_cents"]
        assert data["net_payout_cents"] == 426000000

    def test_withholding_gates_on_advertised_gross_over_threshold(self, api):
        """PRD 3.7: "the threshold gate is evaluated on the **advertised**
        `gross_prize_cents`, not on the possibly-discounted basis. When the advertised
        `gross_prize_cents` is at or above the game's `federal_withholding_threshold_cents`,
        the `federal_withholding_cents` is `gross_payout_cents` multiplied by the
        `federal_withholding_rate`, rounded half-up to the nearest cent"

        Design: Difficulty/combinatorial_formula/payout_branch_min_max_tiered_jackpot_threshold
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="JACKPOT", payout_option="CASH",
            gross_prize_cents=1000000000, clock="2026-01-05T00:00:00Z",
            threshold_cents=600000)
        adj = ctx["adj_headers"]
        data = validate_success(api.approve_claim(ctx["claim"]["id"], adj))
        # advertised G (1e9) >= threshold (600000), so withholding is non-zero,
        # computed on the discounted gross_payout (6e8), not the advertised G.
        assert data["federal_withholding_cents"] == 144000000
        assert data["state_withholding_cents"] == 30000000
        assert data["net_payout_cents"] == 426000000

    def test_cash_nonjackpot_no_factor_applied(self, api):
        """PRD 3.7: "For a `CASH` claim on a non-jackpot game, the basis is exactly the
        advertised `gross_prize_cents` — the cash-option factor is never applied."

        Design: Corner/calculations/cash_nonjackpot_payout_full_gross_no_factor
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        ticket = sell_and_validate_winner(game["id"], term["id"], gross_prize_cents=1000000)
        player = create_player()
        claim = open_claim(ticket["id"], player["id"], "CASH")
        adj = officer_headers("u-adj")
        validate_success(api.begin_adjudication(claim["id"], adj))
        data = validate_success(api.approve_claim(claim["id"], adj))
        assert data["gross_payout_cents"] == 1000000, data["gross_payout_cents"]
        assert data["federal_withholding_cents"] == 240000
        assert data["state_withholding_cents"] == 50000
        assert data["net_payout_cents"] == 710000
        assert data["annual_installment_cents"] == 0


class TestClaimForkJoin:
    def test_annuity_approval_populates_installment(self, api):
        """PRD 3.5: "In both approval branches the system computes the claim's money
        fields by the payout calculation of Section 3.7; the difference is only that the
        cash branch leaves `annual_installment_cents` at 0 while the annuity branch
        populates it."

        Design: Difficulty/non_linear_state_machine/prizeclaim_fork_join_cash_vs_annuity_divergent_side_effects
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="JACKPOT", payout_option="ANNUITY",
            gross_prize_cents=1000000000, clock="2026-01-05T00:00:00Z",
            threshold_cents=600000)
        adj = ctx["adj_headers"]
        data = validate_success(api.approve_claim(ctx["claim"]["id"], adj))
        assert data["status"] == "APPROVED_ANNUITY", data["status"]
        assert data["annual_installment_cents"] == 23666666, data["annual_installment_cents"]
        assert data["gross_payout_cents"] == 1000000000

    def test_cash_approval_status_and_zero_installment(self, api):
        """PRD 3.5: "Approval forks on the elected `payout_option`: a `CASH` claim moves
        `ADJUDICATING → APPROVED_CASH` and an `ANNUITY` claim moves
        `ADJUDICATING → APPROVED_ANNUITY`"
        PRD 3.7: "For a `CASH` claim, `annual_installment_cents` stays 0."

        Design: Difficulty/non_linear_state_machine/prizeclaim_fork_join_cash_vs_annuity_divergent_side_effects
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="JACKPOT", payout_option="CASH",
            gross_prize_cents=1000000000, clock="2026-01-05T00:00:00Z",
            threshold_cents=600000)
        adj = ctx["adj_headers"]
        data = validate_success(api.approve_claim(ctx["claim"]["id"], adj))
        assert data["status"] == "APPROVED_CASH", data["status"]
        assert data["annual_installment_cents"] == 0
