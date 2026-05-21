"""API client — one method per endpoint defined in PRD §4.

Subclasses GenericApiClient; the base `_request()` handles HTTP plumbing.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Plan — PRD §3.1
    # ======================================================================
    def create_plan(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def update_plan(self, plan_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("PATCH", f"/plans/{plan_id}", payload, headers)

    def activate_plan(self, plan_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/plans/{plan_id}/activate", payload, headers,
        )

    def terminate_plan(self, plan_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/plans/{plan_id}/terminate", payload, headers,
        )

    def get_dilution_preview(self, plan_id: str, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/plans/{plan_id}/dilution-preview",
            headers=headers, params=params,
        )

    # ======================================================================
    # OfferingPeriod — PRD §3.2
    # ======================================================================
    def list_offering_periods(self, plan_id: str, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/plans/{plan_id}/offering-periods",
            headers=headers, params=params,
        )

    def get_offering_period(self, offering_period_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/offering-periods/{offering_period_id}",
            headers=headers,
        )

    def record_grant_fmv(self, plan_id: str, offering_period_id: str,
                         payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/offering-periods/"
            f"{offering_period_id}/grant-fmv",
            payload, headers,
        )

    def record_purchase_fmv(self, offering_period_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/offering-periods/{offering_period_id}/fmv",
            payload, headers,
        )

    def run_purchase(self, offering_period_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/offering-periods/{offering_period_id}/run-purchase",
            payload, headers,
        )

    # ======================================================================
    # Enrollment — PRD §3.3
    # ======================================================================
    def create_enrollment(self, offering_period_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/offering-periods/{offering_period_id}/enrollments",
            payload, headers,
        )

    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}", headers=headers,
        )

    def update_enrollment(self, enrollment_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/enrollments/{enrollment_id}", payload, headers,
        )

    def withdraw_enrollment(self, enrollment_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw",
            payload, headers,
        )

    # ======================================================================
    # Contribution — PRD §3.4
    # ======================================================================
    def create_contribution(self, enrollment_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/contributions",
            payload, headers,
        )

    def list_contributions(self, enrollment_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/contributions",
            headers=headers, params=params,
        )

    # ======================================================================
    # Purchase — PRD §3.5, §3.6
    # ======================================================================
    def get_purchase(self, purchase_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/purchases/{purchase_id}", headers=headers,
        )

    def list_purchases(self, participant_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/participants/{participant_id}/purchases",
            headers=headers, params=params,
        )

    # ======================================================================
    # Form3922 — PRD §2.8
    # ======================================================================
    def get_form_3922(self, form_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/form-3922/{form_id}", headers=headers,
        )

    def list_form_3922(self, participant_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/participants/{participant_id}/form-3922",
            headers=headers, params=params,
        )

    # The following three exist only so we can probe ERR_FORM_3922_IMMUTABLE.
    def patch_form_3922(self, form_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/form-3922/{form_id}", payload, headers,
        )

    def delete_form_3922(self, form_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/form-3922/{form_id}", headers=headers,
        )

    # ======================================================================
    # Disposition — PRD §3.7
    # ======================================================================
    def create_disposition(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/dispositions", payload, headers)

    def get_disposition(self, disposition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/dispositions/{disposition_id}", headers=headers,
        )

    def update_disposition(self, disposition_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/dispositions/{disposition_id}", payload, headers,
        )

    def delete_disposition(self, disposition_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/dispositions/{disposition_id}", headers=headers,
        )

    def list_dispositions(self, participant_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/participants/{participant_id}/dispositions",
            headers=headers, params=params,
        )

    # ======================================================================
    # Accrual summary — PRD §3.8
    # ======================================================================
    def get_accrual_summary(self, participant_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/participants/{participant_id}/accrual-summary",
            headers=headers, params=params,
        )

    # ======================================================================
    # System clock + sweep — PRD §2.9
    # ======================================================================
    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", "/_sweep/run", payload, headers)


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
