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
    # Clients — PRD §4
    # =======================================================================
    def create_client(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/clients/{client_id}", headers=headers,
        )

    def patch_client(self, client_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/clients/{client_id}", payload, headers,
        )

    def activate_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/clients/{client_id}/activate", {}, headers,
        )

    def suspend_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/clients/{client_id}/suspend", {}, headers,
        )

    def reinstate_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/clients/{client_id}/reinstate", {}, headers,
        )

    def submit_questionnaire(self, client_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/clients/{client_id}/risk-questionnaire",
            payload, headers,
        )

    # =======================================================================
    # Model Portfolios — PRD §4
    # =======================================================================
    def create_model_portfolio(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/model-portfolios", payload, headers,
        )

    def list_model_portfolios(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/model-portfolios", headers=headers, params=params,
        )

    # =======================================================================
    # Securities — PRD §4
    # =======================================================================
    def create_security(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/securities", payload, headers)

    def set_pricing(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", "/_pricing/set", payload, headers,
        )

    def create_correlation_link(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/correlation-links", payload, headers,
        )

    # =======================================================================
    # Accounts — PRD §4
    # =======================================================================
    def create_account(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/accounts/{account_id}", headers=headers,
        )

    def freeze_account(self, account_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/freeze", {}, headers,
        )

    def unfreeze_account(self, account_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/unfreeze", {}, headers,
        )

    def cash_deposit(self, account_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/cash-deposit",
            payload, headers,
        )

    # =======================================================================
    # Trades — PRD §4
    # =======================================================================
    def create_trade(self, account_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/trades", payload, headers,
        )

    def execute_trade(self, account_id: str, trade_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accounts/{account_id}/trades/{trade_id}/execute",
            {}, headers,
        )

    def settle_trade(self, account_id: str, trade_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accounts/{account_id}/trades/{trade_id}/settle",
            {}, headers,
        )

    def cancel_trade(self, account_id: str, trade_id: str,
                     payload: Optional[Dict[str, Any]],
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accounts/{account_id}/trades/{trade_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def get_trade(self, account_id: str, trade_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/accounts/{account_id}/trades/{trade_id}",
            headers=headers,
        )

    def list_trades(self, account_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/trades",
            headers=headers, params=params,
        )

    # =======================================================================
    # Positions / Drift — PRD §4
    # =======================================================================
    def list_positions(self, account_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/positions",
            headers=headers, params=params,
        )

    def recompute_positions(self, account_id: str,
                            payload: Optional[Dict[str, Any]],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/positions/recompute",
            payload if payload is not None else {}, headers,
        )

    def recompute_drift(self, account_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/drift/recompute",
            {}, headers,
        )

    # =======================================================================
    # Harvest Opportunities — PRD §4
    # =======================================================================
    def list_harvest_opportunities(self, account_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/accounts/{account_id}/harvest-opportunities",
            headers=headers, params=params,
        )

    def approve_harvest_opportunity(self, account_id: str,
                                    opportunity_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accounts/{account_id}/harvest-opportunities/"
            f"{opportunity_id}/approve",
            {}, headers,
        )

    def dismiss_harvest_opportunity(self, account_id: str,
                                    opportunity_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accounts/{account_id}/harvest-opportunities/"
            f"{opportunity_id}/dismiss",
            {}, headers,
        )

    def execute_harvest_opportunity(self, account_id: str,
                                    opportunity_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accounts/{account_id}/harvest-opportunities/"
            f"{opportunity_id}/execute",
            {}, headers,
        )

    # =======================================================================
    # Rebalance — PRD §4
    # =======================================================================
    def start_rebalance(self, account_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/rebalance/start",
            payload, headers,
        )

    def list_rebalance_runs(self, account_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/rebalance-runs",
            headers=headers, params=params,
        )

    # =======================================================================
    # Dividends — PRD §4
    # =======================================================================
    def record_dividend(self, account_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/dividends",
            payload, headers,
        )

    # =======================================================================
    # Form 1099-B — PRD §4
    # =======================================================================
    def create_form_1099b(self, client_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/clients/{client_id}/forms-1099b",
            payload, headers,
        )

    def get_form_1099b(self, client_id: str, form_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/clients/{client_id}/forms-1099b/{form_id}",
            headers=headers,
        )

    def issue_form_1099b(self, client_id: str, form_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/clients/{client_id}/forms-1099b/{form_id}/issue",
            {}, headers,
        )

    def void_form_1099b(self, client_id: str, form_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/clients/{client_id}/forms-1099b/{form_id}/void",
            {}, headers,
        )

    # =======================================================================
    # Test-driving operational endpoints — PRD §3.12
    # =======================================================================
    def advance_clock(self, payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance",
            payload if payload is not None else {}, headers,
        )

    def quarterly_run(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_quarterly/run", {}, headers,
        )

    def settle_run(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_settle/run", {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
