"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/api/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/api/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/api/students/{student_id}", headers=headers)

    def withdraw_student(self, student_id, headers):
        return self._request("POST", f"/api/students/{student_id}/withdraw", headers=headers)

    def get_student_compliance(self, student_id, headers):
        return self._request("GET", f"/api/students/{student_id}/compliance", headers=headers)

    # --- Vaccine requirements ---
    def create_vaccine_requirement(self, payload, headers):
        return self._request("POST", "/api/vaccine-requirements", payload, headers)

    def list_vaccine_requirements(self, headers, params=None):
        return self._request("GET", "/api/vaccine-requirements", headers=headers, params=params)

    # --- Immunization records ---
    def create_immunization_record(self, student_id, payload, headers):
        return self._request(
            "POST", f"/api/students/{student_id}/immunization-records", payload, headers
        )

    def list_immunization_records(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/api/students/{student_id}/immunization-records",
            headers=headers, params=params,
        )

    def verify_immunization_record(self, record_id, headers):
        return self._request(
            "POST", f"/api/immunization-records/{record_id}/verify", headers=headers
        )

    def void_immunization_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/api/immunization-records/{record_id}/void", payload, headers
        )

    # --- Exemption requests ---
    def create_exemption_request(self, student_id, payload, headers):
        return self._request(
            "POST", f"/api/students/{student_id}/exemption-requests", payload, headers
        )

    def list_exemption_requests(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/api/students/{student_id}/exemption-requests",
            headers=headers, params=params,
        )

    def start_exemption_review(self, exemption_id, headers):
        return self._request(
            "POST", f"/api/exemption-requests/{exemption_id}/start-review", headers=headers
        )

    def approve_exemption(self, exemption_id, headers):
        return self._request(
            "POST", f"/api/exemption-requests/{exemption_id}/approve", headers=headers
        )

    def deny_exemption(self, exemption_id, payload, headers):
        return self._request(
            "POST", f"/api/exemption-requests/{exemption_id}/deny", payload, headers
        )

    def resubmit_exemption(self, exemption_id, payload, headers):
        return self._request(
            "POST", f"/api/exemption-requests/{exemption_id}/resubmit", payload, headers
        )

    # --- Compliance notices ---
    def create_compliance_notice(self, student_id, payload, headers):
        return self._request(
            "POST", f"/api/students/{student_id}/compliance-notices", payload, headers
        )

    def list_compliance_notices(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/api/students/{student_id}/compliance-notices",
            headers=headers, params=params,
        )

    def rescind_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/api/compliance-notices/{notice_id}/rescind", payload, headers
        )

    # --- Outbreak events ---
    def create_outbreak_event(self, payload, headers):
        return self._request("POST", "/api/outbreak-events", payload, headers)

    def lift_outbreak_event(self, outbreak_id, headers):
        return self._request(
            "POST", f"/api/outbreak-events/{outbreak_id}/lift", headers=headers
        )

    # --- Clinic sessions ---
    def create_clinic_session(self, payload, headers):
        return self._request("POST", "/api/clinic-sessions", payload, headers)

    def get_clinic_session(self, session_id, headers):
        return self._request("GET", f"/api/clinic-sessions/{session_id}", headers=headers)

    def open_clinic_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/clinic-sessions/{session_id}/open", headers=headers
        )

    def close_clinic_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/clinic-sessions/{session_id}/close", headers=headers
        )

    def cancel_clinic_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/clinic-sessions/{session_id}/cancel", headers=headers
        )

    # --- Clinic appointments ---
    def book_appointment(self, session_id, payload, headers):
        return self._request(
            "POST", f"/api/clinic-sessions/{session_id}/appointments", payload, headers
        )

    def list_session_appointments(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/api/clinic-sessions/{session_id}/appointments",
            headers=headers, params=params,
        )

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/api/clinic-appointments/{appointment_id}", headers=headers
        )

    def list_student_appointments(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/api/students/{student_id}/clinic-appointments",
            headers=headers, params=params,
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/api/clinic-appointments/{appointment_id}/cancel", headers=headers
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/api/clinic-appointments/{appointment_id}/complete", headers=headers
        )

    def list_appointment_records(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/api/clinic-appointments/{appointment_id}/immunization-records",
            headers=headers, params=params,
        )

    # --- Registry reconciliation ---
    def create_registry_sync_run(self, payload, headers):
        return self._request("POST", "/api/registry-sync-runs", payload, headers)

    # --- Compliance snapshots ---
    def generate_compliance_snapshot(self, payload, headers):
        return self._request("POST", "/api/compliance-snapshots/generate", payload, headers)

    def finalize_compliance_snapshot(self, snapshot_id, headers):
        return self._request(
            "POST", f"/api/compliance-snapshots/{snapshot_id}/finalize", headers=headers
        )

    def district_rollup(self, payload, headers):
        return self._request(
            "POST", "/api/compliance-snapshots/district-rollup", payload, headers
        )

    # --- Ops sweep ---
    def run_compliance_sweep(self, headers):
        return self._request("POST", "/api/ops/compliance-sweep", headers=headers)

    # --- Test-driving endpoints (mounted at server root, not under /api) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def seed_registry_dose(self, payload, headers):
        return self._request("POST", "/_registry/seed-doses", payload, headers)


api_client = ApiClient()
