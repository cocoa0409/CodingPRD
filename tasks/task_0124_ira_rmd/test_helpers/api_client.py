"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Simulated clock — PRD §2.10, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def clock_advance_year(self, payload: Optional[Dict[str, Any]],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance-year",
            payload if payload is not None else {}, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # =======================================================================
    # Participants — PRD §3.1, §4
    # =======================================================================
    def create_participant(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/participants/{participant_id}", headers=headers,
        )

    def update_participant(self, participant_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/participants/{participant_id}", payload, headers,
        )

    def decease_participant(self, participant_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/participants/{participant_id}/decease",
            payload, headers,
        )

    # =======================================================================
    # Accounts — PRD §3.2, §4
    # =======================================================================
    def create_account(self, participant_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/participants/{participant_id}/accounts",
            payload, headers,
        )

    def get_account(self, participant_id: str, account_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/participants/{participant_id}/accounts/{account_id}",
            headers=headers,
        )

    def freeze_account(self, account_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/accounts/{account_id}/freeze",
            payload if payload is not None else {}, headers,
        )

    def unfreeze_account(self, account_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/accounts/{account_id}/unfreeze",
            payload if payload is not None else {}, headers,
        )

    def close_account(self, account_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/accounts/{account_id}/close",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Contributions — PRD §3.3, §4
    # =======================================================================
    def create_contribution(self, account_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/contributions",
            payload, headers,
        )

    def reverse_contribution(self, contribution_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/contributions/{contribution_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Distributions & RMD — PRD §3.4, §3.5, §4
    # =======================================================================
    def create_distribution(self, account_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/distributions",
            payload, headers,
        )

    def get_rmd(self, account_id: str,
                headers: Dict[str, str],
                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/rmd",
            headers=headers, params=params,
        )

    def excess_sweep(self, account_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/accounts/{account_id}/excess-sweep",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Conversion requests — PRD §3.7, §4
    # =======================================================================
    def create_conversion_request(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/conversion-requests", payload, headers,
        )

    def get_conversion_request(self, conversion_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/conversion-requests/{conversion_id}",
            headers=headers,
        )

    def approve_conversion_request(self, conversion_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/conversion-requests/{conversion_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def reject_conversion_request(self, conversion_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/conversion-requests/{conversion_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def cancel_conversion_request(self, conversion_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/conversion-requests/{conversion_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def complete_conversion_request(self, conversion_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/conversion-requests/{conversion_id}/complete",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Beneficiary claims — PRD §3.6, §4
    # =======================================================================
    def get_beneficiary_claim(self, claim_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/beneficiary-claims/{claim_id}", headers=headers,
        )

    def suspend_beneficiary_claim(self, claim_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/beneficiary-claims/{claim_id}/suspend",
            payload if payload is not None else {}, headers,
        )

    def resume_beneficiary_claim(self, claim_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/beneficiary-claims/{claim_id}/resume",
            payload if payload is not None else {}, headers,
        )

    def get_beneficiary_projection(self, claim_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/beneficiary-claims/{claim_id}/projection",
            headers=headers, params=params,
        )

    # =======================================================================
    # Forms 1099-R — PRD §3.9, §4
    # =======================================================================
    def list_forms_1099r(self, participant_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/participants/{participant_id}/forms-1099r",
            headers=headers, params=params,
        )

    def correct_form_1099r(self, form_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/forms-1099r/{form_id}/correct",
            payload if payload is not None else {}, headers,
        )

    def void_form_1099r(self, form_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/forms-1099r/{form_id}/void",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
