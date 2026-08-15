"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/bit/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/bit/students/{student_id}", headers=headers)

    def patch_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/bit/students/{student_id}", payload, headers)

    # --- Staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/bit/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/bit/staff/{staff_id}", headers=headers)

    # --- Concern reports ---
    def create_concern_report(self, payload, headers):
        return self._request("POST", "/bit/concern-reports", payload, headers)

    def get_concern_report(self, report_id, headers):
        return self._request("GET", f"/bit/concern-reports/{report_id}", headers=headers)

    def list_concern_reports(self, headers, params=None):
        return self._request("GET", "/bit/concern-reports", headers=headers, params=params)

    def start_review_concern_report(self, report_id, headers):
        return self._request("POST", f"/bit/concern-reports/{report_id}/start-review", headers=headers)

    def accept_concern_report(self, report_id, payload, headers):
        return self._request("POST", f"/bit/concern-reports/{report_id}/accept", payload, headers)

    def close_no_action_concern_report(self, report_id, payload, headers):
        return self._request("POST", f"/bit/concern-reports/{report_id}/close-no-action", payload, headers)

    # --- Care cases ---
    def get_care_case(self, case_id, headers):
        return self._request("GET", f"/bit/care-cases/{case_id}", headers=headers)

    def list_care_cases(self, headers, params=None):
        return self._request("GET", "/bit/care-cases", headers=headers, params=params)

    def assign_case_manager(self, case_id, payload, headers):
        return self._request("POST", f"/bit/care-cases/{case_id}/assign-manager", payload, headers)

    def close_care_case(self, case_id, headers):
        return self._request("POST", f"/bit/care-cases/{case_id}/close", headers=headers)

    # --- Risk scorings ---
    def create_risk_scoring(self, payload, headers):
        return self._request("POST", "/bit/risk-scorings", payload, headers)

    def get_risk_scoring(self, scoring_id, headers):
        return self._request("GET", f"/bit/risk-scorings/{scoring_id}", headers=headers)

    def list_risk_scorings(self, headers, params=None):
        return self._request("GET", "/bit/risk-scorings", headers=headers, params=params)

    # --- Intervention plans ---
    def create_intervention_plan(self, payload, headers):
        return self._request("POST", "/bit/intervention-plans", payload, headers)

    def get_intervention_plan(self, plan_id, headers):
        return self._request("GET", f"/bit/intervention-plans/{plan_id}", headers=headers)

    def list_intervention_plans(self, headers, params=None):
        return self._request("GET", "/bit/intervention-plans", headers=headers, params=params)

    def submit_intervention_plan(self, plan_id, headers):
        return self._request("POST", f"/bit/intervention-plans/{plan_id}/submit", headers=headers)

    def approve_intervention_plan(self, plan_id, headers):
        return self._request("POST", f"/bit/intervention-plans/{plan_id}/approve", headers=headers)

    def return_intervention_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/bit/intervention-plans/{plan_id}/return", payload, headers)

    # --- Mandated assessments ---
    def create_mandated_assessment(self, payload, headers):
        return self._request("POST", "/bit/mandated-assessments", payload, headers)

    def get_mandated_assessment(self, assessment_id, headers):
        return self._request("GET", f"/bit/mandated-assessments/{assessment_id}", headers=headers)

    def list_mandated_assessments(self, headers, params=None):
        return self._request("GET", "/bit/mandated-assessments", headers=headers, params=params)

    def record_assessment_outcome(self, assessment_id, payload, headers):
        return self._request("POST", f"/bit/mandated-assessments/{assessment_id}/record-outcome", payload, headers)

    # --- Leave decisions ---
    def get_leave_decision(self, decision_id, headers):
        return self._request("GET", f"/bit/leave-decisions/{decision_id}", headers=headers)

    def list_leave_decisions(self, headers, params=None):
        return self._request("GET", "/bit/leave-decisions", headers=headers, params=params)

    def decide_leave(self, decision_id, payload, headers):
        return self._request("POST", f"/bit/leave-decisions/{decision_id}/decide", payload, headers)

    # --- Re-entry evaluations ---
    def create_reentry_evaluation(self, payload, headers):
        return self._request("POST", "/bit/reentry-evaluations", payload, headers)

    def get_reentry_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/bit/reentry-evaluations/{evaluation_id}", headers=headers)

    def list_reentry_evaluations(self, headers, params=None):
        return self._request("GET", "/bit/reentry-evaluations", headers=headers, params=params)

    def decide_reentry_evaluation(self, evaluation_id, payload, headers):
        return self._request("POST", f"/bit/reentry-evaluations/{evaluation_id}/decide", payload, headers)

    # --- Follow-up check-ins ---
    def get_follow_up_checkin(self, checkin_id, headers):
        return self._request("GET", f"/bit/follow-up-checkins/{checkin_id}", headers=headers)

    def list_follow_up_checkins(self, headers, params=None):
        return self._request("GET", "/bit/follow-up-checkins", headers=headers, params=params)

    def complete_follow_up_checkin(self, checkin_id, payload, headers):
        return self._request("POST", f"/bit/follow-up-checkins/{checkin_id}/complete", payload, headers)

    # --- Disclosure grants ---
    def create_disclosure_grant(self, payload, headers):
        return self._request("POST", "/bit/disclosure-grants", payload, headers)

    def get_disclosure_grant(self, grant_id, headers):
        return self._request("GET", f"/bit/disclosure-grants/{grant_id}", headers=headers)

    def list_disclosure_grants(self, headers, params=None):
        return self._request("GET", "/bit/disclosure-grants", headers=headers, params=params)

    def approve_disclosure_grant(self, grant_id, headers):
        return self._request("POST", f"/bit/disclosure-grants/{grant_id}/approve", headers=headers)

    def deny_disclosure_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/bit/disclosure-grants/{grant_id}/deny", payload, headers)

    def revoke_disclosure_grant(self, grant_id, headers):
        return self._request("POST", f"/bit/disclosure-grants/{grant_id}/revoke", headers=headers)

    # --- Trend reports ---
    def create_trend_report(self, payload, headers):
        return self._request("POST", "/bit/trend-reports", payload, headers)

    def get_trend_report(self, report_id, headers):
        return self._request("GET", f"/bit/trend-reports/{report_id}", headers=headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/bit/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
