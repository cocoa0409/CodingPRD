"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Guardian ----
    def create_guardian(self, payload, headers=None):
        return self._request("POST", "/guardians", payload, headers=headers)

    def get_guardian(self, guardian_id, headers):
        return self._request("GET", f"/guardians/{guardian_id}", headers=headers)

    def list_guardian_children(self, guardian_id, headers, params=None):
        return self._request("GET", f"/guardians/{guardian_id}/children", headers=headers, params=params)

    def list_guardian_invoices(self, guardian_id, headers, params=None):
        return self._request("GET", f"/guardians/{guardian_id}/invoices", headers=headers, params=params)

    # ---- Child ----
    def create_child(self, payload, headers):
        return self._request("POST", "/children", payload, headers=headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/children/{child_id}", headers=headers)

    def get_child_age_eligibility(self, child_id, headers, params=None):
        return self._request("GET", f"/children/{child_id}/age-eligibility", headers=headers, params=params)

    def list_child_emergency_contacts(self, child_id, headers, params=None):
        return self._request("GET", f"/children/{child_id}/emergency-contacts", headers=headers, params=params)

    def list_child_authorization_forms(self, child_id, headers, params=None):
        return self._request("GET", f"/children/{child_id}/authorization-forms", headers=headers, params=params)

    def list_child_scholarship_awards(self, child_id, headers, params=None):
        return self._request("GET", f"/children/{child_id}/scholarship-awards", headers=headers, params=params)

    # ---- EmergencyContact ----
    def create_emergency_contact(self, payload, headers):
        return self._request("POST", "/emergency-contacts", payload, headers=headers)

    # ---- AuthorizationForm ----
    def create_authorization_form(self, payload, headers):
        return self._request("POST", "/authorization-forms", payload, headers=headers)

    def approve_authorization_form(self, form_id, headers):
        return self._request("POST", f"/authorization-forms/{form_id}/approve", {}, headers=headers)

    def revoke_authorization_form(self, form_id, headers):
        return self._request("POST", f"/authorization-forms/{form_id}/revoke", {}, headers=headers)

    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers=headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_program_sessions(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/sessions", headers=headers, params=params)

    def publish_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/publish", {}, headers=headers)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/archive", {}, headers=headers)

    # ---- Session ----
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers=headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_session_weekly_offerings(self, session_id, headers, params=None):
        return self._request("GET", f"/sessions/{session_id}/weekly-offerings", headers=headers, params=params)

    def open_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/open", {}, headers=headers)

    def close_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/close", {}, headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers=headers)

    # ---- WeeklyOffering ----
    def create_weekly_offering(self, payload, headers):
        return self._request("POST", "/weekly-offerings", payload, headers=headers)

    def get_weekly_offering(self, offering_id, headers):
        return self._request("GET", f"/weekly-offerings/{offering_id}", headers=headers)

    def list_rain_dependents(self, offering_id, headers, params=None):
        return self._request("GET", f"/weekly-offerings/{offering_id}/rain-dependents", headers=headers, params=params)

    def list_offering_enrollments(self, offering_id, headers, params=None):
        return self._request("GET", f"/weekly-offerings/{offering_id}/enrollments", headers=headers, params=params)

    def list_offering_weather_events(self, offering_id, headers, params=None):
        return self._request("GET", f"/weekly-offerings/{offering_id}/weather-events", headers=headers, params=params)

    def configure_rain_alternate(self, offering_id, payload, headers):
        return self._request("PATCH", f"/weekly-offerings/{offering_id}", payload, headers=headers)

    def clear_rain(self, offering_id, headers):
        return self._request("POST", f"/weekly-offerings/{offering_id}/clear-rain", {}, headers=headers)

    # ---- WeatherEvent ----
    def create_weather_event(self, payload, headers):
        return self._request("POST", "/weather-events", payload, headers=headers)

    # ---- ScholarshipAward ----
    def create_scholarship_award(self, payload, headers):
        return self._request("POST", "/scholarship-awards", payload, headers=headers)

    def approve_scholarship_award(self, award_id, headers):
        return self._request("POST", f"/scholarship-awards/{award_id}/approve", {}, headers=headers)

    def deny_scholarship_award(self, award_id, headers):
        return self._request("POST", f"/scholarship-awards/{award_id}/deny", {}, headers=headers)

    def revoke_scholarship_award(self, award_id, headers):
        return self._request("POST", f"/scholarship-awards/{award_id}/revoke", {}, headers=headers)

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers=headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers=headers)

    # ---- Invoice ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments", headers=headers, params=params)

    def finalize_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", payload, headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers=headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers=headers)

    # ---- Audit ----
    def list_audit_entries(self, headers, params=None):
        return self._request("GET", "/audit-entries", headers=headers, params=params)


api_client = ApiClient()
