"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.

All paths are mounted under the /business-registry prefix (PRD §2:
"The whole API is mounted under the /business-registry prefix.").
The two infrastructure endpoints /_clock/advance and /_sweep/run live
under the same prefix per the PRD §4 endpoint table.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # BusinessEntity — PRD §3.1, §3.11, §4
    # ======================================================================
    def create_entity(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/entities", payload, headers,
        )

    def get_entity(self, entity_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/business-registry/entities/{entity_id}",
            headers=headers,
        )

    def list_entities(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/business-registry/entities",
            headers=headers, params=params,
        )

    def form_entity(self, entity_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/entities/{entity_id}/form",
            payload, headers,
        )

    def dissolve_entity(self, entity_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/entities/{entity_id}/dissolve",
            payload, headers,
        )

    def administratively_dissolve_entity(self, entity_id: str,
                                         headers: Dict[str, str],
                                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/entities/{entity_id}/administratively-dissolve",
            payload, headers,
        )

    def get_exposure_summary(self, entity_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/business-registry/entities/{entity_id}/exposure-summary",
            headers=headers, params=params,
        )

    def credit_deposit(self, entity_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/business-registry/entities/{entity_id}/credit-deposit",
            payload, headers,
        )

    def list_compliance_events(self, entity_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/business-registry/entities/{entity_id}/compliance-events",
            headers=headers, params=params,
        )

    # ======================================================================
    # RegisteredAgent — PRD §3.2, §4
    # ======================================================================
    def create_registered_agent(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/registered-agents", payload, headers,
        )

    def patch_registered_agent(self, agent_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/business-registry/registered-agents/{agent_id}",
            payload, headers,
        )

    def resign_registered_agent(self, agent_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/registered-agents/{agent_id}/resign",
            payload, headers,
        )

    # ======================================================================
    # OperatingAgreement — PRD §3.3, §4
    # ======================================================================
    def create_operating_agreement(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/operating-agreements",
            payload, headers,
        )

    # ======================================================================
    # EINApplication — PRD §3.4, §4
    # ======================================================================
    def create_ein_application(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/ein-applications",
            payload, headers,
        )

    def submit_ein_application(self, app_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/ein-applications/{app_id}/submit",
            payload, headers,
        )

    def approve_ein_application(self, app_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/ein-applications/{app_id}/approve",
            payload, headers,
        )

    def reject_ein_application(self, app_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/ein-applications/{app_id}/reject",
            payload, headers,
        )

    # ======================================================================
    # AnnualReport — PRD §3.5, §4
    # ======================================================================
    def create_annual_report(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/annual-reports", payload, headers,
        )

    def patch_annual_report(self, report_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/business-registry/annual-reports/{report_id}",
            payload, headers,
        )

    def submit_annual_report(self, report_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/annual-reports/{report_id}/submit",
            payload, headers,
        )

    def accept_annual_report(self, report_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/annual-reports/{report_id}/accept",
            payload, headers,
        )

    def reject_annual_report(self, report_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/business-registry/annual-reports/{report_id}/reject",
            payload, headers,
        )

    # ======================================================================
    # FranchiseTaxAssessment — PRD §3.6, §4
    # ======================================================================
    def create_tax_assessment(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/tax-assessments", payload, headers,
        )

    def get_tax_assessment(self, assessment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/business-registry/tax-assessments/{assessment_id}",
            headers=headers,
        )

    def pay_tax_assessment(self, assessment_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/tax-assessments/{assessment_id}/pay",
            payload, headers,
        )

    def refund_tax_assessment(self, assessment_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/tax-assessments/{assessment_id}/refund",
            payload, headers,
        )

    # ======================================================================
    # ForeignQualification — PRD §3.7, §4
    # ======================================================================
    def create_foreign_qualification(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/foreign-qualifications",
            payload, headers,
        )

    def patch_foreign_qualification(self, qual_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/business-registry/foreign-qualifications/{qual_id}",
            payload, headers,
        )

    def approve_foreign_qualification(self, qual_id: str,
                                      headers: Dict[str, str],
                                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/foreign-qualifications/{qual_id}/approve",
            payload, headers,
        )

    def reject_foreign_qualification(self, qual_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/foreign-qualifications/{qual_id}/reject",
            payload, headers,
        )

    def withdraw_foreign_qualification(self, qual_id: str,
                                       headers: Dict[str, str],
                                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/foreign-qualifications/{qual_id}/withdraw",
            payload, headers,
        )

    # ======================================================================
    # BeneficialOwner / BOIOwnership / BOIReport — PRD §3.8, §4
    # ======================================================================
    def create_beneficial_owner(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/beneficial-owners",
            payload, headers,
        )

    def add_boi_ownership(self, entity_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/business-registry/entities/{entity_id}/boi-ownership",
            payload, headers,
        )

    def delete_boi_ownership(self, entity_id: str, ownership_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/business-registry/entities/{entity_id}/"
            f"boi-ownership/{ownership_id}",
            headers=headers,
        )

    def create_boi_report(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/boi-reports", payload, headers,
        )

    def file_boi_report(self, report_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/business-registry/boi-reports/{report_id}/file",
            payload, headers,
        )

    # ======================================================================
    # Time-driving (PRD §3.12, §4)
    # ======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/business-registry/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/business-registry/_sweep/run", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
