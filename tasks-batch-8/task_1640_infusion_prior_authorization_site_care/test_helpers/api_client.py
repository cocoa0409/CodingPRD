"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PolicyAdmin only)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/infusion/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Payer policies
    # ------------------------------------------------------------------
    def create_payer_policy(self, payload, headers):
        return self._request("POST", "/infusion/payer-policies", payload, headers)

    def get_payer_policy(self, policy_id, headers):
        return self._request("GET", f"/infusion/payer-policies/{policy_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/infusion/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/infusion/patients/{patient_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Authorization requirement lookup
    # ------------------------------------------------------------------
    def lookup_authorization_requirements(self, headers, params=None):
        return self._request("GET", "/infusion/authorization-requirements/lookup",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Authorization requests
    # ------------------------------------------------------------------
    def create_authorization_request(self, payload, headers):
        return self._request("POST", "/infusion/authorization-requests",
                             payload, headers)

    def list_authorization_requests(self, headers, params=None):
        return self._request("GET", "/infusion/authorization-requests",
                             headers=headers, params=params)

    def get_authorization_request(self, auth_id, headers):
        return self._request("GET", f"/infusion/authorization-requests/{auth_id}",
                             headers=headers)

    def submit_authorization_request(self, auth_id, headers):
        return self._request("POST",
                             f"/infusion/authorization-requests/{auth_id}/submit",
                             {}, headers)

    def record_determination(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/infusion/authorization-requests/{auth_id}/determinations",
            payload, headers)

    # ------------------------------------------------------------------
    # Site-of-care determinations
    # ------------------------------------------------------------------
    def create_site_of_care_determination(self, auth_id, payload, headers):
        return self._request(
            "POST",
            f"/infusion/authorization-requests/{auth_id}/site-of-care-determinations",
            payload, headers)

    def list_site_of_care_determinations(self, auth_id, headers):
        return self._request(
            "GET",
            f"/infusion/authorization-requests/{auth_id}/site-of-care-determinations",
            headers=headers)

    # ------------------------------------------------------------------
    # Benefit investigations
    # ------------------------------------------------------------------
    def create_benefit_investigation(self, auth_id, headers):
        return self._request(
            "POST",
            f"/infusion/authorization-requests/{auth_id}/benefit-investigations",
            {}, headers)

    def list_benefit_investigations(self, auth_id, headers):
        return self._request(
            "GET",
            f"/infusion/authorization-requests/{auth_id}/benefit-investigations",
            headers=headers)

    def verify_benefit_investigation(self, bi_id, payload, headers):
        return self._request("POST",
                             f"/infusion/benefit-investigations/{bi_id}/verify",
                             payload, headers)

    # ------------------------------------------------------------------
    # Clinical criteria submissions
    # ------------------------------------------------------------------
    def create_criteria_submission(self, auth_id, payload, headers):
        return self._request(
            "POST",
            f"/infusion/authorization-requests/{auth_id}/criteria-submissions",
            payload, headers)

    def list_criteria_submissions(self, auth_id, headers):
        return self._request(
            "GET",
            f"/infusion/authorization-requests/{auth_id}/criteria-submissions",
            headers=headers)

    def review_criteria_submission(self, cs_id, payload, headers):
        return self._request("POST",
                             f"/infusion/criteria-submissions/{cs_id}/reviews",
                             payload, headers)

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------
    def create_appeal(self, auth_id, payload, headers):
        return self._request("POST",
                             f"/infusion/authorization-requests/{auth_id}/appeals",
                             payload, headers)

    def list_appeals(self, auth_id, headers):
        return self._request("GET",
                             f"/infusion/authorization-requests/{auth_id}/appeals",
                             headers=headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/infusion/appeals/{appeal_id}",
                             headers=headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/infusion/appeals/{appeal_id}/decisions",
                             payload, headers)

    def escalate_appeal(self, appeal_id, headers):
        return self._request("POST", f"/infusion/appeals/{appeal_id}/escalations",
                             {}, headers)

    # ------------------------------------------------------------------
    # Peer-to-peer reviews
    # ------------------------------------------------------------------
    def create_peer_to_peer_review(self, appeal_id, payload, headers):
        return self._request("POST",
                             f"/infusion/appeals/{appeal_id}/peer-to-peer-reviews",
                             payload, headers)

    def list_peer_to_peer_reviews(self, appeal_id, headers):
        return self._request("GET",
                             f"/infusion/appeals/{appeal_id}/peer-to-peer-reviews",
                             headers=headers)

    def reschedule_peer_to_peer_review(self, p2p_id, payload, headers):
        return self._request("POST",
                             f"/infusion/peer-to-peer-reviews/{p2p_id}/reschedules",
                             payload, headers)

    def complete_peer_to_peer_review(self, p2p_id, payload, headers):
        return self._request("POST",
                             f"/infusion/peer-to-peer-reviews/{p2p_id}/completions",
                             payload, headers)

    # ------------------------------------------------------------------
    # Financial clearances and responsibility line items
    # ------------------------------------------------------------------
    def create_financial_clearance(self, auth_id, headers):
        return self._request(
            "POST",
            f"/infusion/authorization-requests/{auth_id}/financial-clearances",
            {}, headers)

    def list_financial_clearances(self, auth_id, headers):
        return self._request(
            "GET",
            f"/infusion/authorization-requests/{auth_id}/financial-clearances",
            headers=headers)

    def get_financial_clearance(self, fc_id, headers):
        return self._request("GET", f"/infusion/financial-clearances/{fc_id}",
                             headers=headers)

    def create_line_item(self, fc_id, payload, headers):
        return self._request("POST",
                             f"/infusion/financial-clearances/{fc_id}/line-items",
                             payload, headers)

    def list_line_items(self, fc_id, headers):
        return self._request("GET",
                             f"/infusion/financial-clearances/{fc_id}/line-items",
                             headers=headers)

    def void_line_item(self, li_id, headers):
        return self._request("POST",
                             f"/infusion/responsibility-line-items/{li_id}/voids",
                             {}, headers)

    def clear_financial_clearance(self, fc_id, headers):
        return self._request("POST",
                             f"/infusion/financial-clearances/{fc_id}/clear",
                             {}, headers)

    def recompute_financial_clearance(self, fc_id, headers):
        return self._request("POST",
                             f"/infusion/financial-clearances/{fc_id}/recompute",
                             {}, headers)

    # ------------------------------------------------------------------
    # Infusion chairs
    # ------------------------------------------------------------------
    def create_infusion_chair(self, payload, headers):
        return self._request("POST", "/infusion/infusion-chairs", payload, headers)

    def get_infusion_chair(self, chair_id, headers):
        return self._request("GET", f"/infusion/infusion-chairs/{chair_id}",
                             headers=headers)

    def list_chair_appointments(self, chair_id, headers):
        return self._request("GET",
                             f"/infusion/infusion-chairs/{chair_id}/appointments",
                             headers=headers)

    # ------------------------------------------------------------------
    # Infusion appointments
    # ------------------------------------------------------------------
    def create_appointment(self, auth_id, payload, headers):
        return self._request("POST",
                             f"/infusion/authorization-requests/{auth_id}/appointments",
                             payload, headers)

    def list_appointments(self, auth_id, headers):
        return self._request(
            "GET", f"/infusion/authorization-requests/{auth_id}/appointments",
            headers=headers)

    def confirm_appointment(self, appt_id, headers):
        return self._request("POST", f"/infusion/appointments/{appt_id}/confirm",
                             {}, headers)

    def cancel_appointment(self, appt_id, headers):
        return self._request("POST", f"/infusion/appointments/{appt_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Dose-change requests
    # ------------------------------------------------------------------
    def create_dose_change_request(self, auth_id, payload, headers):
        return self._request(
            "POST",
            f"/infusion/authorization-requests/{auth_id}/dose-change-requests",
            payload, headers)

    def list_dose_change_requests(self, auth_id, headers):
        return self._request(
            "GET",
            f"/infusion/authorization-requests/{auth_id}/dose-change-requests",
            headers=headers)

    def decide_dose_change_request(self, dcr_id, payload, headers):
        return self._request("POST",
                             f"/infusion/dose-change-requests/{dcr_id}/decisions",
                             payload, headers)


api_client = ApiClient()
