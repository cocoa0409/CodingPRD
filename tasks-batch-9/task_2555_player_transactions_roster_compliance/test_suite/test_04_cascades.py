"""Single calls whose consequences run several links deep."""

from typing import Any, Dict

from test_helpers.assertions import assert_cap_position, assert_posture
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"


class TestWaiverClearanceCascade:
    """Clearing a wire with no claims runs a five-link chain."""

    @staticmethod
    def _unclaimed_wire_at_clearance(league: League) -> Dict[str, Any]:
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
        wire = league.release_onto_wire(club["id"], player["id"])
        league.set_clock("2026-08-11T14:00:00Z")
        return {
            "club": club,
            "player": player,
            "contract_id": signing["contract_id"],
            "waiver_request_id": wire["waiver_request_id"],
        }

    def test_empty_claim_set_clears_the_wire_and_terminates_the_contract(
        self, league: League
    ) -> None:
        """Links one and two: the wire clears, so the contract ends.

        PRD 3.6: "If no claim survives the three filters, the wire moves `PENDING →
        CLEARED` instead. `processed_at` is stamped, every `SUBMITTED` claim is
        moved to `INVALIDATED`, the player's `roster_designation` moves
        `WAIVED_PENDING → UNROSTERED` with `current_team_id` set to null, and the
        contract moves `ACTIVE → TERMINATED` with `termination_reason`
        `RELEASE_CLEARED`, running the full acceleration-and-forfeiture cascade of
        §3.4."

        Design: Difficulty/transitive_cascade/waiver_clearance_cascade_terminates_contract_and_books_dead_money
        """
        world = self._unclaimed_wire_at_clearance(league)

        processed = league.process_wire(world["waiver_request_id"])

        assert processed["status"] == "CLEARED", (
            f"an unclaimed wire clears, got {processed['status']}"
        )
        assert processed["claim_count"] == 0, (
            f"nobody claimed the player, got {processed['claim_count']}"
        )
        assert processed["processed_at"] == "2026-08-11T14:00:00.000Z", (
            f"processing stamps the logical clock, got {processed['processed_at']}"
        )
        assert processed["awarded_to_team_id"] is None, (
            f"a cleared wire has no winner, got {processed['awarded_to_team_id']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "TERMINATED", (
            f"the clearance should end the contract, got {contract['status']}"
        )
        assert contract["termination_reason"] == "RELEASE_CLEARED", (
            f"the reason should name the clearance, got {contract['termination_reason']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player leaves the roster entirely, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"an unrostered player has no club, got {player['current_team_id']}"
        )

    def test_termination_accelerates_the_proration_rows_and_rewrites_the_posture(
        self, league: League
    ) -> None:
        """Links three, four and five: the bonus accelerates and the club is re-scored.

        PRD 3.4: "Every unamortised `SIGNING_PRORATION` row — the current season's
        row and every later one, that is every such row whose `season_year` is 2026
        or beyond — moves `SCHEDULED → ACCELERATED`, meaning it stops counting as a
        live cap charge and its money is folded into the dead-money split below."
        PRD 3.4: "If the release instant is strictly earlier than the cutoff, the
        current season keeps only its own share: `dead_money_current_season_cents`
        is `annual_proration_cents` and `dead_money_next_season_cents` is the
        unamortised balance less `annual_proration_cents`."

        Design: Difficulty/transitive_cascade/waiver_clearance_cascade_terminates_contract_and_books_dead_money
        """
        world = self._unclaimed_wire_at_clearance(league)

        processed = league.process_wire(world["waiver_request_id"])

        contract = league.contract(world["contract_id"])
        assert contract["dead_money_current_season_cents"] == 3_333_333, (
            "a release before the acceleration cutoff keeps only this season's "
            f"share, got {contract['dead_money_current_season_cents']}"
        )
        assert contract["dead_money_next_season_cents"] == 6_666_667, (
            "the rest of the unamortised balance falls into next season, got "
            f"{contract['dead_money_next_season_cents']}"
        )

        rows = league.allocations(world["contract_id"])
        proration_rows = [
            row for row in rows if row["bonus_type"] == "SIGNING_PRORATION"
        ]
        assert len(proration_rows) == 3, (
            f"a three-year deal has three proration rows, got {len(proration_rows)}"
        )
        assert [row["allocation_status"] for row in proration_rows] == [
            "ACCELERATED", "ACCELERATED", "ACCELERATED",
        ], (
            "every unamortised proration row should accelerate, got "
            f"{[row['allocation_status'] for row in proration_rows]}"
        )

        assert processed["releasing_team_dead_money_cents"] == 3_333_333, (
            "the wire records what the releasing club is charged, got "
            f"{processed['releasing_team_dead_money_cents']}"
        )

        club = league.club(world["club"]["id"])
        assert_cap_position(
            club, provisional=3_333_333, final=3_333_333,
            dead_money=3_333_333, cap_space=496_666_667,
        )
        assert_posture(club, "COMPLIANT", 0)
        assert club["active_roster_count"] == 0, (
            f"the club's active headcount empties, got {club['active_roster_count']}"
        )


