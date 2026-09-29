"""State machines that do not run in a straight line: parallel and cyclic."""

from typing import Any, Dict

from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"


class TestPlayerDimensionsAdvanceIndependently:
    """The roster dimension and the medical dimension never move together."""

    @staticmethod
    def _player_awaiting_ir_placement(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T20:00:00Z",
            performed_at=CLOCK,
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        designation = league.open_injury_designation(
            club["id"], player["id"], "INJURED_RESERVE"
        )
        placement = league.open_ir_placement(
            club["id"], player["id"], designation["id"]
        )
        league.submit_filing(placement["id"], club["id"])
        return {
            "club": club,
            "player": player,
            "contract_id": signing["contract_id"],
            "designation_id": designation["id"],
            "placement_id": placement["id"],
        }

    def test_filing_paperwork_moves_only_the_medical_dimension(
        self, league: League
    ) -> None:
        """Paperwork puts the player in rehab and leaves him on the active roster.

        PRD 3.5: "The server stamps `paperwork_filed_at` with the logical clock
        and, in the same write, moves the player's `medical_status` `CLEARED →
        REHAB`."
        PRD 3.2: "`medical_status` is dimension B, moving through `CLEARED`,
        `PHYSICAL_PENDING`, `REHAB` and `FAILED_PHYSICAL`; it advances on
        examination and injury-paperwork events that have nothing to do with
        dimension A."

        Design: Difficulty/non_linear_state_machine/player_roster_and_medical_dimensions_advance_independently
        """
        world = self._player_awaiting_ir_placement(league)

        league.file_paperwork(
            world["designation_id"], world["club"]["id"], "IR-2026-0001"
        )

        player = league.player(world["player"]["id"])
        assert player["medical_status"] == "REHAB", (
            f"paperwork should move the medical dimension, got {player['medical_status']}"
        )
        assert player["roster_designation"] == "ACTIVE", (
            "the roster dimension must not move on a paperwork event, got "
            f"{player['roster_designation']}"
        )

        designation = league.designation(world["designation_id"])
        assert designation["status"] == "PAPERWORK_FILED", (
            f"the designation should be PAPERWORK_FILED, got {designation['status']}"
        )
        assert designation["paperwork_filed_at"] == "2026-08-10T14:00:00.000Z", (
            "the filing instant is the logical clock, got "
            f"{designation['paperwork_filed_at']}"
        )
        assert designation["activated_at"] is None, (
            "the designation is not activated by paperwork alone, got "
            f"{designation['activated_at']}"
        )

    def test_placement_approval_moves_only_the_roster_dimension(
        self, league: League
    ) -> None:
        """The approved placement moves the roster dimension and leaves rehab intact.

        PRD 3.3: "**`IR_PLACEMENT`**: the player's designation becomes
        `INJURED_RESERVE`; the cited designation moves `PAPERWORK_FILED → ACTIVE`
        with `activated_at` set to the logical clock; and its
        `return_window_opens_at` and `return_window_closes_at` are computed."
        PRD 3.5: "At that moment `activated_at` is stamped with the logical clock
        and the return window is derived: `return_window_opens_at` is
        `activated_at` plus `minimum_stay_days` days, and
        `return_window_closes_at` is `return_window_opens_at` plus a further 21
        days."

        Design: Difficulty/non_linear_state_machine/player_roster_and_medical_dimensions_advance_independently
        """
        world = self._player_awaiting_ir_placement(league)
        league.file_paperwork(
            world["designation_id"], world["club"]["id"], "IR-2026-0001"
        )

        approved = league.approve_filing(world["placement_id"])

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "INJURED_RESERVE", (
            "the approval should move the roster dimension, got "
            f"{player['roster_designation']}"
        )
        assert player["medical_status"] == "REHAB", (
            "the designation move must not reset the medical dimension, got "
            f"{player['medical_status']}"
        )
        assert approved["prior_designation"] == "ACTIVE", (
            "the filing snapshots the designation held before the side effects, "
            f"got {approved['prior_designation']}"
        )

        designation = league.designation(world["designation_id"])
        assert designation["status"] == "ACTIVE", (
            f"the designation should now be ACTIVE, got {designation['status']}"
        )
        assert designation["minimum_stay_days"] == 21, (
            "an injured-reserve designation carries a 21-day minimum stay, got "
            f"{designation['minimum_stay_days']}"
        )
        assert designation["activated_at"] == "2026-08-10T14:00:00.000Z", (
            f"activation stamps the clock, got {designation['activated_at']}"
        )
        assert designation["return_window_opens_at"] == "2026-08-31T14:00:00.000Z", (
            "21 days after activation the window opens, got "
            f"{designation['return_window_opens_at']}"
        )
        assert designation["return_window_closes_at"] == "2026-09-21T14:00:00.000Z", (
            "a further 21 days later it closes, got "
            f"{designation['return_window_closes_at']}"
        )

        club = league.club(world["club"]["id"])
        assert club["injured_reserve_count"] == 1, (
            f"the club's injured-reserve headcount should be 1, got {club['injured_reserve_count']}"
        )
        assert club["active_roster_count"] == 0, (
            f"the active headcount should have emptied, got {club['active_roster_count']}"
        )
        assert club["provisional_cap_committed_cents"] == 83_333_333, (
            "an injured-reserve player still costs his full charge, got "
            f"{club['provisional_cap_committed_cents']}"
        )
        assert club["compliance_status"] == "COMPLIANT", (
            f"nothing here breaks a limit, got {club['compliance_status']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the contract is untouched by the placement, got {contract['status']}"
        )


class TestTradeCounterCycle:
    """The same counter call loops the trade, then kills it."""

    @staticmethod
    def _trade_with_one_pick(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        initiator = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        counterparty = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        trade = league.build_trade(initiator["id"], counterparty["id"], "NONE")
        asset = league.offer_draft_pick(
            trade["id"], initiator["id"], "TO_COUNTERPARTY",
            expected_trade_version=trade["version"],
            draft_pick_year=2028, draft_pick_round=3,
        )
        return {
            "initiator": initiator,
            "counterparty": counterparty,
            "trade_id": trade["id"],
            "asset_id": asset["id"],
        }

    def test_two_counters_return_the_trade_to_proposed_with_a_higher_round_count(
        self, league: League
    ) -> None:
        """The cycle revisits PROPOSED but the round counter has moved on.

        PRD 3.7: "From `PROPOSED`, only the counterparty club may counter, moving
        the trade `PROPOSED → COUNTERED`; from `COUNTERED`, only the initiating
        club may counter back, moving it `COUNTERED → PROPOSED` and closing the
        cycle."

        Design: Difficulty/non_linear_state_machine/trade_counter_cycle_alternates_sides_then_voids_at_round_budget
        """
        world = self._trade_with_one_pick(league)

        first = league.counter(world["trade_id"], world["counterparty"]["id"])
        assert first["status"] == "COUNTERED", (
            f"the counterparty's counter should reach COUNTERED, got {first['status']}"
        )
        assert first["round_count"] == 2, (
            f"the first counter takes the round count to 2, got {first['round_count']}"
        )

        second = league.counter(world["trade_id"], world["initiator"]["id"])
        assert second["status"] == "PROPOSED", (
            "the initiator's counter closes the cycle back at PROPOSED, got "
            f"{second['status']}"
        )
        assert second["round_count"] == 3, (
            "the cycle returned to its earlier state with a higher counter, got "
            f"{second['round_count']}"
        )
        assert second["void_reason"] is None, (
            f"the trade is still alive at the budget, got {second['void_reason']}"
        )

    def test_the_third_counter_voids_the_trade_and_returns_its_assets(
        self, league: League
    ) -> None:
        """Once the budget is spent the identical call has a different target.

        PRD 3.7: "Once `round_count` has reached 3, a counter — by the counterparty
        from `PROPOSED`, or by the initiator from `COUNTERED`, symmetrically on both
        edges — instead moves the trade to `VOIDED` with `void_reason`
        `ROUND_LIMIT_EXCEEDED`, still increments `round_count`, and moves every
        `PROPOSED` asset to `RETURNED`."

        Design: Difficulty/non_linear_state_machine/trade_counter_cycle_alternates_sides_then_voids_at_round_budget
        """
        world = self._trade_with_one_pick(league)
        league.counter(world["trade_id"], world["counterparty"]["id"])
        league.counter(world["trade_id"], world["initiator"]["id"])

        voided = league.counter(world["trade_id"], world["counterparty"]["id"])

        assert voided["status"] == "VOIDED", (
            f"the third counter should void the trade, got {voided['status']}"
        )
        assert voided["void_reason"] == "ROUND_LIMIT_EXCEEDED", (
            f"the void reason should name the round budget, got {voided['void_reason']}"
        )
        assert voided["round_count"] == 4, (
            f"the voiding counter still increments the count, got {voided['round_count']}"
        )
        assert voided["version"] == 5, (
            "one creation, one asset addition and three counters each bumped the "
            f"version, got {voided['version']}"
        )
        assert voided["accepted_at"] is None, (
            f"a voided trade was never accepted, got {voided['accepted_at']}"
        )
        assert voided["executed_at"] is None, (
            f"a voided trade was never executed, got {voided['executed_at']}"
        )
        assert voided["cap_delta_initiating_cents"] == 0, (
            "a returned draft pick contributes nothing, got "
            f"{voided['cap_delta_initiating_cents']}"
        )
        assert voided["cap_delta_counterparty_cents"] == 0, (
            "the mirrored delta is zero too, got "
            f"{voided['cap_delta_counterparty_cents']}"
        )

        assets = league.trade_assets(world["trade_id"])
        assert len(assets) == 1, f"the trade carried one asset, got {len(assets)}"
        assert assets[0]["status"] == "RETURNED", (
            f"the void should return the asset, got {assets[0]['status']}"
        )
