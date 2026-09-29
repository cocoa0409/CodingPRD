"""Ordered admission checks: the gate that passes and the gates that fire."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_FILING_DEADLINE_PASSED,
    ERR_PRACTICE_SQUAD_INELIGIBLE,
    ERR_REVISION_LIMIT_EXCEEDED,
    ERR_ROSTER_LIMIT_EXCEEDED,
)
from test_helpers.assertions import (
    assert_cap_position,
    assert_designation_counts,
    assert_posture,
)
from test_helpers.fixtures import League
from test_helpers.test_users import LEAGUE_OFFICER_USER_ID

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"


def _club(league: League, **overrides: Any) -> Dict[str, Any]:
    """Register one club with the standard cap unless the caller says otherwise."""
    league.set_clock(CLOCK)
    return league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        **overrides,
    )


class TestEveryGateSatisfied:
    """The one approval where none of the ordered checks fires."""

    def test_a_clean_signing_approval_delivers_its_whole_effect_set(
        self, league: League
    ) -> None:
        """One request moves the filing, the contract, the player and the club.

        PRD 3.3: "Once those hold, the approval writes: `status` becomes
        `APPROVED`; `decided_at` and `effective_at` are both set to the logical
        clock; `decided_by_user_id` records the deciding officer; and
        `prior_designation` snapshots the player's `roster_designation` as observed
        immediately *before* the designation side effects below run."
        PRD 3.3: "- **`SIGNING`**: the linked contract moves `PENDING_APPROVAL →
        ACTIVE`; its bonus allocation rows are created; `option_status` becomes
        `PENDING` when the contract carries an option and stays `NOT_APPLICABLE`
        otherwise; the player's designation becomes `PRACTICE_SQUAD` for a
        practice-squad contract and `ACTIVE` otherwise; and `current_team_id`
        becomes the filing club."

        Design: Corner/validations/signing_approval_with_every_gate_satisfied_applies_the_full_effect_set
        """
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"],
            years=3, base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        league.pass_entry_physical(
            club["id"], player["id"], filing["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
        )
        league.submit_filing(filing["id"], club["id"])

        approved = league.approve_filing(filing["id"])

        assert approved["status"] == "APPROVED", (
            f"the filing should be APPROVED, got {approved['status']}"
        )
        assert approved["decided_at"] == "2026-08-10T14:00:00.000Z", (
            f"the decision instant is the logical clock, got {approved['decided_at']}"
        )
        assert approved["effective_at"] == "2026-08-10T14:00:00.000Z", (
            "the approval takes effect on the same clock, got "
            f"{approved['effective_at']}"
        )
        assert approved["decided_by_user_id"] == LEAGUE_OFFICER_USER_ID, (
            "the deciding officer should be recorded, got "
            f"{approved['decided_by_user_id']}"
        )
        assert approved["prior_designation"] == "UNROSTERED", (
            "the snapshot is taken before the cascade, so a free agent reads "
            f"UNROSTERED, got {approved['prior_designation']}"
        )
        assert approved["rejection_reason"] is None, (
            f"an approval stores no reason, got {approved['rejection_reason']}"
        )

        contract = league.contract(filing["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the offered contract should now be ACTIVE, got {contract['status']}"
        )
        assert contract["option_status"] == "NOT_APPLICABLE", (
            "a contract without an option carries no option status, got "
            f"{contract['option_status']}"
        )
        assert contract["current_season_cap_charge_cents"] == 83_333_333, (
            "the current-season charge is unchanged by approval, got "
            f"{contract['current_season_cap_charge_cents']}"
        )

        rostered = league.player(player["id"])
        assert rostered["roster_designation"] == "ACTIVE", (
            "a non-practice-squad signing lands the player on the active roster, "
            f"got {rostered['roster_designation']}"
        )
        assert rostered["current_team_id"] == club["id"], (
            f"the player should now belong to the filing club, got {rostered['current_team_id']}"
        )
        assert rostered["medical_status"] == "CLEARED", (
            f"the passed entry physical leaves the player CLEARED, got {rostered['medical_status']}"
        )
        assert rostered["designation_effective_at"] == "2026-08-10T14:00:00.000Z", (
            "the new designation is dated from the approval, got "
            f"{rostered['designation_effective_at']}"
        )

    def test_the_same_approval_writes_the_ledger_and_leaves_the_club_compliant(
        self, league: League
    ) -> None:
        """The amortisation rows appear and both cap totals move together.

        PRD 3.4: "One `SIGNING_PRORATION` row is created per prorated season,
        carrying `annual_proration_cents` except for the final prorated season,
        which carries `final_season_proration_cents`; the flag on these rows is
        false, because that money already lives inside the contract's current-season
        charge and these rows exist only as the amortisation ledger that dead-money
        acceleration later consumes."
        PRD 3.4: "Every row is born `SCHEDULED`."
        PRD 3.3: "Finally the club's four headcounts, both cap totals,
        `dead_money_cents` and `cap_space_cents` are recomputed, the club's
        compliance posture is re-evaluated in event mode — where a fresh violation
        may move the club from `COMPLIANT` to `GRACE` but can never freeze it — and
        the club's `version` is incremented."

        Design: Corner/validations/signing_approval_with_every_gate_satisfied_applies_the_full_effect_set
        """
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"],
            years=3, base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        league.pass_entry_physical(
            club["id"], player["id"], filing["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
        )
        league.submit_filing(filing["id"], club["id"])
        league.approve_filing(filing["id"])

        rows = league.allocations(filing["contract_id"])
        assert len(rows) == 3, (
            "a three-season spread with no performance money gives three rows, got "
            f"{[row['bonus_type'] for row in rows]}"
        )
        assert [row["amount_cents"] for row in rows] == [
            3_333_333, 3_333_333, 3_333_334
        ], (
            "the amortisation ledger carries the annual share twice and the "
            f"final-season share once, got {[row['amount_cents'] for row in rows]}"
        )
        for index, row in enumerate(rows):
            assert row["bonus_type"] == "SIGNING_PRORATION", (
                f"row {index} should be a proration row, got {row['bonus_type']}"
            )
            assert row["allocation_status"] == "SCHEDULED", (
                f"row {index} should be born SCHEDULED, got {row['allocation_status']}"
            )
            assert row["counts_against_provisional"] is False, (
                f"row {index} must not double-count against the provisional total"
            )
        assert [row["season_year"] for row in rows] == [2026, 2027, 2028], (
            "the rows are charged against consecutive seasons, got "
            f"{[row['season_year'] for row in rows]}"
        )

        settled = league.club(club["id"])
        assert_designation_counts(
            settled, active=1, reserve=0, injured_reserve=0, practice_squad=0
        )
        assert_cap_position(
            settled, provisional=83_333_333, final=83_333_333,
            dead_money=0, cap_space=416_666_667,
        )
        assert_posture(settled, "COMPLIANT", 0)


class TestFilingDeadlineIsInclusive:
    """The deadline instant is on time; one second later it is not."""

    @staticmethod
    def _two_drafts(league: League) -> Dict[str, Any]:
        club = _club(league)
        on_time_player = league.register_player(full_name="Ray Alder", position="QB")
        late_player = league.register_player(full_name="Dane Cole", position="OL")
        on_time = league.open_signing(
            club["id"], on_time_player["id"],
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        late = league.open_signing(
            club["id"], late_player["id"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        return {"club": club, "on_time": on_time, "late": late,
                "late_player": late_player}

    def test_submission_at_exactly_the_deadline_is_still_on_time(
        self, league: League
    ) -> None:
        """A clock equal to the deadline passes the check and files the filing.

        PRD 3.3: "And `filing_deadline_at` is fixed once, at creation, and never
        recomputed: it is the filing's `created_at` plus 48 hours, snapped into the
        daily processing window per §2.5."
        PRD 3.3: "It may be performed only by the filing club's own analyst, only
        while the club is not frozen, only inside the daily processing window, and
        only while the logical clock is at or before `filing_deadline_at` — the
        deadline instant itself is still on time, and only a clock strictly later
        than the deadline is late, at which point the answer is
        `ERR_FILING_DEADLINE_PASSED`."

        Design: Corner/validations/filing_at_exactly_its_deadline_passes_and_one_second_later_is_refused
        """
        world = self._two_drafts(league)

        assert world["on_time"]["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            "48 hours after an in-window creation needs no snap, got "
            f"{world['on_time']['filing_deadline_at']}"
        )
        assert world["late"]["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            "both filings were created at the same instant, got "
            f"{world['late']['filing_deadline_at']}"
        )

        league.set_clock("2026-08-12T14:00:00Z")
        filed = league.submit_filing(world["on_time"]["id"], world["club"]["id"])

        assert filed["status"] == "FILED", (
            f"the deadline instant is on time, got {filed['status']}"
        )
        assert filed["filed_at"] == "2026-08-12T14:00:00.000Z", (
            f"the submission instant is the logical clock, got {filed['filed_at']}"
        )
        assert filed["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            "submission never recomputes the deadline, got "
            f"{filed['filing_deadline_at']}"
        )

    def test_submission_one_second_after_the_deadline_is_refused(
        self, league: League
    ) -> None:
        """A clock strictly past the deadline fails and writes nothing.

        PRD 2.8: "23. The logical clock is no later than the filing's
        `filing_deadline_at` — otherwise `ERR_FILING_DEADLINE_PASSED` (422). Applies
        to `POST /transactions/{id}/file` and `POST /transactions/{id}/revise`."
        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Corner/validations/filing_at_exactly_its_deadline_passes_and_one_second_later_is_refused
        """
        world = self._two_drafts(league)
        league.set_clock("2026-08-12T14:00:00Z")
        league.submit_filing(world["on_time"]["id"], world["club"]["id"])

        league.set_clock("2026-08-12T14:00:01Z")
        response = league.api.file_transaction(
            world["late"]["id"], League.analyst(world["club"])
        )
        validate_error(response, ERR_FILING_DEADLINE_PASSED, 422)

        late = league.filing(world["late"]["id"])
        assert late["status"] == "DRAFT", (
            f"the refused filing stays in draft, got {late['status']}"
        )
        assert late["filed_at"] is None, (
            f"no submission instant should be stamped, got {late['filed_at']}"
        )
        assert late["filed_by_user_id"] is None, (
            f"and no filer either, got {late['filed_by_user_id']}"
        )
        assert late["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            f"the deadline is untouched by the refusal, got {late['filing_deadline_at']}"
        )

        player = league.player(world["late_player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the late player joined nobody, got {player['roster_designation']}"
        )

        club = league.club(world["club"]["id"])
        assert club["provisional_cap_committed_cents"] == 166_666_666, (
            "both offered contracts still consume provisional room, got "
            f"{club['provisional_cap_committed_cents']}"
        )


class TestRosterLimitIsCheckedAtApproval:
    """The slot the first signing filled is the slot the second one needs."""

    @staticmethod
    def _second_filing_against_a_full_roster(league: League) -> Dict[str, Any]:
        club = _club(league, active_roster_limit=2)
        first_player = league.register_player(full_name="Ray Alder", position="QB")
        second_player = league.register_player(full_name="Dane Cole", position="OL")
        first = league.sign_onto_roster(
            club["id"], first_player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        second = league.open_signing(
            club["id"], second_player["id"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        exam = league.pass_entry_physical(
            club["id"], second_player["id"], second["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at="2026-08-10T14:30:00Z",
        )
        league.submit_filing(second["id"], club["id"])
        tightened = league.adjust_limits(club["id"], active_roster_limit=1)
        return {
            "club": club,
            "tightened": tightened,
            "first_contract_id": first["contract_id"],
            "second": second,
            "second_player": second_player,
            "exam": exam,
        }

    def test_a_tightened_limit_still_leaves_the_club_compliant_at_the_limit(
        self, league: League
    ) -> None:
        """Sitting exactly on the limit is not a violation; overshooting it is.

        PRD 3.9: "1. `ACTIVE_ROSTER_OVER_LIMIT`, when `active_roster_count` is
        strictly greater than `active_roster_limit`."
        PRD 3.1: "`grace_expires_at` (the instant the current grace window ends, and
        null unless the posture is `GRACE`)"

        Design: Corner/validations/second_approval_breaches_the_active_roster_limit_the_first_one_filled
        """
        world = self._second_filing_against_a_full_roster(league)

        club = league.club(world["club"]["id"])
        assert club["active_roster_limit"] == 1, (
            f"the limit should have been tightened to 1, got {club['active_roster_limit']}"
        )
        assert club["active_roster_count"] == 1, (
            f"one player is on the active roster, got {club['active_roster_count']}"
        )
        assert_posture(club, "COMPLIANT", 0, grace_expires_at=None)

    def test_the_second_approval_is_refused_and_leaves_the_filing_filed(
        self, league: League
    ) -> None:
        """The projected second active player exceeds the one remaining slot.

        PRD 2.8: "36. The resulting headcount for the affected designation stays
        within the club's corresponding limit — otherwise `ERR_ROSTER_LIMIT_EXCEEDED`
        (409). Applies to `POST /transactions/{id}/decide` with an approving
        decision, `POST /trades/{id}/execute` and `POST
        /waiver-requests/{id}/process`."
        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Corner/validations/second_approval_breaches_the_active_roster_limit_the_first_one_filled
        """
        world = self._second_filing_against_a_full_roster(league)

        response = league.api.decide_transaction(
            world["second"]["id"], fac.approve_payload(), league.officer
        )
        validate_error(response, ERR_ROSTER_LIMIT_EXCEEDED, 409)

        filing = league.filing(world["second"]["id"])
        assert filing["status"] == "FILED", (
            f"the refused filing still awaits a decision, got {filing['status']}"
        )
        assert filing["decided_at"] is None, (
            f"no decision instant should be stamped, got {filing['decided_at']}"
        )
        assert filing["prior_designation"] is None, (
            "the designation snapshot is only taken on an approval that runs, got "
            f"{filing['prior_designation']}"
        )

        contract = league.contract(filing["contract_id"])
        assert contract["status"] == "PENDING_APPROVAL", (
            f"the second contract stays pending, got {contract['status']}"
        )

        player = league.player(world["second_player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the second player joined nobody, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"an unrostered player has no club, got {player['current_team_id']}"
        )

        exam = league.exam(world["exam"]["id"])
        assert exam["status"] == "PASSED", (
            "the second player's physical is spotless, which is what makes the "
            f"roster limit the operative refusal, got {exam['status']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 1, (
            f"the headcount is unchanged, got {club['active_roster_count']}"
        )
        assert club["provisional_cap_committed_cents"] == 166_666_666, (
            "both contracts still sit in the provisional total, got "
            f"{club['provisional_cap_committed_cents']}"
        )
        assert club["final_cap_committed_cents"] == 83_333_333, (
            "only the approved contract reaches the final total, got "
            f"{club['final_cap_committed_cents']}"
        )


class TestPracticeSquadEligibilityIsCheckedAtApproval:
    """A player who has used up his practice-squad seasons cannot be placed there."""

    def test_a_signing_onto_the_practice_squad_needs_an_eligible_player(
        self, league: League
    ) -> None:
        """Two used seasons make the player ineligible and refuse the approval.

        PRD 3.2: "Separately, `practice_squad_eligible` is true only when both of two
        conditions hold: `roster_service_days` is at most 340, and
        `practice_squad_seasons_used` is strictly less than 2."
        PRD 2.8: "34. A player being placed onto or elevated off the practice squad
        has `practice_squad_eligible` true — otherwise `ERR_PRACTICE_SQUAD_INELIGIBLE`
        (422). Applies to `POST /transactions/{id}/decide` with an approving
        decision."

        Design: Corner/validations/practice_squad_signing_of_an_ineligible_player_is_refused_at_approval
        """
        club = _club(league)
        player = league.register_player(
            full_name="Nico Braun", position="WR", practice_squad_seasons_used=2
        )

        assert player["roster_service_days"] == 0, (
            "the player has no accrued days at all, so the day condition holds, got "
            f"{player['roster_service_days']}"
        )
        assert player["practice_squad_eligible"] is False, (
            "two used practice-squad seasons fail the second condition, so "
            "eligibility must be false"
        )

        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"],
            years=1, base_salary_cents=12_000_000, signing_bonus_cents=0,
            start_season_year=2026, is_practice_squad_contract=True,
        )
        league.pass_entry_physical(
            club["id"], player["id"], filing["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
        )
        league.submit_filing(filing["id"], club["id"])

        response = league.api.decide_transaction(
            filing["id"], fac.approve_payload(), league.officer
        )
        validate_error(response, ERR_PRACTICE_SQUAD_INELIGIBLE, 422)

        refused = league.filing(filing["id"])
        assert refused["status"] == "FILED", (
            f"the refused filing still awaits a decision, got {refused['status']}"
        )
        assert refused["decided_at"] is None, (
            f"no decision instant should be stamped, got {refused['decided_at']}"
        )
        assert refused["prior_designation"] is None, (
            "no designation snapshot is taken, got "
            f"{refused['prior_designation']}"
        )

        contract = league.contract(filing["contract_id"])
        assert contract["status"] == "PENDING_APPROVAL", (
            f"the contract stays pending, got {contract['status']}"
        )
        assert contract["is_practice_squad_contract"] is True, (
            "the offered deal is the practice-squad deal that triggered the check"
        )
        assert contract["current_season_cap_charge_cents"] == 12_000_000, (
            "a bonus-free one-year deal charges its base salary, got "
            f"{contract['current_season_cap_charge_cents']}"
        )

        unmoved = league.player(player["id"])
        assert unmoved["roster_designation"] == "UNROSTERED", (
            f"the player never reached the practice squad, got {unmoved['roster_designation']}"
        )
        assert unmoved["current_team_id"] is None, (
            f"and joined no club, got {unmoved['current_team_id']}"
        )
        assert unmoved["contract_rights_class"] == "NONE", (
            "with no pension credit the rights class stays NONE, got "
            f"{unmoved['contract_rights_class']}"
        )

        settled = league.club(club["id"])
        assert_designation_counts(
            settled, active=0, reserve=0, injured_reserve=0, practice_squad=0
        )
        assert settled["provisional_cap_committed_cents"] == 12_000_000, (
            "the offered contract still consumes provisional room, got "
            f"{settled['provisional_cap_committed_cents']}"
        )


class TestRevisionBudgetIsSpentThenReported:
    """Two revisions, a void that costs nothing, and one distinct diagnosis."""

    @staticmethod
    def _filing_voided_at_the_limit(league: League) -> Dict[str, Any]:
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"],
            years=3, base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        league.submit_filing(filing["id"], club["id"])
        league.reject_filing(filing["id"], "cap posture")
        first = league.revise_filing(
            filing["id"], club["id"], base_salary_cents=78_000_000
        )
        league.submit_filing(filing["id"], club["id"])
        league.reject_filing(filing["id"], "cap posture")
        second = league.revise_filing(
            filing["id"], club["id"], base_salary_cents=76_000_000
        )
        league.submit_filing(filing["id"], club["id"])
        league.reject_filing(filing["id"], "cap posture")
        voided = league.revise_filing(
            filing["id"], club["id"], base_salary_cents=74_000_000
        )
        return {
            "club": club, "filing_id": filing["id"],
            "contract_id": filing["contract_id"],
            "first": first, "second": second, "voided": voided,
        }

    def test_the_third_revision_voids_without_spending_a_revision(
        self, league: League
    ) -> None:
        """The budget stops at two, and the void leaves the counter where it was.

        PRD 3.3: "A revision on a `REJECTED` filing whose `revision_count` is
        strictly less than 2 returns it `REJECTED → DRAFT`, increments
        `revision_count` by 1, clears `rejection_reason` and `decided_at` (along with
        `decided_by_user_id`, `filed_at` and `filed_by_user_id`), and leaves
        `filing_deadline_at` exactly as it was — a revision never buys more time, and
        a revision attempted after the deadline has passed is refused with
        `ERR_FILING_DEADLINE_PASSED`."
        PRD 3.3: "Note carefully that the void does **not** itself consume a
        revision: `revision_count` stays at 2, so the pair of a `VOIDED` status with
        a `revision_count` of 2 is the stable signature the system later recognises."

        Design: Corner/validations/revise_of_a_filing_voided_at_the_revision_limit_returns_revision_limit_exceeded
        """
        world = self._filing_voided_at_the_limit(league)

        assert world["first"]["status"] == "DRAFT", (
            f"the first revision returns the filing to draft, got {world['first']['status']}"
        )
        assert world["first"]["revision_count"] == 1, (
            f"the first revision spends one of two, got {world['first']['revision_count']}"
        )
        assert world["first"]["filed_at"] is None, (
            f"a revision clears the submission instant, got {world['first']['filed_at']}"
        )
        assert world["first"]["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            "a revision never buys more time, got "
            f"{world['first']['filing_deadline_at']}"
        )
        assert world["second"]["revision_count"] == 2, (
            f"the second revision spends the last one, got {world['second']['revision_count']}"
        )
        assert world["second"]["status"] == "DRAFT", (
            f"the filing is still revisable in draft, got {world['second']['status']}"
        )

        assert world["voided"]["status"] == "VOIDED", (
            "a revision attempted at the limit voids the filing instead of "
            f"returning it to draft, got {world['voided']['status']}"
        )
        assert world["voided"]["revision_count"] == 2, (
            "the void must not consume a third revision, got "
            f"{world['voided']['revision_count']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "VOIDED", (
            f"the linked contract stays voided permanently, got {contract['status']}"
        )

        club = league.club(world["club"]["id"])
        assert_cap_position(
            club, provisional=0, final=0, dead_money=0, cap_space=500_000_000,
        )

    def test_a_further_revision_on_the_voided_filing_reports_the_revision_limit(
        self, league: League
    ) -> None:
        """The voided filing answers with its own diagnosis, not a state error.

        PRD 2.8: "14. A revision aimed at a filing already voided by the revision
        limit — that is, a filing whose `status` is `VOIDED` and whose
        `revision_count` equals the maximum of 2 — is rejected with
        `ERR_REVISION_LIMIT_EXCEEDED` (409). Applies to `POST
        /transactions/{id}/revise`. A revision on a `REJECTED` filing below the limit
        passes this rule; a revision on a `REJECTED` filing exactly at the limit does
        not error here either — it voids the filing, as described in §3.3."
        PRD 3.3: "A *further* revision aimed at that already-voided filing is the one
        case that reports `ERR_REVISION_LIMIT_EXCEEDED`."

        Design: Corner/validations/revise_of_a_filing_voided_at_the_revision_limit_returns_revision_limit_exceeded
        """
        world = self._filing_voided_at_the_limit(league)

        response = league.api.revise_transaction(
            world["filing_id"],
            fac.revise_payload(base_salary_cents=72_000_000),
            League.analyst(world["club"]),
        )
        validate_error(response, ERR_REVISION_LIMIT_EXCEEDED, 409)

        filing = league.filing(world["filing_id"])
        assert filing["status"] == "VOIDED", (
            f"the filing is terminally voided, got {filing['status']}"
        )
        assert filing["revision_count"] == 2, (
            "the refused attempt spends nothing, got "
            f"{filing['revision_count']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "VOIDED", (
            f"the contract is not revived by a refused revision, got {contract['status']}"
        )

        club = league.club(world["club"]["id"])
        assert club["provisional_cap_committed_cents"] == 0, (
            "a voided contract commits nothing, got "
            f"{club['provisional_cap_committed_cents']}"
        )