class TestFailedTradePhysicalCascade:
    """One failed examination unwinds a whole trade."""

    @staticmethod
    def _trade_in_medical_review(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        initiator = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        counterparty = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            initiator["id"], player["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T14:30:00Z",
            performed_at=CLOCK,
            expected_team_version=initiator["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        trade = league.build_trade(
            initiator["id"], counterparty["id"], "PHYSICAL_CONTINGENT",
            condition_note="Deal void unless the acquiring club's physical is passed.",
        )
        asset = league.offer_contract(
            trade["id"], initiator["id"], signing["contract_id"], "TO_COUNTERPARTY",
            expected_trade_version=trade["version"],
        )
        league.accept_trade(trade["id"], counterparty["id"])
        exam = league.schedule_exam(
            counterparty["id"], player["id"], "TRADE_PHYSICAL",
            "2026-08-10T13:00:00Z", "2026-08-10T20:00:00Z",
            trade_id=trade["id"],
        )
        league.set_clock("2026-08-10T16:00:00Z")
        return {
            "initiator": initiator,
            "counterparty": counterparty,
            "player": player,
            "contract_id": signing["contract_id"],
            "trade_id": trade["id"],
            "asset_id": asset["id"],
            "exam_id": exam["id"],
        }

    def test_failed_trade_physical_voids_the_trade_and_returns_the_contract_asset(
        self, league: League
    ) -> None:
        """Links one to three: the failure reaches the trade and then its assets.

        PRD 3.5: "When the failed exam was a `TRADE_PHYSICAL`, the failure cascades
        through three further steps in order: the linked trade moves `MEDICAL_REVIEW
        → VOIDED` with `void_reason` `FAILED_PHYSICAL`; every one of that trade's
        assets moves `PROPOSED → RETURNED`; and because the medical-review interval
        is thereby released, both clubs' `open_medical_review_count` is decremented
        by 1."

        Design: Difficulty/transitive_cascade/failed_trade_physical_cascade_voids_trade_and_returns_assets
        """
        world = self._trade_in_medical_review(league)

        league.record_exam(
            world["exam_id"], world["counterparty"]["id"], "FAILED",
            "2026-08-10T15:00:00Z",
        )

        exam = league.exam(world["exam_id"])
        assert exam["status"] == "FAILED", (
            f"the recorded failure should fail the exam, got {exam['status']}"
        )
        assert exam["result_recorded_at"] == "2026-08-10T16:00:00.000Z", (
            "the recording instant is the logical clock, not the performance "
            f"instant, got {exam['result_recorded_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["medical_status"] == "FAILED_PHYSICAL", (
            f"the player's medical dimension should fail, got {player['medical_status']}"
        )

        trade = league.trade(world["trade_id"])
        assert trade["status"] == "VOIDED", (
            f"the contingent trade should void, got {trade['status']}"
        )
        assert trade["void_reason"] == "FAILED_PHYSICAL", (
            f"the void reason should name the physical, got {trade['void_reason']}"
        )
        assert trade["executed_at"] is None, (
            f"a voided trade never executes, got {trade['executed_at']}"
        )

        assets = league.trade_assets(world["trade_id"])
        assert assets[0]["status"] == "RETURNED", (
            f"the contract asset should be returned, got {assets[0]['status']}"
        )

    def test_returned_asset_leaves_the_contract_and_both_clubs_where_they_were(
        self, league: League
    ) -> None:
        """Links three and four: nothing moved, and both review slots reopen.

        PRD 3.7: "All three void paths move every `PROPOSED` asset to `RETURNED`,
        and the two medical-review paths additionally decrement both clubs'
        `open_medical_review_count` by 1. A returned asset changes no contract and
        no player — it never moved."

        Design: Difficulty/transitive_cascade/failed_trade_physical_cascade_voids_trade_and_returns_assets
        """
        world = self._trade_in_medical_review(league)

        league.record_exam(
            world["exam_id"], world["counterparty"]["id"], "FAILED",
            "2026-08-10T15:00:00Z",
        )

        contract = league.contract(world["contract_id"])
        assert contract["team_id"] == world["initiator"]["id"], (
            f"the contract never changed hands, got {contract['team_id']}"
        )
        player = league.player(world["player"]["id"])
        assert player["current_team_id"] == world["initiator"]["id"], (
            f"the player never changed hands, got {player['current_team_id']}"
        )
        assert player["roster_designation"] == "ACTIVE", (
            "the medical failure did not move the roster dimension, got "
            f"{player['roster_designation']}"
        )

        sender = league.club(world["initiator"]["id"])
        receiver = league.club(world["counterparty"]["id"])
        assert sender["open_medical_review_count"] == 0, (
            "the sending club's review slot should reopen, got "
            f"{sender['open_medical_review_count']}"
        )
        assert receiver["open_medical_review_count"] == 0, (
            "the receiving club's review slot should reopen, got "
            f"{receiver['open_medical_review_count']}"
        )
        assert sender["provisional_cap_committed_cents"] == 83_333_333, (
            "the sending club keeps the whole charge, got "
            f"{sender['provisional_cap_committed_cents']}"
        )
        assert receiver["provisional_cap_committed_cents"] == 0, (
            "the receiving club takes on nothing, got "
            f"{receiver['provisional_cap_committed_cents']}"
        )
        assert sender["active_roster_count"] == 1, (
            f"the sending club keeps its player, got {sender['active_roster_count']}"
        )
        assert receiver["active_roster_count"] == 0, (
            f"the receiving club gains nobody, got {receiver['active_roster_count']}"
        )
