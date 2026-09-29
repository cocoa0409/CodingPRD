"""Formulas whose branches, parameters and stage order all have to be right."""

from typing import Any, Dict

from test_helpers.assertions import assert_cap_position
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"


class TestTenderAmountBranches:
    """The tender floor and the offer-type multiplier compose."""

    @staticmethod
    def _three_tenders(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        restricted_player = league.register_player(
            full_name="Nate Orr", position="WR", accrued_active_days=340
        )
        offer_player = league.register_player(
            full_name="Cy Boone", position="DB", accrued_active_days=340
        )
        arbitration_player = league.register_player(
            full_name="Vic Lund", position="LB", accrued_active_days=520
        )
        restricted_tender = league.issue_tender(
            club["id"], restricted_player["id"], "RESTRICTED_TENDER",
            "FIRST_ROUND", 50_000_000,
        )
        qualifying_offer = league.issue_tender(
            club["id"], offer_player["id"], "QUALIFYING_OFFER",
            "FIRST_ROUND", 50_000_000,
        )
        arbitration_tender = league.issue_tender(
            club["id"], arbitration_player["id"], "ARBITRATION_TENDER",
            "ORIGINAL_ROUND", 50_000_000,
        )
        return {
            "club": club,
            "restricted_player": restricted_player,
            "arbitration_player": arbitration_player,
            "restricted_tender": restricted_tender,
            "qualifying_offer": qualifying_offer,
            "arbitration_tender": arbitration_tender,
        }

    def test_offer_type_multiplier_and_level_floor_pick_the_amount(
        self, league: League
    ) -> None:
        """Two offers land on the same amount from two different floors.

        PRD 3.8: "Three worked cases: a prior base of 50,000,000 cents at
        `FIRST_ROUND` for a player with two service years, issued as a
        `RESTRICTED_TENDER`, has a floor of 60,000,000 cents and an amount of
        66,000,000 cents; the same prior base at `ORIGINAL_ROUND` for a player
        with three service years, issued as an `ARBITRATION_TENDER`, has a floor
        of 50,000,000 cents and an amount of 60,000,000 cents; and the same inputs
        issued as a plain `QUALIFYING_OFFER` have a floor of 50,000,000 cents and
        an amount of 50,000,000 cents."

        Design: Difficulty/combinatorial_formula/qualifying_offer_branch_selection_over_nested_floor_max
        """
        world = self._three_tenders(league)

        restricted = world["restricted_tender"]
        offer = world["qualifying_offer"]
        arbitration = world["arbitration_tender"]

        assert restricted["amount_cents"] == 66_000_000, (
            "a restricted tender over the first-round floor of 60000000 should "
            f"amount to 66000000, got {restricted['amount_cents']}"
        )
        assert offer["amount_cents"] == 60_000_000, (
            "a plain qualifying offer over the same floor applies no multiplier "
            f"and should amount to 60000000, got {offer['amount_cents']}"
        )
        assert arbitration["amount_cents"] == 60_000_000, (
            "an arbitration tender over the original-round floor of 50000000 "
            f"should amount to 60000000, got {arbitration['amount_cents']}"
        )
        assert restricted["amount_cents"] != offer["amount_cents"], (
            "the same floor under two different multipliers must not collapse to "
            "one amount"
        )
        assert offer["amount_cents"] == arbitration["amount_cents"], (
            "two different floors under two different multipliers happen to meet "
            "at 60000000, which is what makes the amount alone insufficient"
        )
        assert restricted["prior_base_salary_cents"] == 50_000_000, (
            "the prior base salary is stored as supplied, got "
            f"{restricted['prior_base_salary_cents']}"
        )
        assert arbitration["tender_level"] == "ORIGINAL_ROUND", (
            "the arbitration tender should record the original-round level, got "
            f"{arbitration['tender_level']}"
        )

    def test_issued_tender_carries_its_deadline_and_commits_no_cap(
        self, league: League
    ) -> None:
        """A tender is born issued, dated 72 hours out, and costs nothing yet.

        PRD 3.8: "Issuance stamps `issued_at` with the logical clock, leaves the
        tender `ISSUED`, and computes `deadline_at` as `issued_at` plus 72 hours,
        snapped into the daily processing window per §2.5."

        Design: Difficulty/combinatorial_formula/qualifying_offer_branch_selection_over_nested_floor_max
        """
        world = self._three_tenders(league)

        restricted = world["restricted_tender"]
        assert restricted["deadline_at"] == "2026-08-13T14:00:00.000Z", (
            "72 hours after an in-window issue instant is still in window and "
            f"needs no snap, got {restricted['deadline_at']}"
        )
        assert restricted["status"] == "ISSUED", (
            f"a new tender should be ISSUED, got {restricted['status']}"
        )
        assert world["arbitration_tender"]["status"] == "ISSUED", (
            "the arbitration tender should be ISSUED too, got "
            f"{world['arbitration_tender']['status']}"
        )

        restricted_player = league.player(world["restricted_player"]["id"])
        arbitration_player = league.player(world["arbitration_player"]["id"])
        assert restricted_player["contract_rights_class"] == "RESTRICTED", (
            "two service years give restricted rights, got "
            f"{restricted_player['contract_rights_class']}"
        )
        assert arbitration_player["contract_rights_class"] == "ARBITRATION_ELIGIBLE", (
            "three service years give arbitration eligibility, got "
            f"{arbitration_player['contract_rights_class']}"
        )

        club = league.club(world["club"]["id"])
        assert club["provisional_cap_committed_cents"] == 0, (
            "an issued tender creates no contract, so the club's provisional "
            f"commitment stays at 0, got {club['provisional_cap_committed_cents']}"
        )


class TestSigningBonusProrationRemainder:
    """One proration formula, two year counts, two remainder placements."""

    @staticmethod
    def _two_contracts(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        short_deal_player = league.register_player(
            full_name="Ray Alder", position="QB"
        )
        long_deal_player = league.register_player(
            full_name="Dane Cole", position="OL"
        )
        short_filing = league.open_signing(
            club["id"], short_deal_player["id"],
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        long_filing = league.open_signing(
            club["id"], long_deal_player["id"], years=7,
            base_salary_cents=30_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        return {
            "club": club,
            "short_contract": league.contract(short_filing["contract_id"]),
            "long_contract": league.contract(long_filing["contract_id"]),
        }

    def test_three_year_deal_puts_the_odd_cent_in_the_final_season(
        self, league: League
    ) -> None:
        """A three-season spread carries the remainder in its last season.

        PRD 3.4: "A 10,000,000-cent bonus on a three-year deal gives an annual
        proration of 3,333,333 cents and a final-season proration of 3,333,334
        cents, and twice 3,333,333 plus 3,333,334 is exactly 10,000,000."

        Design: Difficulty/combinatorial_formula/signing_bonus_proration_remainder_placement_across_year_counts
        """
        world = self._two_contracts(league)
        contract = world["short_contract"]

        assert contract["proration_years"] == 3, (
            f"a three-year deal spreads over 3 seasons, got {contract['proration_years']}"
        )
        assert contract["annual_proration_cents"] == 3_333_333, (
            "the annual proration should be 3333333, got "
            f"{contract['annual_proration_cents']}"
        )
        assert contract["final_season_proration_cents"] == 3_333_334, (
            "the final season should absorb the remainder as 3333334, got "
            f"{contract['final_season_proration_cents']}"
        )
        reconstructed = (
            contract["annual_proration_cents"] * 2
            + contract["final_season_proration_cents"]
        )
        assert reconstructed == 10_000_000, (
            f"the season charges must sum back to the bonus, got {reconstructed}"
        )
        assert contract["current_season_cap_charge_cents"] == 83_333_333, (
            "the current-season charge is the base plus this season's share, got "
            f"{contract['current_season_cap_charge_cents']}"
        )
        assert contract["total_value_cents"] == 250_000_000, (
            "three seasons of 80000000 plus the bonus is 250000000, got "
            f"{contract['total_value_cents']}"
        )

    def test_seven_year_deal_clamps_the_spread_and_divides_the_bonus_evenly(
        self, league: League
    ) -> None:
        """A seven-season deal is clamped to five seasons before dividing.

        PRD 3.4: "When `years` is at most 5 every contract season carries a share;
        when `years` exceeds 5 the spread is clamped to five seasons, so each
        annual charge is larger than a simple division by `years` would give and
        seasons six onward carry no proration at all."

        Design: Difficulty/combinatorial_formula/signing_bonus_proration_remainder_placement_across_year_counts
        """
        world = self._two_contracts(league)
        contract = world["long_contract"]

        assert contract["proration_years"] == 5, (
            "a seven-year deal is clamped to a five-season spread, got "
            f"{contract['proration_years']}"
        )
        assert contract["annual_proration_cents"] == 2_000_000, (
            "the annual proration should be 2000000, got "
            f"{contract['annual_proration_cents']}"
        )
        assert contract["final_season_proration_cents"] == 2_000_000, (
            "an evenly divisible bonus leaves no remainder, so the final season "
            f"carries 2000000 too, got {contract['final_season_proration_cents']}"
        )
        reconstructed = (
            contract["annual_proration_cents"] * 4
            + contract["final_season_proration_cents"]
        )
        assert reconstructed == 10_000_000, (
            f"the season charges must sum back to the bonus, got {reconstructed}"
        )
        assert contract["current_season_cap_charge_cents"] == 32_000_000, (
            "the current-season charge should be 32000000, got "
            f"{contract['current_season_cap_charge_cents']}"
        )
        assert contract["total_value_cents"] == 220_000_000, (
            "seven seasons of 30000000 plus the bonus is 220000000, got "
            f"{contract['total_value_cents']}"
        )

        club = league.club(world["club"]["id"])
        assert club["provisional_cap_committed_cents"] == 115_333_333, (
            "both pending contracts sit in the provisional total, got "
            f"{club['provisional_cap_committed_cents']}"
        )


class TestWaiverAwardPipelineOrder:
    """The cap filter runs before the ranking step, and the order is visible."""

    @staticmethod
    def _wire_with_two_claims(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        releasing_club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=5,
        )
        top_priority_club = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=50_000_000, waiver_priority_rank=1,
        )
        second_priority_club = league.register_club(
            name="Cedar Ridge", market_code="CDR",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")

        signing = league.sign_onto_roster(
            releasing_club["id"], player["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T20:00:00Z",
            performed_at=CLOCK,
            expected_team_version=releasing_club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        wire = league.release_onto_wire(releasing_club["id"], player["id"])
        top_claim = league.submit_claim(
            wire["waiver_request_id"], top_priority_club["id"]
        )
        second_claim = league.submit_claim(
            wire["waiver_request_id"], second_priority_club["id"]
        )
        league.set_clock("2026-08-11T14:00:00Z")
        return {
            "releasing_club": releasing_club,
            "top_priority_club": top_priority_club,
            "second_priority_club": second_priority_club,
            "player": player,
            "contract_id": signing["contract_id"],
            "waiver_request_id": wire["waiver_request_id"],
            "top_claim": top_claim,
            "second_claim": second_claim,
        }

    def test_rank_one_claim_fails_the_cap_filter_and_rank_two_takes_the_player(
        self, league: League
    ) -> None:
        """Eliminating on cap before ranking hands the player to rank two.

        PRD 3.6: "Because the cap filter runs *before* the ranking step, a rank-1
        claim that fails the cap test is eliminated outright and a rank-9 claim
        wins the player; applying the same three tests after ranking would instead
        award the rank-1 claim and then have to reject the award, so the sequence
        genuinely decides the outcome."

        Design: Difficulty/combinatorial_formula/waiver_award_pipeline_cap_stage_precedes_priority_ranking
        """
        world = self._wire_with_two_claims(league)

        processed = league.process_wire(world["waiver_request_id"])

        assert processed["status"] == "CLAIMED", (
            f"a surviving claim makes the wire CLAIMED, got {processed['status']}"
        )
        assert processed["awarded_to_team_id"] == world["second_priority_club"]["id"], (
            "the rank-2 club should take the player, got "
            f"{processed['awarded_to_team_id']}"
        )
        assert processed["claim_count"] == 2, (
            f"both claims stay counted on the wire, got {processed['claim_count']}"
        )
        assert processed["clearance_deadline_at"] == "2026-08-11T14:00:00.000Z", (
            "a revocable wire placed at 14:00 clears 24 hours later, got "
            f"{processed['clearance_deadline_at']}"
        )

        eliminated = league.claim(world["top_claim"]["id"])
        winner = league.claim(world["second_claim"]["id"])
        assert eliminated["priority_rank_snapshot"] == 1, (
            "the eliminated claim held the best priority, got "
            f"{eliminated['priority_rank_snapshot']}"
        )
        assert eliminated["status"] == "INVALIDATED", (
            "a claim dropped by the cap filter is never ranked, got "
            f"{eliminated['status']}"
        )
        assert eliminated["required_cap_charge_cents"] == 80_000_000, (
            "the charge the claimant would assume is the wired contract's base "
            f"salary, got {eliminated['required_cap_charge_cents']}"
        )
        assert winner["priority_rank_snapshot"] == 2, (
            f"the winner held the second priority, got {winner['priority_rank_snapshot']}"
        )
        assert winner["status"] == "AWARDED", (
            f"the surviving claim should be AWARDED, got {winner['status']}"
        )

    def test_awarded_claim_moves_the_player_and_charges_the_releasing_club(
        self, league: League
    ) -> None:
        """A claimed wire transfers the contract and books dead money at source.

        PRD 3.6: "On the releasing side, `releasing_team_dead_money_cents` is
        charged to `from_team_id` and is the dead-money split applied to the
        **unamortised signing bonus only** — the base salary travels with the
        contract to the claiming club, so the releasing club keeps no base charge —
        after which the releasing club's cap fields and posture are likewise
        recomputed."

        Design: Difficulty/combinatorial_formula/waiver_award_pipeline_cap_stage_precedes_priority_ranking
        """
        world = self._wire_with_two_claims(league)

        processed = league.process_wire(world["waiver_request_id"])

        player = league.player(world["player"]["id"])
        assert player["current_team_id"] == world["second_priority_club"]["id"], (
            f"the player should now belong to the winner, got {player['current_team_id']}"
        )
        assert player["roster_designation"] == "ACTIVE", (
            f"a claimed player becomes ACTIVE at the winner, got {player['roster_designation']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["team_id"] == world["second_priority_club"]["id"], (
            f"the contract should move with the player, got {contract['team_id']}"
        )
        assert contract["status"] == "ACTIVE", (
            f"a claimed contract is not terminated, got {contract['status']}"
        )

        winner = league.club(world["second_priority_club"]["id"])
        assert winner["provisional_cap_committed_cents"] == 83_333_333, (
            "the winner assumes the whole current-season charge, got "
            f"{winner['provisional_cap_committed_cents']}"
        )
        assert winner["active_roster_count"] == 1, (
            f"the winner's active headcount should be 1, got {winner['active_roster_count']}"
        )

        loser = league.club(world["top_priority_club"]["id"])
        assert loser["provisional_cap_committed_cents"] == 0, (
            "the eliminated claimant assumes nothing, got "
            f"{loser['provisional_cap_committed_cents']}"
        )
        assert loser["active_roster_count"] == 0, (
            f"the eliminated claimant gains no player, got {loser['active_roster_count']}"
        )

        assert processed["releasing_team_dead_money_cents"] == 3_333_333, (
            "the releasing club keeps only this season's unamortised bonus share, "
            f"got {processed['releasing_team_dead_money_cents']}"
        )
        releasing_club = league.club(world["releasing_club"]["id"])
        assert_cap_position(
            releasing_club, provisional=3_333_333, final=3_333_333,
            dead_money=3_333_333, cap_space=496_666_667,
        )
