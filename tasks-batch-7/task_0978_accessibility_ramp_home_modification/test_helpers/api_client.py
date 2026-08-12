"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- System / test-driving ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Case ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/cancel", {}, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/close", {}, headers)

    # --- Assessment ---
    def create_assessment(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/assessments", payload, headers)

    def list_assessments(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/assessments", headers=headers, params=params)

    def get_assessment(self, case_id, assessment_id, headers):
        return self._request("GET", f"/cases/{case_id}/assessments/{assessment_id}", headers=headers)

    def start_assessment(self, case_id, assessment_id, headers):
        return self._request("POST", f"/cases/{case_id}/assessments/{assessment_id}/start", {}, headers)

    def complete_assessment(self, case_id, assessment_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/assessments/{assessment_id}/complete", payload, headers)

    def cancel_assessment(self, case_id, assessment_id, headers):
        return self._request("POST", f"/cases/{case_id}/assessments/{assessment_id}/cancel", {}, headers)

    # --- Quote ---
    def create_quote(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/quotes", payload, headers)

    def list_quotes(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/quotes", headers=headers, params=params)

    def get_quote(self, case_id, quote_id, headers):
        return self._request("GET", f"/cases/{case_id}/quotes/{quote_id}", headers=headers)

    def add_quote_line_item(self, case_id, quote_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/quotes/{quote_id}/line-items", payload, headers)

    def submit_quote(self, case_id, quote_id, headers):
        return self._request("POST", f"/cases/{case_id}/quotes/{quote_id}/submit", {}, headers)

    def start_quote_review(self, case_id, quote_id, headers):
        return self._request("POST", f"/cases/{case_id}/quotes/{quote_id}/start-review", {}, headers)

    def approve_quote(self, case_id, quote_id, headers):
        return self._request("POST", f"/cases/{case_id}/quotes/{quote_id}/approve", {}, headers)

    def reject_quote(self, case_id, quote_id, headers):
        return self._request("POST", f"/cases/{case_id}/quotes/{quote_id}/reject", {}, headers)

    # --- FundingSource ---
    def create_funding_source(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/funding-sources", payload, headers)

    def list_funding_sources(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/funding-sources", headers=headers, params=params)

    def get_funding_source(self, case_id, source_id, headers):
        return self._request("GET", f"/cases/{case_id}/funding-sources/{source_id}", headers=headers)

    def approve_funding_source(self, case_id, source_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/funding-sources/{source_id}/approve", payload, headers)

    def deny_funding_source(self, case_id, source_id, headers):
        return self._request("POST", f"/cases/{case_id}/funding-sources/{source_id}/deny", {}, headers)

    def withdraw_funding_source(self, case_id, source_id, headers):
        return self._request("POST", f"/cases/{case_id}/funding-sources/{source_id}/withdraw", {}, headers)

    def create_funding_allocation(self, case_id, source_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/funding-sources/{source_id}/allocations", payload, headers)

    def list_funding_allocations(self, case_id, source_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/funding-sources/{source_id}/allocations", headers=headers, params=params)

    def reverse_funding_allocation(self, case_id, source_id, alloc_id, headers):
        return self._request("POST", f"/cases/{case_id}/funding-sources/{source_id}/allocations/{alloc_id}/reverse", {}, headers)

    # --- InstallationJob ---
    def create_installation_job(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/installation-jobs", payload, headers)

    def list_installation_jobs(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/installation-jobs", headers=headers, params=params)

    def get_installation_job(self, case_id, job_id, headers):
        return self._request("GET", f"/cases/{case_id}/installation-jobs/{job_id}", headers=headers)

    def order_materials(self, case_id, job_id, headers):
        return self._request("POST", f"/cases/{case_id}/installation-jobs/{job_id}/order-materials", {}, headers)

    def start_installation(self, case_id, job_id, headers):
        return self._request("POST", f"/cases/{case_id}/installation-jobs/{job_id}/start", {}, headers)

    def enter_punch_list(self, case_id, job_id, headers):
        return self._request("POST", f"/cases/{case_id}/installation-jobs/{job_id}/punch-list", {}, headers)

    def complete_installation(self, case_id, job_id, headers):
        return self._request("POST", f"/cases/{case_id}/installation-jobs/{job_id}/complete", {}, headers)

    def cancel_installation_job(self, case_id, job_id, headers):
        return self._request("POST", f"/cases/{case_id}/installation-jobs/{job_id}/cancel", {}, headers)

    # --- RentalRamp ---
    def create_rental_ramp(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/rental-ramps", payload, headers)

    def list_rental_ramps(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/rental-ramps", headers=headers, params=params)

    def get_rental_ramp(self, case_id, ramp_id, headers):
        return self._request("GET", f"/cases/{case_id}/rental-ramps/{ramp_id}", headers=headers)

    def deliver_rental_ramp(self, case_id, ramp_id, headers):
        return self._request("POST", f"/cases/{case_id}/rental-ramps/{ramp_id}/deliver", {}, headers)

    def install_rental_ramp(self, case_id, ramp_id, headers):
        return self._request("POST", f"/cases/{case_id}/rental-ramps/{ramp_id}/install", {}, headers)

    def schedule_pickup(self, case_id, ramp_id, headers):
        return self._request("POST", f"/cases/{case_id}/rental-ramps/{ramp_id}/schedule-pickup", {}, headers)

    def confirm_pickup(self, case_id, ramp_id, headers):
        return self._request("POST", f"/cases/{case_id}/rental-ramps/{ramp_id}/confirm-pickup", {}, headers)

    def cancel_rental_ramp(self, case_id, ramp_id, headers):
        return self._request("POST", f"/cases/{case_id}/rental-ramps/{ramp_id}/cancel", {}, headers)

    # --- InventoryUnit ---
    def create_inventory_unit(self, payload, headers):
        return self._request("POST", "/inventory-units", payload, headers)

    def list_inventory_units(self, headers, params=None):
        return self._request("GET", "/inventory-units", headers=headers, params=params)

    def get_inventory_unit(self, unit_id, headers):
        return self._request("GET", f"/inventory-units/{unit_id}", headers=headers)

    def send_unit_to_maintenance(self, unit_id, headers):
        return self._request("POST", f"/inventory-units/{unit_id}/maintenance", {}, headers)

    def return_unit_to_service(self, unit_id, headers):
        return self._request("POST", f"/inventory-units/{unit_id}/return-to-service", {}, headers)

    def retire_unit(self, unit_id, headers):
        return self._request("POST", f"/inventory-units/{unit_id}/retire", {}, headers)

    # --- Inspection ---
    def create_inspection(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/inspections", payload, headers)

    def list_inspections(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/inspections", headers=headers, params=params)

    def get_inspection(self, case_id, inspection_id, headers):
        return self._request("GET", f"/cases/{case_id}/inspections/{inspection_id}", headers=headers)

    def pass_inspection(self, case_id, inspection_id, headers):
        return self._request("POST", f"/cases/{case_id}/inspections/{inspection_id}/pass", {}, headers)

    def fail_inspection(self, case_id, inspection_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/inspections/{inspection_id}/fail", payload, headers)

    # --- Invoice ---
    def create_invoice(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/invoices", payload, headers)

    def list_invoices(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/invoices", headers=headers, params=params)

    def get_invoice(self, case_id, invoice_id, headers):
        return self._request("GET", f"/cases/{case_id}/invoices/{invoice_id}", headers=headers)

    def add_invoice_line_item(self, case_id, invoice_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/invoices/{invoice_id}/line-items", payload, headers)

    def send_invoice(self, case_id, invoice_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/invoices/{invoice_id}/send", payload, headers)

    def record_payment(self, case_id, invoice_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/invoices/{invoice_id}/record-payment", payload, headers)

    def void_invoice(self, case_id, invoice_id, headers):
        return self._request("POST", f"/cases/{case_id}/invoices/{invoice_id}/void", {}, headers)

    def dispute_invoice(self, case_id, invoice_id, headers):
        return self._request("POST", f"/cases/{case_id}/invoices/{invoice_id}/dispute", {}, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/warranty-claims", payload, headers)

    def list_warranty_claims(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, case_id, claim_id, headers):
        return self._request("GET", f"/cases/{case_id}/warranty-claims/{claim_id}", headers=headers)

    def assign_warranty_claim(self, case_id, claim_id, headers):
        return self._request("POST", f"/cases/{case_id}/warranty-claims/{claim_id}/assign", {}, headers)

    def start_warranty_work(self, case_id, claim_id, headers):
        return self._request("POST", f"/cases/{case_id}/warranty-claims/{claim_id}/start", {}, headers)

    def resolve_warranty_claim(self, case_id, claim_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/warranty-claims/{claim_id}/resolve", payload, headers)

    def deny_warranty_claim(self, case_id, claim_id, headers):
        return self._request("POST", f"/cases/{case_id}/warranty-claims/{claim_id}/deny", {}, headers)

    # --- OTConsultation ---
    def create_ot_consultation(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/ot-consultations", payload, headers)

    def list_ot_consultations(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/ot-consultations", headers=headers, params=params)

    def get_ot_consultation(self, case_id, consult_id, headers):
        return self._request("GET", f"/cases/{case_id}/ot-consultations/{consult_id}", headers=headers)

    def complete_ot_consultation(self, case_id, consult_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/ot-consultations/{consult_id}/complete", payload, headers)

    def cancel_ot_consultation(self, case_id, consult_id, headers):
        return self._request("POST", f"/cases/{case_id}/ot-consultations/{consult_id}/cancel", {}, headers)

    # --- ReassessmentSchedule ---
    def create_reassessment_schedule(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/reassessment-schedules", payload, headers)

    def list_reassessment_schedules(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/reassessment-schedules", headers=headers, params=params)

    def get_reassessment_schedule(self, case_id, schedule_id, headers):
        return self._request("GET", f"/cases/{case_id}/reassessment-schedules/{schedule_id}", headers=headers)

    def schedule_reassessment(self, case_id, schedule_id, headers):
        return self._request("POST", f"/cases/{case_id}/reassessment-schedules/{schedule_id}/schedule", {}, headers)

    def waive_reassessment(self, case_id, schedule_id, headers):
        return self._request("POST", f"/cases/{case_id}/reassessment-schedules/{schedule_id}/waive", {}, headers)


api_client = ApiClient()
