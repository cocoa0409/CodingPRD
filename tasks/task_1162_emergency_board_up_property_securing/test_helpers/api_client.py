"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Markets ---
    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    # --- Subcontractors ---
    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/subcontractors", payload, headers)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request("GET", f"/subcontractors/{subcontractor_id}", headers=headers)

    def patch_subcontractor(self, subcontractor_id, payload, headers):
        return self._request("PATCH", f"/subcontractors/{subcontractor_id}", payload, headers)

    # --- Coverage ---
    def create_coverage(self, payload, headers):
        return self._request("POST", "/coverages", payload, headers)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"/coverages/{coverage_id}", headers=headers)

    def list_coverages(self, headers, params=None):
        return self._request("GET", "/coverages", headers=headers, params=params)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # --- Jobs ---
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def dispatch_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/dispatch", payload, headers)

    def check_in_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/check-in", {}, headers)

    def complete_securing(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/complete-securing", {}, headers)

    def verify_repair(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/verify-repair", payload, headers)

    def record_removal(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/record-removal", {}, headers)

    def close_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/close", {}, headers)

    # --- Assignments ---
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def respond_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/respond", payload, headers)

    def withdraw_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/withdraw", {}, headers)

    # --- Safety assessments ---
    def create_safety_assessment(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/safety-assessments", payload, headers)

    def get_safety_assessment(self, assessment_id, headers):
        return self._request("GET", f"/safety-assessments/{assessment_id}", headers=headers)

    def list_safety_assessments(self, headers, params=None):
        return self._request("GET", "/safety-assessments", headers=headers, params=params)

    def mitigate_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/safety-assessments/{assessment_id}/mitigate", payload, headers)

    # --- Scope items ---
    def create_scope_item(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/scope-items", payload, headers)

    def list_scope_items(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/scope-items", headers=headers, params=params)

    def install_scope_item(self, scope_item_id, payload, headers):
        return self._request("POST", f"/scope-items/{scope_item_id}/install", payload, headers)

    def void_scope_item(self, scope_item_id, headers):
        return self._request("POST", f"/scope-items/{scope_item_id}/void", {}, headers)

    # --- Temporary services ---
    def create_temporary_service(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/temporary-services", payload, headers)

    def list_temporary_services(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/temporary-services", headers=headers, params=params)

    def get_temporary_service(self, service_id, headers):
        return self._request("GET", f"/temporary-services/{service_id}", headers=headers)

    def deactivate_service(self, service_id, headers):
        return self._request("POST", f"/temporary-services/{service_id}/deactivate", {}, headers)

    # --- Patrol visits ---
    def create_patrol_visit(self, service_id, payload, headers):
        return self._request("POST", f"/temporary-services/{service_id}/patrol-visits", payload, headers)

    def list_patrol_visits(self, service_id, headers, params=None):
        return self._request("GET", f"/temporary-services/{service_id}/patrol-visits", headers=headers, params=params)

    def check_in_patrol_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/patrol-visits/{visit_id}/check-in", payload, headers)

    # --- Permit cases ---
    def create_permit_case(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/permit-cases", payload, headers)

    def list_permit_cases(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/permit-cases", headers=headers, params=params)

    def file_permit_case(self, permit_case_id, payload, headers):
        return self._request("POST", f"/permit-cases/{permit_case_id}/file", payload, headers)

    def record_permit_decision(self, permit_case_id, payload, headers):
        return self._request("POST", f"/permit-cases/{permit_case_id}/record-decision", payload, headers)

    # --- Document packages ---
    def create_document_package(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/document-packages", {}, headers)

    def list_document_packages(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/document-packages", headers=headers, params=params)

    def add_artifact(self, package_id, payload, headers):
        return self._request("POST", f"/document-packages/{package_id}/artifacts", payload, headers)

    # --- Invoices ---
    def create_invoice(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/invoices", payload, headers)

    def list_invoices(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def submit_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/submit", payload, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", payload, headers)

    def record_payment(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/record-payment", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
