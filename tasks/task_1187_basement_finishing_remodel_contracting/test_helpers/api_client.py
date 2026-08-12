"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- identity anchors ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/api/contractors", payload, headers)

    def create_homeowner(self, payload, headers):
        return self._request("POST", "/api/homeowners", payload, headers)

    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/api/subcontractors", payload, headers)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request("GET", f"/api/subcontractors/{subcontractor_id}", headers=headers)

    def list_subcontractor_site_logs(self, subcontractor_id, headers, params=None):
        return self._request(
            "GET", f"/api/subcontractors/{subcontractor_id}/site-logs",
            headers=headers, params=params,
        )

    # --- project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def resume_project(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/resume", payload, headers)

    def cancel_project(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/cancel", payload, headers)

    # --- moisture assessments ---
    def create_moisture_assessment(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/moisture-assessments", payload, headers
        )

    def list_moisture_assessments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/moisture-assessments",
            headers=headers, params=params,
        )

    def submit_moisture_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/api/moisture-assessments/{assessment_id}/submit", headers=headers
        )

    def reopen_moisture_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/api/moisture-assessments/{assessment_id}/reopen", payload, headers
        )

    # --- design packages ---
    def create_design_package(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/design-packages", payload, headers
        )

    def list_design_packages(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/design-packages",
            headers=headers, params=params,
        )

    def get_design_package(self, package_id, headers):
        return self._request("GET", f"/api/design-packages/{package_id}", headers=headers)

    def list_design_package_permits(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/api/design-packages/{package_id}/permits",
            headers=headers, params=params,
        )

    def submit_design_package(self, package_id, headers):
        return self._request(
            "POST", f"/api/design-packages/{package_id}/submit", headers=headers
        )

    def approve_design_package(self, package_id, headers):
        return self._request(
            "POST", f"/api/design-packages/{package_id}/approve", headers=headers
        )

    def request_design_revision(self, package_id, payload, headers):
        return self._request(
            "POST", f"/api/design-packages/{package_id}/request-revision", payload, headers
        )

    # --- permits ---
    def create_permit(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/permits", payload, headers)

    def list_permits(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/permits", headers=headers, params=params
        )

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/submit", headers=headers)

    def record_permit_decision(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/api/permits/{permit_id}/record-decision", payload, headers
        )

    # --- allowance lines ---
    def create_allowance_line(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/allowance-lines", payload, headers
        )

    def list_allowance_lines(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/allowance-lines",
            headers=headers, params=params,
        )

    def select_allowance_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/api/allowance-lines/{line_id}/select", payload, headers
        )

    # --- change orders ---
    def create_change_order(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/change-orders", payload, headers
        )

    def list_change_orders(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/change-orders",
            headers=headers, params=params,
        )

    def approve_change_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/change-orders/{order_id}/approve", headers=headers
        )

    def reject_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/change-orders/{order_id}/reject", payload, headers
        )

    def withdraw_change_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/change-orders/{order_id}/withdraw", headers=headers
        )

    # --- work phases ---
    def create_work_phase(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/work-phases", payload, headers
        )

    def list_work_phases(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/work-phases",
            headers=headers, params=params,
        )

    def get_work_phase(self, phase_id, headers):
        return self._request("GET", f"/api/work-phases/{phase_id}", headers=headers)

    def list_all_work_phases(self, headers, params=None):
        return self._request("GET", "/api/work-phases", headers=headers, params=params)

    def start_work_phase(self, phase_id, headers):
        return self._request("POST", f"/api/work-phases/{phase_id}/start", headers=headers)

    def complete_work_phase(self, phase_id, headers):
        return self._request(
            "POST", f"/api/work-phases/{phase_id}/complete", headers=headers
        )

    def cancel_work_phase(self, phase_id, payload, headers):
        return self._request(
            "POST", f"/api/work-phases/{phase_id}/cancel", payload, headers
        )

    # --- daily site logs ---
    def create_site_log(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/site-logs", payload, headers
        )

    def list_site_logs(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/site-logs", headers=headers, params=params
        )

    # --- inspections ---
    def create_inspection(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/inspections", payload, headers
        )

    def list_inspections(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/inspections",
            headers=headers, params=params,
        )

    def list_phase_inspections(self, phase_id, headers, params=None):
        return self._request(
            "GET", f"/api/work-phases/{phase_id}/inspections",
            headers=headers, params=params,
        )

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/api/inspections/{inspection_id}/record-result", payload, headers
        )

    # --- certificates & warranty ---
    def list_certificates(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/certificates",
            headers=headers, params=params,
        )

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/api/certificates/{certificate_id}", headers=headers)

    def create_warranty_claim(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/warranty-claims", payload, headers
        )

    def list_warranty_claims(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/warranty-claims",
            headers=headers, params=params,
        )

    def list_certificate_claims(self, certificate_id, headers, params=None):
        return self._request(
            "GET", f"/api/certificates/{certificate_id}/warranty-claims",
            headers=headers, params=params,
        )

    def decide_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/api/warranty-claims/{claim_id}/decide", payload, headers
        )

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
