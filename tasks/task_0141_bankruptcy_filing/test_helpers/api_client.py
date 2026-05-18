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
    # Debtor — PRD §4
    # =======================================================================
    def create_debtor(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/debtors", payload, headers)

    def get_debtor(self, debtor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/debtors/{debtor_id}", headers=headers,
        )

    # =======================================================================
    # Creditor — PRD §4
    # =======================================================================
    def create_creditor(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/creditors", payload, headers)

    def get_creditor(self, creditor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/creditors/{creditor_id}", headers=headers,
        )

    # =======================================================================
    # Case — PRD §4
    # =======================================================================
    def create_case(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}", headers=headers,
        )

    def withdraw_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/cases/{case_id}", headers=headers,
        )

    def submit_schedule(self, case_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/schedules", payload, headers,
        )

    def run_means_test(self, case_id: str,
                       payload: Optional[Dict[str, Any]],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/means-test",
            payload if payload is not None else {}, headers,
        )

    def file_case(self, case_id: str,
                  payload: Optional[Dict[str, Any]],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/file",
            payload if payload is not None else {}, headers,
        )

    def schedule_341(self, case_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/schedule-341", payload, headers,
        )

    def conduct_341(self, case_id: str,
                    payload: Optional[Dict[str, Any]],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/conduct-341",
            payload if payload is not None else {}, headers,
        )

    def dismiss_case(self, case_id: str,
                     payload: Optional[Dict[str, Any]],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/dismiss",
            payload if payload is not None else {}, headers,
        )

    def discharge_case(self, case_id: str,
                       payload: Optional[Dict[str, Any]],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/discharge",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Claim — PRD §4
    # =======================================================================
    def create_claim(self, case_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/claims", payload, headers,
        )

    def get_claim(self, case_id: str, claim_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/claims/{claim_id}", headers=headers,
        )

    def disallow_claim(self, case_id: str, claim_id: str,
                       payload: Optional[Dict[str, Any]],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/claims/{claim_id}/disallow",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Plan — PRD §4
    # =======================================================================
    def create_plan(self, case_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/plans", payload, headers,
        )

    def get_plan(self, case_id: str, plan_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/plans/{plan_id}", headers=headers,
        )

    def withdraw_plan(self, case_id: str, plan_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/cases/{case_id}/plans/{plan_id}",
            headers=headers,
        )

    def confirm_plan(self, case_id: str, plan_id: str,
                     payload: Optional[Dict[str, Any]],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/plans/{plan_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    def record_payment(self, case_id: str, plan_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/plans/{plan_id}/payments",
            payload, headers,
        )

    # =======================================================================
    # CollectionAction — PRD §4
    # =======================================================================
    def create_collection_action(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/collection-actions", payload, headers,
        )

    def list_collection_actions(self, case_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cases/{case_id}/collection-actions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Clock — PRD §4 (test-only)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
