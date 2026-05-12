"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID and X-User-Role mandatory for every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Investor (PRD §3.1, §4)
    # =====================================================================
    def create_investor(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request("POST", "/investors", payload, headers)

    def approve_kyc(self, investor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/investors/{investor_id}/approve-kyc",
            headers=headers,
        )

    def credit_cash(
        self,
        investor_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/investors/{investor_id}/credit-cash",
            payload,
            headers,
        )

    def get_investor(self, investor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/investors/{investor_id}", headers=headers
        )

    def list_investor_holdings(
        self,
        investor_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/investors/{investor_id}/holdings",
            headers=headers,
            params=params,
        )

    # =====================================================================
    # Fund (PRD §3.2, §4)
    # =====================================================================
    def create_fund(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request("POST", "/funds", payload, headers)

    def submit_fund_for_review(self, fund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/funds/{fund_id}/submit-for-review",
            headers=headers,
        )

    def approve_fund_shelf(self, fund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/funds/{fund_id}/approve-shelf", headers=headers
        )

    def reject_fund_shelf(self, fund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/funds/{fund_id}/reject-shelf", headers=headers
        )

    def suspend_fund(self, fund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/funds/{fund_id}/suspend", headers=headers
        )

    def resume_fund(self, fund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/funds/{fund_id}/resume", headers=headers
        )

    def off_shelf_fund(self, fund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/funds/{fund_id}/off-shelf", headers=headers
        )

    def list_funds(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/funds", headers=headers, params=params
        )

    def get_fund(self, fund_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/funds/{fund_id}", headers=headers
        )

    # =====================================================================
    # NAV (PRD §3.4, §4)
    # =====================================================================
    def publish_nav(
        self,
        fund_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/funds/{fund_id}/nav/publish",
            payload,
            headers,
        )

    def adjust_nav(
        self,
        fund_id: str,
        nav_date: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/funds/{fund_id}/nav/{nav_date}/adjust",
            payload,
            headers,
        )

    def get_nav(
        self,
        fund_id: str,
        nav_date: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/funds/{fund_id}/nav/{nav_date}",
            headers=headers,
        )

    # =====================================================================
    # Order (PRD §3.3, §3.4, §4)
    # =====================================================================
    def create_order(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request("POST", "/orders", payload, headers)

    def cancel_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/cancel", headers=headers
        )

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/orders/{order_id}", headers=headers
        )

    def list_orders(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/orders", headers=headers, params=params
        )

    # =====================================================================
    # Dividend (PRD §3.6, §4)
    # =====================================================================
    def create_dividend_plan(
        self,
        fund_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/funds/{fund_id}/dividend-plans",
            payload,
            headers,
        )

    def mark_ex_dividend(
        self,
        plan_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/dividend-plans/{plan_id}/mark-ex-dividend",
            headers=headers,
        )

    def set_distribution_option(
        self,
        plan_id: str,
        investor_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/dividend-plans/{plan_id}/distributions/{investor_id}/set-option",
            payload,
            headers,
        )

    def execute_dividend_payment(
        self,
        plan_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/dividend-plans/{plan_id}/execute-payment",
            headers=headers,
        )

    def cancel_dividend_plan(
        self,
        plan_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/dividend-plans/{plan_id}/cancel",
            headers=headers,
        )

    def get_dividend_plan(
        self,
        plan_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/dividend-plans/{plan_id}",
            headers=headers,
        )

    # =====================================================================
    # Reconciliation (PRD §3.7, §4)
    # =====================================================================
    def create_reconciliation(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/reconciliations", payload, headers
        )

    def run_match(self, run_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/reconciliations/{run_id}/run-match",
            headers=headers,
        )

    def adjust_exception(
        self,
        run_id: str,
        exception_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/reconciliations/{run_id}/exceptions/{exception_id}/adjust",
            payload,
            headers,
        )

    def waive_exception(
        self,
        run_id: str,
        exception_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/reconciliations/{run_id}/exceptions/{exception_id}/waive",
            headers=headers,
        )

    def finalize_reconciliation(
        self,
        run_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/reconciliations/{run_id}/finalize",
            headers=headers,
        )

    def close_reconciliation(
        self,
        run_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/reconciliations/{run_id}/close-and-instruct",
            headers=headers,
        )

    def get_reconciliation(
        self,
        run_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/reconciliations/{run_id}", headers=headers
        )

    # =====================================================================
    # Audit log (PRD §3.8, §4)
    # =====================================================================
    def list_audit_logs(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params
        )

    # =====================================================================
    # Clock (PRD §2.12, §4)
    # =====================================================================
    def advance_clock(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_clock/advance", payload, headers
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
