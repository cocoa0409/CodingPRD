"""API client: one method per endpoint defined in the construction materials
testing PRD. All resources are mounted under the /api prefix. Transition
endpoints with no request body send an empty JSON object so implementations
parsing JSON bodies never see a missing body.
"""
from prd_bench_local_runner.testing import GenericApiClient

_EMPTY = {}


class ApiClient(GenericApiClient):
    # --- Logical clock / ops (PRD §2.5, §3.6) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/api/ops/run-daily-sweep", _EMPTY, headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    # --- SSI revisions ---
    def create_ssi_revision(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/ssi-revisions", payload, headers)

    def list_ssi_revisions(self, project_id, headers, params=None):
        return self._request("GET", f"/api/projects/{project_id}/ssi-revisions", headers=headers, params=params)

    def get_ssi_revision(self, ssi_id, headers):
        return self._request("GET", f"/api/ssi-revisions/{ssi_id}", headers=headers)

    def submit_ssi_revision(self, ssi_id, headers):
        return self._request("POST", f"/api/ssi-revisions/{ssi_id}/submit", _EMPTY, headers)

    def approve_ssi_revision(self, ssi_id, payload, headers):
        return self._request("POST", f"/api/ssi-revisions/{ssi_id}/approve", payload, headers)

    def list_scope_items(self, ssi_id, headers):
        return self._request("GET", f"/api/ssi-revisions/{ssi_id}/scope-items", headers=headers)

    # --- Technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/api/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/api/technicians/{technician_id}", headers=headers)

    def append_certification(self, technician_id, payload, headers):
        return self._request("POST", f"/api/technicians/{technician_id}/certifications", payload, headers)

    def deactivate_technician(self, technician_id, headers):
        return self._request("POST", f"/api/technicians/{technician_id}/deactivate", _EMPTY, headers)

    # --- Assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/api/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/api/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/assignments/{assignment_id}", headers=headers)

    def dispatch_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/assignments/{assignment_id}/dispatch", _EMPTY, headers)

    def cancel_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/assignments/{assignment_id}/cancel", payload, headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/assignments/{assignment_id}/complete", payload, headers)

    # --- Field tests ---
    def create_field_test(self, payload, headers):
        return self._request("POST", "/api/field-tests", payload, headers)

    def list_assignment_field_tests(self, assignment_id, headers):
        return self._request("GET", f"/api/assignments/{assignment_id}/field-tests", headers=headers)

    def void_field_test(self, field_test_id, headers):
        return self._request("POST", f"/api/field-tests/{field_test_id}/void", _EMPTY, headers)

    # --- Lab samples ---
    def create_lab_sample(self, payload, headers):
        return self._request("POST", "/api/lab-samples", payload, headers)

    def get_lab_sample(self, sample_id, headers):
        return self._request("GET", f"/api/lab-samples/{sample_id}", headers=headers)

    def list_assignment_lab_samples(self, assignment_id, headers):
        return self._request("GET", f"/api/assignments/{assignment_id}/lab-samples", headers=headers)

    def schedule_break(self, sample_id, payload, headers):
        return self._request("POST", f"/api/lab-samples/{sample_id}/schedule-break", payload, headers)

    def record_break(self, sample_id, payload, headers):
        return self._request("POST", f"/api/lab-samples/{sample_id}/record-break", payload, headers)

    def discard_lab_sample(self, sample_id, headers):
        return self._request("POST", f"/api/lab-samples/{sample_id}/discard", _EMPTY, headers)

    # --- Labs ---
    def create_lab(self, payload, headers):
        return self._request("POST", "/api/labs", payload, headers)

    def get_lab(self, lab_id, headers):
        return self._request("GET", f"/api/labs/{lab_id}", headers=headers)

    def list_lab_samples(self, lab_id, headers, params=None):
        return self._request("GET", f"/api/labs/{lab_id}/lab-samples", headers=headers, params=params)

    # --- Nonconformance reports ---
    def list_project_ncrs(self, project_id, headers, params=None):
        return self._request("GET", f"/api/projects/{project_id}/ncrs", headers=headers, params=params)

    def submit_correction(self, ncr_id, payload, headers):
        return self._request("POST", f"/api/ncrs/{ncr_id}/submit-correction", payload, headers)

    def verify_ncr(self, ncr_id, payload, headers):
        return self._request("POST", f"/api/ncrs/{ncr_id}/verify", payload, headers)

    # --- Daily inspection reports ---
    def create_daily_report(self, payload, headers):
        return self._request("POST", "/api/daily-reports", payload, headers)

    def list_project_daily_reports(self, project_id, headers, params=None):
        return self._request("GET", f"/api/projects/{project_id}/daily-reports", headers=headers, params=params)

    def acknowledge_daily_report(self, report_id, headers):
        return self._request("POST", f"/api/daily-reports/{report_id}/acknowledge", _EMPTY, headers)

    # --- Discrepancy tickets ---
    def create_discrepancy(self, payload, headers):
        return self._request("POST", "/api/discrepancies", payload, headers)

    def list_project_discrepancies(self, project_id, headers, params=None):
        return self._request("GET", f"/api/projects/{project_id}/discrepancies", headers=headers, params=params)

    def respond_discrepancy(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/discrepancies/{ticket_id}/respond", payload, headers)

    def resolve_discrepancy(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/discrepancies/{ticket_id}/resolve", payload, headers)

    # --- Final compliance letter ---
    def issue_letter(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/issue-letter", _EMPTY, headers)

    def void_letter(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/void-letter", payload, headers)


api_client = ApiClient()
