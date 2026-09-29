"""Lifecycle edges: the legal moves, the refused ones and their side effects."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_INVALID_DESIGNATION_STATE,
    ERR_INVALID_EXAM_STATE,
    ERR_INVALID_TRANSACTION_STATE,
    ERR_INVALID_WAIVER_STATE,
    ERR_OUTSIDE_PROCESSING_WINDOW,
)
from test_helpers.assertions import assert_cap_position, assert_designation_counts
from test_helpers.fixtures import League
from test_helpers.test_users import make_cap_analyst_headers, make_medical_officer_headers

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"


def _club_and_player(league: League) -> Dict[str, Any]:
    """One club with a free agent waiting, at the standard clock."""
    league.set_clock(CLOCK)
    club = league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
    )
    player = league.register_player(full_name="Ray Alder", position="QB")
    return {"club": club, "player": player}


def _rostered(league: League) -> Dict[str, Any]:
    """One player driven all the way onto a club's active roster."""
    world = _club_and_player(league)
    signing = league.sign_onto_roster(
        world["club"]["id"], world["player"]["id"],
        window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
        expected_team_version=world["club"]["version"], years=3,
        base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
        start_season_year=2026,
    )
    world["signing_transaction_id"] = signing["transaction_id"]
    world["contract_id"] = signing["contract_id"]
    return world


