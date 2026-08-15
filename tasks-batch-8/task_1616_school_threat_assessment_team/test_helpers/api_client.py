"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # District administration: schools, logical clock, retention, report
    # ------------------------------------------------------------------
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def purge_records(self, headers):
        return self._request("POST", "/records-retention/purge", {}, headers)

    def get_district_annual_report(self, school_year, headers):
        return self._request("GET", "/annual-reports/district",
                             {"school_year": school_year}, headers)

    # ------------------------------------------------------------------
    # Threat cases
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/threat-cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/threat-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/threat-cases/{case_id}", headers=headers)

    def triage_case(self, case_id, payload, headers):
        return self._request("POST", f"/threat-cases/{case_id}/triage", payload, headers)

    def record_screening(self, case_id, payload, headers):
        return self._request("POST", f"/threat-cases/{case_id}/screening", payload, headers)

    def remove_case(self, case_id, payload, headers):
        return self._request("POST", f"/threat-cases/{case_id}/remove", payload, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/threat-cases/{case_id}/close", {}, headers)

    def reopen_case(self, case_id, headers):
        return self._request("POST", f"/threat-cases/{case_id}/reopen", {}, headers)

    # ------------------------------------------------------------------
    # Case sub-resource reads and case documents
    # ------------------------------------------------------------------
    def list_case_interviews(self, case_id, headers, params=None):
        return self._request("GET", f"/threat-cases/{case_id}/interviews",
                             headers=headers, params=params)

    def list_case_assessments(self, case_id, headers, params=None):
        return self._request("GET", f"/threat-cases/{case_id}/risk-assessments",
                             headers=headers, params=params)

    def list_case_plans(self, case_id, headers, params=None):
        return self._request("GET", f"/threat-cases/{case_id}/management-plans",
                             headers=headers, params=params)

    def list_case_referrals(self, case_id, headers, params=None):
        return self._request("GET", f"/threat-cases/{case_id}/referrals",
                             headers=headers, params=params)

    def list_case_checkins(self, case_id, headers, params=None):
        return self._request("GET", f"/threat-cases/{case_id}/monitoring-check-ins",
                             headers=headers, params=params)

    def list_case_reentry_plans(self, case_id, headers, params=None):
        return self._request("GET", f"/threat-cases/{case_id}/re-entry-plans",
                             headers=headers, params=params)

    def list_case_documents(self, case_id, headers, params=None):
        return self._request("GET", f"/threat-cases/{case_id}/documents",
                             headers=headers, params=params)

    def create_case_document(self, case_id, payload, headers):
        return self._request("POST", f"/threat-cases/{case_id}/documents",
                             payload, headers)

    def list_case_audit_events(self, case_id, headers, params=None):
        return self._request("GET", f"/threat-cases/{case_id}/audit-events",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Interviews
    # ------------------------------------------------------------------
    def create_interview(self, payload, headers):
        return self._request("POST", "/interviews", payload, headers)

    def complete_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/interviews/{interview_id}/complete",
                             payload, headers)

    def cancel_interview(self, interview_id, headers):
        return self._request("POST", f"/interviews/{interview_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Risk assessments
    # ------------------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/risk-assessments", payload, headers)

    def update_assessment(self, assessment_id, payload, headers):
        return self._request("PUT", f"/risk-assessments/{assessment_id}",
                             payload, headers)

    def submit_assessment(self, assessment_id, headers):
        return self._request("POST", f"/risk-assessments/{assessment_id}/submit",
                             {}, headers)

    def return_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/risk-assessments/{assessment_id}/return",
                             payload, headers)

    def finalize_assessment(self, assessment_id, headers):
        return self._request("POST", f"/risk-assessments/{assessment_id}/finalize",
                             {}, headers)

    # ------------------------------------------------------------------
    # Management plans
    # ------------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/management-plans", payload, headers)

    def activate_plan(self, plan_id, expected_threat_case_version, headers):
        return self._request(
            "POST", f"/management-plans/{plan_id}/activate",
            {"expected_threat_case_version": expected_threat_case_version}, headers)

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def acknowledge_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/acknowledge",
                             {}, headers)

    def decline_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/decline",
                             payload, headers)

    def withdraw_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Monitoring check-ins
    # ------------------------------------------------------------------
    def create_checkin(self, payload, headers):
        return self._request("POST", "/monitoring-check-ins", payload, headers)

    def complete_checkin(self, checkin_id, payload, headers):
        return self._request("POST", f"/monitoring-check-ins/{checkin_id}/complete",
                             payload, headers)

    def reschedule_checkin(self, checkin_id, payload, headers):
        return self._request("POST", f"/monitoring-check-ins/{checkin_id}/reschedule",
                             payload, headers)

    # ------------------------------------------------------------------
    # Re-entry plans
    # ------------------------------------------------------------------
    def create_reentry_plan(self, payload, headers):
        return self._request("POST", "/re-entry-plans", payload, headers)

    def approve_reentry_plan(self, plan_id, headers):
        return self._request("POST", f"/re-entry-plans/{plan_id}/approve",
                             {}, headers)

    def deny_reentry_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/re-entry-plans/{plan_id}/deny",
                             payload, headers)

    def verify_reentry_condition(self, plan_id, condition_index, payload, headers):
        return self._request(
            "POST",
            f"/re-entry-plans/{plan_id}/conditions/{condition_index}/verify",
            payload, headers)

    def complete_reentry(self, plan_id, headers):
        return self._request("POST", f"/re-entry-plans/{plan_id}/complete-re-entry",
                             {}, headers)


api_client = ApiClient()
