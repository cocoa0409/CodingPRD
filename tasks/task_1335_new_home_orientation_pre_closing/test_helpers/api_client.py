"""API client: one method per endpoint defined in the PRD (routing table §4).

GET endpoints pass their filter/pagination parameters as query params via the
`params` argument; POST endpoints carry a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Community / analytics ---
    def create_community(self, payload, headers):
        return self._request("POST", "/api/communities", payload, headers)

    def get_quality_trend(self, community_id, headers, params=None):
        return self._request(
            "GET", f"/api/communities/{community_id}/quality-trend",
            headers=headers, params=params,
        )

    # --- Registries ---
    def create_homebuyer(self, payload, headers):
        return self._request("POST", "/api/homebuyers", payload, headers)

    def create_rep(self, payload, headers):
        return self._request("POST", "/api/reps", payload, headers)

    # --- Homes ---
    def create_home(self, payload, headers):
        return self._request("POST", "/api/homes", payload, headers)

    def get_home(self, home_id, headers):
        return self._request("GET", f"/api/homes/{home_id}", headers=headers)

    def list_homes(self, headers, params=None):
        return self._request("GET", "/api/homes", headers=headers, params=params)

    def mark_home_ready(self, home_id, headers):
        return self._request("POST", f"/api/homes/{home_id}/mark-ready", {}, headers)

    def reschedule_closing(self, home_id, payload, headers):
        return self._request(
            "POST", f"/api/homes/{home_id}/reschedule-closing", payload, headers
        )

    def close_home(self, home_id, payload, headers):
        return self._request("POST", f"/api/homes/{home_id}/close", payload, headers)

    # --- Orientation appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/api/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/api/appointments/{appointment_id}", headers=headers
        )

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/api/appointments", headers=headers, params=params)

    def confirm_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/confirm", {}, headers
        )

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/reschedule", payload, headers
        )

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/cancel", payload, headers
        )

    def start_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/start", {}, headers
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/complete", {}, headers
        )

    def mark_checklist_item(self, appointment_id, system_key, payload, headers):
        return self._request(
            "POST",
            f"/api/appointments/{appointment_id}/checklist-items/{system_key}/mark",
            payload,
            headers,
        )

    # --- Attendees ---
    def create_attendee(self, payload, headers):
        return self._request("POST", "/api/attendees", payload, headers)

    def get_attendee(self, attendee_id, headers):
        return self._request("GET", f"/api/attendees/{attendee_id}", headers=headers)

    def list_attendees(self, headers, params=None):
        return self._request("GET", "/api/attendees", headers=headers, params=params)

    def decide_attendee_verification(self, attendee_id, payload, headers):
        return self._request(
            "POST",
            f"/api/attendees/{attendee_id}/decide-verification",
            payload,
            headers,
        )

    # --- Deficiency items ---
    def create_deficiency_item(self, payload, headers):
        return self._request("POST", "/api/deficiency-items", payload, headers)

    def get_deficiency_item(self, item_id, headers):
        return self._request(
            "GET", f"/api/deficiency-items/{item_id}", headers=headers
        )

    def list_deficiency_items(self, headers, params=None):
        return self._request(
            "GET", "/api/deficiency-items", headers=headers, params=params
        )

    def classify_deficiency_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/api/deficiency-items/{item_id}/classify", payload, headers
        )

    def decide_deficiency_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/api/deficiency-items/{item_id}/decide", payload, headers
        )

    def start_repair(self, item_id, headers):
        return self._request(
            "POST", f"/api/deficiency-items/{item_id}/start-repair", {}, headers
        )

    def complete_repair(self, item_id, headers):
        return self._request(
            "POST", f"/api/deficiency-items/{item_id}/complete-repair", {}, headers
        )

    def withdraw_deficiency_item(self, item_id, headers):
        return self._request(
            "POST", f"/api/deficiency-items/{item_id}/withdraw", {}, headers
        )

    def sign_off_deficiency_item(self, item_id, headers):
        return self._request(
            "POST", f"/api/deficiency-items/{item_id}/sign-off", {}, headers
        )

    # --- Reinspection visits ---
    def create_reinspection_visit(self, payload, headers):
        return self._request("POST", "/api/reinspection-visits", payload, headers)

    def get_reinspection_visit(self, visit_id, headers):
        return self._request(
            "GET", f"/api/reinspection-visits/{visit_id}", headers=headers
        )

    def list_reinspection_visits(self, headers, params=None):
        return self._request(
            "GET", "/api/reinspection-visits", headers=headers, params=params
        )

    def complete_reinspection_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/api/reinspection-visits/{visit_id}/complete", payload, headers
        )

    # --- Escrow holdbacks ---
    def get_escrow_holdback(self, escrow_id, headers):
        return self._request(
            "GET", f"/api/escrow-holdbacks/{escrow_id}", headers=headers
        )

    def list_escrow_holdbacks(self, headers, params=None):
        return self._request(
            "GET", "/api/escrow-holdbacks", headers=headers, params=params
        )

    def release_escrow_holdback(self, escrow_id, payload, headers):
        return self._request(
            "POST", f"/api/escrow-holdbacks/{escrow_id}/release", payload, headers
        )

    # --- Acknowledgment signatures ---
    def get_acknowledgment_signature(self, signature_id, headers):
        return self._request(
            "GET", f"/api/acknowledgment-signatures/{signature_id}", headers=headers
        )

    def list_acknowledgment_signatures(self, headers, params=None):
        return self._request(
            "GET", "/api/acknowledgment-signatures", headers=headers, params=params
        )

    def respond_acknowledgment_signature(self, signature_id, payload, headers):
        return self._request(
            "POST",
            f"/api/acknowledgment-signatures/{signature_id}/respond",
            payload,
            headers,
        )

    def re_request_acknowledgment_signature(self, signature_id, headers):
        return self._request(
            "POST",
            f"/api/acknowledgment-signatures/{signature_id}/re-request",
            {},
            headers,
        )

    # --- Feedback surveys ---
    def get_feedback_survey(self, survey_id, headers):
        return self._request(
            "GET", f"/api/feedback-surveys/{survey_id}", headers=headers
        )

    def list_feedback_surveys(self, headers, params=None):
        return self._request(
            "GET", "/api/feedback-surveys", headers=headers, params=params
        )

    def submit_feedback_survey(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/api/feedback-surveys/{survey_id}/submit", payload, headers
        )

    def expire_due_feedback_surveys(self, headers):
        return self._request("POST", "/api/feedback-surveys/expire-due", {}, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
