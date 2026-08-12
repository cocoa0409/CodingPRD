"""API client: one method per endpoint defined in the PRD (all paths under /api)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Home ---
    def create_home(self, payload, headers):
        return self._request("POST", "/api/homes", payload, headers)

    def list_homes(self, headers, params=None):
        return self._request("GET", "/api/homes", headers=headers, params=params)

    def get_home(self, home_id, headers):
        return self._request("GET", f"/api/homes/{home_id}", headers=headers)

    def license_home(self, home_id, headers):
        return self._request("POST", f"/api/homes/{home_id}/license", {}, headers)

    def suspend_home(self, home_id, headers):
        return self._request("POST", f"/api/homes/{home_id}/suspend", {}, headers)

    def reinstate_home(self, home_id, headers):
        return self._request("POST", f"/api/homes/{home_id}/reinstate", {}, headers)

    def close_home(self, home_id, headers):
        return self._request("POST", f"/api/homes/{home_id}/close", {}, headers)

    def get_staffing_compliance(self, home_id, headers, params=None):
        return self._request("GET", f"/api/homes/{home_id}/staffing-compliance",
                             headers=headers, params=params)

    # --- Bed ---
    def create_bed(self, home_id, payload, headers):
        return self._request("POST", f"/api/homes/{home_id}/beds", payload, headers)

    def list_beds(self, home_id, headers, params=None):
        return self._request("GET", f"/api/homes/{home_id}/beds",
                             headers=headers, params=params)

    def get_bed(self, bed_id, headers):
        return self._request("GET", f"/api/beds/{bed_id}", headers=headers)

    def take_bed_out_of_service(self, bed_id, headers):
        return self._request("POST", f"/api/beds/{bed_id}/take-out-of-service", {}, headers)

    def return_bed_to_service(self, bed_id, headers):
        return self._request("POST", f"/api/beds/{bed_id}/return-to-service", {}, headers)

    # --- Resident ---
    def create_resident(self, home_id, payload, headers):
        return self._request("POST", f"/api/homes/{home_id}/residents", payload, headers)

    def list_residents(self, home_id, headers, params=None):
        return self._request("GET", f"/api/homes/{home_id}/residents",
                             headers=headers, params=params)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/api/residents/{resident_id}", headers=headers)

    def withdraw_resident(self, resident_id, headers):
        return self._request("POST", f"/api/residents/{resident_id}/withdraw", {}, headers)

    def discharge_resident(self, resident_id, payload, headers):
        return self._request("POST", f"/api/residents/{resident_id}/discharge",
                             payload, headers)

    # --- Assessment ---
    def create_assessment(self, resident_id, payload, headers):
        return self._request("POST", f"/api/residents/{resident_id}/assessments",
                             payload, headers)

    def list_assessments(self, resident_id, headers, params=None):
        return self._request("GET", f"/api/residents/{resident_id}/assessments",
                             headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/assessments/{assessment_id}", headers=headers)

    def finalize_assessment(self, assessment_id, headers):
        return self._request("POST", f"/api/assessments/{assessment_id}/finalize",
                             {}, headers)

    # --- Admission ---
    def create_admission(self, payload, headers):
        return self._request("POST", "/api/admissions", payload, headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/api/admissions", headers=headers, params=params)

    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/api/admissions/{admission_id}", headers=headers)

    def approve_admission(self, admission_id, headers):
        return self._request("POST", f"/api/admissions/{admission_id}/approve", {}, headers)

    def reject_admission(self, admission_id, headers):
        return self._request("POST", f"/api/admissions/{admission_id}/reject", {}, headers)

    def cancel_admission(self, admission_id, headers):
        return self._request("POST", f"/api/admissions/{admission_id}/cancel", {}, headers)

    def complete_admission(self, admission_id, headers):
        return self._request("POST", f"/api/admissions/{admission_id}/complete", {}, headers)

    # --- Medication orders & logs ---
    def create_medication_order(self, resident_id, payload, headers):
        return self._request("POST", f"/api/residents/{resident_id}/medication-orders",
                             payload, headers)

    def list_medication_orders(self, resident_id, headers, params=None):
        return self._request("GET", f"/api/residents/{resident_id}/medication-orders",
                             headers=headers, params=params)

    def discontinue_medication_order(self, order_id, headers):
        return self._request("POST", f"/api/medication-orders/{order_id}/discontinue",
                             {}, headers)

    def create_medication_log(self, payload, headers):
        return self._request("POST", "/api/medication-logs", payload, headers)

    def list_medication_logs(self, headers, params=None):
        return self._request("GET", "/api/medication-logs", headers=headers, params=params)

    def get_medication_log(self, log_id, headers):
        return self._request("GET", f"/api/medication-logs/{log_id}", headers=headers)

    # --- ADL logs ---
    def create_adl_log(self, payload, headers):
        return self._request("POST", "/api/adl-logs", payload, headers)

    def list_adl_logs(self, headers, params=None):
        return self._request("GET", "/api/adl-logs", headers=headers, params=params)

    def get_adl_log(self, log_id, headers):
        return self._request("GET", f"/api/adl-logs/{log_id}", headers=headers)

    # --- Caregivers ---
    def create_caregiver(self, home_id, payload, headers):
        return self._request("POST", f"/api/homes/{home_id}/caregivers", payload, headers)

    def list_caregivers(self, home_id, headers, params=None):
        return self._request("GET", f"/api/homes/{home_id}/caregivers",
                             headers=headers, params=params)

    def get_caregiver(self, caregiver_id, headers):
        return self._request("GET", f"/api/caregivers/{caregiver_id}", headers=headers)

    def suspend_caregiver(self, caregiver_id, headers):
        return self._request("POST", f"/api/caregivers/{caregiver_id}/suspend", {}, headers)

    def reinstate_caregiver(self, caregiver_id, headers):
        return self._request("POST", f"/api/caregivers/{caregiver_id}/reinstate",
                             {}, headers)

    def terminate_caregiver(self, caregiver_id, headers):
        return self._request("POST", f"/api/caregivers/{caregiver_id}/terminate",
                             {}, headers)

    # --- Shifts ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/api/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/api/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/api/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/api/shifts/{shift_id}/cancel", {}, headers)

    # --- Incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/api/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/api/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/api/incidents/{incident_id}", headers=headers)

    def open_incident_case(self, incident_id, headers):
        return self._request("POST", f"/api/incidents/{incident_id}/open-case",
                             {}, headers)

    def reopen_incident(self, incident_id, headers):
        return self._request("POST", f"/api/incidents/{incident_id}/reopen", {}, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/api/incidents/{incident_id}/close", {}, headers)

    def close_minor_incident(self, incident_id, headers):
        return self._request("POST", f"/api/incidents/{incident_id}/close-minor",
                             {}, headers)

    # --- Compliance cases ---
    def list_compliance_cases(self, headers, params=None):
        return self._request("GET", "/api/compliance-cases", headers=headers, params=params)

    def get_compliance_case(self, case_id, headers):
        return self._request("GET", f"/api/compliance-cases/{case_id}", headers=headers)

    def substantiate_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/compliance-cases/{case_id}/substantiate",
                             payload, headers)

    def mark_case_unfounded(self, case_id, headers):
        return self._request("POST", f"/api/compliance-cases/{case_id}/mark-unfounded",
                             {}, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/compliance-cases/{case_id}/close",
                             payload, headers)

    # --- Billing ---
    def create_rate_schedule(self, home_id, payload, headers):
        return self._request("POST", f"/api/homes/{home_id}/rate-schedules",
                             payload, headers)

    def list_rate_schedules(self, home_id, headers, params=None):
        return self._request("GET", f"/api/homes/{home_id}/rate-schedules",
                             headers=headers, params=params)

    def generate_invoice(self, resident_id, payload, headers):
        return self._request("POST", f"/api/residents/{resident_id}/invoices/generate",
                             payload, headers)

    def list_invoices(self, resident_id, headers, params=None):
        return self._request("GET", f"/api/residents/{resident_id}/invoices",
                             headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", {}, headers)

    # --- Payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/api/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/api/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/api/payments/{payment_id}", headers=headers)

    # --- Discharge records ---
    def list_discharge_records(self, headers, params=None):
        return self._request("GET", "/api/discharge-records", headers=headers, params=params)

    def get_discharge_record(self, record_id, headers):
        return self._request("GET", f"/api/discharge-records/{record_id}", headers=headers)


api_client = ApiClient()
