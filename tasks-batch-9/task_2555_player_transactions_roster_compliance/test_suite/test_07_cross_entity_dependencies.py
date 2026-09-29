"""Writes on one record that are decided by the state of another."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers.api_errors import ERR_ASSET_NOT_OWNED, ERR_PHYSICAL_NOT_PASSED
from test_helpers.fixtures import League
from test_helpers.test_users import make_cap_analyst_headers

CLOCK = "2026-08-10T14:00:00Z"


class TestSigningApprovalDependsOnExamValidity:
    """A perfect filing is refused because its exam has just stopped counting."""

    @staticmethod
    def _filed_signing_with_exam_expiring_now(league: League) -> Dict[str, Any]:
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
        exam = league.pass_entry_physical(
            club["id"], player["id"], filing["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T20:00:00Z",
            performed_at=CLOCK,
        )
        league.submit_filing(filing["id"], club["id"])
        league.set_clock("2026-08-24T14:00:00Z")
        return {
            "club": club,
            "player": player,
            "filing_id": filing["id"],
            "contract_id": filing["contract_id"],
            "exam": exam,
        }

    def test_an_exam_expiring_exactly_now_is_no_longer_citable(
        self, league: League
    ) -> None:
        """Validity is strict, so the boundary instant already fails the approval.

        PRD 3.5: "Validity is tested strictly: an approval may cite an exam only
        while that exam is `PASSED` and its `expires_at` is strictly later than the
        logical clock, so an exam performed at 2026-08-10T14:00:00Z may still be
        cited at 2026-08-24T13:59:59Z but no longer at 2026-08-24T14:00:00Z, at
        which point the sweep moves it `PASSED → EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/signing_approval_depends_on_unexpired_physical_exam_state
        """
        world = self._filed_signing_with_exam_expiring_now(league)

        assert world["exam"]["expires_at"] == "2026-08-24T14:00:00.000Z", (
            "a pass expires 14 days after it was performed, got "
            f"{world['exam']['expires_at']}"
        )

        response = league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(), league.officer
        )
        validate_error(response, ERR_PHYSICAL_NOT_PASSED, 422)

        exam = league.exam(world["exam"]["id"])
        assert exam["status"] == "PASSED", (
            "no sweep has run, so the exam row itself is still PASSED even though "
            f"it is no longer citable, got {exam['status']}"
        )

    def test_the_refused_approval_leaves_the_whole_signing_where_it_was(
        self, league: League
    ) -> None:
        """The filing stays filed, the contract pending and the player unrostered.

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Difficulty/cross_entity_state_dependency/signing_approval_depends_on_unexpired_physical_exam_state
        """
        world = self._filed_signing_with_exam_expiring_now(league)

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
        assert filing["requires_physical"] is True, (
            "a signing filing demands a physical, got "
            f"{filing['requires_physical']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "PENDING_APPROVAL", (
            f"the contract should still be pending, got {contract['status']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player joined nobody, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"an unrostered player has no club, got {player['current_team_id']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 0, (
            f"the active headcount is unchanged, got {club['active_roster_count']}"
        )
        assert club["provisional_cap_committed_cents"] == 83_333_333, (
            "the pending contract still consumes provisional room, got "
            f"{club['provisional_cap_committed_cents']}"
        )


class TestTradeAssetAdmissionDependsOnContractOwnership:
    """A club cannot offer somebody else's contract."""

    @staticmethod
    def _trade_offering_the_wrong_clubs_contract(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        initiator = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        owner = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            owner["id"], player["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T20:00:00Z",
            performed_at=CLOCK,
            expected_team_version=owner["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        trade = league.build_trade(initiator["id"], owner["id"], "NONE")
        return {
            "initiator": initiator,
            "owner": owner,
            "player": player,
            "contract_id": signing["contract_id"],
            "trade": trade,
        }

    def test_offering_a_contract_the_sender_does_not_own_is_refused(
        self, league: League
    ) -> None:
        """The trade is impeccable; the other entity's owner field is not.

        PRD 3.7: "A `CONTRACT` asset must reference a contract whose `status` is
        `ACTIVE` and whose `team_id` is the sending club, or the request fails with
        `ERR_ASSET_NOT_OWNED` — and that same ownership test is applied again at
        execution time, because a contract can change hands in between."

        Design: Difficulty/cross_entity_state_dependency/trade_asset_admission_depends_on_contract_ownership_by_sender
        """
        world = self._trade_offering_the_wrong_clubs_contract(league)

        response = league.api.add_trade_asset(
            world["trade"]["id"],
            fac.contract_asset_payload(
                world["contract_id"], "TO_COUNTERPARTY",
                world["trade"]["version"],
            ),
            make_cap_analyst_headers(world["initiator"]["id"]),
        )
        validate_error(response, ERR_ASSET_NOT_OWNED, 422)

        contract = league.contract(world["contract_id"])
        assert contract["team_id"] == world["owner"]["id"], (
            "the contract belongs to the counterparty, which is exactly why the "
            f"admission failed, got {contract['team_id']}"
        )
        assert contract["status"] == "ACTIVE", (
            f"the contract itself is perfectly tradeable, got {contract['status']}"
        )

    def test_the_refused_admission_leaves_the_trade_untouched(
        self, league: League
    ) -> None:
        """No asset row, no version bump, no cap delta.

        PRD 3.7: "The asset is born `PROPOSED` and every addition re-derives both
        clubs' cap deltas and increments the trade's `version`."

        Design: Difficulty/cross_entity_state_dependency/trade_asset_admission_depends_on_contract_ownership_by_sender
        """
        world = self._trade_offering_the_wrong_clubs_contract(league)

        league.api.add_trade_asset(
            world["trade"]["id"],
            fac.contract_asset_payload(
                world["contract_id"], "TO_COUNTERPARTY",
                world["trade"]["version"],
            ),
            make_cap_analyst_headers(world["initiator"]["id"]),
        )

        assets, meta = validate_paginated(
            league.api.list_trade_assets(world["trade"]["id"], league.officer)
        )
        assert meta["total_count"] == 0, (
            f"no asset should have been created, got {meta['total_count']}"
        )
        assert assets == [], f"the asset list should be empty, got {assets}"

        trade = league.trade(world["trade"]["id"])
        assert trade["version"] == world["trade"]["version"], (
            f"the rejected admission bumped nothing, got version {trade['version']}"
        )
        assert trade["status"] == "PROPOSED", (
            f"the trade is still on the table, got {trade['status']}"
        )
        assert trade["round_count"] == 1, (
            f"no negotiation round was consumed, got {trade['round_count']}"
        )
        assert trade["cap_delta_initiating_cents"] == 0, (
            f"there is nothing to value, got {trade['cap_delta_initiating_cents']}"
        )
        assert trade["cap_delta_counterparty_cents"] == 0, (
            f"and nothing on the other side either, got {trade['cap_delta_counterparty_cents']}"
        )

        player = league.player(world["player"]["id"])
        assert player["current_team_id"] == world["owner"]["id"], (
            f"the player never moved, got {player['current_team_id']}"
        )


class TestIrActivationDependsOnDesignationWindowState:
    """The same approval is refused, then granted, because a designation moved."""

    ACTIVATION_INSTANT = "2026-08-31T14:00:00Z"

    @staticmethod
    def _filed_activation_before_the_window_opens(league: League) -> Dict[str, Any]:
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
        placement = league.place_on_injured_reserve(club["id"], player["id"])

        league.set_clock(TestIrActivationDependsOnDesignationWindowState.ACTIVATION_INSTANT)
        activation = league.open_ir_activation(
            club["id"], player["id"], placement["designation_id"]
        )
        exam = league.schedule_exam(
            club["id"], player["id"], "RETURN_PHYSICAL",
            "2026-08-31T13:00:00Z", "2026-08-31T20:00:00Z",
            transaction_id=activation["id"],
        )
        league.record_exam(
            exam["id"], club["id"], "PASSED",
            TestIrActivationDependsOnDesignationWindowState.ACTIVATION_INSTANT,
        )
        league.submit_filing(activation["id"], club["id"])
        return {
            "club": club,
            "player": player,
            "contract_id": signing["contract_id"],
            "designation_id": placement["designation_id"],
            "activation_id": activation["id"],
            "exam_id": exam["id"],
        }

    def test_the_sweep_and_not_the_filing_opens_the_return_window(
        self, league: League
    ) -> None:
        """A filed activation cannot advance itself past a designation still ACTIVE.

        PRD 3.5: "The window opens on the clock, not on request: the daily sweep
        moves a designation `ACTIVE → RETURN_WINDOW_OPEN` once the logical clock has
        reached `return_window_opens_at` and has not yet passed
        `return_window_closes_at`, and that step changes no roster or cap value — it
        merely makes the `IR_ACTIVATION` filing approvable."

        Design: Difficulty/cross_entity_state_dependency/ir_activation_approval_depends_on_designation_return_window_state
        """
        world = self._filed_activation_before_the_window_opens(league)

        before = league.designation(world["designation_id"])
        assert before["status"] == "ACTIVE", (
            "reaching the opening instant does not by itself move the designation, "
            f"got {before['status']}"
        )
        assert before["return_window_opens_at"] == "2026-08-31T14:00:00.000Z", (
            "the window opens 21 days after activation, got "
            f"{before['return_window_opens_at']}"
        )

        league.api.decide_transaction(
            world["activation_id"], fac.approve_payload(), league.officer
        )

        filing = league.filing(world["activation_id"])
        assert filing["status"] == "FILED", (
            "an approval blocked by the designation's state writes nothing, so the "
            f"filing is still FILED, got {filing['status']}"
        )
        assert filing["decided_at"] is None, (
            f"no decision instant should be stamped, got {filing['decided_at']}"
        )
        untouched = league.designation(world["designation_id"])
        assert untouched["status"] == "ACTIVE", (
            f"the designation is likewise untouched, got {untouched['status']}"
        )
        assert untouched["closed_at"] is None, (
            f"nothing closed the designation, got {untouched['closed_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "INJURED_RESERVE", (
            f"the player is still on injured reserve, got {player['roster_designation']}"
        )

        sweep = league.run_sweep(world["club"]["id"])
        assert sweep["result"] == "COMPLIANT", (
            f"the club breaks no quota, so the sweep passes, got {sweep['result']}"
        )
        opened = league.designation(world["designation_id"])
        assert opened["status"] == "RETURN_WINDOW_OPEN", (
            f"the sweep should open the return window, got {opened['status']}"
        )
        assert opened["closed_at"] is None, (
            f"opening the window closes nothing, got {opened['closed_at']}"
        )

        swept_club = league.club(world["club"]["id"])
        assert swept_club["injured_reserve_count"] == 1, (
            "opening the window changes no roster value, got "
            f"{swept_club['injured_reserve_count']}"
        )
        assert swept_club["provisional_cap_committed_cents"] == 83_333_333, (
            "and no cap value either, got "
            f"{swept_club['provisional_cap_committed_cents']}"
        )

    def test_the_identical_approval_succeeds_once_the_window_is_open(
        self, league: League
    ) -> None:
        """With the other record advanced, the same request runs the full cascade.

        PRD 3.3: "**`IR_ACTIVATION`**: the player's designation becomes `ACTIVE` and
        their `medical_status` returns to `CLEARED`; the cited designation moves
        `RETURN_WINDOW_OPEN → CLOSED` with `closed_at` set to the logical clock and
        `ir_service_credit_days` computed as the floored whole days between
        `activated_at` and `closed_at`."

        Design: Difficulty/cross_entity_state_dependency/ir_activation_approval_depends_on_designation_return_window_state
        """
        world = self._filed_activation_before_the_window_opens(league)
        league.run_sweep(world["club"]["id"])

        approved = league.approve_filing(world["activation_id"])

        assert approved["status"] == "APPROVED", (
            f"the second attempt should be approved, got {approved['status']}"
        )
        assert approved["effective_at"] == "2026-08-31T14:00:00.000Z", (
            f"the activation takes effect on the clock, got {approved['effective_at']}"
        )
        assert approved["prior_designation"] == "INJURED_RESERVE", (
            "the snapshot records where the player was before the cascade, got "
            f"{approved['prior_designation']}"
        )

        designation = league.designation(world["designation_id"])
        assert designation["status"] == "CLOSED", (
            f"the designation should now be CLOSED, got {designation['status']}"
        )
        assert designation["closed_at"] == "2026-08-31T14:00:00.000Z", (
            f"the close instant is the logical clock, got {designation['closed_at']}"
        )
        assert designation["ir_service_credit_days"] == 21, (
            "21 whole days separate activation from closure, got "
            f"{designation['ir_service_credit_days']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            f"the player returns to the active roster, got {player['roster_designation']}"
        )
        assert player["medical_status"] == "CLEARED", (
            f"and is medically cleared again, got {player['medical_status']}"
        )
        assert player["accrued_ir_days"] == 21, (
            "the injured-reserve bucket absorbs the elapsed days, got "
            f"{player['accrued_ir_days']}"
        )
        assert player["pension_credit_days"] == 21, (
            "pension credit takes those days at full weight, got "
            f"{player['pension_credit_days']}"
        )
        assert player["roster_service_days"] == 10, (
            "roster service takes them at half weight, floored, got "
            f"{player['roster_service_days']}"
        )

        club = league.club(world["club"]["id"])
        assert club["injured_reserve_count"] == 0, (
            f"the injured-reserve headcount empties, got {club['injured_reserve_count']}"
        )
        assert club["active_roster_count"] == 1, (
            f"the active headcount takes the player, got {club['active_roster_count']}"
        )
        assert club["compliance_status"] == "COMPLIANT", (
            f"the club breaks nothing, got {club['compliance_status']}"
        )
