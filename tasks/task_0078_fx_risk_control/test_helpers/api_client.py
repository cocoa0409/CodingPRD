"""API client: one method per endpoint defined in PRD §4.

The server is reachable via API_BASE_URL (injected by the runner) and every
request carries X-User-ID and X-User-Role per PRD §2.1.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Traders
    # =======================================================================
    def create_trader(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/fx-risk/traders", payload, headers)

    def get_trader(self, trader_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fx-risk/traders/{trader_id}", headers=headers,
        )

    # =======================================================================
    # Desks
    # =======================================================================
    def list_desk_positions(self, desk_code: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/fx-risk/desks/{desk_code}/positions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Currency Pairs & Market Data
    # =======================================================================
    def create_currency_pair(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/currency-pairs", payload, headers,
        )

    def post_market_quote(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/market-data/quote", payload, headers,
        )

    # =======================================================================
    # Limits
    # =======================================================================
    def create_limit(self, trader_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/traders/{trader_id}/limits",
            payload, headers,
        )

    def list_limits(self, trader_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/fx-risk/traders/{trader_id}/limits",
            headers=headers, params=params,
        )

    def patch_limit(self, limit_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/fx-risk/limits/{limit_id}", payload, headers,
        )

    # =======================================================================
    # Limit Adjustments
    # =======================================================================
    def create_limit_adjustment(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/limit-adjustments", payload, headers,
        )

    def approve_limit_adjustment(self, adj_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/limit-adjustments/{adj_id}/approve",
            {}, headers,
        )

    def reject_limit_adjustment(self, adj_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/limit-adjustments/{adj_id}/reject",
            {}, headers,
        )

    def request_revision_limit_adjustment(self, adj_id: str,
                                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/fx-risk/limit-adjustments/{adj_id}/request-revision",
            {}, headers,
        )

    def patch_limit_adjustment(self, adj_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/fx-risk/limit-adjustments/{adj_id}",
            payload, headers,
        )

    # =======================================================================
    # Trades & Positions
    # =======================================================================
    def create_trade(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/trades", payload, headers,
        )

    def list_positions(self, trader_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/fx-risk/traders/{trader_id}/positions",
            headers=headers, params=params,
        )

    def get_exposure(self, trader_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fx-risk/traders/{trader_id}/exposure",
            headers=headers,
        )

    def get_var(self, trader_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fx-risk/traders/{trader_id}/var",
            headers=headers,
        )

    # =======================================================================
    # Stop-Loss
    # =======================================================================
    def create_stop_loss(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/stop-loss", payload, headers,
        )

    def evaluate_stop_loss(self, sl_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/stop-loss/{sl_id}/evaluate",
            {}, headers,
        )

    def acknowledge_stop_loss(self, sl_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/stop-loss/{sl_id}/acknowledge",
            {}, headers,
        )

    def override_stop_loss(self, sl_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/stop-loss/{sl_id}/override",
            {}, headers,
        )

    def execute_stop_loss(self, sl_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/stop-loss/{sl_id}/execute",
            {}, headers,
        )

    # =======================================================================
    # Counterparties
    # =======================================================================
    def create_counterparty(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/counterparties", payload, headers,
        )

    def patch_counterparty(self, cp_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/fx-risk/counterparties/{cp_id}", payload, headers,
        )

    # =======================================================================
    # Settlement
    # =======================================================================
    def generate_settlements(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/settlements/generate", payload, headers,
        )

    def send_settlement(self, si_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/settlements/{si_id}/send", {}, headers,
        )

    def confirm_settlement(self, si_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/settlements/{si_id}/confirm", {}, headers,
        )

    def mark_failed_settlement(self, si_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/settlements/{si_id}/mark-failed",
            {}, headers,
        )

    def reconcile_settlement(self, si_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fx-risk/settlements/{si_id}/reconcile",
            {}, headers,
        )

    # =======================================================================
    # Reports
    # =======================================================================
    def list_reports(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/fx-risk/reports", headers=headers, params=params,
        )

    def create_report(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/reports", payload, headers,
        )

    # =======================================================================
    # Audit log
    # =======================================================================
    def list_audit_log(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/fx-risk/audit-log", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving infrastructure (PRD §2.12)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/fx-risk/_sweep/run", {}, headers,
        )

    def reset_test_state(self):
        """Test-only: POST /fx-risk/_test/reset — wipes the in-memory store
        between tests so the benchmark can use deterministic, collision-free
        pair codes, trader names, etc. Mirrors the _clock/advance precedent.

        No auth required — this endpoint exists solely to isolate test cases
        and has no behavioral semantics.
        """
        return self._request(
            "POST", "/fx-risk/_test/reset", {}, headers={},
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
