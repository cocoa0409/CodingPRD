"""API client: one method per endpoint defined in the PRD (§4).

All resource collections are mounted under /api; only the logical-clock
control lives at the server root (PRD §2.11, §4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- payers ---
    def create_payer(self, payload, headers):
        return self._request("POST", "/api/payers", payload, headers)

    def list_payers(self, headers, params=None):
        return self._request("GET", "/api/payers", headers=headers, params=params)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/api/payers/{payer_id}", headers=headers)

    # --- physicians ---
    def create_physician(self, payload, headers):
        return self._request("POST", "/api/physicians", payload, headers)

    def list_physicians(self, headers, params=None):
        return self._request("GET", "/api/physicians", headers=headers, params=params)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/api/physicians/{physician_id}", headers=headers)

    def list_physician_conferences(self, physician_id, headers):
        return self._request(
            "GET", f"/api/physicians/{physician_id}/peer-to-peer-conferences",
            headers=headers)

    def list_physician_cc44_requests(self, physician_id, headers):
        return self._request(
            "GET", f"/api/physicians/{physician_id}/condition-code-44-requests",
            headers=headers)

    # --- utilization cases ---
    def create_utilization_case(self, payload, headers):
        return self._request("POST", "/api/utilization-cases", payload, headers)

    def list_utilization_cases(self, headers, params=None):
        return self._request("GET", "/api/utilization-cases", headers=headers,
                             params=params)

    def get_utilization_case(self, case_id, headers):
        return self._request("GET", f"/api/utilization-cases/{case_id}",
                             headers=headers)

    def discharge_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/utilization-cases/{case_id}/discharge",
                             payload, headers)

    # --- admission reviews ---
    def create_admission_review(self, case_id, payload, headers):
        return self._request(
            "POST", f"/api/utilization-cases/{case_id}/admission-reviews",
            payload, headers)

    def list_admission_reviews(self, case_id, headers):
        return self._request(
            "GET", f"/api/utilization-cases/{case_id}/admission-reviews",
            headers=headers)

    def get_admission_review(self, review_id, headers):
        return self._request("GET", f"/api/admission-reviews/{review_id}",
                             headers=headers)

    def submit_admission_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/admission-reviews/{review_id}/submit",
                             payload, headers)

    def advisor_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/api/admission-reviews/{review_id}/advisor-review",
            payload, headers)

    # --- authorization requests ---
    def create_authorization_request(self, case_id, payload, headers):
        return self._request(
            "POST", f"/api/utilization-cases/{case_id}/authorization-requests",
            payload, headers)

    def list_authorization_requests(self, case_id, headers):
        return self._request(
            "GET", f"/api/utilization-cases/{case_id}/authorization-requests",
            headers=headers)

    def get_authorization_request(self, auth_id, headers):
        return self._request("GET", f"/api/authorization-requests/{auth_id}",
                             headers=headers)

    def auth_payer_decision(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/api/authorization-requests/{auth_id}/payer-decision",
            payload, headers)

    def resubmit_authorization_request(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/api/authorization-requests/{auth_id}/resubmit",
            payload, headers)

    def withdraw_authorization_request(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/api/authorization-requests/{auth_id}/withdraw",
            payload, headers)

    def list_auth_denial_cases(self, auth_id, headers):
        return self._request(
            "GET", f"/api/authorization-requests/{auth_id}/denial-cases",
            headers=headers)

    # --- concurrent reviews ---
    def create_concurrent_review(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/api/authorization-requests/{auth_id}/concurrent-reviews",
            payload, headers)

    def list_concurrent_reviews(self, auth_id, headers):
        return self._request(
            "GET", f"/api/authorization-requests/{auth_id}/concurrent-reviews",
            headers=headers)

    def concurrent_review_payer_decision(self, review_id, payload, headers):
        return self._request(
            "POST", f"/api/concurrent-reviews/{review_id}/payer-decision",
            payload, headers)

    # --- peer-to-peer conferences ---
    def create_p2p_conference(self, auth_id, payload, headers):
        return self._request(
            "POST",
            f"/api/authorization-requests/{auth_id}/peer-to-peer-conferences",
            payload, headers)

    def list_p2p_conferences(self, auth_id, headers):
        return self._request(
            "GET",
            f"/api/authorization-requests/{auth_id}/peer-to-peer-conferences",
            headers=headers)

    def get_p2p_conference(self, conference_id, headers):
        return self._request(
            "GET", f"/api/peer-to-peer-conferences/{conference_id}",
            headers=headers)

    def reschedule_p2p(self, conference_id, payload, headers):
        return self._request(
            "POST", f"/api/peer-to-peer-conferences/{conference_id}/reschedule",
            payload, headers)

    def complete_p2p(self, conference_id, payload, headers):
        return self._request(
            "POST", f"/api/peer-to-peer-conferences/{conference_id}/complete",
            payload, headers)

    def cancel_p2p(self, conference_id, payload, headers):
        return self._request(
            "POST", f"/api/peer-to-peer-conferences/{conference_id}/cancel",
            payload, headers)

    # --- condition code 44 ---
    def create_cc44_request(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/api/utilization-cases/{case_id}/condition-code-44-requests",
            payload, headers)

    def list_cc44_requests(self, case_id, headers):
        return self._request(
            "GET",
            f"/api/utilization-cases/{case_id}/condition-code-44-requests",
            headers=headers)

    def cc44_concurrence(self, cc44_id, payload, headers):
        return self._request(
            "POST", f"/api/condition-code-44-requests/{cc44_id}/concurrence",
            payload, headers)

    def cc44_committee_review(self, cc44_id, payload, headers):
        return self._request(
            "POST",
            f"/api/condition-code-44-requests/{cc44_id}/committee-review",
            payload, headers)

    def cc44_rescind(self, cc44_id, payload, headers):
        return self._request(
            "POST", f"/api/condition-code-44-requests/{cc44_id}/rescind",
            payload, headers)

    # --- avoidable days ---
    def create_avoidable_day(self, case_id, payload, headers):
        return self._request(
            "POST", f"/api/utilization-cases/{case_id}/avoidable-days",
            payload, headers)

    def list_avoidable_days(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/utilization-cases/{case_id}/avoidable-days",
            headers=headers, params=params)

    def mitigate_avoidable_day(self, day_id, payload, headers):
        return self._request("POST", f"/api/avoidable-days/{day_id}/mitigate",
                             payload, headers)

    # --- escalations ---
    def list_escalation_cases(self, case_id, headers):
        return self._request(
            "GET", f"/api/utilization-cases/{case_id}/escalation-cases",
            headers=headers)

    def acknowledge_escalation(self, escalation_id, payload, headers):
        return self._request(
            "POST", f"/api/escalation-cases/{escalation_id}/acknowledge",
            payload, headers)

    def resolve_escalation(self, escalation_id, payload, headers):
        return self._request(
            "POST", f"/api/escalation-cases/{escalation_id}/resolve",
            payload, headers)

    def apply_escalation_credit(self, escalation_id, payload, headers):
        return self._request(
            "POST", f"/api/escalation-cases/{escalation_id}/apply-credit",
            payload, headers)

    # --- denials and appeals ---
    def list_denial_cases(self, case_id, headers):
        return self._request(
            "GET", f"/api/utilization-cases/{case_id}/denial-cases",
            headers=headers)

    def get_denial_case(self, denial_id, headers):
        return self._request("GET", f"/api/denial-cases/{denial_id}",
                             headers=headers)

    def file_appeal(self, denial_id, payload, headers):
        return self._request("POST", f"/api/denial-cases/{denial_id}/appeals",
                             payload, headers)

    def list_appeals(self, denial_id, headers):
        return self._request("GET", f"/api/denial-cases/{denial_id}/appeals",
                             headers=headers)

    def appeal_decision(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/decision",
                             payload, headers)

    # --- audit trail ---
    def list_audit_events(self, case_id, headers):
        return self._request(
            "GET", f"/api/utilization-cases/{case_id}/audit-events",
            headers=headers)

    # --- logical clock (test-driving capability, PRD §2.11) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
