"""Requests that break two rules at once, where only the earlier one is reported."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_CAP_LIMIT_EXCEEDED,
    ERR_INJURY_PAPERWORK_MISSING,
    ERR_OUTSIDE_PROCESSING_WINDOW,
    ERR_PLAYER_FAILED_PHYSICAL,
    ERR_ROSTER_LIMIT_EXCEEDED,
    ERR_TEAM_TRANSACTIONS_FROZEN,
)
from test_helpers.fixtures import League
from test_helpers.test_users import make_cap_analyst_headers

CLOCK = "2026-08-10T14:00:00Z"


class TestFrozenClubBeatsCapExcess:
    """A frozen club never gets as far as the money check."""

    @staticmethod
    def _frozen_club_over_its_cap(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        signed_player = league.register_player(full_name="Ray Alder", position="QB")
        league.sign_onto_roster(
            club["id"], signed_player["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T20:00:00Z",
            performed_at=CLOCK,
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        league.adjust_limits(club["id"], salary_cap_limit_cents=50_000_000)
        league.set_clock("2026-08-11T14:00:00Z")
        league.run_sweep(club["id"])
        league.run_sweep(club["id"])
        newcomer = league.register_player(full_name="Ollie Frame", position="RB")
        frozen = league.club(club["id"])
        return {
            "club": frozen,
            "newcomer": newcomer,
            "frozen_version": frozen["version"],
        }

    def test_frozen_posture_is_reported_instead_of_the_cap_excess(
        self, league: League
    ) -> None:
        """Precedence 15 answers before precedence 37 ever runs.

        PRD 2.8: "because the frozen-club check sits at precedence 15, a club that
        has been frozen sees `ERR_TEAM_TRANSACTIONS_FROZEN` rather than a downstream
        cap or roster error even when both would apply"

        Design: Difficulty/priority_pair_validation_conflict/frozen_club_safety_check_beats_cap_excess_on_filing_creation
        """
        world = self._frozen_club_over_its_cap(league)
        club_id = world["club"]["id"]

        response = league.api.create_transaction(
            fac.signing_payload(
                club_id, world["newcomer"]["id"], world["frozen_version"],
                years=1, base_salary_cents=40_000_000, signing_bonus_cents=0,
                start_season_year=2026,
            ),
            make_cap_analyst_headers(club_id),
        )

        error = validate_error(response, ERR_TEAM_TRANSACTIONS_FROZEN, 409)
        assert error["error_id"] != ERR_CAP_LIMIT_EXCEEDED, (
            "the cap check must not mask the frozen check even though 83333333 "
            "plus 40000000 exceeds a 50000000 limit"
        )

    def test_the_refused_filing_writes_absolutely_nothing(
        self, league: League
    ) -> None:
        """A rejected precondition leaves the club and the ledger alone.

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Difficulty/priority_pair_validation_conflict/frozen_club_safety_check_beats_cap_excess_on_filing_creation
        """
        world = self._frozen_club_over_its_cap(league)
        club_id = world["club"]["id"]

        league.api.create_transaction(
            fac.signing_payload(
                club_id, world["newcomer"]["id"], world["frozen_version"],
                years=1, base_salary_cents=40_000_000, signing_bonus_cents=0,
                start_season_year=2026,
            ),
            make_cap_analyst_headers(club_id),
        )

        filings, filing_meta = validate_paginated(
            league.api.list_transactions(league.officer)
        )
        assert filing_meta["total_count"] == 1, (
            "only the original signing filing should exist, got "
            f"{filing_meta['total_count']}"
        )
        assert len(filings) == 1, f"one filing row should come back, got {len(filings)}"

        club = league.club(club_id)
        assert club["version"] == world["frozen_version"], (
            f"the refused call bumped nothing, got version {club['version']}"
        )
        assert club["compliance_status"] == "TRANSACTION_FROZEN", (
            f"the club is still frozen, got {club['compliance_status']}"
        )
        assert club["consecutive_noncompliant_checks"] == 3, (
            "two sweeps past an armed grace reach the freeze threshold, got "
            f"{club['consecutive_noncompliant_checks']}"
        )
        assert club["provisional_cap_committed_cents"] == 83_333_333, (
            "the provisional total is unchanged, got "
            f"{club['provisional_cap_committed_cents']}"
        )
        assert club["cap_space_cents"] == -33_333_333, (
            "cap space is permitted to go negative, got "
            f"{club['cap_space_cents']}"
        )

        history = league.sweep_history(club_id)
        assert len(history) == 2, f"two sweeps ran, got {len(history)}"
        for row in history:
            assert row["violation_codes"] == ["CAP_OVER_LIMIT"], (
                "the only violation is the cap, got "
                f"{row['violation_codes']}"
            )


class TestFailedPhysicalBeatsMissingPaperwork:
    """An unsafe player is refused before the paperwork is looked at."""

    @staticmethod
    def _placement_with_failed_player(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T14:30:00Z",
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
        second_exam = league.schedule_exam(
            club["id"], player["id"], "ENTRY_PHYSICAL",
            "2026-08-10T15:00:00Z", "2026-08-10T20:00:00Z",
        )
        league.set_clock("2026-08-10T17:00:00Z")
        league.record_exam(
            second_exam["id"], club["id"], "FAILED", "2026-08-10T16:00:00Z"
        )
        return {
            "club": club,
            "player": player,
            "designation_id": designation["id"],
            "placement_id": placement["id"],
        }

    def test_failed_physical_is_reported_instead_of_the_missing_paperwork(
        self, league: League
    ) -> None:
        """Precedence 16 answers before precedence 18 ever runs.

        PRD 2.8: "The subject player's `medical_status` is not `FAILED_PHYSICAL` —
        otherwise `ERR_PLAYER_FAILED_PHYSICAL` (422)."
        PRD 2.8: "and because the medical checks at 16 through 18 sit above every
        temporal and fiscal check, an unsafe or undocumented approval is refused
        before the league ever looks at deadlines or arithmetic."

        Design: Difficulty/priority_pair_validation_conflict/failed_physical_safety_check_beats_missing_ir_paperwork_on_approval
        """
        world = self._placement_with_failed_player(league)

        response = league.api.decide_transaction(
            world["placement_id"], fac.approve_payload(), league.officer
        )

        error = validate_error(response, ERR_PLAYER_FAILED_PHYSICAL, 422)
        assert error["error_id"] != ERR_INJURY_PAPERWORK_MISSING, (
            "the paperwork check must not mask the medical check even though the "
            "cited designation never left PENDING_PAPERWORK"
        )
        designation = league.designation(world["designation_id"])
        assert designation["status"] == "PENDING_PAPERWORK", (
            "the later rule genuinely would have fired, got "
            f"{designation['status']}"
        )

    def test_the_refused_approval_leaves_filing_designation_and_roster_alone(
        self, league: League
    ) -> None:
        """Nothing about the placement advances on a refused approval.

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Difficulty/priority_pair_validation_conflict/failed_physical_safety_check_beats_missing_ir_paperwork_on_approval
        """
        world = self._placement_with_failed_player(league)

        league.api.decide_transaction(
            world["placement_id"], fac.approve_payload(), league.officer
        )

        placement = league.filing(world["placement_id"])
        assert placement["status"] == "FILED", (
            f"the filing should still await a decision, got {placement['status']}"
        )
        assert placement["decided_at"] is None, (
            f"no decision instant should be stamped, got {placement['decided_at']}"
        )

        designation = league.designation(world["designation_id"])
        assert designation["status"] == "PENDING_PAPERWORK", (
            f"the designation should not activate, got {designation['status']}"
        )
        assert designation["activated_at"] is None, (
            f"no activation instant should be stamped, got {designation['activated_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            f"the player stays on the active roster, got {player['roster_designation']}"
        )
        assert player["medical_status"] == "FAILED_PHYSICAL", (
            f"the medical dimension keeps its failure, got {player['medical_status']}"
        )

        club = league.club(world["club"]["id"])
        assert club["injured_reserve_count"] == 0, (
            f"nobody reached injured reserve, got {club['injured_reserve_count']}"
        )
        assert club["active_roster_count"] == 1, (
            f"the active headcount is unchanged, got {club['active_roster_count']}"
        )


class TestProcessingWindowBeatsRosterLimit:
    """A decision taken outside the window is refused before the headcount matters."""

    @staticmethod
    def _filed_signing_against_a_full_roster(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        rostered = league.register_player(full_name="Ray Alder", position="QB")
        newcomer = league.register_player(full_name="Milo Vance", position="WR")
        league.sign_onto_roster(
            club["id"], rostered["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T20:00:00Z",
            performed_at=CLOCK,
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        second_filing = league.open_signing(
            club["id"], newcomer["id"], years=1,
            base_salary_cents=40_000_000, signing_bonus_cents=0,
            start_season_year=2026,
        )
        league.pass_entry_physical(
            club["id"], newcomer["id"], second_filing["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T20:00:00Z",
            performed_at=CLOCK,
        )
        league.submit_filing(second_filing["id"], club["id"])
        league.adjust_limits(club["id"], active_roster_limit=1)
        league.set_clock("2026-08-10T21:00:00Z")
        return {
            "club": club,
            "newcomer": newcomer,
            "filing_id": second_filing["id"],
            "contract_id": second_filing["contract_id"],
        }

    def test_the_window_boundary_is_reported_instead_of_the_roster_limit(
        self, league: League
    ) -> None:
        """Precedence 22 answers before precedence 36 ever runs.

        PRD 2.8: "The logical clock's time of day is inside the half-open processing
        window — otherwise `ERR_OUTSIDE_PROCESSING_WINDOW` (422)."
        PRD 2.8: "Validation is therefore strictly ordered, and **the first rule
        violated decides the response**; no later rule can mask an earlier one."

        Design: Difficulty/priority_pair_validation_conflict/processing_window_temporal_check_beats_roster_limit_on_approval
        """
        world = self._filed_signing_against_a_full_roster(league)

        response = league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(), league.officer
        )

        error = validate_error(response, ERR_OUTSIDE_PROCESSING_WINDOW, 422)
        assert error["error_id"] != ERR_ROSTER_LIMIT_EXCEEDED, (
            "the headcount check must not mask the window check even though "
            "approving would raise the active roster to 2 against a limit of 1"
        )
        club = league.club(world["club"]["id"])
        assert club["active_roster_limit"] == 1, (
            f"the limit really is 1, got {club['active_roster_limit']}"
        )
        assert club["active_roster_count"] == 1, (
            f"the club really is at its limit, got {club['active_roster_count']}"
        )

    def test_the_refused_approval_leaves_the_contract_pending_and_the_player_free(
        self, league: League
    ) -> None:
        """The filing, its contract and the club all stay exactly as they were.

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Difficulty/priority_pair_validation_conflict/processing_window_temporal_check_beats_roster_limit_on_approval
        """
        world = self._filed_signing_against_a_full_roster(league)

        league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(), league.officer
        )

        filing = league.filing(world["filing_id"])
        assert filing["status"] == "FILED", (
            f"the filing should still await a decision, got {filing['status']}"
        )
        assert filing["decided_at"] is None, (
            f"no decision instant should be stamped, got {filing['decided_at']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "PENDING_APPROVAL", (
            f"the contract should still be pending, got {contract['status']}"
        )

        player = league.player(world["newcomer"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the newcomer joined nobody, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"an unrostered player has no club, got {player['current_team_id']}"
        )

        club = league.club(world["club"]["id"])
        assert club["compliance_status"] == "COMPLIANT", (
            "sitting exactly at a limit is not a violation, got "
            f"{club['compliance_status']}"
        )
        assert club["provisional_cap_committed_cents"] == 123_333_333, (
            "the pending contract already sits in the provisional total, got "
            f"{club['provisional_cap_committed_cents']}"
        )
