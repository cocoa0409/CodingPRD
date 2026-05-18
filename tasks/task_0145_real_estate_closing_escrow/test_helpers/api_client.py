"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.

PRD §2.7: every POST and state-transition endpoint requires
Idempotency-Key. The runner / GenericApiClient injects a fresh key per
call unless one is provided in headers.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Parties — PRD §3.1
    # =======================================================================
    def create_party(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/parties", payload, headers)

    def get_party(self, party_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/parties/{party_id}", headers=headers,
        )

    # =======================================================================
    # Properties — PRD §3.1
    # =======================================================================
    def create_property(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/properties/{property_id}", headers=headers,
        )

    # =======================================================================
    # Escrow files — PRD §3.2, §3.9
    # =======================================================================
    def create_escrow_file(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/escrow-files", payload, headers)

    def get_escrow_file(self, escrow_file_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/escrow-files/{escrow_file_id}", headers=headers,
        )

    def list_escrow_files(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/escrow-files", headers=headers, params=params,
        )

    def advance_escrow_file(self, escrow_file_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/escrow-files/{escrow_file_id}/advance",
            payload if payload is not None else {}, headers,
        )

    def close_escrow_file(self, escrow_file_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/escrow-files/{escrow_file_id}/close",
            payload, headers,
        )

    def cancel_escrow_file(self, escrow_file_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/escrow-files/{escrow_file_id}/cancel",
            payload, headers,
        )

    def list_audit_events(self, escrow_file_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/escrow-files/{escrow_file_id}/audit-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Earnest Money Deposit — PRD §3.2
    # =======================================================================
    def create_emd(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/earnest-money", payload, headers)

    def get_emd(self, emd_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/earnest-money/{emd_id}", headers=headers,
        )

    def fund_emd(self, emd_id: str, payload: Dict[str, Any],
                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/earnest-money/{emd_id}/fund", payload, headers,
        )

    def release_emd(self, emd_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/earnest-money/{emd_id}/release",
            payload, headers,
        )

    # =======================================================================
    # Title search — PRD §3.3
    # =======================================================================
    def create_title_search(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/title-searches", payload, headers,
        )

    def patch_title_search(self, title_search_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/title-searches/{title_search_id}",
            payload, headers,
        )

    def clear_title_search(self, title_search_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/title-searches/{title_search_id}/clear",
            payload, headers,
        )

    def mark_title_search_defective(self, title_search_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/title-searches/{title_search_id}/mark-defective",
            payload, headers,
        )

    def get_title_search(self, title_search_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/title-searches/{title_search_id}",
            headers=headers,
        )

    # =======================================================================
    # Title insurance policy — PRD §3.3
    # =======================================================================
    def create_title_policy(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/title-policies", payload, headers,
        )

    def get_title_policy(self, policy_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/title-policies/{policy_id}", headers=headers,
        )

    def bind_title_policy(self, policy_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/title-policies/{policy_id}/bind",
            payload, headers,
        )

    def void_title_policy(self, policy_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/title-policies/{policy_id}/void",
            payload, headers,
        )

    # =======================================================================
    # CCR disclosure — PRD §3.4
    # =======================================================================
    def create_ccr_disclosure(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/ccr-disclosures", payload, headers,
        )

    def get_ccr_disclosure(self, ccr_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/ccr-disclosures/{ccr_id}", headers=headers,
        )

    # =======================================================================
    # Closing disclosure — PRD §3.5
    # =======================================================================
    def create_closing_disclosure(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/closing-disclosures", payload, headers,
        )

    def get_closing_disclosure(self, cd_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/closing-disclosures/{cd_id}", headers=headers,
        )

    def issue_closing_disclosure(self, cd_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/closing-disclosures/{cd_id}/issue",
            payload, headers,
        )

    def acknowledge_closing_disclosure(self, cd_id: str,
                                       payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/closing-disclosures/{cd_id}/acknowledge",
            payload, headers,
        )

    def promote_closing_disclosure(self, cd_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/closing-disclosures/{cd_id}/promote",
            payload, headers,
        )

    def revise_closing_disclosure(self, cd_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/closing-disclosures/{cd_id}/revise",
            payload, headers,
        )

    def void_closing_disclosure(self, cd_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/closing-disclosures/{cd_id}/void",
            payload, headers,
        )

    # =======================================================================
    # Wire instructions — PRD §3.6
    # =======================================================================
    def create_wire_instruction(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/wire-instructions", payload, headers,
        )

    def get_wire_instruction(self, wire_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/wire-instructions/{wire_id}", headers=headers,
        )

    def submit_wire_instruction(self, wire_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/wire-instructions/{wire_id}/submit",
            payload, headers,
        )

    def confirm_callback_wire(self, wire_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/wire-instructions/{wire_id}/confirm-callback",
            payload, headers,
        )

    def flag_fraud_wire(self, wire_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/wire-instructions/{wire_id}/flag-fraud",
            payload, headers,
        )

    def void_wire_instruction(self, wire_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/wire-instructions/{wire_id}/void",
            payload, headers,
        )

    # =======================================================================
    # Disbursements — PRD §3.7
    # =======================================================================
    def create_disbursement(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/disbursements", payload, headers,
        )

    def get_disbursement(self, disb_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/disbursements/{disb_id}", headers=headers,
        )

    def approve_disbursement(self, disb_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/disbursements/{disb_id}/approve",
            payload, headers,
        )

    def send_disbursement(self, disb_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/disbursements/{disb_id}/send",
            payload, headers,
        )

    def settle_disbursement(self, disb_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/disbursements/{disb_id}/settle",
            payload, headers,
        )

    def reverse_disbursement(self, disb_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/disbursements/{disb_id}/reverse",
            payload, headers,
        )

    # =======================================================================
    # §1031 Exchange — PRD §3.8
    # =======================================================================
    def create_exchange(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/exchanges", payload, headers)

    def get_exchange(self, exchange_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/exchanges/{exchange_id}", headers=headers,
        )

    def identify_exchange(self, exchange_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/exchanges/{exchange_id}/identify",
            payload, headers,
        )

    def close_deferred_exchange(self, exchange_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/exchanges/{exchange_id}/close-deferred",
            payload, headers,
        )

    def fail_exchange(self, exchange_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/exchanges/{exchange_id}/fail",
            payload, headers,
        )

    # =======================================================================
    # Clock — PRD §2.10 / §3.10
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def clock_now(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/now", payload={}, headers=headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
