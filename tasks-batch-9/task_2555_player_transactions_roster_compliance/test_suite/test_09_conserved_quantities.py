"""Quantities that must come back to exactly where they started."""

from typing import Any, Dict

from test_helpers.assertions import assert_cap_position
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"


class TestHeadcountConservedAcrossWaiverWithdrawal:
    """A release and its withdrawal leave no orphaned roster slot."""

    @staticmethod
    def _player_on_the_wire(league: League) -> Dict[str, Any]:
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
        baseline = league.club(club["id"])
        wire = league.release_onto_wire(club["id"], player["id"])
        return {
            "club": club,
            "player": player,
            "baseline": baseline,
            "signing_id": signing["transaction_id"],
            "contract_id": signing["contract_id"],
            "release_id": wire["release_transaction_id"],
            "waiver_request_id": wire["waiver_request_id"],
            "waiver_request": wire["waiver_request"],
        }

    def test_withdrawal_restores_the_player_to_the_origin_designation(
        self, league: League
    ) -> None:
        """The wire is pulled and the player lands back where the release found him.

        PRD 3.6: "A withdrawal moves the wire `PENDING → WITHDRAWN`, stamps
        `processed_at`, restores the player's `roster_designation` from
        `WAIVED_PENDING` back to `origin_designation` with `current_team_id` restored
        to `from_team_id`, increments the releasing club's headcount for that
        designation by 1, re-evaluates the club's posture in event mode, voids the
        authorising `RELEASE` filing `APPROVED → VOIDED`, and moves every
        still-`SUBMITTED` claim on the wire to `INVALIDATED`."

        Design: Difficulty/compensating_invariant/roster_headcount_conserved_on_waiver_withdraw
        """
        world = self._player_on_the_wire(league)

        assert world["baseline"]["active_roster_count"] == 1, (
            "the pre-release baseline holds one active player, got "
            f"{world['baseline']['active_roster_count']}"
        )
        assert world["waiver_request"]["origin_designation"] == "ACTIVE", (
            "the wire records where the player came from, got "
            f"{world['waiver_request']['origin_designation']}"
        )
        assert world["waiver_request"]["clearance_deadline_at"] == (
            "2026-08-11T14:00:00.000Z"
        ), (
            "a revocable wire clears 24 hours out, got "
            f"{world['waiver_request']['clearance_deadline_at']}"
        )

        withdrawn = league.withdraw_wire(
            world["waiver_request_id"], world["club"]["id"]
        )

        assert withdrawn["status"] == "WITHDRAWN", (
            f"the wire should be WITHDRAWN, got {withdrawn['status']}"
        )
        assert withdrawn["processed_at"] == "2026-08-10T14:00:00.000Z", (
            f"the withdrawal is stamped on the clock, got {withdrawn['processed_at']}"
        )
        assert withdrawn["awarded_to_team_id"] is None, (
            f"nobody was awarded the player, got {withdrawn['awarded_to_team_id']}"
        )
        assert withdrawn["claim_count"] == 0, (
            f"no claim was ever submitted, got {withdrawn['claim_count']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            "the player returns to the origin designation, got "
            f"{player['roster_designation']}"
        )
        assert player["current_team_id"] == world["club"]["id"], (
            f"and back to the releasing club, got {player['current_team_id']}"
        )
        assert player["designation_effective_at"] == "2026-08-10T14:00:00.000Z", (
            "the restored designation dates from the clock, got "
            f"{player['designation_effective_at']}"
        )
        assert player["accrued_active_days"] == 0, (
            "no time passed, so no service day accrued, got "
            f"{player['accrued_active_days']}"
        )

        release = league.filing(world["release_id"])
        assert release["status"] == "VOIDED", (
            f"the authorising release is voided, got {release['status']}"
        )
        assert release["effective_at"] is None, (
            "the authorised release never took hold, so its effective instant is "
            f"cleared, got {release['effective_at']}"
        )
        assert league.filing(world["signing_id"])["status"] == "APPROVED", (
            "the original signing is untouched"
        )

    def test_withdrawal_is_fiscally_and_numerically_a_no_op(
        self, league: League
    ) -> None:
        """Every headcount and every cent returns to the pre-release figure.

        PRD 3.6: "`releasing_team_dead_money_cents` stays at 0 and the contract keeps
        its `ACTIVE` status — a withdrawal is fiscally and numerically a no-op, and
        the club's roster headcount ends up exactly where it began before the
        release."

        Design: Difficulty/compensating_invariant/roster_headcount_conserved_on_waiver_withdraw
        """
        world = self._player_on_the_wire(league)

        withdrawn = league.withdraw_wire(
            world["waiver_request_id"], world["club"]["id"]
        )
        assert withdrawn["releasing_team_dead_money_cents"] == 0, (
            "a withdrawal books no dead money, got "
            f"{withdrawn['releasing_team_dead_money_cents']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the contract never lapsed, got {contract['status']}"
        )
        assert contract["current_season_cap_charge_cents"] == 83_333_333, (
            "and still charges its full current-season figure, got "
            f"{contract['current_season_cap_charge_cents']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == world["baseline"]["active_roster_count"], (
            "the active headcount must equal the pre-release baseline of 1, got "
            f"{club['active_roster_count']}"
        )
        assert club["reserve_roster_count"] == 0, (
            f"no reserve slot was created, got {club['reserve_roster_count']}"
        )
        assert club["injured_reserve_count"] == 0, (
            f"no injured-reserve slot either, got {club['injured_reserve_count']}"
        )
        assert club["practice_squad_count"] == 0, (
            f"and no practice-squad slot, got {club['practice_squad_count']}"
        )
        assert_cap_position(
            club, provisional=83_333_333, final=83_333_333,
            dead_money=0, cap_space=416_666_667,
        )
        assert club["compliance_status"] == "COMPLIANT", (
            f"the club is in order throughout, got {club['compliance_status']}"
        )


