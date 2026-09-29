"""State refusals: which dimension of a record answers, and with which error."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_INVALID_CONTRACT_STATE,
    ERR_INVALID_OPTION_STATE,
    ERR_INVALID_TENDER_STATE,
    ERR_INVALID_TRADE_STATE,
)
from test_helpers.assertions import find_by_id
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"
TERMS = {
    "years": 3,
    "base_salary_cents": 80_000_000,
    "signing_bonus_cents": 10_000_000,
    "start_season_year": 2026,
}


def _rostered(league: League, **terms: Any) -> Dict[str, Any]:
    """One club with one player signed to a three-year deal."""
    league.set_clock(CLOCK)
    club = league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
    )
    player = league.register_player(full_name="Ray Alder", position="QB")
    signing = league.sign_onto_roster(
        club["id"], player["id"],
        window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
        expected_team_version=club["version"], **{**TERMS, **terms},
    )
    return {
        "club": club,
        "player": player,
        "contract_id": signing["contract_id"],
    }


class TestAnOptionDecisionOnAContractWithoutAnOption:
    """The status dimension is fine; the option dimension never opened."""

    def test_exercising_a_contract_that_carries_no_option_is_refused(
        self, league: League
    ) -> None:
        """NOT_APPLICABLE is not PENDING, so the option dimension answers.

        PRD 3.4: "An `option_type` of `NONE` leaves the dimension at
        `NOT_APPLICABLE` forever, and an attempt to decide an option that is not
        `PENDING` — never applicable, or already resolved — is refused with
        `ERR_INVALID_OPTION_STATE`."

        PRD 2.8: "The target record is in a state that has an outgoing transition
        for this trigger, including the parallel dimension the trigger writes —
        otherwise the matching 409 state error (`ERR_INVALID_TRANSACTION_STATE`,
        `ERR_INVALID_CONTRACT_STATE`, `ERR_INVALID_OPTION_STATE`,
        `ERR_INVALID_WAIVER_STATE`, `ERR_INVALID_TRADE_STATE`,
        `ERR_INVALID_TENDER_STATE`, `ERR_INVALID_DESIGNATION_STATE`,
        `ERR_INVALID_EXAM_STATE`)."

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Corner/errors/an_option_decision_on_a_contract_that_carries_no_option_is_refused
        """
        world = _rostered(league)

        before = league.contract(world["contract_id"])
        assert before["status"] == "ACTIVE", (
            "the contract status itself allows an option decision, got "
            f"{before['status']}"
        )
        assert before["option_type"] == "NONE", (
            f"this deal carries no option clause, got {before['option_type']}"
        )
        assert before["option_status"] == "NOT_APPLICABLE", (
            "so the parallel dimension never left NOT_APPLICABLE, got "
            f"{before['option_status']}"
        )

        response = league.api.decide_option(
            world["contract_id"],
            fac.option_decision_payload("EXERCISE", before["version"]),
            League.analyst(world["club"]),
        )
        validate_error(response, ERR_INVALID_OPTION_STATE, 409)

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the contract is untouched, got {contract['status']}"
        )
        assert contract["option_status"] == "NOT_APPLICABLE", (
            f"and so is its option dimension, got {contract['option_status']}"
        )
        assert contract["version"] == before["version"], (
            "a refused decision increments no version, got "
            f"{contract['version']}"
        )
        assert contract["base_salary_cents"] == 80_000_000, (
            "no option salary replaced the base salary, got "
            f"{contract['base_salary_cents']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            f"the player keeps his place on the roster, got {player['roster_designation']}"
        )
        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 1, (
            f"the active headcount is unchanged, got {club['active_roster_count']}"
        )


class TestAnOptionDecisionOnATerminatedContract:
    """The option dimension is PENDING; the status dimension has moved on."""

    @staticmethod
    def _cleared_release_of_an_optioned_contract(league: League) -> Dict[str, Any]:
        world = _rostered(
            league, option_type="TEAM_OPTION",
            option_deadline_at="2026-12-01T14:00:00Z",
            option_salary_cents=40_000_000,
        )
        wire = league.release_onto_wire(world["club"]["id"], world["player"]["id"])
        world["waiver_request_id"] = wire["waiver_request_id"]
        world["clearance_deadline_at"] = (
            wire["waiver_request"]["clearance_deadline_at"]
        )
        league.set_clock("2026-08-11T14:00:00Z")
        world["processed"] = league.process_wire(wire["waiver_request_id"])
        return world

    def test_a_contract_terminated_by_clearance_answers_on_its_status(
        self, league: League
    ) -> None:
        """The exercise edge exists but demands an ACTIVE contract.

        PRD 3.4: "In both cases the contract's `status` must be `ACTIVE`, the
        logical clock must be at or before `option_deadline_at` — a decision landing
        exactly on the deadline instant is accepted, and only a clock strictly later
        is refused with `ERR_OPTION_DEADLINE_PASSED` — and the request must carry
        `expected_contract_version` matching the contract's current `version`."

        PRD 2.8: "The target record is in a state that has an outgoing transition
        for this trigger, including the parallel dimension the trigger writes —
        otherwise the matching 409 state error (`ERR_INVALID_TRANSACTION_STATE`,
        `ERR_INVALID_CONTRACT_STATE`, `ERR_INVALID_OPTION_STATE`,
        `ERR_INVALID_WAIVER_STATE`, `ERR_INVALID_TRADE_STATE`,
        `ERR_INVALID_TENDER_STATE`, `ERR_INVALID_DESIGNATION_STATE`,
        `ERR_INVALID_EXAM_STATE`)."

        PRD 3.6: "`clearance_deadline_at` is `placed_at` plus 24 hours for a
        `REVOCABLE` placement or plus 48 hours for an `IRREVOCABLE` one, snapped
        into the daily processing window per §2.5."

        PRD 3.6: "If no claim survives the three filters, the wire moves `PENDING →
        CLEARED` instead. `processed_at` is stamped, every `SUBMITTED` claim is
        moved to `INVALIDATED`, the player's `roster_designation` moves
        `WAIVED_PENDING → UNROSTERED` with `current_team_id` set to null, and the
        contract moves `ACTIVE → TERMINATED` with `termination_reason`
        `RELEASE_CLEARED`, running the full acceleration-and-forfeiture cascade of
        §3.4."

        Design: Corner/errors/an_option_decision_on_a_contract_terminated_by_waiver_clearance_is_refused
        """
        world = self._cleared_release_of_an_optioned_contract(league)

        assert world["clearance_deadline_at"] == "2026-08-11T14:00:00.000Z", (
            "a revocable wire placed at 14:00 clears 24 hours later, got "
            f"{world['clearance_deadline_at']}"
        )
        assert world["processed"]["status"] == "CLEARED", (
            f"an unclaimed wire clears, got {world['processed']['status']}"
        )

        before = league.contract(world["contract_id"])
        assert before["status"] == "TERMINATED", (
            f"the clearance terminated the contract, got {before['status']}"
        )
        assert before["termination_reason"] == "RELEASE_CLEARED", (
            f"and named the clearance as the reason, got {before['termination_reason']}"
        )
        assert before["option_status"] == "PENDING", (
            "the option dimension advanced independently and is still PENDING, got "
            f"{before['option_status']}"
        )

        response = league.api.decide_option(
            world["contract_id"],
            fac.option_decision_payload("EXERCISE", before["version"]),
            League.analyst(world["club"]),
        )
        validate_error(response, ERR_INVALID_CONTRACT_STATE, 409)

        contract = league.contract(world["contract_id"])
        assert contract["option_status"] == "PENDING", (
            "the option dimension is left exactly where it was, got "
            f"{contract['option_status']}"
        )
        assert contract["version"] == before["version"], (
            f"a refused decision increments no version, got {contract['version']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the cleared player belongs to nobody, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"and has no club, got {player['current_team_id']}"
        )
        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 0, (
            f"the releasing club's roster is empty, got {club['active_roster_count']}"
        )


class TestCounteringAnAcceptedTrade:
    """The version is current; the state simply has no counter edge left."""

    @staticmethod
    def _accepted_trade(league: League) -> Dict[str, Any]:
        world = _rostered(league)
        counterparty = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        trade = league.build_trade(
            world["club"]["id"], counterparty["id"], "NONE"
        )
        asset = league.offer_contract(
            trade["id"], world["club"]["id"], world["contract_id"],
            "TO_COUNTERPARTY", expected_trade_version=trade["version"],
        )
        world["counterparty"] = counterparty
        world["trade_id"] = trade["id"]
        world["asset_id"] = asset["id"]
        world["accepted"] = league.accept_trade(trade["id"], counterparty["id"])
        return world

    def test_a_counter_on_an_accepted_trade_is_refused(
        self, league: League
    ) -> None:
        """Countering is an edge out of PROPOSED or COUNTERED only.

        PRD 3.7: "The negotiation alternates strictly. From `PROPOSED`, only the
        counterparty club may counter, moving the trade `PROPOSED → COUNTERED`; from
        `COUNTERED`, only the initiating club may counter back, moving it `COUNTERED
        → PROPOSED` and closing the cycle."

        PRD 2.8: "The target record is in a state that has an outgoing transition
        for this trigger, including the parallel dimension the trigger writes —
        otherwise the matching 409 state error (`ERR_INVALID_TRANSACTION_STATE`,
        `ERR_INVALID_CONTRACT_STATE`, `ERR_INVALID_OPTION_STATE`,
        `ERR_INVALID_WAIVER_STATE`, `ERR_INVALID_TRADE_STATE`,
        `ERR_INVALID_TENDER_STATE`, `ERR_INVALID_DESIGNATION_STATE`,
        `ERR_INVALID_EXAM_STATE`)."

        Design: Corner/errors/countering_a_trade_that_was_already_accepted_is_refused
        """
        world = self._accepted_trade(league)

        assert world["accepted"]["status"] == "ACCEPTED", (
            "a plain trade accepted by the counterparty is ACCEPTED, got "
            f"{world['accepted']['status']}"
        )
        assert world["accepted"]["round_count"] == 1, (
            "the trade was created with round_count at 1 and no counter has run, "
            f"got {world['accepted']['round_count']}"
        )

        before = league.trade(world["trade_id"])
        response = league.api.counter_trade(
            world["trade_id"], fac.counter_payload(before["version"]),
            League.analyst(world["counterparty"]),
        )
        validate_error(response, ERR_INVALID_TRADE_STATE, 409)

        trade = league.trade(world["trade_id"])
        assert trade["status"] == "ACCEPTED", (
            f"the acceptance stands, got {trade['status']}"
        )
        assert trade["round_count"] == 1, (
            "the refused counter consumed no round, got "
            f"{trade['round_count']}"
        )
        assert trade["version"] == before["version"], (
            f"and bumped no version, got {trade['version']}"
        )

    def test_the_refused_counter_leaves_the_asset_and_the_contract_alone(
        self, league: League
    ) -> None:
        """The offered contract is still proposed, and still at its own club.

        PRD 3.7: "Adding an asset stores its `cap_charge_snapshot_cents`: for a
        `CONTRACT` asset that is the referenced contract's
        `current_season_cap_charge_cents` as it stands at the moment of the
        addition; for a `CASH_CONSIDERATION` asset it is the `cash_amount_cents`;
        and for a `DRAFT_PICK` asset it is 0."

        PRD 3.7: "Execution moves the trade to `EXECUTED`, stamps `executed_at`, and
        stores both `cap_delta_initiating_cents` and `cap_delta_counterparty_cents`.
        Every `PROPOSED` asset moves `PROPOSED → TRANSFERRED`."

        Design: Corner/errors/countering_a_trade_that_was_already_accepted_is_refused
        """
        world = self._accepted_trade(league)

        before = league.trade(world["trade_id"])
        league.api.counter_trade(
            world["trade_id"], fac.counter_payload(before["version"]),
            League.analyst(world["counterparty"]),
        )

        asset = find_by_id(
            league.trade_assets(world["trade_id"]), world["asset_id"]
        )
        assert asset["status"] == "PROPOSED", (
            "only an execution transfers an asset, so it is still PROPOSED, got "
            f"{asset['status']}"
        )
        assert asset["cap_charge_snapshot_cents"] == 83_333_333, (
            "the snapshot is the contract's current-season charge, got "
            f"{asset['cap_charge_snapshot_cents']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["team_id"] == world["club"]["id"], (
            f"nothing changed hands, got {contract['team_id']}"
        )
        assert contract["status"] == "ACTIVE", (
            f"and the contract is still live, got {contract['status']}"
        )

        counterparty = league.club(world["counterparty"]["id"])
        assert counterparty["active_roster_count"] == 0, (
            "the receiving club has taken on nobody, got "
            f"{counterparty['active_roster_count']}"
        )
        assert counterparty["provisional_cap_committed_cents"] == 0, (
            "and no charge, got "
            f"{counterparty['provisional_cap_committed_cents']}"
        )


class TestRespondingTwiceToOneTender:
    """DECLINED is terminal, and the first answer's timestamp survives.

    PRD 3.8: "Only the player's own agent may answer, supplying a `response` of
    either `ACCEPT` or `DECLINE`, and only while the logical clock is at or before
    `deadline_at` — a response strictly later is refused with
    `ERR_TENDER_DEADLINE_PASSED`."
    """

    @staticmethod
    def _declined_tender(league: League) -> Dict[str, Any]:
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
        declined = league.respond_to_tender(
            tender["id"], player["id"], "DECLINE"
        )
        return {
            "club": club,
            "player": player,
            "tender": tender,
            "declined": declined,
        }

    def test_a_second_answer_to_a_declined_tender_is_refused(
        self, league: League
    ) -> None:
        """The deadline has not passed; the tender simply is no longer ISSUED.

        PRD 3.8: "Answering a tender that is not `ISSUED` is
        `ERR_INVALID_TENDER_STATE`."

        PRD 3.8: "Either answer stamps `responded_at` with the logical clock."

        Design: Corner/errors/responding_twice_to_one_tender_is_refused
        """
        world = self._declined_tender(league)

        assert world["tender"]["deadline_at"] == "2026-08-13T14:00:00.000Z", (
            "the answer window runs 72 hours from issuance, so the second attempt "
            f"is well inside it, got {world['tender']['deadline_at']}"
        )
        assert world["declined"]["status"] == "DECLINED", (
            f"the first answer declined the tender, got {world['declined']['status']}"
        )
        assert world["declined"]["responded_at"] == "2026-08-10T14:00:00.000Z", (
            "and stamped the logical clock, got "
            f"{world['declined']['responded_at']}"
        )

        response = league.api.respond_to_tender(
            world["tender"]["id"], fac.tender_response_payload("ACCEPT"),
            League.agent(world["player"]),
        )
        validate_error(response, ERR_INVALID_TENDER_STATE, 409)

        tender = league.tender(world["tender"]["id"])
        assert tender["status"] == "DECLINED", (
            f"the decline stands, got {tender['status']}"
        )
        assert tender["responded_at"] == "2026-08-10T14:00:00.000Z", (
            "and the first answer's instant is preserved rather than overwritten, "
            f"got {tender['responded_at']}"
        )

    def test_the_refused_answer_creates_no_filing_and_no_contract(
        self, league: League
    ) -> None:
        """An accept would have cascaded into a draft filing; this one does not.

        PRD 3.8: "A decline moves the tender `ISSUED → DECLINED` and changes nothing
        else — no filing is created."

        PRD 3.8: "Because the tender was accepted, a filing of type `SIGNING` is
        created for that club and player in `DRAFT` status, and
        `resulting_transaction_id` is set to point at it."

        PRD 3.2: "`service_years` is the floor of `pension_credit_days` divided by
        170 days per season, and it selects the player's `contract_rights_class`:
        `UNRESTRICTED` at 4 or more service years, `ARBITRATION_ELIGIBLE` at exactly
        3, `RESTRICTED` at 1 or 2, and `NONE` at 0."

        Design: Corner/errors/responding_twice_to_one_tender_is_refused
        """
        world = self._declined_tender(league)

        player_before = league.player(world["player"]["id"])
        assert player_before["service_years"] == 2, (
            "400 pension-credit days floor to two service years, got "
            f"{player_before['service_years']}"
        )
        assert player_before["contract_rights_class"] == "RESTRICTED", (
            "which makes his rights restricted and the tender legal in the first "
            f"place, got {player_before['contract_rights_class']}"
        )
        assert world["tender"]["amount_cents"] == 66_000_000, (
            "a first-round restricted tender over a 50000000 prior base amounts to "
            f"66000000, got {world['tender']['amount_cents']}"
        )

        league.api.respond_to_tender(
            world["tender"]["id"], fac.tender_response_payload("ACCEPT"),
            League.agent(world["player"]),
        )

        tender = league.tender(world["tender"]["id"])
        assert tender["resulting_transaction_id"] is None, (
            "no filing was ever spawned, so the link stays null, got "
            f"{tender['resulting_transaction_id']}"
        )

        _, filing_meta = validate_paginated(
            league.api.list_transactions(league.officer)
        )
        assert filing_meta["total_count"] == 0, (
            f"no filing should exist at all, got {filing_meta['total_count']}"
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
            "and the club has committed nothing, got "
            f"{club['provisional_cap_committed_cents']}"
        )
