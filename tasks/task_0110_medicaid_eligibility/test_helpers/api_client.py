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
    # StatePolicy — PRD §3.1, §4 (PolicyAdmin-only writes)
    # =======================================================================
    def create_state_policy(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/state-policies", payload, headers)

    def get_state_policy(self, state_code: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/state-policies/{state_code}", headers=headers,
        )

    # =======================================================================
    # EmergencyDeclaration — PRD §3.5, §4
    # =======================================================================
    def create_emergency_declaration(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/emergency-declarations", payload, headers,
        )

    def get_emergency_declaration(self, declaration_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/emergency-declarations/{declaration_id}",
            headers=headers,
        )

    def list_emergency_declarations(self, headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/emergency-declarations",
            headers=headers, params=params,
        )

    # =======================================================================
    # Household — PRD §3.1, §4
    # =======================================================================
    def create_household(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/households/{household_id}", headers=headers,
        )

    def patch_household(self, household_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/households/{household_id}", payload, headers,
        )

    # =======================================================================
    # Applicant + Income + Asset — PRD §3.1, §3.2, §4
    # =======================================================================
    def create_applicant(self, household_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/households/{household_id}/applicants",
            payload, headers,
        )

    def get_applicant(self, household_id: str, applicant_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/households/{household_id}/applicants/{applicant_id}",
            headers=headers,
        )

    def create_income_record(self, household_id: str, applicant_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/households/{household_id}/applicants/{applicant_id}/income",
            payload, headers,
        )

    def create_asset_record(self, household_id: str, applicant_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/households/{household_id}/applicants/{applicant_id}/assets",
            payload, headers,
        )

    # =======================================================================
    # Application — PRD §3.3, §4
    # =======================================================================
    def create_application(self, household_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/households/{household_id}/applications",
            payload, headers,
        )

    def get_application(self, household_id: str, application_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/households/{household_id}/applications/{application_id}",
            headers=headers,
        )

    def patch_application(self, household_id: str, application_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/households/{household_id}/applications/{application_id}",
            payload, headers,
        )

    def submit_application(self, household_id: str, application_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/households/{household_id}/applications/{application_id}/submit",
            {}, headers,
        )

    def decide_application(self, household_id: str, application_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/households/{household_id}/applications/{application_id}/decide",
            payload, headers,
        )

    def withdraw_application(self, household_id: str, application_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/households/{household_id}/applications/{application_id}/withdraw",
            {}, headers,
        )

    # =======================================================================
    # Enrollment — PRD §3.4, §4
    # =======================================================================
    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}", headers=headers,
        )

    def list_enrollments(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/enrollments", headers=headers, params=params,
        )

    def suspend_enrollment(self, enrollment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/suspend", {}, headers,
        )

    def reactivate_enrollment(self, enrollment_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/reactivate", {}, headers,
        )

    # =======================================================================
    # Redetermination — PRD §3.4, §4
    # =======================================================================
    def get_redetermination(self, redetermination_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/redeterminations/{redetermination_id}",
            headers=headers,
        )

    def submit_redetermination(self, redetermination_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/redeterminations/{redetermination_id}/submit",
            payload, headers,
        )

    def withdraw_redetermination(self, redetermination_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/redeterminations/{redetermination_id}/withdraw",
            {}, headers,
        )

    # =======================================================================
    # Appeal — PRD §3.6, §4
    # =======================================================================
    def create_appeal(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appeals/{appeal_id}", headers=headers,
        )

    def schedule_hearing(self, appeal_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/schedule-hearing",
            payload, headers,
        )

    def grant_appeal(self, appeal_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/grant", payload, headers,
        )

    def uphold_appeal(self, appeal_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/uphold", payload, headers,
        )

    def withdraw_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/withdraw", {}, headers,
        )

    # =======================================================================
    # FairHearing — PRD §3.6, §4
    # =======================================================================
    def get_fair_hearing(self, fair_hearing_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/fair-hearings/{fair_hearing_id}", headers=headers,
        )

    def hold_fair_hearing(self, fair_hearing_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/fair-hearings/{fair_hearing_id}/hold", {}, headers,
        )

    # =======================================================================
    # Test-driving endpoints — PRD §2.11, §4 (PolicyAdmin-only)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_redetermination_sweep(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/redeterminations", {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
