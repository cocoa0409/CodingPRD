"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. PRD §4 endpoint paths verbatim.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =====================================================================
    # Recruiters — PRD §3.1, §4
    # =====================================================================
    def create_recruiter(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/recruiters", payload, headers)

    def get_recruiter(self, recruiter_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/recruiters/{recruiter_id}", headers=headers,
        )

    # =====================================================================
    # HiringManagers — PRD §3.1, §4
    # =====================================================================
    def create_hiring_manager(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/hiring-managers", payload, headers)

    # =====================================================================
    # Interviewers — PRD §3.1, §4
    # =====================================================================
    def create_interviewer(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/interviewers", payload, headers)

    # =====================================================================
    # Requisitions — PRD §3.2, §4
    # =====================================================================
    def create_requisition(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/requisitions", payload, headers)

    def list_requisitions(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/requisitions", headers=headers, params=params,
        )

    def get_requisition(self, requisition_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/requisitions/{requisition_id}", headers=headers,
        )

    def patch_requisition(self, requisition_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/requisitions/{requisition_id}", payload, headers,
        )

    def submit_requisition(self, requisition_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/submit",
            payload, headers,
        )

    def approve_requisition(self, requisition_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/approve",
            payload, headers,
        )

    def reject_requisition(self, requisition_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/reject",
            payload, headers,
        )

    def hold_requisition(self, requisition_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/hold",
            payload, headers,
        )

    def resume_requisition(self, requisition_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/resume",
            payload, headers,
        )

    def cancel_requisition(self, requisition_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/cancel",
            payload, headers,
        )

    # =====================================================================
    # Candidates / EEO — PRD §3.1, §4
    # =====================================================================
    def create_candidate(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/candidates/{candidate_id}", headers=headers,
        )

    def create_eeo_record(self, candidate_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/candidates/{candidate_id}/eeo-record",
            payload, headers,
        )

    def get_eeo_record(self, candidate_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/candidates/{candidate_id}/eeo-record",
            headers=headers,
        )

    # =====================================================================
    # Applications — PRD §3.3, §4
    # =====================================================================
    def create_application(self, requisition_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/applications",
            payload, headers,
        )

    def get_application(self, application_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/applications/{application_id}", headers=headers,
        )

    def list_applications(self, requisition_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/requisitions/{requisition_id}/applications",
            headers=headers, params=params,
        )

    def advance_application(self, application_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/advance",
            payload, headers,
        )

    def reject_application(self, application_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/reject",
            payload, headers,
        )

    def withdraw_application(self, application_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw",
            payload, headers,
        )

    # =====================================================================
    # Interviews / Feedback — PRD §3.4, §4
    # =====================================================================
    def create_interview(self, application_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/interviews",
            payload, headers,
        )

    def get_interview(self, interview_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/interviews/{interview_id}", headers=headers,
        )

    def complete_interview(self, interview_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/interviews/{interview_id}/complete",
            payload, headers,
        )

    def no_show_interview(self, interview_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/interviews/{interview_id}/no-show",
            payload, headers,
        )

    def cancel_interview(self, interview_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/interviews/{interview_id}/cancel",
            payload, headers,
        )

    def create_interview_feedback(self, interview_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/interviews/{interview_id}/feedback",
            payload, headers,
        )

    def list_interview_feedback(self, interview_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/interviews/{interview_id}/feedback",
            headers=headers, params=params,
        )

    # =====================================================================
    # Offers / Approval Chain — PRD §3.5, §4
    # =====================================================================
    def create_offer(self, application_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/offers",
            payload, headers,
        )

    def get_offer(self, offer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/offers/{offer_id}", headers=headers,
        )

    def patch_offer(self, offer_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/offers/{offer_id}", payload, headers,
        )

    def submit_offer(self, offer_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/offers/{offer_id}/submit", payload, headers,
        )

    def approve_offer(self, offer_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/offers/{offer_id}/approve", payload, headers,
        )

    def request_revision_offer(self, offer_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/offers/{offer_id}/request-revision",
            payload, headers,
        )

    def extend_offer(self, offer_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/offers/{offer_id}/extend", payload, headers,
        )

    def accept_offer(self, offer_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/offers/{offer_id}/accept", payload, headers,
        )

    def decline_offer(self, offer_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/offers/{offer_id}/decline", payload, headers,
        )

    def rescind_offer(self, offer_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/offers/{offer_id}/rescind", payload, headers,
        )

    def get_approval_chain(self, offer_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/offers/{offer_id}/approval-chain", headers=headers,
        )

    # =====================================================================
    # Background Checks — PRD §3.7, §4
    # =====================================================================
    def create_background_check(self, offer_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/offers/{offer_id}/background-check",
            payload, headers,
        )

    def get_background_check(self, bgc_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/background-checks/{bgc_id}", headers=headers,
        )

    def report_background_check_result(self, bgc_id: str,
                                       payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/background-checks/{bgc_id}/report-result",
            payload, headers,
        )

    def cancel_background_check(self, bgc_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/background-checks/{bgc_id}/cancel",
            payload, headers,
        )

    # =====================================================================
    # Referral Bonuses — PRD §3.6, §4
    # =====================================================================
    def list_referral_bonuses(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/referral-bonuses", headers=headers, params=params,
        )

    def get_referral_bonus(self, bonus_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/referral-bonuses/{bonus_id}", headers=headers,
        )

    def pay_referral_bonus(self, bonus_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/referral-bonuses/{bonus_id}/pay",
            payload, headers,
        )

    # =====================================================================
    # Diversity Goals — PRD §3.6, §4
    # =====================================================================
    def create_diversity_goal(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/diversity-goals", payload, headers)

    def get_diversity_goal(self, goal_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/diversity-goals/{goal_id}", headers=headers,
        )

    def lock_diversity_goal(self, goal_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/diversity-goals/{goal_id}/lock",
            payload, headers,
        )

    # =====================================================================
    # Test-driving harness — PRD §2.11, §4
    # =====================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
