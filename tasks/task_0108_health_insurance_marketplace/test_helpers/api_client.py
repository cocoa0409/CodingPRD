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
    # Applications — PRD §4
    # =======================================================================
    def create_application(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/applications/{application_id}", headers=headers,
        )

    def list_applications(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/applications", headers=headers, params=params,
        )

    def submit_application(self, application_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/submit", {}, headers,
        )

    def amend_application(self, application_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/amend", {}, headers,
        )

    def determine_eligibility(self, application_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/determine-eligibility",
            {}, headers,
        )

    def approve_application(self, application_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/approve", {},
            headers,
        )

    def deny_application(self, application_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/deny",
            payload or {}, headers,
        )

    def redetermine_application(self, application_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/redetermine", {},
            headers,
        )

    # =======================================================================
    # HouseholdMember — PRD §4
    # =======================================================================
    def create_household_member(self, application_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/household-members",
            payload, headers,
        )

    def patch_household_member(self, application_id: str, member_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/applications/{application_id}/household-members/{member_id}",
            payload, headers,
        )

    def delete_household_member(self, application_id: str,
                                member_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/applications/{application_id}/household-members/{member_id}",
            headers=headers,
        )

    # =======================================================================
    # IncomeRecord — PRD §4
    # =======================================================================
    def create_income_record(self, application_id: str, member_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/household-members/"
            f"{member_id}/income-records",
            payload, headers,
        )

    # =======================================================================
    # SEP events — PRD §4
    # =======================================================================
    def create_sep_event(self, application_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/sep-events",
            payload, headers,
        )

    def verify_sep_event(self, application_id: str, sep_event_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/sep-events/{sep_event_id}/verify",
            {}, headers,
        )

    def reject_sep_event(self, application_id: str, sep_event_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/applications/{application_id}/sep-events/{sep_event_id}/reject",
            payload or {}, headers,
        )

    def appeal_sep_event(self, application_id: str, sep_event_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/sep-events/{sep_event_id}/appeal",
            {}, headers,
        )

    # =======================================================================
    # Insurer — PRD §4
    # =======================================================================
    def create_insurer(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/insurers", payload, headers)

    def list_insurers(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/insurers", headers=headers, params=params,
        )

    # =======================================================================
    # Plan + PlanVariant — PRD §4
    # =======================================================================
    def create_plan(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/plans", payload, headers)

    def patch_plan(self, plan_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/plans/{plan_id}", payload, headers,
        )

    def list_plans(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/plans", headers=headers, params=params,
        )

    def create_plan_variant(self, plan_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/plans/{plan_id}/variants", payload, headers,
        )

    # =======================================================================
    # Enrollment — PRD §4
    # =======================================================================
    def create_enrollment(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}", headers=headers,
        )

    def cancel_enrollment(self, enrollment_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/cancel", {}, headers,
        )

    # =======================================================================
    # PremiumInvoice — PRD §4
    # =======================================================================
    def list_premium_invoices(self, enrollment_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/enrollments/{enrollment_id}/premium-invoices",
            headers=headers, params=params,
        )

    def post_payment(self, invoice_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/premium-invoices/{invoice_id}/post-payment",
            payload, headers,
        )

    def waive_invoice(self, invoice_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/premium-invoices/{invoice_id}/waive",
            payload or {}, headers,
        )

    # =======================================================================
    # Test-driving endpoints — PRD §2.9 / §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def sweep_age_invoices(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/age-invoices", {}, headers,
        )

    def sweep_reconcile_aptc(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/reconcile-aptc", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
