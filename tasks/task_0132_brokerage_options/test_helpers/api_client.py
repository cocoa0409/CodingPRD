"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.

All endpoints are mounted under the /brokerage path prefix (PRD §4).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Customer + KYC — PRD §3.1, §4
    # =======================================================================
    def create_customer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/brokerage/customers",
                             payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerage/customers/{customer_id}",
            headers=headers,
        )

    def submit_kyc(self, customer_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/brokerage/customers/{customer_id}/kyc",
            payload, headers,
        )

    def kyc_decision(self, customer_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerage/customers/{customer_id}/kyc/decision",
            payload, headers,
        )

    # =======================================================================
    # Accounts — PRD §3.1, §3.4, §3.6, §4
    # =======================================================================
    def create_account(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/brokerage/accounts",
                             payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerage/accounts/{account_id}",
            headers=headers,
        )

    def list_accounts(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/brokerage/accounts",
            headers=headers, params=params,
        )

    def close_account(self, account_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/brokerage/accounts/{account_id}/close",
            payload if payload is not None else {}, headers,
        )

    def pdt_reset(self, account_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/brokerage/accounts/{account_id}/pdt/reset",
            payload, headers,
        )

    # =======================================================================
    # Options Approvals — PRD §3.2, §4
    # =======================================================================
    def create_options_approval(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/brokerage/options-approvals", payload, headers,
        )

    def get_options_approval(self, approval_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerage/options-approvals/{approval_id}",
            headers=headers,
        )

    def start_options_review(self, approval_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerage/options-approvals/{approval_id}/start-review",
            payload if payload is not None else {}, headers,
        )

    def decide_options_approval(self, approval_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerage/options-approvals/{approval_id}/decide",
            payload, headers,
        )

    def patch_options_approval(self, approval_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/brokerage/options-approvals/{approval_id}",
            payload, headers,
        )

    # =======================================================================
    # Orders — PRD §3.3, §3.4, §4
    # =======================================================================
    def create_order(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/brokerage/orders",
                             payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerage/orders/{order_id}", headers=headers,
        )

    def list_orders(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/brokerage/orders",
            headers=headers, params=params,
        )

    def fill_order(self, order_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/brokerage/orders/{order_id}/fill",
            payload, headers,
        )

    def cancel_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/brokerage/orders/{order_id}",
            headers=headers,
        )

    # =======================================================================
    # ACAT Transfers — PRD §3.5, §4
    # =======================================================================
    def create_acat_transfer(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/brokerage/acat-transfers",
                             payload, headers)

    def get_acat_transfer(self, transfer_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerage/acat-transfers/{transfer_id}",
            headers=headers,
        )

    def list_acat_transfers(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/brokerage/acat-transfers",
            headers=headers, params=params,
        )

    def validate_acat_transfer(self, transfer_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerage/acat-transfers/{transfer_id}/validate",
            payload if payload is not None else {}, headers,
        )

    def reject_acat_transfer(self, transfer_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerage/acat-transfers/{transfer_id}/reject",
            payload, headers,
        )

    def cancel_acat_transfer(self, transfer_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/brokerage/acat-transfers/{transfer_id}",
            headers=headers,
        )

    # =======================================================================
    # Test-only clock + sweep — PRD §2.6, §3.8, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/brokerage/_clock/advance",
                             payload, headers)

    def sweep_run(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/brokerage/_sweep/run",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
