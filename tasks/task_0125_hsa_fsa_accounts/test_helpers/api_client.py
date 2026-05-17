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
    # Server clock — PRD §2.7, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # =======================================================================
    # AccountHolder — PRD §3.1, §4
    # =======================================================================
    def create_account_holder(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/account-holders", payload, headers)

    def get_account_holder(self, account_holder_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/account-holders/{account_holder_id}",
            headers=headers,
        )

    # =======================================================================
    # Dependent — PRD §3.1, §4
    # =======================================================================
    def create_dependent(self, account_holder_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/account-holders/{account_holder_id}/dependents",
            payload, headers,
        )

    def deactivate_dependent(self, dependent_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/dependents/{dependent_id}/deactivate",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Account — PRD §3.1, §4
    # =======================================================================
    def create_account(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/accounts/{account_id}", headers=headers,
        )

    def list_accounts(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/accounts", headers=headers,
                             params=params)

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
    # PlanYear — PRD §3.2, §4
    # =======================================================================
    def create_plan_year(self, account_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/plan-years",
            payload, headers,
        )

    def get_plan_year(self, account_id: str, plan_year_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/accounts/{account_id}/plan-years/{plan_year_id}",
            headers=headers,
        )

    def list_plan_years(self, account_id: str,
                        headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/plan-years",
            headers=headers, params=params,
        )

    def get_tax_form(self, account_id: str, plan_year_id: str,
                     headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/accounts/{account_id}/plan-years/{plan_year_id}/tax-form",
            headers=headers, params=params,
        )

    # =======================================================================
    # Contribution — PRD §3.3, §4
    # =======================================================================
    def create_contribution(self, plan_year_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/plan-years/{plan_year_id}/contributions",
            payload, headers,
        )

    def reverse_contribution(self, contribution_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/contributions/{contribution_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    def list_contributions(self, plan_year_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/plan-years/{plan_year_id}/contributions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Claim — PRD §3.5, §4
    # =======================================================================
    def create_claim(self, account_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/claims",
            payload, headers,
        )

    def submit_claim(self, claim_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def approve_claim(self, claim_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def pay_claim(self, claim_id: str,
                  headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/pay",
            payload if payload is not None else {}, headers,
        )

    def deny_claim(self, claim_id: str,
                   payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/deny",
            payload, headers,
        )

    def reverse_claim(self, claim_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    def get_claim(self, claim_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/claims/{claim_id}", headers=headers,
        )

    def list_claims(self, account_id: str,
                    headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/claims",
            headers=headers, params=params,
        )

    # =======================================================================
    # QualifiedExpense — PRD §3.4, §4
    # =======================================================================
    def create_qualified_expense(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/qualified-expenses", payload, headers,
        )

    def list_qualified_expenses(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/qualified-expenses", headers=headers, params=params,
        )

    # =======================================================================
    # AuditEvent — PRD §2.8, §3.9, §4
    # =======================================================================
    def list_audit_events(self, account_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/audit-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # OpsRun — PRD §3.7, §4
    # =======================================================================
    def create_ops_run(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/ops-runs", payload, headers)

    def list_ops_runs(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/ops-runs", headers=headers,
                             params=params)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
