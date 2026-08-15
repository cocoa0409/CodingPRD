"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Hospitalists ----------------
    def create_hospitalist(self, payload, headers):
        return self._request("POST", "/hospitalists", payload, headers)

    def list_hospitalists(self, headers, params=None):
        return self._request("GET", "/hospitalists", headers=headers, params=params)

    def get_hospitalist(self, hospitalist_id, headers):
        return self._request("GET", f"/hospitalists/{hospitalist_id}", headers=headers)

    # ---------------- Patients ----------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---------------- Shifts ----------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def activate_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/activate", headers=headers)

    def close_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/close", headers=headers)

    # ---------------- Admissions ----------------
    def create_admission(self, payload, headers):
        return self._request("POST", "/admissions", payload, headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/admissions", headers=headers, params=params)

    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/admissions/{admission_id}", headers=headers)

    def accept_admission(self, admission_id, headers):
        return self._request("POST", f"/admissions/{admission_id}/accept", headers=headers)

    def decline_admission(self, admission_id, headers):
        return self._request("POST", f"/admissions/{admission_id}/decline", headers=headers)

    # ---------------- Assignments ----------------
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def transfer_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/transfer", payload, headers)

    def accept_transfer(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept-transfer", headers=headers)

    def cancel_transfer(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/cancel-transfer", headers=headers)

    # ---------------- Discharge Orders ----------------
    def create_discharge_order(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/discharge-orders", payload, headers)

    def list_discharge_orders(self, headers, params=None):
        return self._request("GET", "/discharge-orders", headers=headers, params=params)

    def get_discharge_order(self, order_id, headers):
        return self._request("GET", f"/discharge-orders/{order_id}", headers=headers)

    def order_discharge_order(self, order_id, headers):
        return self._request("POST", f"/discharge-orders/{order_id}/order", headers=headers)

    def execute_discharge_order(self, order_id, headers):
        return self._request("POST", f"/discharge-orders/{order_id}/execute", headers=headers)

    # ---------------- Handoffs ----------------
    def create_handoff(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/handoffs", payload, headers)

    def list_handoffs(self, headers, params=None):
        return self._request("GET", "/handoffs", headers=headers, params=params)

    def get_handoff(self, handoff_id, headers):
        return self._request("GET", f"/handoffs/{handoff_id}", headers=headers)

    def revise_handoff(self, handoff_id, payload, headers):
        return self._request("PUT", f"/handoffs/{handoff_id}", payload, headers)

    def submit_handoff(self, handoff_id, headers):
        return self._request("POST", f"/handoffs/{handoff_id}/submit", headers=headers)

    def accept_handoff(self, handoff_id, headers):
        return self._request("POST", f"/handoffs/{handoff_id}/accept", headers=headers)

    def return_handoff(self, handoff_id, payload, headers):
        return self._request("POST", f"/handoffs/{handoff_id}/return", payload, headers)

    # ---------------- Consult Requests ----------------
    def create_consult_request(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/consult-requests", payload, headers)

    def list_consult_requests(self, headers, params=None):
        return self._request("GET", "/consult-requests", headers=headers, params=params)

    def get_consult_request(self, consult_id, headers):
        return self._request("GET", f"/consult-requests/{consult_id}", headers=headers)

    def acknowledge_consult(self, consult_id, headers):
        return self._request("POST", f"/consult-requests/{consult_id}/acknowledge", headers=headers)

    def complete_consult(self, consult_id, headers, payload=None):
        return self._request("POST", f"/consult-requests/{consult_id}/complete", payload or {}, headers)

    def reopen_consult(self, consult_id, headers, payload=None):
        return self._request("POST", f"/consult-requests/{consult_id}/reopen", payload or {}, headers)

    # ---------------- Encounters ----------------
    def create_encounter(self, payload, headers):
        return self._request("POST", "/encounters", payload, headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)

    def void_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/void", headers=headers)

    # ---------------- Productivity Reports ----------------
    def generate_productivity_report(self, payload, headers):
        return self._request("POST", "/productivity-reports/generate", payload, headers)

    def list_productivity_reports(self, headers, params=None):
        return self._request("GET", "/productivity-reports", headers=headers, params=params)

    def get_productivity_report(self, report_id, headers):
        return self._request("GET", f"/productivity-reports/{report_id}", headers=headers)

    def finalize_productivity_report(self, report_id, headers):
        return self._request("POST", f"/productivity-reports/{report_id}/finalize", headers=headers)

    def reopen_productivity_report(self, report_id, headers):
        return self._request("POST", f"/productivity-reports/{report_id}/reopen", headers=headers)

    # ---------------- Coverage Windows ----------------
    def create_coverage_window(self, payload, headers):
        return self._request("POST", "/coverage-windows", payload, headers)

    def list_coverage_windows(self, headers, params=None):
        return self._request("GET", "/coverage-windows", headers=headers, params=params)

    def get_coverage_window(self, window_id, headers):
        return self._request("GET", f"/coverage-windows/{window_id}", headers=headers)

    def enroll_coverage_window(self, window_id, headers):
        return self._request("POST", f"/coverage-windows/{window_id}/enroll", headers=headers)

    def withdraw_coverage_window(self, window_id, headers):
        return self._request("POST", f"/coverage-windows/{window_id}/withdraw", headers=headers)

    # ---------------- Ops / Reports / Clock ----------------
    def monitor_run(self, headers):
        return self._request("POST", "/ops/monitor-run", headers=headers)

    def get_census_leveling_report(self, headers):
        return self._request("GET", "/reports/census-leveling", headers=headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
