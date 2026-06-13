"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    # --- Applicants ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicant_applications(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"/applicants/{applicant_id}/applications", headers=headers, params=params
        )

    # --- Enrollment Centers ---
    def create_center(self, payload, headers):
        return self._request("POST", "/enrollment-centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/enrollment-centers/{center_id}", headers=headers)

    def suspend_center(self, center_id, headers):
        return self._request(
            "POST", f"/enrollment-centers/{center_id}/suspend", {}, headers
        )

    def list_center_slots(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/enrollment-centers/{center_id}/appointment-slots",
            headers=headers, params=params,
        )

    # --- Appointment Slots ---
    def create_slot(self, payload, headers):
        return self._request("POST", "/appointment-slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/appointment-slots/{slot_id}", headers=headers)

    def release_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/appointment-slots/{slot_id}/release", {}, headers
        )

    def list_slot_appointments(self, slot_id, headers, params=None):
        return self._request(
            "GET", f"/appointment-slots/{slot_id}/appointments",
            headers=headers, params=params,
        )

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def pay_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/pay", payload, headers
        )

    def list_fee_transactions(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/fee-transactions",
            headers=headers, params=params,
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit", {}, headers
        )

    def withdraw_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", payload, headers
        )

    # --- Background Checks ---
    def create_background_check(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/background-checks", payload, headers
        )

    def list_background_checks(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/background-checks",
            headers=headers, params=params,
        )

    def adjudicate(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/adjudicate", {}, headers
        )

    def manual_clear(self, background_check_id, headers):
        return self._request(
            "POST", f"/background-checks/{background_check_id}/manual-clear", {}, headers
        )

    def manual_deny(self, background_check_id, headers):
        return self._request(
            "POST", f"/background-checks/{background_check_id}/manual-deny", {}, headers
        )

    def get_background_check(self, background_check_id, headers):
        return self._request(
            "GET", f"/background-checks/{background_check_id}", headers=headers
        )

    # --- Appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_application_appointments(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/appointments",
            headers=headers, params=params,
        )

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", {}, headers
        )

    def no_show_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/no-show", {}, headers
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/complete", {}, headers
        )

    # --- Biometric Captures ---
    def create_biometric_capture(self, payload, headers):
        return self._request("POST", "/biometric-captures", payload, headers)

    def list_appointment_biometrics(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/biometric-captures",
            headers=headers, params=params,
        )

    # --- Approval / KTN ---
    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/approve", {}, headers
        )

    def list_application_ktns(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/known-traveler-numbers",
            headers=headers, params=params,
        )

    def get_ktn(self, ktn_id, headers):
        return self._request("GET", f"/known-traveler-numbers/{ktn_id}", headers=headers)

    def list_ktn_renewals(self, ktn_id, headers, params=None):
        return self._request(
            "GET", f"/known-traveler-numbers/{ktn_id}/renewals",
            headers=headers, params=params,
        )

    def revoke_ktn(self, ktn_id, headers):
        return self._request(
            "POST", f"/known-traveler-numbers/{ktn_id}/revoke", {}, headers
        )

    def expire_sweep_ktn(self, ktn_id, headers):
        return self._request(
            "POST", f"/known-traveler-numbers/{ktn_id}/expire-sweep", {}, headers
        )

    # --- Appeals ---
    def file_appeal(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/appeals", payload, headers
        )

    def list_appeals(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/appeals",
            headers=headers, params=params,
        )

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # --- Redress Cases ---
    def create_redress_case(self, payload, headers):
        return self._request("POST", "/redress-cases", payload, headers)

    def list_redress_cases(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/redress-cases",
            headers=headers, params=params,
        )

    def get_redress_case(self, redress_id, headers):
        return self._request("GET", f"/redress-cases/{redress_id}", headers=headers)

    def resolve_redress_case(self, redress_id, headers):
        return self._request(
            "POST", f"/redress-cases/{redress_id}/resolve", {}, headers
        )

    # --- Audit ---
    def list_audit_events(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/audit-events",
            headers=headers, params=params,
        )


api_client = ApiClient()
