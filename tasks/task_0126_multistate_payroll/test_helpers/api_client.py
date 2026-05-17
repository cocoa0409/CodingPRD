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
    # Test-only clock — PRD §3.9, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    # =======================================================================
    # Employees — PRD §3.1, §4
    # =======================================================================
    def create_employee(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/employees", payload, headers)

    def list_employees(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/employees", headers=headers, params=params,
        )

    def get_employee(self, employee_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/employees/{employee_id}", headers=headers,
        )

    def terminate_employee(self, employee_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/employees/{employee_id}/terminate",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # W-4 Profiles — PRD §3.1, §4
    # =======================================================================
    def create_w4_profile(self, employee_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/employees/{employee_id}/w4-profiles",
            payload, headers,
        )

    def prefill_w4_profile(self, employee_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/employees/{employee_id}/w4-profiles/prefill",
            payload, headers,
        )

    def list_w4_profiles(self, employee_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/employees/{employee_id}/w4-profiles",
            headers=headers, params=params,
        )

    # =======================================================================
    # Garnishment Orders — PRD §3.5, §4
    # =======================================================================
    def create_garnishment_order(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/garnishment-orders", payload, headers,
        )

    def list_garnishment_orders(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/garnishment-orders",
            headers=headers, params=params,
        )

    def get_garnishment_order(self, order_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/garnishment-orders/{order_id}", headers=headers,
        )

    def release_garnishment_order(self, order_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/garnishment-orders/{order_id}/release",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Pay Periods — PRD §3.2, §4
    # =======================================================================
    def create_pay_period(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/pay-periods", payload, headers)

    def list_pay_periods(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pay-periods", headers=headers, params=params,
        )

    def get_pay_period(self, period_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pay-periods/{period_id}", headers=headers,
        )

    def lock_pay_period(self, period_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pay-periods/{period_id}/lock",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Payroll Items — PRD §3.3, §4
    # =======================================================================
    def create_payroll_item(self, period_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/pay-periods/{period_id}/payroll-items",
            payload, headers,
        )

    def update_payroll_item(self, item_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "PUT", f"/payroll-items/{item_id}", payload, headers,
        )

    # =======================================================================
    # Paychecks — PRD §3.4, §3.6, §3.7, §4
    # =======================================================================
    def list_paychecks(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/paychecks", headers=headers, params=params,
        )

    def get_paycheck(self, paycheck_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/paychecks/{paycheck_id}", headers=headers,
        )

    def calculate_paycheck(self, paycheck_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/paychecks/{paycheck_id}/calculate",
            payload if payload is not None else {}, headers,
        )

    def recalculate_paycheck(self, paycheck_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/paychecks/{paycheck_id}/recalculate",
            payload if payload is not None else {}, headers,
        )

    def approve_paycheck(self, paycheck_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/paychecks/{paycheck_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def mark_paid_paycheck(self, paycheck_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/paychecks/{paycheck_id}/mark-paid",
            payload if payload is not None else {}, headers,
        )

    def issue_correction_paycheck(self, paycheck_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/paychecks/{paycheck_id}/issue-correction",
            payload, headers,
        )

    # =======================================================================
    # Remittance Periods — PRD §3.10, §4
    # =======================================================================
    def create_remittance_period(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", "/remittance-periods", payload, headers,
        )

    def list_remittance_periods(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/remittance-periods",
            headers=headers, params=params,
        )

    def get_remittance_period(self, remit_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "GET", f"/remittance-periods/{remit_id}", headers=headers,
        )

    def finalize_remittance(self, remit_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/remittance-periods/{remit_id}/finalize",
            payload if payload is not None else {}, headers,
        )

    def reopen_remittance(self, remit_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/remittance-periods/{remit_id}/reopen",
            payload if payload is not None else {}, headers,
        )

    def remit_remittance(self, remit_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/remittance-periods/{remit_id}/remit",
            payload if payload is not None else {}, headers,
        )

    def amend_remittance(self, remit_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/remittance-periods/{remit_id}/amend",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Tax Bracket Tables — PRD §3.9, §4
    # =======================================================================
    def create_tax_bracket_table(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", "/tax-bracket-tables", payload, headers,
        )

    def list_tax_bracket_tables(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/tax-bracket-tables",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
