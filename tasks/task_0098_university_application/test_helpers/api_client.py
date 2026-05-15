"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Test harness — clock advance (PRD §3.11)
    # =======================================================================
    def advance_clock(self, seconds: int, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"seconds": seconds}, headers,
        )

    # =======================================================================
    # Applicants (PRD §3.1)
    # =======================================================================
    def create_applicant(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/applicants/{applicant_id}", headers=headers,
        )

    def patch_applicant(self, applicant_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/applicants/{applicant_id}", payload, headers,
        )

    # =======================================================================
    # Universities (PRD §3.2)
    # =======================================================================
    def create_university(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/universities", payload, headers)

    def get_university(self, university_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/universities/{university_id}", headers=headers,
        )

    # =======================================================================
    # Programs (PRD §3.2)
    # =======================================================================
    def create_program(self, university_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/universities/{university_id}/programs",
            payload, headers,
        )

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/programs/{program_id}", headers=headers,
        )

    # =======================================================================
    # Applications (PRD §3.3, §3.6, §3.7, §3.10)
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
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/submit",
            payload or {}, headers,
        )

    def withdraw_submission(self, application_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/applications/{application_id}/withdraw-submission",
            payload or {}, headers,
        )

    def withdraw_application(self, application_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw",
            payload or {}, headers,
        )

    def begin_review(self, application_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/begin-review",
            {}, headers,
        )

    def decide_application(self, application_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/decide",
            payload, headers,
        )

    def enroll_application(self, application_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/enroll",
            payload or {}, headers,
        )

    # =======================================================================
    # Essays (PRD §3.4)
    # =======================================================================
    def attach_essay(self, application_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/essays",
            payload, headers,
        )

    def patch_essay(self, essay_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/essays/{essay_id}", payload, headers,
        )

    def get_essay(self, essay_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/essays/{essay_id}", headers=headers,
        )

    # =======================================================================
    # Recommendations (PRD §3.5)
    # =======================================================================
    def create_recommendation(self, application_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/recommendations",
            payload, headers,
        )

    def get_recommendation(self, recommendation_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/recommendations/{recommendation_id}",
            headers=headers,
        )

    def accept_recommendation(self, recommendation_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/recommendations/{recommendation_id}/accept",
            {}, headers,
        )

    def decline_recommendation(self, recommendation_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/recommendations/{recommendation_id}/decline",
            {}, headers,
        )

    def reassign_recommendation(self, recommendation_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/recommendations/{recommendation_id}/reassign",
            payload, headers,
        )

    def submit_letter(self, recommendation_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/recommendations/{recommendation_id}/submit-letter",
            payload, headers,
        )

    # =======================================================================
    # Financial aid (PRD §3.8)
    # =======================================================================
    def create_financial_aid(self, application_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/financial-aid",
            payload, headers,
        )

    def get_financial_aid(self, package_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/financial-aid/{package_id}", headers=headers,
        )

    def issue_aid_offer(self, package_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/financial-aid/{package_id}/issue-offer",
            {}, headers,
        )

    def accept_aid_offer(self, package_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/financial-aid/{package_id}/accept",
            payload or {}, headers,
        )

    def decline_aid_offer(self, package_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/financial-aid/{package_id}/decline",
            payload or {}, headers,
        )

    # =======================================================================
    # Waitlist (PRD §3.9)
    # =======================================================================
    def get_waitlist_entry(self, entry_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/waitlist/{entry_id}", headers=headers,
        )

    def accept_waitlist_offer(self, entry_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/waitlist/{entry_id}/accept-offer",
            payload or {}, headers,
        )

    # =======================================================================
    # Yield management (PRD §3.9)
    # =======================================================================
    def run_yield_sweep(self, university_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/universities/{university_id}/yield-sweep",
            {}, headers,
        )

    def list_yield_sweeps(self, university_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/universities/{university_id}/yield-sweeps",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
