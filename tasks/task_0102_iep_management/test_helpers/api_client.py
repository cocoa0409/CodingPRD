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
    # District + deterministic clock — PRD §3.1, §2.7
    # =======================================================================
    def create_district(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/districts", payload, headers)

    def get_district(self, district_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/districts/{district_id}", headers=headers,
        )

    def advance_clock(self, district_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/districts/{district_id}/clock/advance",
            payload, headers,
        )

    # =======================================================================
    # Student — PRD §3.1
    # =======================================================================
    def create_student(self, district_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/districts/{district_id}/students", payload, headers,
        )

    def list_students(self, district_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/districts/{district_id}/students",
            headers=headers, params=params,
        )

    def get_student(self, district_id: str, student_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/districts/{district_id}/students/{student_id}",
            headers=headers,
        )

    # =======================================================================
    # Eligibility Evaluations — PRD §3.2
    # =======================================================================
    def create_eligibility_evaluation(
        self, district_id: str, student_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"eligibility-evaluations",
            payload, headers,
        )

    def request_evaluation_consent(
        self, district_id: str, student_id: str,
        evaluation_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"eligibility-evaluations/{evaluation_id}/request-consent",
            {}, headers,
        )

    def finalize_evaluation(
        self, district_id: str, student_id: str,
        evaluation_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"eligibility-evaluations/{evaluation_id}/finalize",
            payload, headers,
        )

    def list_evaluations(self, district_id: str, student_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/"
            f"eligibility-evaluations",
            headers=headers, params=params,
        )

    def get_evaluation(self, district_id: str, student_id: str,
                       evaluation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/"
            f"eligibility-evaluations/{evaluation_id}",
            headers=headers,
        )

    # =======================================================================
    # Parental Consents — PRD §3.4
    # =======================================================================
    def create_parental_consent(
        self, district_id: str, student_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"parental-consents",
            payload, headers,
        )

    def approve_consent(self, district_id: str, student_id: str,
                        consent_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"parental-consents/{consent_id}/approve",
            {}, headers,
        )

    def reject_consent(self, district_id: str, student_id: str,
                       consent_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"parental-consents/{consent_id}/reject",
            {}, headers,
        )

    def withdraw_consent(self, district_id: str, student_id: str,
                         consent_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"parental-consents/{consent_id}/withdraw",
            {}, headers,
        )

    def list_consents(self, district_id: str, student_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/"
            f"parental-consents",
            headers=headers, params=params,
        )

    # =======================================================================
    # IEPs — PRD §3.3, §3.5
    # =======================================================================
    def create_iep(self, district_id: str, student_id: str,
                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/ieps",
            payload, headers,
        )

    def list_ieps(self, district_id: str, student_id: str,
                  headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/ieps",
            headers=headers, params=params,
        )

    def get_iep(self, district_id: str, student_id: str,
                iep_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}",
            headers=headers,
        )

    def get_lre_summary(self, district_id: str, student_id: str,
                        iep_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/lre-summary",
            headers=headers,
        )

    def activate_iep(self, district_id: str, student_id: str,
                     iep_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/activate",
            {}, headers,
        )

    def begin_iep_amendment(self, district_id: str, student_id: str,
                            iep_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/begin-amendment",
            {}, headers,
        )

    def finalize_iep_amendment(self, district_id: str, student_id: str,
                                iep_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/finalize-amendment",
            {}, headers,
        )

    # =======================================================================
    # IEP Goals — PRD §3.3, §3.5, §3.7
    # =======================================================================
    def create_goal(self, district_id: str, student_id: str,
                    iep_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/goals",
            payload, headers,
        )

    def list_goals(self, district_id: str, student_id: str,
                   iep_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/goals",
            headers=headers, params=params,
        )

    def close_goal(self, district_id: str, student_id: str,
                   iep_id: str, goal_id: str,
                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/goals/{goal_id}/close",
            payload, headers,
        )

    def create_progress_report(self, district_id: str, student_id: str,
                                iep_id: str, goal_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/goals/{goal_id}/progress-reports",
            payload, headers,
        )

    # =======================================================================
    # Related Services — PRD §3.6
    # =======================================================================
    def create_related_service(
        self, district_id: str, student_id: str, iep_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/related-services",
            payload, headers,
        )

    def list_related_services(
        self, district_id: str, student_id: str, iep_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/related-services",
            headers=headers, params=params,
        )

    def activate_related_service(
        self, district_id: str, student_id: str, iep_id: str,
        service_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PUT",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/related-services/{service_id}/activate",
            payload, headers,
        )

    def suspend_related_service(
        self, district_id: str, student_id: str, iep_id: str,
        service_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "PUT",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/related-services/{service_id}/suspend",
            {}, headers,
        )

    def resume_related_service(
        self, district_id: str, student_id: str, iep_id: str,
        service_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PUT",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/related-services/{service_id}/resume",
            payload, headers,
        )

    # =======================================================================
    # Service Sessions — PRD §3.6
    # =======================================================================
    def create_session(
        self, district_id: str, student_id: str, iep_id: str,
        service_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/related-services/{service_id}/sessions",
            payload, headers,
        )

    def deliver_session(
        self, district_id: str, student_id: str, iep_id: str,
        service_id: str, session_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/related-services/{service_id}/"
            f"sessions/{session_id}/deliver",
            payload, headers,
        )

    def cancel_session(
        self, district_id: str, student_id: str, iep_id: str,
        service_id: str, session_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/related-services/{service_id}/"
            f"sessions/{session_id}/cancel",
            {}, headers,
        )

    # =======================================================================
    # Transition Plan — PRD §3.3, §3.5
    # =======================================================================
    def create_transition_plan(
        self, district_id: str, student_id: str, iep_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/transition-plan",
            payload, headers,
        )

    def finalize_transition_plan(
        self, district_id: str, student_id: str, iep_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/transition-plan/finalize",
            {}, headers,
        )

    def get_transition_plan(
        self, district_id: str, student_id: str, iep_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/districts/{district_id}/students/{student_id}/"
            f"ieps/{iep_id}/transition-plan",
            headers=headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