class TestCapDollarsConservedAcrossRejectionCycles:
    """Two rejection round trips leave no residual cent."""

    @staticmethod
    def _filed_signing_awaiting_a_decision(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"],
            years=3, base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        after_creation = league.club(club["id"])
        league.submit_filing(filing["id"], club["id"])
        return {
            "club": club,
            "player": player,
            "filing_id": filing["id"],
            "contract_id": filing["contract_id"],
            "after_creation": after_creation,
        }

    def test_rejection_returns_the_provisional_total_to_its_pre_creation_value(
        self, league: League
    ) -> None:
        """The commitment the filing created is given back cent for cent.

        PRD 3.3: "The invariant here is exact, not approximate: after a signing
        rejection the club's provisional commitment and cap space return to precisely
        the values they held before the filing was created, cent for cent."

        Design: Difficulty/compensating_invariant/cap_dollars_conserved_on_signing_rejection
        """
        world = self._filed_signing_awaiting_a_decision(league)

        assert_cap_position(
            world["after_creation"], provisional=83_333_333, final=0,
            dead_money=0, cap_space=416_666_667,
        )
        assert league.contract(world["contract_id"])["status"] == (
            "PENDING_APPROVAL"
        ), "the offered contract begins pending approval"

        rejected = league.reject_filing(
            world["filing_id"], "cap certification incomplete"
        )

        assert rejected["status"] == "REJECTED", (
            f"the filing should be REJECTED, got {rejected['status']}"
        )
        assert rejected["rejection_reason"] == "cap certification incomplete", (
            f"the stated reason is stored, got {rejected['rejection_reason']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "VOIDED", (
            f"a rejected signing voids its contract, got {contract['status']}"
        )

        club = league.club(world["club"]["id"])
        assert_cap_position(
            club, provisional=0, final=0, dead_money=0, cap_space=500_000_000,
        )

    def test_a_revise_refile_reject_cycle_leaves_no_residual_cent(
        self, league: League
    ) -> None:
        """The money rises again on revision and falls back again on rejection.

        PRD 3.3: "A revision may amend `target_designation`, `injury_designation_id`,
        `years`, `base_salary_cents`, `base_guaranteed`, `signing_bonus_cents`,
        `option_type`, `option_deadline_at` and `option_salary_cents`; for a
        `SIGNING`, the contract is revived `VOIDED → PENDING_APPROVAL` with the
        amended terms, re-prorated, and the club's provisional total rises again."

        Design: Difficulty/compensating_invariant/cap_dollars_conserved_on_signing_rejection
        """
        world = self._filed_signing_awaiting_a_decision(league)
        league.reject_filing(world["filing_id"], "cap certification incomplete")

        revised = league.revise_filing(world["filing_id"], world["club"]["id"])

        assert revised["status"] == "DRAFT", (
            f"a revision returns the filing to draft, got {revised['status']}"
        )
        assert revised["revision_count"] == 1, (
            f"the first revision is counted, got {revised['revision_count']}"
        )
        assert revised["rejection_reason"] is None, (
            f"the stale reason is cleared, got {revised['rejection_reason']}"
        )
        assert revised["decided_at"] is None, (
            f"and the stale decision instant too, got {revised['decided_at']}"
        )
        assert revised["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            "a revision never buys more time, got "
            f"{revised['filing_deadline_at']}"
        )
        assert league.contract(world["contract_id"])["status"] == (
            "PENDING_APPROVAL"
        ), "the contract is revived by the revision"
        assert_cap_position(
            league.club(world["club"]["id"]), provisional=83_333_333, final=0,
            dead_money=0, cap_space=416_666_667,
        )

        league.submit_filing(world["filing_id"], world["club"]["id"])
        second = league.reject_filing(
            world["filing_id"], "terms still not certified"
        )

        assert second["status"] == "REJECTED", (
            f"the second decision rejects again, got {second['status']}"
        )
        assert second["revision_count"] == 1, (
            "a rejection consumes no revision budget, got "
            f"{second['revision_count']}"
        )
        assert league.contract(world["contract_id"])["status"] == "VOIDED", (
            "the revived contract is voided again"
        )

        club = league.club(world["club"]["id"])
        assert_cap_position(
            club, provisional=0, final=0, dead_money=0, cap_space=500_000_000,
        )
        assert club["active_roster_count"] == 0, (
            f"nobody ever joined the roster, got {club['active_roster_count']}"
        )
        assert club["compliance_status"] == "COMPLIANT", (
            f"the club never broke a rule, got {club['compliance_status']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player is still unrostered, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"and belongs to no club, got {player['current_team_id']}"
        )
        assert player["pension_credit_days"] == 0, (
            f"no service time accrued, got {player['pension_credit_days']}"
        )
