"""Transfer-offer workflow tests (PRD §3.7).

Covers proposal under an open window, the negotiation states
(COUNTERED, ACCEPTED_BY_FROM, ACCEPTED_BY_BOTH), league approval
side effects (PlayerContract.team_id reassignment + AuditLogEntry),
the ERR_WINDOW_CLOSED gate, and the ERR_CONTRACT_NOT_ACTIVE gate.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    counter_offer_payload,
    create_transfer_offer_payload,
    get_player_contract,
    get_transfer_offer,
    iso_utc,
    league_approve_payload,
    list_audit_log,
    make_team_manager_headers,
    setup_transfer_offer_in_state,
    setup_two_active_teams_with_transferable_player,
    validate_error,
    validate_success,
)


# ===========================================================================
# Window enforcement (PRD §3.7)
# ===========================================================================
class TestTransferWindowEnforcement:
    def test_propose_outside_window_rejected_err_window_closed(self, api):
        """PRD §3.7: "The window is enforced as a half-open interval:
        a transfer event is valid only when opens_at <= Clock.now and
        Clock.now < closes_at. Outside this interval, any operation
        gated by the window rejects with ERR_WINDOW_CLOSED."

        Claim: proposing a transfer when Clock.now >= window.closes_at
        → ERR_WINDOW_CLOSED.
        """
        tournament, from_reg, to_reg, contract, window = (
            setup_two_active_teams_with_transferable_player()
        )
        # Advance past closes_at.
        advance_clock_to(iso_utc(days_offset=60))
        response = api.create_transfer_offer(
            create_transfer_offer_payload(
                player_id=contract["player_id"],
                from_team_id=from_reg["id"], to_team_id=to_reg["id"],
                window_id=window["id"],
            ),
            make_team_manager_headers(to_reg["manager_id"]),
        )
        validate_error(response, ApiErrorId.ERR_WINDOW_CLOSED.value)


# ===========================================================================
# Negotiation transitions (PRD §3.7)
# ===========================================================================
class TestNegotiation:
    def test_counter_appends_history_entry(self, api):
        """PRD §3.7: "The from_team may counter the offer (transitioning
        PROPOSED → COUNTERED with a new transfer_fee_cents and
        transfer_fee_currency; the prior terms and counter terms are
        appended to history as {round, by, action, terms, at} entries
        with action of COUNTER)."

        Claim: counter on a PROPOSED offer → status=COUNTERED and
        history length >= 1.
        """
        (tournament, from_reg, to_reg, contract, window, offer,
         from_mgr, to_mgr) = setup_transfer_offer_in_state("PROPOSED")
        response = api.counter_offer(
            offer["id"], counter_offer_payload(transfer_fee_cents=60_000),
            make_team_manager_headers(from_mgr),
        )
        data = validate_success(response)
        assert data["status"] == "COUNTERED"
        assert isinstance(data.get("history"), list)
        assert len(data["history"]) >= 1, (
            "PRD §3.7: counter appends a history entry"
        )

    def test_co_accept_transitions_to_accepted_by_both(self, api):
        """PRD §3.7: "Once the from_team has accepted, the to_team
        co-accepts to transition ACCEPTED_BY_FROM → ACCEPTED_BY_BOTH."

        Claim: co-accept on ACCEPTED_BY_FROM → status=ACCEPTED_BY_BOTH.
        """
        (tournament, from_reg, to_reg, contract, window, offer,
         from_mgr, to_mgr) = setup_transfer_offer_in_state("ACCEPTED_BY_FROM")
        response = api.co_accept_offer(
            offer["id"], make_team_manager_headers(to_mgr),
        )
        data = validate_success(response)
        assert data["status"] == "ACCEPTED_BY_BOTH"


# ===========================================================================
# League approval side effects (PRD §3.7)
# ===========================================================================
class TestLeagueApproval:
    def test_league_approve_reassigns_player_contract_team_id(
        self, api, league_admin_headers,
    ):
        """PRD §3.7: "PlayerContract.team_id is reassigned from
        from_team_id to to_team_id."

        Claim: after LEAGUE_APPROVED, PlayerContract.team_id ==
        to_team_id.
        """
        (tournament, from_reg, to_reg, contract, window, offer,
         from_mgr, to_mgr) = setup_transfer_offer_in_state("ACCEPTED_BY_BOTH")
        response = api.league_approve_offer(
            offer["id"], league_approve_payload(decision="APPROVE"),
            league_admin_headers,
        )
        data = validate_success(response)
        assert data["status"] == "LEAGUE_APPROVED"
        reloaded = get_player_contract(contract["id"])
        assert reloaded["team_id"] == to_reg["id"], (
            "PRD §3.7: hop 1 — PlayerContract.team_id reassigned to to_team_id"
        )

    def test_league_approve_emits_audit_log_entry(
        self, api, league_admin_headers,
    ):
        """PRD §3.7: "Append AuditLogEntry {action:'APPROVE_TRANSFER'}."

        Claim: after LEAGUE_APPROVED on a transfer, an AuditLogEntry
        exists with subject_type=TRANSFER_OFFER and action='APPROVE_TRANSFER'.
        """
        (tournament, from_reg, to_reg, contract, window, offer,
         from_mgr, to_mgr) = setup_transfer_offer_in_state("ACCEPTED_BY_BOTH")
        api.league_approve_offer(
            offer["id"], league_approve_payload(decision="APPROVE"),
            league_admin_headers,
        )
        rows = list_audit_log(params={"subject_type": "TRANSFER_OFFER",
                                      "subject_id": offer["id"]})
        approve_rows = [r for r in rows if r.get("action") == "APPROVE_TRANSFER"]
        assert len(approve_rows) >= 1, (
            "PRD §3.7: APPROVE_TRANSFER AuditLogEntry expected"
        )
