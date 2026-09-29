"""One unit either side of a threshold, and the outcome flips."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as fac
from test_helpers.api_errors import ERR_OUTSIDE_PROCESSING_WINDOW
from test_helpers.assertions import assert_service_profile
from test_helpers.fixtures import League
from test_helpers.test_users import make_cap_analyst_headers

CLOCK = "2026-08-10T14:00:00Z"


class TestServiceYearThreshold:
    """679 pension days and 680 pension days are different careers."""

    @staticmethod
    def _two_players_either_side(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        high = league.register_player(
            full_name="Boundary High", position="DL", accrued_active_days=500,
            accrued_reserve_days=100, accrued_ir_days=80,
            accrued_practice_days=0, practice_squad_seasons_used=0,
        )
        low = league.register_player(
            full_name="Boundary Low", position="DL", accrued_active_days=500,
            accrued_reserve_days=100, accrued_ir_days=79,
            accrued_practice_days=0, practice_squad_seasons_used=0,
        )
        return {"high": high, "low": low}

    def test_six_hundred_and_eighty_pension_days_are_four_service_years(
        self, league: League
    ) -> None:
        """Exactly four whole seasons of credit make the player unrestricted.

        PRD 3.2: "Take a player with 500 active days, 100 reserve days, 80
        injured-reserve days and 200 practice-squad days: pension credit is 680
        days, which is 4 service years, so the rights class is `UNRESTRICTED`;
        roster service is 640 days, so the player is not practice-squad eligible."

        Design: Difficulty/boundary_precision_check/service_year_threshold_at_679_versus_680_pension_days
        """
        world = self._two_players_either_side(league)

        assert_service_profile(
            world["high"], pension_credit_days=680, roster_service_days=640,
            service_years=4, contract_rights_class="UNRESTRICTED",
            practice_squad_eligible=False,
        )

    def test_one_injured_reserve_day_fewer_drops_the_rights_class(
        self, league: League
    ) -> None:
        """679 days is still only three seasons, and the class changes.

        PRD 3.2: "Shift the injured-reserve figure to 79 days and the outcome
        moves: pension credit becomes 679 days, which is still only 3 service
        years, so the rights class drops to `ARBITRATION_ELIGIBLE`, and roster
        service becomes 639 days."

        Design: Difficulty/boundary_precision_check/service_year_threshold_at_679_versus_680_pension_days
        """
        world = self._two_players_either_side(league)

        low = world["low"]
        assert low["pension_credit_days"] == 679, (
            f"one fewer injured-reserve day gives 679, got {low['pension_credit_days']}"
        )
        assert low["service_years"] == 3, (
            f"679 divided by 170 floors to 3, got {low['service_years']}"
        )
        assert low["contract_rights_class"] == "ARBITRATION_ELIGIBLE", (
            f"three service years are arbitration eligible, got {low['contract_rights_class']}"
        )
        assert low["roster_service_days"] == 639, (
            "half of 79 floors to 39 rather than rounding to 40, got "
            f"{low['roster_service_days']}"
        )
        assert (
            low["contract_rights_class"] != world["high"]["contract_rights_class"]
        ), "a single accrued injured-reserve day must change the rights class"


class TestSurvivorSetCardinality:
    """One claim submitted, zero claims surviving: the wire still clears."""

    @staticmethod
    def _wire_with_one_unaffordable_claim(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        releasing_club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=5,
        )
        claiming_club = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=50_000_000, waiver_priority_rank=1,
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
        claim = league.submit_claim(wire["waiver_request_id"], claiming_club["id"])
        league.set_clock("2026-08-11T14:00:00Z")
        return {
            "releasing_club": releasing_club,
            "claiming_club": claiming_club,
            "player": player,
            "contract_id": signing["contract_id"],
            "waiver_request_id": wire["waiver_request_id"],
            "claim_id": claim["id"],
        }

    def test_the_only_claim_is_eliminated_and_the_wire_clears_rather_than_awards(
        self, league: League
    ) -> None:
        """A non-empty candidate set with an empty survivor set takes the clear branch.

        PRD 3.6: "First the **cap filter** drops every claim whose
        `required_cap_charge_cents` is greater than the claiming club's
        `cap_space_cents` *read live at processing time* — not the audit snapshot
        captured at submission."
        PRD 3.6: "If no claim survives the three filters, the wire moves `PENDING →
        CLEARED` instead."

        Design: Difficulty/boundary_precision_check/waiver_survivor_set_empties_only_after_elimination_and_clears
        """
        world = self._wire_with_one_unaffordable_claim(league)

        processed = league.process_wire(world["waiver_request_id"])

        assert processed["status"] == "CLEARED", (
            f"no survivor means the wire clears, got {processed['status']}"
        )
        assert processed["claim_count"] == 1, (
            "the eliminated claim is still counted on the wire, got "
            f"{processed['claim_count']}"
        )
        assert processed["awarded_to_team_id"] is None, (
            f"a cleared wire has no winner, got {processed['awarded_to_team_id']}"
        )

        claim = league.claim(world["claim_id"])
        assert claim["status"] == "INVALIDATED", (
            f"the only claim is dropped by the cap filter, got {claim['status']}"
        )
        assert claim["required_cap_charge_cents"] == 80_000_000, (
            "the charge the claimant would assume is the wired base salary, got "
            f"{claim['required_cap_charge_cents']}"
        )
        assert claim["cap_space_snapshot_cents"] == 50_000_000, (
            "the audit snapshot copies the club's cap space at submission, got "
            f"{claim['cap_space_snapshot_cents']}"
        )

    def test_the_clearance_still_runs_the_full_termination_cascade(
        self, league: League
    ) -> None:
        """Because nobody survived, the player and the contract both fall away.

        PRD 3.6: "`processed_at` is stamped, every `SUBMITTED` claim is moved to
        `INVALIDATED`, the player's `roster_designation` moves `WAIVED_PENDING →
        UNROSTERED` with `current_team_id` set to null, and the contract moves
        `ACTIVE → TERMINATED` with `termination_reason` `RELEASE_CLEARED`, running
        the full acceleration-and-forfeiture cascade of §3.4."

        Design: Difficulty/boundary_precision_check/waiver_survivor_set_empties_only_after_elimination_and_clears
        """
        world = self._wire_with_one_unaffordable_claim(league)

        league.process_wire(world["waiver_request_id"])

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player leaves the roster, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"an unrostered player has no club, got {player['current_team_id']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "TERMINATED", (
            f"the contract should end, got {contract['status']}"
        )
        assert contract["termination_reason"] == "RELEASE_CLEARED", (
            f"the reason should name the clearance, got {contract['termination_reason']}"
        )

        claimant = league.club(world["claiming_club"]["id"])
        assert claimant["provisional_cap_committed_cents"] == 0, (
            "the eliminated claimant took on nothing, got "
            f"{claimant['provisional_cap_committed_cents']}"
        )
        assert claimant["active_roster_count"] == 0, (
            f"the eliminated claimant gained nobody, got {claimant['active_roster_count']}"
        )

        releasing_club = league.club(world["releasing_club"]["id"])
        assert releasing_club["dead_money_cents"] == 3_333_333, (
            "the releasing club books this season's unamortised share, got "
            f"{releasing_club['dead_money_cents']}"
        )


class TestProcessingWindowCloseBoundary:
    """20:59:59Z is inside the office hours; 21:00:00Z is not."""

    @staticmethod
    def _two_drafts_one_second_before_close(league: League) -> Dict[str, Any]:
        league.set_clock("2026-08-10T20:59:59Z")
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        first_player = league.register_player(full_name="Ray Alder", position="QB")
        second_player = league.register_player(full_name="Milo Vance", position="WR")
        third_player = league.register_player(full_name="Ollie Frame", position="RB")
        first_filing = league.open_signing(
            club["id"], first_player["id"],
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        second_filing = league.open_signing(
            club["id"], second_player["id"], years=1,
            base_salary_cents=40_000_000, signing_bonus_cents=0,
            start_season_year=2026,
        )
        return {
            "club": club,
            "third_player": third_player,
            "first_filing": first_filing,
            "second_filing": second_filing,
        }

    def test_a_filing_one_second_before_the_close_is_inside_the_window(
        self, league: League
    ) -> None:
        """The half-open window still admits 20:59:59Z, and 48 hours later needs no snap.

        PRD 2.5: "The interval is half-open: an operation attempted at exactly
        13:00:00 UTC is inside the window, and an operation attempted at exactly
        21:00:00 UTC is outside it."
        PRD 3.3: "And `filing_deadline_at` is fixed once, at creation, and never
        recomputed: it is the filing's `created_at` plus 48 hours, snapped into the
        daily processing window per §2.5."

        Design: Difficulty/boundary_precision_check/processing_window_close_excludes_2100z_and_snaps_next_deadline
        """
        world = self._two_drafts_one_second_before_close(league)

        assert world["first_filing"]["filing_deadline_at"] == (
            "2026-08-12T20:59:59.000Z"
        ), (
            "a raw deadline whose time of day is still inside the window is kept "
            f"unchanged, got {world['first_filing']['filing_deadline_at']}"
        )

        filed = league.submit_filing(
            world["first_filing"]["id"], world["club"]["id"]
        )
        assert filed["status"] == "FILED", (
            f"filing one second before the close succeeds, got {filed['status']}"
        )
        assert filed["filed_at"] == "2026-08-10T20:59:59.000Z", (
            f"the submission instant is the logical clock, got {filed['filed_at']}"
        )

    def test_the_close_instant_itself_refuses_the_filing_and_snaps_a_new_deadline(
        self, league: League
    ) -> None:
        """At exactly 21:00:00Z the office is shut and new deadlines jump a day.

        PRD 2.5: "if its time of day is 13:00:00 or later but earlier than 21:00:00,
        the raw instant is kept unchanged; otherwise — that is, at 21:00:00 or later
        — the deadline becomes 13:00:00 UTC on the following calendar date."

        Design: Difficulty/boundary_precision_check/processing_window_close_excludes_2100z_and_snaps_next_deadline
        """
        world = self._two_drafts_one_second_before_close(league)
        league.set_clock("2026-08-10T21:00:00Z")

        response = league.api.file_transaction(
            world["second_filing"]["id"],
            make_cap_analyst_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_OUTSIDE_PROCESSING_WINDOW, 422)

        blocked = league.filing(world["second_filing"]["id"])
        assert blocked["status"] == "DRAFT", (
            f"the refused filing stays a draft, got {blocked['status']}"
        )
        assert blocked["filed_at"] is None, (
            f"no submission instant should be stamped, got {blocked['filed_at']}"
        )

        third_filing = league.open_filing(
            fac.signing_payload(
                world["club"]["id"], world["third_player"]["id"],
                league.version_of(world["club"]["id"]), years=1,
                base_salary_cents=40_000_000, signing_bonus_cents=0,
                start_season_year=2026,
            ),
            world["club"]["id"],
        )
        assert third_filing["filing_deadline_at"] == "2026-08-13T13:00:00.000Z", (
            "a raw deadline of 2026-08-12T21:00:00Z sits at the exclusive close, so "
            f"it snaps to the next date's open, got {third_filing['filing_deadline_at']}"
        )
        assert third_filing["status"] == "DRAFT", (
            f"a new filing is born a draft, got {third_filing['status']}"
        )
