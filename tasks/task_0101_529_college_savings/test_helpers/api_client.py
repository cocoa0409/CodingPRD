"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Donor — PRD §3.1
    # =======================================================================
    def create_donor(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/donors", payload, headers)

    def get_donor(self, donor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/donors/{donor_id}", headers=headers,
        )

    # =======================================================================
    # Beneficiary — PRD §3.1
    # =======================================================================
    def create_beneficiary(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/beneficiaries/{beneficiary_id}", headers=headers,
        )

    # =======================================================================
    # Account — PRD §3.2
    # =======================================================================
    def create_account(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/accounts/{account_id}", headers=headers,
        )

    def list_accounts(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/accounts", headers=headers, params=params,
        )

    def restrict_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/restrict", {}, headers,
        )

    def release_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/release", {}, headers,
        )

    def close_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/close", {}, headers,
        )

    # =======================================================================
    # Contribution — PRD §3.3
    # =======================================================================
    def create_contribution(self, account_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/contributions",
            payload, headers,
        )

    def settle_contribution(self, contribution_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/contributions/{contribution_id}/settle", {}, headers,
        )

    def reverse_contribution(self, contribution_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/contributions/{contribution_id}/reverse", {}, headers,
        )

    def get_contribution(self, contribution_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/contributions/{contribution_id}", headers=headers,
        )

    def list_account_contributions(self, account_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/contributions",
            headers=headers, params=params,
        )

    # =======================================================================
    # RecurringPlan — PRD §3.3, §3.4
    # =======================================================================
    def create_recurring_plan(self, account_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/recurring-plans",
            payload, headers,
        )

    def patch_recurring_plan(self, plan_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/recurring-plans/{plan_id}", payload, headers,
        )

    def pause_recurring_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/recurring-plans/{plan_id}/pause", {}, headers,
        )

    def resume_recurring_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/recurring-plans/{plan_id}/resume", {}, headers,
        )

    def cancel_recurring_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/recurring-plans/{plan_id}/cancel", {}, headers,
        )

    # =======================================================================
    # Withdrawal + EducationExpense — PRD §3.5
    # =======================================================================
    def create_withdrawal(self, account_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/withdrawals", payload, headers,
        )

    def disburse_withdrawal(self, withdrawal_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/withdrawals/{withdrawal_id}/disburse", {}, headers,
        )

    def reject_withdrawal(self, withdrawal_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/withdrawals/{withdrawal_id}/reject", payload, headers,
        )

    def attach_education_expense(self, withdrawal_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/withdrawals/{withdrawal_id}/expenses",
            payload, headers,
        )

    def classify_withdrawal(self, withdrawal_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/withdrawals/{withdrawal_id}/classify", {}, headers,
        )

    def get_withdrawal(self, withdrawal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/withdrawals/{withdrawal_id}", headers=headers,
        )

    def list_account_withdrawals(self, account_id: str,
                                 headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/withdrawals",
            headers=headers, params=params,
        )

    # =======================================================================
    # BeneficiaryChangeRequest — PRD §3.6
    # =======================================================================
    def create_beneficiary_change_request(self, account_id: str,
                                          payload: Dict[str, Any],
                                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/beneficiary-change-requests",
            payload, headers,
        )

    def approve_beneficiary_change_request(self, request_id: str,
                                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/beneficiary-change-requests/{request_id}/approve",
            {}, headers,
        )

    def reject_beneficiary_change_request(self, request_id: str,
                                          payload: Dict[str, Any],
                                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/beneficiary-change-requests/{request_id}/reject",
            payload, headers,
        )

    # =======================================================================
    # TaxReport — PRD §3.7
    # =======================================================================
    def create_tax_report(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/tax-reports", payload, headers)

    def get_tax_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tax-reports/{report_id}", headers=headers,
        )

    def finalize_tax_report(self, report_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/tax-reports/{report_id}/finalize", {}, headers,
        )

    # =======================================================================
    # StateRule — PRD §3.1
    # =======================================================================
    def create_state_rule(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/state-rules", payload, headers)

    def get_state_rule(self, state_code: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/state-rules/{state_code}", headers=headers,
        )

    def list_state_rules(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/state-rules", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving — PRD §3.8 (PlanAdministrator-only)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_recurring_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run-recurring", {}, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
