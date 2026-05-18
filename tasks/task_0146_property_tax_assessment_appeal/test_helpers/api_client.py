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
    # Owners — PRD §3.1, §4
    # =======================================================================
    def create_owner(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/owners/{owner_id}", headers=headers,
        )

    # =======================================================================
    # HearingOfficers — PRD §3.1, §4
    # =======================================================================
    def create_hearing_officer(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", "/hearing_officers", payload, headers)

    def get_hearing_officer(self, officer_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/hearing_officers/{officer_id}", headers=headers,
        )

    # =======================================================================
    # Properties — PRD §3.1, §4
    # =======================================================================
    def create_property(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/properties/{property_id}", headers=headers,
        )

    def transfer_owner(self, property_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/properties/{property_id}/owner", payload, headers,
        )

    # =======================================================================
    # Assessments — PRD §3.2, §4
    # =======================================================================
    def create_assessment(self, property_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/properties/{property_id}/assessments",
            payload, headers,
        )

    def get_assessment(self, property_id: str, assessment_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/properties/{property_id}/assessments/{assessment_id}",
            headers=headers,
        )

    def issue_assessment(self, property_id: str, assessment_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/assessments/{assessment_id}/issue",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # ExemptionApplications — PRD §3.3, §4
    # =======================================================================
    def submit_exemption_application(self, property_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/properties/{property_id}/exemption_applications",
            payload, headers,
        )

    def approve_exemption_application(self, property_id: str,
                                      exemption_application_id: str,
                                      headers: Dict[str, str],
                                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/exemption_applications/"
            f"{exemption_application_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def deny_exemption_application(self, property_id: str,
                                   exemption_application_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/exemption_applications/"
            f"{exemption_application_id}/deny",
            payload if payload is not None else {}, headers,
        )

    def revoke_exemption_application(self, property_id: str,
                                     exemption_application_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/properties/{property_id}/exemption_applications/"
            f"{exemption_application_id}/revoke",
            payload, headers,
        )

    # =======================================================================
    # Appeals — PRD §3.5, §4
    # =======================================================================
    def file_appeal(self, property_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/properties/{property_id}/appeals", payload, headers,
        )

    def get_appeal(self, property_id: str, appeal_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "GET", f"/properties/{property_id}/appeals/{appeal_id}",
            headers=headers,
        )

    def schedule_appeal(self, property_id: str, appeal_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/properties/{property_id}/appeals/{appeal_id}/schedule",
            payload, headers,
        )

    def conduct_appeal(self, property_id: str, appeal_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/appeals/{appeal_id}/conduct",
            payload if payload is not None else {}, headers,
        )

    def decide_appeal(self, property_id: str, appeal_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/properties/{property_id}/appeals/{appeal_id}/decide",
            payload, headers,
        )

    def withdraw_appeal(self, property_id: str, appeal_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/appeals/{appeal_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    def get_hearing(self, property_id: str, appeal_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/properties/{property_id}/appeals/{appeal_id}/hearing",
            headers=headers,
        )

    # =======================================================================
    # TaxBills — PRD §3.4, §4
    # =======================================================================
    def create_tax_bill(self, property_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/properties/{property_id}/tax_bills", payload, headers,
        )

    def get_tax_bill(self, property_id: str, tax_bill_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/properties/{property_id}/tax_bills/{tax_bill_id}",
            headers=headers,
        )

    def issue_tax_bill(self, property_id: str, tax_bill_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/tax_bills/{tax_bill_id}/issue",
            payload if payload is not None else {}, headers,
        )

    def create_payment(self, property_id: str, tax_bill_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/properties/{property_id}/tax_bills/{tax_bill_id}/payments",
            payload, headers,
        )

    def list_payments(self, property_id: str, tax_bill_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/properties/{property_id}/tax_bills/{tax_bill_id}/payments",
            headers=headers, params=params,
        )

    # =======================================================================
    # DeferralPlans — PRD §3.6, §4
    # =======================================================================
    def request_deferral_plan(self, property_id: str, tax_bill_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/tax_bills/{tax_bill_id}/"
            f"deferral_plans",
            payload if payload is not None else {}, headers,
        )

    def activate_deferral_plan(self, property_id: str, tax_bill_id: str,
                               deferral_plan_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/tax_bills/{tax_bill_id}/"
            f"deferral_plans/{deferral_plan_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def cancel_deferral_plan(self, property_id: str, tax_bill_id: str,
                             deferral_plan_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/properties/{property_id}/tax_bills/{tax_bill_id}/"
            f"deferral_plans/{deferral_plan_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def get_deferral_plan(self, property_id: str, tax_bill_id: str,
                          deferral_plan_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/properties/{property_id}/tax_bills/{tax_bill_id}/"
            f"deferral_plans/{deferral_plan_id}",
            headers=headers,
        )

    # =======================================================================
    # Clock — PRD §2.11, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
