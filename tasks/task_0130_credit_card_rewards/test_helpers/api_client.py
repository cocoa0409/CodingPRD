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
    # Cardholder — PRD §4
    # =======================================================================
    def create_cardholder(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/cardholders", payload, headers)

    def get_cardholder(self, cardholder_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/cardholders/{cardholder_id}", headers=headers,
        )

    # =======================================================================
    # Account — PRD §4
    # =======================================================================
    def create_account(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/accounts/{account_id}", headers=headers,
        )

    def mark_delinquent(self, account_id: str,
                        payload: Optional[Dict[str, Any]],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/mark-delinquent",
            payload if payload is not None else {}, headers,
        )

    def clear_delinquency(self, account_id: str,
                          payload: Optional[Dict[str, Any]],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/clear-delinquency",
            payload if payload is not None else {}, headers,
        )

    def close_account(self, account_id: str,
                      payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/close",
            payload if payload is not None else {}, headers,
        )

    def activate_category(self, account_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/activate-category",
            payload, headers,
        )

    def list_activations(self, account_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/activations",
            headers=headers, params=params,
        )

    def list_ledger(self, account_id: str,
                    headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/ledger",
            headers=headers, params=params,
        )

    def list_account_transactions(self, account_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/transactions",
            headers=headers, params=params,
        )

    # =======================================================================
    # CashbackCategory — PRD §4
    # =======================================================================
    def create_cashback_category(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/cashback-categories", payload, headers,
        )

    def list_cashback_categories(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/cashback-categories", headers=headers, params=params,
        )

    # =======================================================================
    # Transaction — PRD §4
    # =======================================================================
    def create_transaction(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, transaction_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/transactions/{transaction_id}", headers=headers,
        )

    # =======================================================================
    # TransferPartner — PRD §4
    # =======================================================================
    def create_transfer_partner(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/transfer-partners", payload, headers,
        )

    def list_transfer_partners(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/transfer-partners", headers=headers, params=params,
        )

    # =======================================================================
    # PointsTransfer — PRD §4
    # =======================================================================
    def create_points_transfer(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", "/points-transfers", payload, headers)

    def confirm_points_transfer(self, transfer_id: str,
                                payload: Optional[Dict[str, Any]],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/points-transfers/{transfer_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    def reverse_points_transfer(self, transfer_id: str,
                                payload: Optional[Dict[str, Any]],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/points-transfers/{transfer_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # StatementCredit — PRD §4
    # =======================================================================
    def create_statement_credit(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", "/statement-credits", payload, headers)

    def reverse_statement_credit(self, credit_id: str,
                                 payload: Optional[Dict[str, Any]],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/statement-credits/{credit_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Clock & Sweeps — PRD §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_run(self, payload: Optional[Dict[str, Any]],
                  headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/run",
            payload if payload is not None else {}, headers,
        )

    def sweep_year_rollover(self, payload: Optional[Dict[str, Any]],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/year-rollover",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