class TestFilingSubmissionEdge:
    """The one edge that carries a draft into the league's hands."""

    def test_submission_records_the_clock_and_the_acting_club(
        self, league: League
    ) -> None:
        """A draft becomes filed, stamped with who filed it and when.

        PRD 3.3: "On success the server records `filed_at` as the logical clock
        and `filed_by_user_id` as the acting identifier."
        PRD 3.3: "`requires_physical` is true exactly when the
        `transaction_type` is `SIGNING` or `IR_ACTIVATION`, and false for all four
        other types."

        Design: Corner/state_machines/file_draft_filing_moves_to_filed_and_records_the_filer
        """
        world = _club_and_player(league)
        filing = league.open_signing(
            world["club"]["id"], world["player"]["id"],
            expected_team_version=world["club"]["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )

        assert filing["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            "the deadline is fixed at creation as 48 hours out, got "
            f"{filing['filing_deadline_at']}"
        )
        assert filing["requires_physical"] is True, (
            f"a signing demands a physical, got {filing['requires_physical']}"
        )

        response = league.api.file_transaction(
            filing["id"], make_cap_analyst_headers(world["club"]["id"])
        )
        filed = validate_success(response, 200)

        assert filed["status"] == "FILED", (
            f"submission should move the filing to FILED, got {filed['status']}"
        )
        assert filed["filed_at"] == "2026-08-10T14:00:00.000Z", (
            f"the filing instant is the logical clock, got {filed['filed_at']}"
        )
        assert filed["filed_by_user_id"] == world["club"]["id"], (
            "the acting analyst's identifier is its own club id, got "
            f"{filed['filed_by_user_id']}"
        )
        assert filed["decided_at"] is None, (
            f"nobody has decided yet, got {filed['decided_at']}"
        )
        assert filed["revision_count"] == 0, (
            f"a first submission consumes no revision, got {filed['revision_count']}"
        )
        assert filed["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            "submission never recomputes the deadline, got "
            f"{filed['filing_deadline_at']}"
        )

    def test_filing_at_the_excluded_close_of_the_window_is_refused(
        self, league: League
    ) -> None:
        """21:00:00Z is outside the window, so the draft cannot be submitted.

        PRD 2.5: "The interval is half-open: an operation attempted at exactly
        13:00:00 UTC is inside the window, and an operation attempted at exactly
        21:00:00 UTC is outside it."
        PRD 2.8: "The logical clock's time of day is inside the half-open
        processing window — otherwise `ERR_OUTSIDE_PROCESSING_WINDOW` (422)."

        Design: Corner/state_machines/file_filing_outside_processing_window_rejected
        """
        world = _club_and_player(league)
        filing = league.open_signing(
            world["club"]["id"], world["player"]["id"],
            expected_team_version=world["club"]["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        league.set_clock("2026-08-10T21:00:00Z")
        version_before = league.club(world["club"]["id"])["version"]

        response = league.api.file_transaction(
            filing["id"], make_cap_analyst_headers(world["club"]["id"])
        )
        validate_error(response, ERR_OUTSIDE_PROCESSING_WINDOW, 422)

        refused = league.filing(filing["id"])
        assert refused["status"] == "DRAFT", (
            f"the filing never left DRAFT, got {refused['status']}"
        )
        assert refused["filed_at"] is None, (
            f"no filing instant was stamped, got {refused['filed_at']}"
        )
        assert refused["filed_by_user_id"] is None, (
            f"and no filer was recorded, got {refused['filed_by_user_id']}"
        )
        assert league.club(world["club"]["id"])["version"] == version_before, (
            "a refused submission writes nothing, so the club's version is "
            f"unchanged at {version_before}"
        )


class TestReleaseApprovalEdge:
    """Approving a release moves the player without ending the obligation."""

    def test_release_approval_waives_the_player_and_keeps_the_contract(
        self, league: League
    ) -> None:
        """The roster empties, the money stays, and the snapshot records both.

        PRD 3.3: "**`RELEASE`**: the player's designation becomes
        `WAIVED_PENDING`. The contract stays `ACTIVE` and keeps its full cap
        charge, and `current_team_id` is left alone — the release only authorises a
        waiver placement, it does not by itself end the club's obligation."

        Design: Corner/state_machines/release_approval_flips_player_to_waived_pending_and_drops_active_count
        """
        world = _rostered(league)
        release = league.open_release(world["club"]["id"], world["player"]["id"])
        league.submit_filing(release["id"], world["club"]["id"])

        approved = league.approve_filing(release["id"])

        assert approved["status"] == "APPROVED", (
            f"the release should be approved, got {approved['status']}"
        )
        assert approved["prior_designation"] == "ACTIVE", (
            "the snapshot records where the player stood before the cascade, got "
            f"{approved['prior_designation']}"
        )
        assert approved["effective_at"] == "2026-08-10T14:00:00.000Z", (
            f"the release takes effect on the clock, got {approved['effective_at']}"
        )
        assert approved["requires_physical"] is False, (
            f"a release demands no physical, got {approved['requires_physical']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "WAIVED_PENDING", (
            f"the player is now awaiting the wire, got {player['roster_designation']}"
        )
        assert player["current_team_id"] == world["club"]["id"], (
            "the club still owns him until the wire resolves, got "
            f"{player['current_team_id']}"
        )
        assert player["accrued_active_days"] == 0, (
            "no whole day elapsed in the active bucket, so it accrues nothing, got "
            f"{player['accrued_active_days']}"
        )
        assert player["designation_effective_at"] == "2026-08-10T14:00:00.000Z", (
            "the designation clock restarts on the move, got "
            f"{player['designation_effective_at']}"
        )

        club = league.club(world["club"]["id"])
        assert_designation_counts(
            club, active=0, reserve=0, injured_reserve=0, practice_squad=0
        )
        assert_cap_position(
            club, provisional=83_333_333, final=83_333_333,
            dead_money=0, cap_space=416_666_667,
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the contract survives the release, got {contract['status']}"
        )
        assert contract["current_season_cap_charge_cents"] == 83_333_333, (
            "and keeps its full charge, got "
            f"{contract['current_season_cap_charge_cents']}"
        )


class TestApprovedFilingHasNoSecondDecision:
    """APPROVED is the end of the decision road."""

    def test_deciding_an_approved_filing_a_second_time_is_refused(
        self, league: League
    ) -> None:
        """The reversal is refused and no cascade fires twice.

        PRD 2.8: "The target record is in a state that has an outgoing transition
        for this trigger, including the parallel dimension the trigger writes —
        otherwise the matching 409 state error (`ERR_INVALID_TRANSACTION_STATE`,
        `ERR_INVALID_CONTRACT_STATE`, `ERR_INVALID_OPTION_STATE`,
        `ERR_INVALID_WAIVER_STATE`, `ERR_INVALID_TRADE_STATE`,
        `ERR_INVALID_TENDER_STATE`, `ERR_INVALID_DESIGNATION_STATE`,
        `ERR_INVALID_EXAM_STATE`)."

        Design: Corner/state_machines/decide_on_already_approved_filing_returns_invalid_transaction_state
        """
        world = _rostered(league)

        response = league.api.decide_transaction(
            world["signing_transaction_id"],
            fac.reject_payload("changed our mind"),
            league.officer,
        )
        validate_error(response, ERR_INVALID_TRANSACTION_STATE, 409)

        filing = league.filing(world["signing_transaction_id"])
        assert filing["status"] == "APPROVED", (
            f"the approval stands, got {filing['status']}"
        )
        assert filing["rejection_reason"] is None, (
            f"the refused reason was never stored, got {filing['rejection_reason']}"
        )
        assert filing["decided_at"] == "2026-08-10T14:00:00.000Z", (
            "the original decision instant is untouched, got "
            f"{filing['decided_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            f"the player stays on the roster, got {player['roster_designation']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 1, (
            f"the headcount is not touched twice, got {club['active_roster_count']}"
        )
        assert club["provisional_cap_committed_cents"] == 83_333_333, (
            "and neither is the cap, got "
            f"{club['provisional_cap_committed_cents']}"
        )


class TestInjuryDesignationBirthState:
    """A designation is born waiting for paperwork and moves nothing."""

    def test_a_new_injured_reserve_designation_waits_for_its_paperwork(
        self, league: League
    ) -> None:
        """Creation fixes the stay length and leaves every later instant null.

        PRD 3.5: "On creation the designation records `placed_at` as the logical
        clock, lands in `PENDING_PAPERWORK`, and fixes `minimum_stay_days` from the
        type: 21 days for `INJURED_RESERVE`, 14 days for
        `INJURED_RESERVE_RETURN_ELIGIBLE` and 28 days for `NON_ROSTER_INJURY`."
        PRD 3.5: "Both are null until activation."

        Design: Corner/state_machines/new_injury_designation_starts_in_pending_paperwork
        """
        world = _rostered(league)

        designation = league.open_injury_designation(
            world["club"]["id"], world["player"]["id"], "INJURED_RESERVE"
        )

        assert designation["status"] == "PENDING_PAPERWORK", (
            f"a fresh designation waits for paperwork, got {designation['status']}"
        )
        assert designation["minimum_stay_days"] == 21, (
            "an injured-reserve stay is 21 days, got "
            f"{designation['minimum_stay_days']}"
        )
        assert designation["placed_at"] == "2026-08-10T14:00:00.000Z", (
            f"the placement instant is the clock, got {designation['placed_at']}"
        )
        assert designation["paperwork_filed_at"] is None, (
            f"no paperwork is on file yet, got {designation['paperwork_filed_at']}"
        )
        assert designation["activated_at"] is None, (
            f"nothing has activated it, got {designation['activated_at']}"
        )
        assert designation["closed_at"] is None, (
            f"and nothing has closed it, got {designation['closed_at']}"
        )
        assert designation["return_window_opens_at"] is None, (
            "the return window is not derived before activation, got "
            f"{designation['return_window_opens_at']}"
        )
        assert designation["return_window_closes_at"] is None, (
            "nor is its close, got "
            f"{designation['return_window_closes_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            "opening a designation moves no roster bucket, got "
            f"{player['roster_designation']}"
        )
        assert player["medical_status"] == "CLEARED", (
            "and touches the medical dimension only when the paperwork is filed, "
            f"got {player['medical_status']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 1, (
            f"the player is still counted as active, got {club['active_roster_count']}"
        )
        assert club["injured_reserve_count"] == 0, (
            "and the injured-reserve bucket is still empty, got "
            f"{club['injured_reserve_count']}"
        )


class TestWithdrawnWireIsTerminal:
    """A wire that has already been pulled cannot be pulled again."""

    def test_a_second_withdrawal_is_refused_and_restores_nothing_twice(
        self, league: League
    ) -> None:
        """The refusal protects the headcount the first withdrawal restored.

        PRD 3.6: "A withdrawal attempt on an `IRREVOCABLE` placement, or on a wire
        that has already resolved, is refused with `ERR_INVALID_WAIVER_STATE`."

        Design: Corner/state_machines/withdrawn_waiver_request_cannot_be_withdrawn_again
        """
        world = _rostered(league)
        wire = league.release_onto_wire(world["club"]["id"], world["player"]["id"])
        league.withdraw_wire(wire["waiver_request_id"], world["club"]["id"])

        response = league.api.withdraw_waiver_request(
            wire["waiver_request_id"],
            make_cap_analyst_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_INVALID_WAIVER_STATE, 409)

        pulled = league.wire(wire["waiver_request_id"])
        assert pulled["status"] == "WITHDRAWN", (
            f"the wire is still withdrawn, got {pulled['status']}"
        )
        assert pulled["processed_at"] == "2026-08-10T14:00:00.000Z", (
            "the first withdrawal's instant is unchanged, got "
            f"{pulled['processed_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            f"the player stays where the first withdrawal put him, got {player['roster_designation']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 1, (
            "the headcount was restored once and only once, got "
            f"{club['active_roster_count']}"
        )

        release = league.filing(wire["release_transaction_id"])
        assert release["status"] == "VOIDED", (
            f"the authorising release stays voided, got {release['status']}"
        )


class TestPaperworkIsFiledOnce:
    """The paperwork edge is not idempotent, it is closed."""

    def test_filing_the_paperwork_twice_keeps_the_first_reference(
        self, league: League
    ) -> None:
        """The second reference is refused and never overwrites the first.

        PRD 3.5: "Filing paperwork twice is refused with
        `ERR_INVALID_DESIGNATION_STATE`."
        PRD 3.5: "The server stamps `paperwork_filed_at` with the logical clock
        and, in the same write, moves the player's `medical_status` `CLEARED →
        REHAB`."

        Design: Corner/state_machines/filing_injury_paperwork_twice_returns_invalid_designation_state
        """
        world = _rostered(league)
        designation = league.open_injury_designation(
            world["club"]["id"], world["player"]["id"], "INJURED_RESERVE"
        )
        first = league.file_paperwork(
            designation["id"], world["club"]["id"], "IR-2026-0001"
        )
        assert first["paperwork_reference"] == "IR-2026-0001", (
            f"the first reference is stored as supplied, got {first['paperwork_reference']}"
        )

        response = league.api.file_injury_paperwork(
            designation["id"],
            fac.paperwork_payload("IR-2026-0002"),
            make_medical_officer_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_INVALID_DESIGNATION_STATE, 409)

        stored = league.designation(designation["id"])
        assert stored["paperwork_reference"] == "IR-2026-0001", (
            "the refused call must not overwrite the reference, got "
            f"{stored['paperwork_reference']}"
        )
        assert stored["paperwork_filed_at"] == "2026-08-10T14:00:00.000Z", (
            "nor the instant the first call stamped, got "
            f"{stored['paperwork_filed_at']}"
        )
        assert stored["status"] == "PAPERWORK_FILED", (
            f"the designation stays where the first call left it, got {stored['status']}"
        )

        player = league.player(world["player"]["id"])
        assert player["medical_status"] == "REHAB", (
            "the medical move happened once, on the first call, got "
            f"{player['medical_status']}"
        )
        assert player["roster_designation"] == "ACTIVE", (
            "filing paperwork moves no roster bucket, got "
            f"{player['roster_designation']}"
        )

        club = league.club(world["club"]["id"])
        assert club["injured_reserve_count"] == 0, (
            "only an approved placement fills the injured-reserve bucket, got "
            f"{club['injured_reserve_count']}"
        )


class TestExamResultIsRecordedOnce:
    """A passed exam has no outgoing record-result edge."""

    def test_recording_a_second_result_cannot_rewrite_the_expiry(
        self, league: League
    ) -> None:
        """The refusal keeps both the pass and the expiry it derived.

        PRD 3.5: "Recording a result on an exam that is not `SCHEDULED` is
        `ERR_INVALID_EXAM_STATE`."
        PRD 3.5: "A passed result moves the exam `SCHEDULED → PASSED` and sets
        `expires_at` to `performed_at` plus 14 days."

        Design: Corner/state_machines/recording_a_result_twice_on_one_physical_returns_invalid_exam_state
        """
        world = _club_and_player(league)
        exam = league.schedule_exam(
            world["club"]["id"], world["player"]["id"], "ENTRY_PHYSICAL",
            EXAM_START, EXAM_END,
        )
        passed = league.record_exam(
            exam["id"], world["club"]["id"], "PASSED", CLOCK
        )
        assert passed["expires_at"] == "2026-08-24T14:00:00.000Z", (
            f"a pass is good for 14 days, got {passed['expires_at']}"
        )

        response = league.api.record_exam_result(
            exam["id"],
            fac.exam_result_payload("FAILED", "2026-08-10T15:00:00Z"),
            make_medical_officer_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_INVALID_EXAM_STATE, 409)

        stored = league.exam(exam["id"])
        assert stored["status"] == "PASSED", (
            f"the exam is still a pass, got {stored['status']}"
        )
        assert stored["performed_at"] == "2026-08-10T14:00:00.000Z", (
            "the later performed_at was never accepted, got "
            f"{stored['performed_at']}"
        )
        assert stored["expires_at"] == "2026-08-24T14:00:00.000Z", (
            "so the expiry was never recomputed from it, got "
            f"{stored['expires_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["medical_status"] == "CLEARED", (
            "the refused failure never reached the player, got "
            f"{player['medical_status']}"
        )


class TestOptionDeclineCascade:
    """One decision on the parallel option dimension empties a roster spot."""

    def test_declining_a_team_option_terminates_and_unrosters(
        self, league: League
    ) -> None:
        """The decline writes the contract, the player and the club at once.

        PRD 3.4: "A `DECLINE` decision moves `option_status` `PENDING → DECLINED`
        and simultaneously terminates the contract `ACTIVE → TERMINATED` with
        `termination_reason` `OPTION_DECLINED`, running the full dead-money and
        allocation cascade, sending the player to `UNROSTERED` with a null
        `current_team_id`, and recomputing the club's headcounts and cap fields."

        Design: Corner/state_machines/team_option_decline_terminates_contract_and_unrosters_the_player
        """
        world = _club_and_player(league)
        signing = league.sign_onto_roster(
            world["club"]["id"], world["player"]["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=world["club"]["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026, option_type="TEAM_OPTION",
            option_deadline_at="2026-08-20T14:00:00Z",
            option_salary_cents=90_000_000,
        )
        contract_id = signing["contract_id"]

        before = league.contract(contract_id)
        assert before["option_status"] == "PENDING", (
            "activation arms the option dimension, got "
            f"{before['option_status']}"
        )

        declined = league.decide_option(
            contract_id, "DECLINE", League.analyst(world["club"])
        )

        assert declined["status"] == "TERMINATED", (
            f"the decline ends the contract, got {declined['status']}"
        )
        assert declined["termination_reason"] == "OPTION_DECLINED", (
            f"and names the reason, got {declined['termination_reason']}"
        )
        assert declined["option_status"] == "DECLINED", (
            f"the option dimension records the decline, got {declined['option_status']}"
        )
        assert declined["base_salary_cents"] == 80_000_000, (
            "a declined option never replaces the base salary, got "
            f"{declined['base_salary_cents']}"
        )
        assert declined["dead_money_current_season_cents"] == 3_333_333, (
            "before the acceleration cutoff this season keeps only its own share, "
            f"got {declined['dead_money_current_season_cents']}"
        )
        assert declined["dead_money_next_season_cents"] == 6_666_667, (
            "and the rest of the unamortised balance falls into next season, got "
            f"{declined['dead_money_next_season_cents']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player leaves the roster entirely, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"and belongs to nobody, got {player['current_team_id']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 0, (
            f"the active headcount empties, got {club['active_roster_count']}"
        )
        assert_cap_position(
            club, provisional=3_333_333, final=3_333_333,
            dead_money=3_333_333, cap_space=496_666_667,
        )

        rows = league.allocations(contract_id)
        proration_rows = [
            row for row in rows if row["bonus_type"] == "SIGNING_PRORATION"
        ]
        assert len(proration_rows) == 3, (
            f"a three-year bonus spreads over three rows, got {len(proration_rows)}"
        )
        assert all(
            row["allocation_status"] == "ACCELERATED" for row in proration_rows
        ), (
            "every unamortised proration row accelerates, got "
            f"{[row['allocation_status'] for row in proration_rows]}"
        )


class TestDesignationChangeResyncsTheLedger:
    """A cap-neutral move that still rewrites all four headcounts."""

    def test_moving_a_player_to_reserve_reshuffles_only_the_headcounts(
        self, league: League
    ) -> None:
        """One bucket empties, another fills, and the money does not move.

        PRD 3.3: "**`DESIGNATION_CHANGE`** and **`PRACTICE_SQUAD_ELEVATION`**: the
        player's designation becomes the filing's `target_designation`."
        PRD 3.3: "Finally the club's four headcounts, both cap totals,
        `dead_money_cents` and `cap_space_cents` are recomputed, the club's
        compliance posture is re-evaluated in event mode — where a fresh violation
        may move the club from `COMPLIANT` to `GRACE` but can never freeze it — and
        the club's `version` is incremented."

        Design: Corner/state_machines/designation_change_approval_resyncs_all_four_roster_counters
        """
        world = _rostered(league)
        before = league.club(world["club"]["id"])
        assert before["active_roster_count"] == 1, (
            f"the player starts on the active roster, got {before['active_roster_count']}"
        )

        change = league.open_designation_change(
            world["club"]["id"], world["player"]["id"], "RESERVE"
        )
        league.submit_filing(change["id"], world["club"]["id"])
        approved = league.approve_filing(change["id"])

        assert approved["status"] == "APPROVED", (
            f"the change should be approved, got {approved['status']}"
        )
        assert approved["prior_designation"] == "ACTIVE", (
            f"the snapshot names the outgoing bucket, got {approved['prior_designation']}"
        )
        assert approved["requires_physical"] is False, (
            f"a designation change demands no physical, got {approved['requires_physical']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "RESERVE", (
            f"the player takes the target designation, got {player['roster_designation']}"
        )
        assert player["designation_effective_at"] == "2026-08-10T14:00:00.000Z", (
            "the designation clock restarts on the move, got "
            f"{player['designation_effective_at']}"
        )

        club = league.club(world["club"]["id"])
        assert_designation_counts(
            club, active=0, reserve=1, injured_reserve=0, practice_squad=0
        )
        assert_cap_position(
            club, provisional=83_333_333, final=83_333_333,
            dead_money=0, cap_space=416_666_667,
        )
        assert club["compliance_status"] == "COMPLIANT", (
            f"the club breaks no quota, got {club['compliance_status']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the contract is unaffected by the move, got {contract['status']}"
        )


class TestTerminationCascadeIsConditionalPerRow:
    """The same cascade forfeits one child row, accelerates three and spares one."""

    def test_a_cleared_wire_accelerates_prorations_and_spares_earned_money(
        self, league: League
    ) -> None:
        """Each bonus row's own type and state decides what happens to it.

        PRD 3.6: "If no claim survives the three filters, the wire moves `PENDING →
        CLEARED` instead."
        PRD 3.4: "Every unamortised `SIGNING_PRORATION` row — the current season's
        row and every later one, that is every such row whose `season_year` is 2026
        or beyond — moves `SCHEDULED → ACCELERATED`, meaning it stops counting as a
        live cap charge and its money is folded into the dead-money split below."
        PRD 3.4: "Every still-`SCHEDULED` `ROSTER_BONUS`, `PERFORMANCE_LTBE` and
        `PERFORMANCE_NLTBE` row moves `SCHEDULED → FORFEITED`, leaving both cap
        variants and contributing nothing to dead money — a declined option
        forfeits unearned performance money outright. Rows already `EARNED` are
        untouched."

        Design: Corner/state_machines/contract_termination_forfeits_scheduled_bonus_rows_but_spares_earned_ones
        """
        world = _club_and_player(league)
        signing = league.sign_onto_roster(
            world["club"]["id"], world["player"]["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=world["club"]["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026, performance_ltbe_cents=5_000_000,
            performance_nltbe_cents=7_000_000,
        )
        contract_id = signing["contract_id"]

        rows = league.allocations(contract_id)
        assert len(rows) == 5, (
            f"three prorations plus two performance rows is five, got {len(rows)}"
        )
        ltbe_id = rows[3]["id"]
        nltbe_id = rows[4]["id"]
        earned = league.earn_allocation(nltbe_id)
        assert earned["allocation_status"] == "EARNED", (
            "the not-likely row is earned before the release, got "
            f"{earned['allocation_status']}"
        )

        wire = league.release_onto_wire(world["club"]["id"], world["player"]["id"])
        league.set_clock("2026-08-11T14:00:00Z")

        processed = league.process_wire(wire["waiver_request_id"])

        assert processed["status"] == "CLEARED", (
            f"nobody claimed him, so the wire clears, got {processed['status']}"
        )
        assert processed["releasing_team_dead_money_cents"] == 3_333_333, (
            "the releasing club keeps this season's dead-money share, got "
            f"{processed['releasing_team_dead_money_cents']}"
        )

        contract = league.contract(contract_id)
        assert contract["status"] == "TERMINATED", (
            f"a cleared wire ends the contract, got {contract['status']}"
        )
        assert contract["termination_reason"] == "RELEASE_CLEARED", (
            f"and names the clearing route, got {contract['termination_reason']}"
        )
        assert contract["dead_money_current_season_cents"] == 3_333_333, (
            "this season carries one proration share, got "
            f"{contract['dead_money_current_season_cents']}"
        )
        assert contract["dead_money_next_season_cents"] == 6_666_667, (
            "next season carries the remaining balance, got "
            f"{contract['dead_money_next_season_cents']}"
        )

        after = league.allocations(contract_id)
        assert len(after) == 5, (
            f"the cascade creates and destroys no rows, got {len(after)}"
        )
        assert [row["bonus_type"] for row in after] == [
            "SIGNING_PRORATION", "SIGNING_PRORATION", "SIGNING_PRORATION",
            "PERFORMANCE_LTBE", "PERFORMANCE_NLTBE",
        ], (
            "the rows keep their order, got "
            f"{[row['bonus_type'] for row in after]}"
        )
        assert [row["allocation_status"] for row in after[:3]] == [
            "ACCELERATED", "ACCELERATED", "ACCELERATED",
        ], (
            "every unamortised proration row accelerates, got "
            f"{[row['allocation_status'] for row in after[:3]]}"
        )

        forfeited = next(row for row in after if row["id"] == ltbe_id)
        assert forfeited["allocation_status"] == "FORFEITED", (
            "the still-scheduled likely bonus is forfeited, got "
            f"{forfeited['allocation_status']}"
        )
        assert forfeited["amount_cents"] == 5_000_000, (
            f"with its amount left intact, got {forfeited['amount_cents']}"
        )

        spared = next(row for row in after if row["id"] == nltbe_id)
        assert spared["allocation_status"] == "EARNED", (
            "the already-earned row is untouched by the cascade, got "
            f"{spared['allocation_status']}"
        )
        assert spared["earned_at"] == "2026-08-10T14:00:00.000Z", (
            "and keeps the instant it was earned, got "
            f"{spared['earned_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player leaves the roster, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"and belongs to nobody, got {player['current_team_id']}"
        )
