"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/api/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/activate", {}, headers)

    def begin_closing_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/begin-closing", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/close", {}, headers)

    def get_completion_report(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}/completion-report", headers=headers)

    # --- Contractor ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/api/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/api/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/api/contractors/{contractor_id}", headers=headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/api/contractors/{contractor_id}/suspend", {}, headers)

    def reinstate_contractor(self, contractor_id, headers):
        return self._request("POST", f"/api/contractors/{contractor_id}/reinstate", {}, headers)

    # --- ServiceAccount ---
    def create_account(self, payload, headers):
        return self._request("POST", "/api/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    # --- Meter ---
    def create_meter(self, payload, headers):
        return self._request("POST", "/api/meters", payload, headers)

    def list_meters(self, headers, params=None):
        return self._request("GET", "/api/meters", headers=headers, params=params)

    def get_meter(self, meter_id, headers):
        return self._request("GET", f"/api/meters/{meter_id}", headers=headers)

    def install_meter(self, meter_id, payload, headers):
        return self._request("POST", f"/api/meters/{meter_id}/install", payload, headers)

    def dispose_meter(self, meter_id, headers):
        return self._request("POST", f"/api/meters/{meter_id}/dispose", {}, headers)

    # --- Wave ---
    def create_wave(self, payload, headers):
        return self._request("POST", "/api/waves", payload, headers)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/api/waves", headers=headers, params=params)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/api/waves/{wave_id}", headers=headers)

    def open_wave(self, wave_id, headers):
        return self._request("POST", f"/api/waves/{wave_id}/open", {}, headers)

    def lock_wave(self, wave_id, headers):
        return self._request("POST", f"/api/waves/{wave_id}/lock", {}, headers)

    def complete_wave(self, wave_id, headers):
        return self._request("POST", f"/api/waves/{wave_id}/complete", {}, headers)

    def cancel_wave(self, wave_id, headers):
        return self._request("POST", f"/api/waves/{wave_id}/cancel", {}, headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/api/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/api/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/api/work-orders/{work_order_id}", headers=headers)

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/assign", payload, headers)

    def swap_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/swap", payload, headers)

    def reconcile_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/reconcile", payload, headers)

    def submit_rework(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/submit-rework", payload, headers)

    def close_work_order(self, work_order_id, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/close", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/cancel", {}, headers)

    # --- CustomerNotification ---
    def create_notification(self, payload, headers):
        return self._request("POST", "/api/notifications", payload, headers)

    def confirm_delivery(self, notification_id, payload, headers):
        return self._request("POST", f"/api/notifications/{notification_id}/confirm-delivery", payload, headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/api/notifications", headers=headers, params=params)

    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/api/notifications/{notification_id}", headers=headers)

    # --- Appointment ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/api/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/api/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/api/appointments/{appointment_id}", headers=headers)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/confirm", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/complete", {}, headers)

    def no_access_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/no-access", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/cancel", {}, headers)

    # --- NoAccessCase ---
    def list_no_access_cases(self, headers, params=None):
        return self._request("GET", "/api/no-access-cases", headers=headers, params=params)

    def get_no_access_case(self, case_id, headers):
        return self._request("GET", f"/api/no-access-cases/{case_id}", headers=headers)

    def advance_no_access_case(self, case_id, headers):
        return self._request("POST", f"/api/no-access-cases/{case_id}/advance", {}, headers)

    def resolve_no_access_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/no-access-cases/{case_id}/resolve", payload, headers)

    # --- MeterReading ---
    def create_reading(self, payload, headers):
        return self._request("POST", "/api/readings", payload, headers)

    def list_readings(self, headers, params=None):
        return self._request("GET", "/api/readings", headers=headers, params=params)

    def get_reading(self, reading_id, headers):
        return self._request("GET", f"/api/readings/{reading_id}", headers=headers)

    # --- EndpointRegistration ---
    def create_endpoint_registration(self, payload, headers):
        return self._request("POST", "/api/endpoint-registrations", payload, headers)

    def list_endpoint_registrations(self, headers, params=None):
        return self._request("GET", "/api/endpoint-registrations", headers=headers, params=params)

    def get_endpoint_registration(self, registration_id, headers):
        return self._request("GET", f"/api/endpoint-registrations/{registration_id}", headers=headers)

    def verify_endpoint_registration(self, registration_id, headers):
        return self._request("POST", f"/api/endpoint-registrations/{registration_id}/verify", {}, headers)

    def replace_endpoint_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/api/endpoint-registrations/{registration_id}/replace", payload, headers)

    def ingest_ami_read(self, payload, headers):
        return self._request("POST", "/api/_ami/ingest-read", payload, headers)

    # --- BenchTest ---
    def create_bench_test(self, payload, headers):
        return self._request("POST", "/api/bench-tests", payload, headers)

    def list_bench_tests(self, headers, params=None):
        return self._request("GET", "/api/bench-tests", headers=headers, params=params)

    def get_bench_test(self, bench_test_id, headers):
        return self._request("GET", f"/api/bench-tests/{bench_test_id}", headers=headers)

    # --- HighBillComplaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/api/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/api/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/api/complaints/{complaint_id}", headers=headers)

    def triage_complaint(self, complaint_id, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/triage", {}, headers)

    def order_bench_test(self, complaint_id, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/order-bench-test", {}, headers)

    def adjudicate_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/adjudicate", payload, headers)

    def withdraw_complaint(self, complaint_id, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/withdraw", {}, headers)

    # --- QualityAudit ---
    def create_quality_audit(self, payload, headers):
        return self._request("POST", "/api/quality-audits", payload, headers)

    def list_quality_audits(self, headers, params=None):
        return self._request("GET", "/api/quality-audits", headers=headers, params=params)

    def get_quality_audit(self, audit_id, headers):
        return self._request("GET", f"/api/quality-audits/{audit_id}", headers=headers)

    def record_quality_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/api/quality-audits/{audit_id}/record", payload, headers)

    # --- ContractorInvoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/api/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def submit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/submit", {}, headers)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/approve", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/dispute", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
