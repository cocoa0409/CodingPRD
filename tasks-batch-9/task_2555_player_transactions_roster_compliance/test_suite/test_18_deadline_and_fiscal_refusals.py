"""One second past a deadline, and one contract too many for a cap."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_MEDICAL_WINDOW_EXPIRED,
    ERR_OPTION_DEADLINE_PASSED,
    ERR_TENDER_DEADLINE_PASSED,
    ERR_TRADE_CAP_INCOMPATIBLE,
)
from test_helpers.assertions import find_by_id
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"


class TestATenderAnsweredOneSecondLate:
    """The tender is still ISSUED; only the clock has moved."""

    LATE = "2026-08-13T14:00:01Z"

    @staticmethod
    def _issued_tender_then_the_clock_moves(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(
            full_name="Ray Alder", position="QB", accrued_active_days=400
        )
        tender = league.issue_tender(
            club["id"], player["id"], "RESTRICTED_TENDER", "FIRST_ROUND",
            50_000_000,
        )
        league.set_clock(TestATenderAnsweredOneSecondLate.LATE)
        return {"club": club, "player": player, "tender": tender}

    def test_an_answer_one_second_past_the_deadline_is_refused(
        self, league: League
    ) -> None:
        """The deadline instant itself would have been on time.

        PRD 3.8: "Issuance stamps `issued_at` with the logical clock, leaves the
        tender `ISSUED`, and computes `deadline_at` as `issued_at` plus 72 hours,
        snapped into the daily processing window per §2.5."

        PRD 3.8: "Only the player's own agent may answer, supplying a `response` of
        either `ACCEPT` or `DECLINE`, and only while the logical clock is at or
        before `deadline_at` — a response strictly later is refused with
        `ERR_TENDER_DEADLINE_PASSED`."

        Design: Corner/errors/a_tender_response_one_second_after_the_deadline_is_refused
        """
        world = self._issued_tender_then_the_clock_moves(league)

        assert world["tender"]["issued_at"] == "2026-08-10T14:00:00.000Z", (
            f"issuance stamps the clock, got {world['tender']['issued_at']}"
        )
        assert world["tender"]["deadline_at"] == "2026-08-13T14:00:00.000Z", (
            "72 hours later is still inside the processing window, so the snap "
            f"leaves it alone, got {world['tender']['deadline_at']}"
        )

        response = league.api.respond_to_tender(
            world["tender"]["id"], fac.tender_response_payload("ACCEPT"),
            League.agent(world["player"]),
        )
        validate_error(response, ERR_TENDER_DEADLINE_PASSED, 422)

        tender = league.tender(world["tender"]["id"])
        assert tender["status"] == "ISSUED", (
            "no sweep has run, so the tender has not even lapsed yet, got "
            f"{tender['status']}"
        )
        assert tender["responded_at"] is None, (
            f"nobody answered it in time, got {tender['responded_at']}"
        )

    def test_the_late_answer_spawns_no_filing_and_no_contract(
        self, league: League
    ) -> None:
        """An accept would have created a draft filing and a pending contract.

        PRD 3.8: "Because the tender was accepted, a filing of type `SIGNING` is
        created for that club and player in `DRAFT` status, and
        `resulting_transaction_id` is set to point at it."

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Corner/errors/a_tender_response_one_second_after_the_deadline_is_refused
        """
        world = self._issued_tender_then_the_clock_moves(league)

        league.api.respond_to_tender(
            world["tender"]["id"], fac.tender_response_payload("ACCEPT"),
            League.agent(world["player"]),
        )

        tender = league.tender(world["tender"]["id"])
        assert tender["resulting_transaction_id"] is None, (
            "the accept cascade never ran, so no filing is linked, got "
            f"{tender['resulting_transaction_id']}"
        )

        _, filing_meta = validate_paginated(
            league.api.list_transactions(league.officer)
        )
        assert filing_meta["total_count"] == 0, (
            f"no filing should exist, got {filing_meta['total_count']}"
        )
        _, contract_meta = validate_paginated(
            league.api.list_contracts(league.officer)
        )
        assert contract_meta["total_count"] == 0, (
            f"and no contract either, got {contract_meta['total_count']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player is still a free agent, got {player['roster_designation']}"
        )
        club = league.club(world["club"]["id"])
        assert club["provisional_cap_committed_cents"] == 0, (
            "and the club committed nothing, got "
            f"{club['provisional_cap_committed_cents']}"
        )


class TestAnOptionDecidedOneSecondLate:
    """PENDING has an exercise edge; the clock has closed the door on it."""

    LATE = "2026-08-20T14:00:01Z"

    @staticmethod
    def _optioned_contract_past_its_deadline(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026, option_type="TEAM_OPTION",
            option_deadline_at="2026-08-20T14:00:00Z",
            option_salary_cents=40_000_000,
        )
        before = league.contract(signing["contract_id"])
        league.set_clock(TestAnOptionDecidedOneSecondLate.LATE)
        return {
            "club": club,
            "player": player,
            "contract_id": signing["contract_id"],
            "before": before,
        }

    def test_an_exercise_one_second_past_the_option_deadline_is_refused(
        self, league: League
    ) -> None:
        """The option is still PENDING because no sweep has lapsed it.

        PRD 3.4: "In both cases the contract's `status` must be `ACTIVE`, the logical
        clock must be at or before `option_deadline_at` — a decision landing exactly
        on the deadline instant is accepted, and only a clock strictly later is
        refused with `ERR_OPTION_DEADLINE_PASSED` — and the request must carry
        `expected_contract_version` matching the contract's current `version`."

        PRD 3.4: "If nobody decides at all, the daily sweep moves `option_status`
        `PENDING → LAPSED` once the logical clock passes `option_deadline_at`,
        terminating the contract with `termination_reason` `OPTION_LAPSED` and
        applying exactly the same dead-money and roster consequences as the decline
        path."

        Design: Corner/errors/an_option_decision_one_second_after_the_option_deadline_is_refused
        """
        world = self._optioned_contract_past_its_deadline(league)

        assert world["before"]["option_status"] == "PENDING", (
            "activation opened the option dimension, got "
            f"{world['before']['option_status']}"
        )
        assert world["before"]["option_deadline_at"] == "2026-08-20T14:00:00.000Z", (
            f"the option deadline stands as offered, got {world['before']['option_deadline_at']}"
        )

        response = league.api.decide_option(
            world["contract_id"],
            fac.option_decision_payload("EXERCISE", world["before"]["version"]),
            League.analyst(world["club"]),
        )
        validate_error(response, ERR_OPTION_DEADLINE_PASSED, 422)

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            "no sweep has run, so the contract has not lapsed into termination, got "
            f"{contract['status']}"
        )
        assert contract["option_status"] == "PENDING", (
            f"and the option dimension is still PENDING, got {contract['option_status']}"
        )

    def test_the_late_option_decision_moves_no_money_and_no_roster(
        self, league: League
    ) -> None:
        """An exercise would have replaced the salary and re-valued the club.

        PRD 3.4: "An `EXERCISE` decision moves `option_status` `PENDING → EXERCISED`,
        replaces `base_salary_cents` with `option_salary_cents`, adds one to `years`,
        then recomputes the contract's current-season charge and the owning club's
        cap fields."

        PRD 3.4: "Either branch increments the contract's `version` by 1."

        Design: Corner/errors/an_option_decision_one_second_after_the_option_deadline_is_refused
        """
        world = self._optioned_contract_past_its_deadline(league)

        league.api.decide_option(
            world["contract_id"],
            fac.option_decision_payload("EXERCISE", world["before"]["version"]),
            League.analyst(world["club"]),
        )

        contract = league.contract(world["contract_id"])
        assert contract["base_salary_cents"] == 80_000_000, (
            "the option salary never replaced the base salary, got "
            f"{contract['base_salary_cents']}"
        )
        assert contract["years"] == 3, (
            f"and no year was added, got {contract['years']}"
        )
        assert contract["version"] == world["before"]["version"], (
            f"a refused decision increments no version, got {contract['version']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            f"the player keeps his place, got {player['roster_designation']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 1, (
            f"the active headcount is unchanged, got {club['active_roster_count']}"
        )
        assert club["final_cap_committed_cents"] == 83_333_333, (
            "and the final variant still carries the original charge, got "
            f"{club['final_cap_committed_cents']}"
        )


class TestATradeExecutedPastItsMedicalWindow:
    """The trade physical passed; the 72-hour review window did not wait."""

    LATE = "2026-08-13T14:00:01Z"

    @staticmethod
    def _contingent_trade_past_its_window(league: League) -> Dict[str, Any]:
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
            window_start_at=EXAM_START, window_end_at="2026-08-10T14:30:00Z",
            performed_at=CLOCK,
            expected_team_version=initiator["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        trade = league.build_trade(
            initiator["id"], counterparty["id"], "PHYSICAL_CONTINGENT",
            condition_note="Contingent on the acquiring club's physical.",
        )
        asset = league.offer_contract(
            trade["id"], initiator["id"], signing["contract_id"],
            "TO_COUNTERPARTY", expected_trade_version=trade["version"],
        )
        accepted = league.accept_trade(trade["id"], counterparty["id"])

        league.set_clock("2026-08-10T15:00:00Z")
        exam = league.schedule_exam(
            counterparty["id"], player["id"], "TRADE_PHYSICAL",
            "2026-08-10T14:30:00Z", "2026-08-10T20:00:00Z",
            trade_id=trade["id"],
        )
        passed = league.record_exam(
            exam["id"], counterparty["id"], "PASSED", "2026-08-10T15:00:00Z"
        )
        league.set_clock(TestATradeExecutedPastItsMedicalWindow.LATE)
        return {
            "initiator": initiator,
            "counterparty": counterparty,
            "player": player,
            "contract_id": signing["contract_id"],
            "trade_id": trade["id"],
            "asset_id": asset["id"],
            "accepted": accepted,
            "passed": passed,
        }

    def test_an_execution_one_second_past_the_review_deadline_is_refused(
        self, league: League
    ) -> None:
        """Every other execution precondition holds, including the physical.

        PRD 3.7: "A successful contingent acceptance stamps `accepted_at`, sets
        `medical_review_deadline_at` to `accepted_at` plus 72 hours, and increments
        both clubs' `open_medical_review_count` by 1."

        PRD 3.7: "A `MEDICAL_REVIEW` trade must satisfy all of those and two more:
        the logical clock must be at or before `medical_review_deadline_at`, or the
        answer is `ERR_MEDICAL_WINDOW_EXPIRED`; and every physical exam tied to this
        trade must be `PASSED` with an `expires_at` strictly later than the logical
        clock."

        Design: Corner/errors/executing_a_trade_after_its_medical_review_deadline_is_refused
        """
        world = self._contingent_trade_past_its_window(league)

        assert world["accepted"]["status"] == "MEDICAL_REVIEW", (
            "a contingent acceptance parks the trade in medical review, got "
            f"{world['accepted']['status']}"
        )
        assert world["accepted"]["medical_review_deadline_at"] == "2026-08-13T14:00:00.000Z", (
            "the review window runs 72 hours from acceptance, got "
            f"{world['accepted']['medical_review_deadline_at']}"
        )
        assert world["passed"]["expires_at"] == "2026-08-24T15:00:00.000Z", (
            "the trade physical is still valid, so the exam gate is satisfied, got "
            f"{world['passed']['expires_at']}"
        )

        response = league.api.execute_trade(world["trade_id"], league.officer)
        validate_error(response, ERR_MEDICAL_WINDOW_EXPIRED, 422)

        trade = league.trade(world["trade_id"])
        assert trade["status"] == "MEDICAL_REVIEW", (
            f"the trade is neither executed nor voided, got {trade['status']}"
        )
        assert trade["executed_at"] is None, (
            f"nothing was executed, got {trade['executed_at']}"
        )

    def test_the_refused_execution_transfers_nothing(
        self, league: League
    ) -> None:
        """Only the sweep voids such a trade, and no sweep has run.

        PRD 3.7: "And `MEDICAL_WINDOW_EXPIRED` covers a trade still in
        `MEDICAL_REVIEW` when the daily sweep finds the logical clock past
        `medical_review_deadline_at`."

        PRD 3.7: "Every `PROPOSED` asset moves `PROPOSED → TRANSFERRED`. For each
        `CONTRACT` asset the underlying contract's `team_id` and the player's
        `current_team_id` move to the receiving club, the player's
        `roster_designation` becomes `ACTIVE`, and their outgoing designation bucket
        accrues its elapsed days before `designation_effective_at` is reset to the
        logical clock."

        Design: Corner/errors/executing_a_trade_after_its_medical_review_deadline_is_refused
        """
        world = self._contingent_trade_past_its_window(league)

        league.api.execute_trade(world["trade_id"], league.officer)

        trade = league.trade(world["trade_id"])
        assert trade["void_reason"] is None, (
            "the refusal is not a void — that is the sweep's job, got "
            f"{trade['void_reason']}"
        )

        asset = find_by_id(
            league.trade_assets(world["trade_id"]), world["asset_id"]
        )
        assert asset["status"] == "PROPOSED", (
            f"the asset never transferred, got {asset['status']}"
        )
        assert asset["cap_charge_snapshot_cents"] == 83_333_333, (
            "and still carries the charge captured when it was added, got "
            f"{asset['cap_charge_snapshot_cents']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["team_id"] == world["initiator"]["id"], (
            f"the contract stayed with the sending club, got {contract['team_id']}"
        )
        player = league.player(world["player"]["id"])
        assert player["current_team_id"] == world["initiator"]["id"], (
            f"and so did the player, got {player['current_team_id']}"
        )

        initiator = league.club(world["initiator"]["id"])
        counterparty = league.club(world["counterparty"]["id"])
        assert initiator["active_roster_count"] == 1, (
            f"the sending club still holds him, got {initiator['active_roster_count']}"
        )
        assert counterparty["active_roster_count"] == 0, (
            f"and the receiving club holds nobody, got {counterparty['active_roster_count']}"
        )


class TestATradeThatWouldBreachTheReceivingCap:
    """Two consenting clubs, one arithmetic that does not fit."""

    @staticmethod
    def _accepted_trade_into_a_small_cap(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        initiator = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        counterparty = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=100_000_000, waiver_priority_rank=2,
        )
        star = league.register_player(full_name="Ray Alder", position="QB")
        incumbent = league.register_player(full_name="Milo Sarr", position="WR")
        expensive = league.sign_onto_roster(
            initiator["id"], star["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
            expected_team_version=initiator["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        held = league.sign_onto_roster(
            counterparty["id"], incumbent["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
            expected_team_version=counterparty["version"], years=7,
            base_salary_cents=30_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        trade = league.build_trade(initiator["id"], counterparty["id"], "NONE")
        asset = league.offer_contract(
            trade["id"], initiator["id"], expensive["contract_id"],
            "TO_COUNTERPARTY", expected_trade_version=trade["version"],
        )
        accepted = league.accept_trade(trade["id"], counterparty["id"])
        return {
            "initiator": initiator,
            "counterparty": counterparty,
            "star": star,
            "incumbent": incumbent,
            "expensive_contract_id": expensive["contract_id"],
            "held_contract_id": held["contract_id"],
            "trade_id": trade["id"],
            "asset_id": asset["id"],
            "accepted": accepted,
        }

    def test_an_execution_that_would_exceed_the_receiving_limit_is_refused(
        self, league: League
    ) -> None:
        """32,000,000 already committed plus 83,333,333 incoming beats 100,000,000.

        PRD 3.4: "When `years` is at most 5 every contract season carries a share;
        when `years` exceeds 5 the spread is clamped to five seasons, so each annual
        charge is larger than a simple division by `years` would give and seasons six
        onward carry no proration at all."

        PRD 3.4: "The contract's current-season charge is then `base_salary_cents`
        plus that share."

        PRD 3.7: "`cap_delta_initiating_cents` is the initiating club's incoming total
        less its outgoing total, and `cap_delta_counterparty_cents` is the counterparty
        club's incoming total less its outgoing total."

        PRD 3.7: "The compatibility test, applied at execution, requires that for
        **both** clubs the club's `provisional_cap_committed_cents` plus its own delta
        is at or below its `salary_cap_limit_cents`; a failure is reported for the
        offending club as `ERR_TRADE_CAP_INCOMPATIBLE`."

        Design: Corner/errors/executing_a_trade_that_pushes_the_receiving_club_over_its_cap_is_refused
        """
        world = self._accepted_trade_into_a_small_cap(league)

        receiver_before = league.club(world["counterparty"]["id"])
        assert receiver_before["provisional_cap_committed_cents"] == 32_000_000, (
            "a seven-year 30,000,000 deal with a 10,000,000 bonus prorated over the "
            "five-year ceiling charges 32,000,000, got "
            f"{receiver_before['provisional_cap_committed_cents']}"
        )
        assert world["accepted"]["cap_delta_counterparty_cents"] == 83_333_333, (
            "the receiving club takes on the whole snapshot, got "
            f"{world['accepted']['cap_delta_counterparty_cents']}"
        )
        assert world["accepted"]["cap_delta_initiating_cents"] == -83_333_333, (
            "and the sending club sheds it, got "
            f"{world['accepted']['cap_delta_initiating_cents']}"
        )

        response = league.api.execute_trade(world["trade_id"], league.officer)
        validate_error(response, ERR_TRADE_CAP_INCOMPATIBLE, 409)

        trade = league.trade(world["trade_id"])
        assert trade["status"] == "ACCEPTED", (
            f"the trade is still accepted but unexecuted, got {trade['status']}"
        )
        assert trade["executed_at"] is None, (
            f"nothing was executed, got {trade['executed_at']}"
        )

    def test_the_refused_execution_moves_neither_contract(
        self, league: League
    ) -> None:
        """Both rosters and both cap positions are exactly as they were.

        PRD 3.1: "`cap_space_cents` is always the club's `salary_cap_limit_cents`
        less its **provisional** commitment, and it is permitted to go negative."

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Corner/errors/executing_a_trade_that_pushes_the_receiving_club_over_its_cap_is_refused
        """
        world = self._accepted_trade_into_a_small_cap(league)

        league.api.execute_trade(world["trade_id"], league.officer)

        asset = find_by_id(
            league.trade_assets(world["trade_id"]), world["asset_id"]
        )
        assert asset["status"] == "PROPOSED", (
            f"the asset never transferred, got {asset['status']}"
        )
        assert asset["cap_charge_snapshot_cents"] == 83_333_333, (
            "and still carries the charge that made the trade impossible, got "
            f"{asset['cap_charge_snapshot_cents']}"
        )

        expensive = league.contract(world["expensive_contract_id"])
        assert expensive["team_id"] == world["initiator"]["id"], (
            f"the expensive contract stayed put, got {expensive['team_id']}"
        )
        held = league.contract(world["held_contract_id"])
        assert held["team_id"] == world["counterparty"]["id"], (
            f"and so did the receiving club's own contract, got {held['team_id']}"
        )
        star = league.player(world["star"]["id"])
        assert star["current_team_id"] == world["initiator"]["id"], (
            f"the traded player never moved, got {star['current_team_id']}"
        )

        initiator = league.club(world["initiator"]["id"])
        assert initiator["active_roster_count"] == 1, (
            f"the sending club still fields him, got {initiator['active_roster_count']}"
        )
        assert initiator["provisional_cap_committed_cents"] == 83_333_333, (
            "and still carries his charge, got "
            f"{initiator['provisional_cap_committed_cents']}"
        )

        counterparty = league.club(world["counterparty"]["id"])
        assert counterparty["active_roster_count"] == 1, (
            f"the receiving club gained nobody, got {counterparty['active_roster_count']}"
        )
        assert counterparty["provisional_cap_committed_cents"] == 32_000_000, (
            "its commitment is unchanged, got "
            f"{counterparty['provisional_cap_committed_cents']}"
        )
        assert counterparty["cap_space_cents"] == 68_000_000, (
            "100,000,000 less 32,000,000 leaves room for far less than the incoming "
            f"charge, got {counterparty['cap_space_cents']}"
        )
