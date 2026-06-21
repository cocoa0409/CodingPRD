"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Registration (PRD §3.1) ───────────────────────────────────
    def register_applicant(self, payload, headers):
        return self._request("POST", "/uscis/applicants/register", payload, headers)

    def register_attorney(self, payload, headers):
        return self._request("POST", "/uscis/attorneys/register", payload, headers)

    # ─── Applicant / Attorney reads ────────────────────────────────
    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/uscis/applicants/{applicant_id}", headers=headers)

    def get_attorney(self, attorney_id, headers):
        return self._request("GET", f"/uscis/attorneys/{attorney_id}", headers=headers)

    # ─── Case CRUD (PRD §3.1) ──────────────────────────────────────
    def create_case(self, payload, headers):
        return self._request("POST", "/uscis/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/uscis/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/uscis/cases", headers=headers, params=params)

    # ─── Case lifecycle transitions (PRD §3.2, §3.3, §3.5, §3.7) ──
    def file_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/uscis/cases/{case_id}/file",
            payload if payload is not None else {},
            headers,
        )

    def advance_review(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/uscis/cases/{case_id}/advance-review",
            payload if payload is not None else {},
            headers,
        )

    def decide_case(self, case_id, payload, headers):
        return self._request("POST", f"/uscis/cases/{case_id}/decide", payload, headers)

    # ─── Biometrics (PRD §3.3) ─────────────────────────────────────
    def schedule_biometrics(self, case_id, payload, headers):
        return self._request(
            "POST", f"/uscis/cases/{case_id}/biometrics", payload, headers
        )

    def list_biometrics_for_case(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/uscis/cases/{case_id}/biometrics", headers=headers, params=params
        )

    def get_biometrics(self, biom_id, headers):
        return self._request("GET", f"/uscis/biometrics/{biom_id}", headers=headers)

    def complete_biometrics(self, biom_id, headers, payload=None):
        return self._request(
            "POST",
            f"/uscis/biometrics/{biom_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def reschedule_biometrics(self, biom_id, payload, headers):
        return self._request(
            "POST", f"/uscis/biometrics/{biom_id}/reschedule", payload, headers
        )

    def mark_biometrics_no_show(self, biom_id, headers, payload=None):
        return self._request(
            "POST",
            f"/uscis/biometrics/{biom_id}/mark-no-show",
            payload if payload is not None else {},
            headers,
        )

    # ─── RFE (PRD §3.5, §3.6) ──────────────────────────────────────
    def issue_rfe(self, case_id, payload, headers):
        return self._request("POST", f"/uscis/cases/{case_id}/rfes", payload, headers)

    def list_rfes_for_case(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/uscis/cases/{case_id}/rfes", headers=headers, params=params
        )

    def get_rfe(self, rfe_id, headers):
        return self._request("GET", f"/uscis/rfes/{rfe_id}", headers=headers)

    def respond_to_rfe(self, rfe_id, payload, headers):
        return self._request("POST", f"/uscis/rfes/{rfe_id}/respond", payload, headers)

    # ─── Interview (PRD §3.5, §3.7) ────────────────────────────────
    def schedule_interview(self, case_id, payload, headers):
        return self._request(
            "POST", f"/uscis/cases/{case_id}/interviews", payload, headers
        )

    def list_interviews_for_case(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/uscis/cases/{case_id}/interviews", headers=headers, params=params
        )

    def get_interview(self, interview_id, headers):
        return self._request("GET", f"/uscis/interviews/{interview_id}", headers=headers)

    def complete_interview(self, interview_id, payload, headers):
        return self._request(
            "POST", f"/uscis/interviews/{interview_id}/complete", payload, headers
        )

    def mark_interview_no_show(self, interview_id, headers, payload=None):
        return self._request(
            "POST",
            f"/uscis/interviews/{interview_id}/mark-no-show",
            payload if payload is not None else {},
            headers,
        )

    # ─── Case events & visa availability reads ─────────────────────
    def list_case_events(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/uscis/cases/{case_id}/events", headers=headers, params=params
        )

    def get_visa_availability(self, case_id, headers):
        return self._request(
            "GET", f"/uscis/cases/{case_id}/visa-availability", headers=headers
        )

    # ─── Visa bulletin (PRD §3.4) ──────────────────────────────────
    def publish_visa_bulletin(self, payload, headers):
        return self._request("POST", "/uscis/visa-bulletin", payload, headers)

    def list_visa_bulletin(self, headers, params=None):
        return self._request(
            "GET", "/uscis/visa-bulletin", headers=headers, params=params
        )

    # ─── Officer workload (PRD §3.8) ───────────────────────────────
    def get_officer_workload(self, officer_id, headers):
        return self._request(
            "GET", f"/uscis/officers/{officer_id}/workload", headers=headers
        )

    # ─── Test-driving (PRD §2.5) ───────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/uscis/_clock/set_current_utc", payload, headers)

    def sweep_rfe_deadlines(self, headers, payload=None):
        return self._request(
            "POST",
            "/uscis/_ops/sweep-rfe-deadlines",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
