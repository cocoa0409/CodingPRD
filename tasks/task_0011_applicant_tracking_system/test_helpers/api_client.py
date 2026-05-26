"""API client: one method per endpoint (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Department ----------
    def create_department(self, payload, headers):
        return self._request("POST", "/ats/departments", payload, headers)

    def get_department(self, dept_id, headers):
        return self._request("GET", f"/ats/departments/{dept_id}", headers=headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/ats/departments", headers=headers, params=params)

    # ---------- JobRequisition ----------
    def create_requisition(self, payload, headers):
        return self._request("POST", "/ats/requisitions", payload, headers)

    def get_requisition(self, req_id, headers):
        return self._request("GET", f"/ats/requisitions/{req_id}", headers=headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/ats/requisitions", headers=headers, params=params)

    def submit_requisition(self, req_id, headers, payload=None):
        return self._request("POST", f"/ats/requisitions/{req_id}/submit",
                             payload if payload is not None else {}, headers)

    def approve_requisition(self, req_id, headers, payload=None):
        return self._request("POST", f"/ats/requisitions/{req_id}/approve",
                             payload if payload is not None else {}, headers)

    def reject_requisition(self, req_id, headers, payload=None):
        return self._request("POST", f"/ats/requisitions/{req_id}/reject",
                             payload if payload is not None else {}, headers)

    def cancel_requisition(self, req_id, payload, headers):
        return self._request("POST", f"/ats/requisitions/{req_id}/cancel", payload, headers)

    # ---------- Candidate ----------
    def create_candidate(self, payload, headers):
        return self._request("POST", "/ats/candidates", payload, headers)

    def get_candidate(self, cand_id, headers):
        return self._request("GET", f"/ats/candidates/{cand_id}", headers=headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/ats/candidates", headers=headers, params=params)

    # ---------- Application ----------
    def create_application(self, payload, headers):
        return self._request("POST", "/ats/applications", payload, headers)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/ats/applications/{app_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/ats/applications", headers=headers, params=params)

    def screen_application(self, app_id, headers, payload=None):
        return self._request("POST", f"/ats/applications/{app_id}/screen",
                             payload if payload is not None else {}, headers)

    def reject_application(self, app_id, headers, payload=None):
        return self._request("POST", f"/ats/applications/{app_id}/reject",
                             payload if payload is not None else {}, headers)

    def withdraw_application(self, app_id, headers, payload=None):
        return self._request("POST", f"/ats/applications/{app_id}/withdraw",
                             payload if payload is not None else {}, headers)

    # ---------- Interview ----------
    def create_interview(self, payload, headers):
        return self._request("POST", "/ats/interviews", payload, headers)

    def get_interview(self, intv_id, headers):
        return self._request("GET", f"/ats/interviews/{intv_id}", headers=headers)

    def list_interviews(self, headers, params=None):
        return self._request("GET", "/ats/interviews", headers=headers, params=params)

    def complete_interview(self, intv_id, headers, payload=None):
        return self._request("POST", f"/ats/interviews/{intv_id}/complete",
                             payload if payload is not None else {}, headers)

    def cancel_interview(self, intv_id, headers, payload=None):
        return self._request("POST", f"/ats/interviews/{intv_id}/cancel",
                             payload if payload is not None else {}, headers)

    # ---------- InterviewFeedback ----------
    def create_interview_feedback(self, payload, headers):
        return self._request("POST", "/ats/interview-feedback", payload, headers)

    def list_interview_feedback(self, headers, params=None):
        return self._request("GET", "/ats/interview-feedback", headers=headers, params=params)

    # ---------- Offer ----------
    def create_offer(self, payload, headers):
        return self._request("POST", "/ats/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/ats/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/ats/offers", headers=headers, params=params)

    def approve_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/ats/offers/{offer_id}/approve", payload, headers)

    def reject_offer(self, offer_id, headers, payload=None):
        return self._request("POST", f"/ats/offers/{offer_id}/reject",
                             payload if payload is not None else {}, headers)

    def extend_offer(self, offer_id, headers, payload=None):
        return self._request("POST", f"/ats/offers/{offer_id}/extend",
                             payload if payload is not None else {}, headers)

    def accept_offer(self, offer_id, headers, payload=None):
        return self._request("POST", f"/ats/offers/{offer_id}/accept",
                             payload if payload is not None else {}, headers)

    def decline_offer(self, offer_id, headers, payload=None):
        return self._request("POST", f"/ats/offers/{offer_id}/decline",
                             payload if payload is not None else {}, headers)

    def revoke_offer(self, offer_id, headers, payload=None):
        return self._request("POST", f"/ats/offers/{offer_id}/revoke",
                             payload if payload is not None else {}, headers)

    # ---------- BackgroundCheck ----------
    def get_background_check(self, bgc_id, headers):
        return self._request("GET", f"/ats/background-checks/{bgc_id}", headers=headers)

    def list_background_checks(self, headers, params=None):
        return self._request("GET", "/ats/background-checks", headers=headers, params=params)

    def start_background_check(self, bgc_id, headers, payload=None):
        return self._request("POST", f"/ats/background-checks/{bgc_id}/start",
                             payload if payload is not None else {}, headers)

    def resolve_background_check(self, bgc_id, payload, headers):
        return self._request("POST", f"/ats/background-checks/{bgc_id}/resolve", payload, headers)

    # ---------- ReferralBonus ----------
    def get_referral_bonus(self, rb_id, headers):
        return self._request("GET", f"/ats/referral-bonuses/{rb_id}", headers=headers)

    def list_referral_bonuses(self, headers, params=None):
        return self._request("GET", "/ats/referral-bonuses", headers=headers, params=params)

    def pay_referral_bonus(self, rb_id, headers, payload=None):
        return self._request("POST", f"/ats/referral-bonuses/{rb_id}/pay",
                             payload if payload is not None else {}, headers)

    def void_referral_bonus(self, rb_id, headers, payload=None):
        return self._request("POST", f"/ats/referral-bonuses/{rb_id}/void",
                             payload if payload is not None else {}, headers)

    # ---------- DiversityGoal ----------
    def create_diversity_goal(self, payload, headers):
        return self._request("POST", "/ats/diversity-goals", payload, headers)

    def get_diversity_goal(self, goal_id, headers):
        return self._request("GET", f"/ats/diversity-goals/{goal_id}", headers=headers)

    def list_diversity_goals(self, headers, params=None):
        return self._request("GET", "/ats/diversity-goals", headers=headers, params=params)

    # ---------- Test-driving clock ----------
    def set_clock(self, payload, headers=None):
        # Clock endpoint is not authenticated (PRD §2.1, §3.8) — headers optional.
        return self._request("POST", "/_clock/set_current_utc", payload, headers or {})


api_client = ApiClient()
