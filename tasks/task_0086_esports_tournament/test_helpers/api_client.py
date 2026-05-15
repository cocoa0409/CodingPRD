"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Tournament (PRD §3.1)
    # =======================================================================
    def create_tournament(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/tournaments", payload, headers)

    def get_tournament(self, tournament_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/tournaments/{tournament_id}", headers=headers,
        )

    def list_tournaments(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/tournaments", headers=headers, params=params,
        )

    def open_registration(self, tournament_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/open-registration",
            {}, headers,
        )

    def lock_rosters(self, tournament_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/lock-rosters",
            {}, headers,
        )

    def publish_bracket(self, tournament_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/publish-bracket",
            {}, headers,
        )

    def start_tournament(self, tournament_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/start",
            {}, headers,
        )

    def complete_tournament(self, tournament_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/complete",
            {}, headers,
        )

    def finalize_prize_pool(self, tournament_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/finalize-prize-pool",
            {}, headers,
        )

    def distribute_prizes(self, tournament_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/distribute-prizes",
            {}, headers,
        )

    def cancel_tournament(self, tournament_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/cancel",
            payload, headers,
        )

    def list_tournament_matches(self, tournament_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tournaments/{tournament_id}/matches",
            headers=headers, params=params,
        )

    def list_tournament_prize_payouts(self, tournament_id: str,
                                      headers: Dict[str, str],
                                      params: Optional[Dict[str, Any]] = None):
        """PRD §3.6 — convenience read for assertions. If implementations
        do not expose this list endpoint, tests can fall back to listing
        audit-log + read individual rows; tests that depend on this
        method only use it for ranking, sum invariants, etc."""
        return self._request(
            "GET", f"/tournaments/{tournament_id}/prize-payouts",
            headers=headers, params=params,
        )

    # =======================================================================
    # TeamRegistration (PRD §3.2)
    # =======================================================================
    def create_team_registration(self, tournament_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/team-registrations",
            payload, headers,
        )

    def get_team_registration(self, registration_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/team-registrations/{registration_id}",
            headers=headers,
        )

    def pay_entry_fee(self, registration_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/team-registrations/{registration_id}/pay-entry-fee",
            payload, headers,
        )

    def withdraw_team(self, registration_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/team-registrations/{registration_id}/withdraw",
            {}, headers,
        )

    # =======================================================================
    # PlayerContract (PRD §3.3)
    # =======================================================================
    def create_player_contract(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/player-contracts", payload, headers,
        )

    def get_player_contract(self, contract_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/player-contracts/{contract_id}",
            headers=headers,
        )

    def file_identity_verification(self, contract_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/player-contracts/{contract_id}/identity-verifications",
            payload, headers,
        )

    def initiate_signing(self, contract_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/player-contracts/{contract_id}/initiate-signing",
            {}, headers,
        )

    def sign_contract(self, contract_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/player-contracts/{contract_id}/sign",
            payload or {}, headers,
        )

    def file_amendment(self, contract_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/player-contracts/{contract_id}/amendments",
            payload, headers,
        )

    def approve_amendment(self, contract_id: str, amendment_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/player-contracts/{contract_id}/amendments/"
            f"{amendment_id}/approve",
            {}, headers,
        )

    def terminate_contract(self, contract_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/player-contracts/{contract_id}/terminate",
            payload, headers,
        )

    # =======================================================================
    # Match (PRD §3.4)
    # =======================================================================
    def get_match(self, match_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/matches/{match_id}", headers=headers,
        )

    def update_match(self, match_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/matches/{match_id}", payload, headers,
        )

    def assign_referee(self, match_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/matches/{match_id}/assign-referee",
            payload, headers,
        )

    def start_draft(self, match_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/matches/{match_id}/start-draft",
            {}, headers,
        )

    def post_draft_event(self, match_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/matches/{match_id}/draft-events",
            payload, headers,
        )

    def complete_draft(self, match_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/matches/{match_id}/complete-draft",
            {}, headers,
        )

    def report_result(self, match_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/matches/{match_id}/report-result",
            payload, headers,
        )

    def forfeit_match(self, match_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/matches/{match_id}/forfeit",
            payload, headers,
        )

    def list_draft_events(self, match_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/matches/{match_id}/draft-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # MatchIncident (PRD §3.5)
    # =======================================================================
    def file_incident(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/match-incidents", payload, headers,
        )

    def get_incident(self, incident_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/match-incidents/{incident_id}",
            headers=headers,
        )

    def assign_incident(self, incident_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/match-incidents/{incident_id}/assign",
            {}, headers,
        )

    def rule_incident(self, incident_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/match-incidents/{incident_id}/rule",
            payload, headers,
        )

    def appeal_incident(self, incident_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/match-incidents/{incident_id}/appeal",
            payload, headers,
        )

    def appeal_decide_incident(self, incident_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/match-incidents/{incident_id}/appeal-decide",
            payload, headers,
        )

    def close_incident(self, incident_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/match-incidents/{incident_id}/close",
            {}, headers,
        )

    # =======================================================================
    # Referee (PRD §3.4)
    # =======================================================================
    def create_referee(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/referees", payload, headers)

    def get_referee(self, referee_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/referees/{referee_id}", headers=headers,
        )

    def update_referee(self, referee_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/referees/{referee_id}", payload, headers,
        )

    # =======================================================================
    # CrowdfundContribution (PRD §3.7)
    # =======================================================================
    def create_crowdfund_contribution(self, tournament_id: str,
                                      payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tournaments/{tournament_id}/crowdfund-contributions",
            payload, headers,
        )

    # =======================================================================
    # TransferWindow + TransferOffer (PRD §3.7)
    # =======================================================================
    def create_transfer_window(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/transfer-windows", payload, headers,
        )

    def get_transfer_window(self, window_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/transfer-windows/{window_id}",
            headers=headers,
        )

    def create_transfer_offer(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/transfer-offers", payload, headers,
        )

    def get_transfer_offer(self, offer_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/transfer-offers/{offer_id}", headers=headers,
        )

    def counter_offer(self, offer_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-offers/{offer_id}/counter",
            payload, headers,
        )

    def accept_offer(self, offer_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-offers/{offer_id}/accept",
            {}, headers,
        )

    def co_accept_offer(self, offer_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-offers/{offer_id}/co-accept",
            {}, headers,
        )

    def reject_offer(self, offer_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-offers/{offer_id}/reject",
            payload, headers,
        )

    def league_approve_offer(self, offer_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-offers/{offer_id}/league-approve",
            payload, headers,
        )

    # =======================================================================
    # AuditLog (PRD §3.5 / §3.7)
    # =======================================================================
    def list_audit_log(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-log", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driver endpoints (PRD §2.7)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/run", {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
