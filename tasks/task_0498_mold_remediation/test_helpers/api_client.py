"""API client: one method per endpoint defined in the Mold Remediation PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (test-driving) ─────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── Workers ──────────────────────────────────────────────────────────
    def create_worker(self, payload, headers):
        return self._request("POST", "/api/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/api/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/api/workers/{worker_id}", headers=headers)

    # ─── Projects ─────────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def signoff_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/signoff", {}, headers)

    def abandon_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/abandon", {}, headers)

    # ─── Assessments ──────────────────────────────────────────────────────
    def create_assessment(self, payload, headers):
        return self._request("POST", "/api/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/api/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/assessments/{assessment_id}", headers=headers)

    # ─── Samples ──────────────────────────────────────────────────────────
    def create_sample(self, payload, headers):
        return self._request("POST", "/api/samples", payload, headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/api/samples", headers=headers, params=params)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/api/samples/{sample_id}", headers=headers)

    def upload_sample_result(self, sample_id, payload, headers):
        return self._request("POST", f"/api/samples/{sample_id}/result", payload, headers)

    def void_sample(self, sample_id, headers):
        return self._request("POST", f"/api/samples/{sample_id}/void", {}, headers)

    # ─── Containment Zones ────────────────────────────────────────────────
    def create_zone(self, payload, headers):
        return self._request("POST", "/api/containment-zones", payload, headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/api/containment-zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/api/containment-zones/{zone_id}", headers=headers)

    def create_pressure_log(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/api/containment-zones/{zone_id}/pressure-logs", payload, headers,
        )

    def list_pressure_logs(self, headers, params=None):
        return self._request("GET", "/api/pressure-logs", headers=headers, params=params)

    def get_pressure_log(self, plid, headers):
        return self._request("GET", f"/api/pressure-logs/{plid}", headers=headers)

    def activate_zone(self, zone_id, headers):
        return self._request("POST", f"/api/containment-zones/{zone_id}/activate", {}, headers)

    def dismantle_zone(self, zone_id, headers):
        return self._request("POST", f"/api/containment-zones/{zone_id}/dismantle", {}, headers)

    # ─── Abatement Orders ─────────────────────────────────────────────────
    def create_abatement_order(self, payload, headers):
        return self._request("POST", "/api/abatement-orders", payload, headers)

    def list_abatement_orders(self, headers, params=None):
        return self._request("GET", "/api/abatement-orders", headers=headers, params=params)

    def get_abatement_order(self, order_id, headers):
        return self._request("GET", f"/api/abatement-orders/{order_id}", headers=headers)

    def start_abatement_order(self, order_id, headers):
        return self._request("POST", f"/api/abatement-orders/{order_id}/start", {}, headers)

    def complete_abatement_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/abatement-orders/{order_id}/complete", payload, headers,
        )

    def cancel_abatement_order(self, order_id, headers):
        return self._request("POST", f"/api/abatement-orders/{order_id}/cancel", {}, headers)

    # ─── Worker Assignments ───────────────────────────────────────────────
    def create_assignment(self, payload, headers):
        return self._request("POST", "/api/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/api/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/assignments/{assignment_id}", headers=headers)

    # ─── Disposal Manifests ───────────────────────────────────────────────
    def create_manifest(self, payload, headers):
        return self._request("POST", "/api/disposal-manifests", payload, headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/api/disposal-manifests", headers=headers, params=params)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/api/disposal-manifests/{manifest_id}", headers=headers)

    def submit_manifest(self, manifest_id, headers):
        return self._request("POST", f"/api/disposal-manifests/{manifest_id}/submit", {}, headers)

    def accept_manifest(self, manifest_id, headers):
        return self._request("POST", f"/api/disposal-manifests/{manifest_id}/accept", {}, headers)

    def void_manifest(self, manifest_id, headers):
        return self._request("POST", f"/api/disposal-manifests/{manifest_id}/void", {}, headers)

    # ─── Clearance Tests ──────────────────────────────────────────────────
    def create_clearance_test(self, payload, headers):
        return self._request("POST", "/api/clearance-tests", payload, headers)

    def list_clearance_tests(self, headers, params=None):
        return self._request("GET", "/api/clearance-tests", headers=headers, params=params)

    def get_clearance_test(self, clearance_id, headers):
        return self._request("GET", f"/api/clearance-tests/{clearance_id}", headers=headers)

    def analyze_clearance_test(self, clearance_id, headers):
        return self._request("POST", f"/api/clearance-tests/{clearance_id}/analyze", {}, headers)

    def signoff_clearance_test(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"/api/clearance-tests/{clearance_id}/signoff", payload, headers,
        )

    # ─── Permits ──────────────────────────────────────────────────────────
    def create_permit(self, payload, headers):
        return self._request("POST", "/api/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/api/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/api/permits/{permit_id}", headers=headers)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/submit", {}, headers)

    def acknowledge_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/acknowledge", {}, headers)

    def expire_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/expire", {}, headers)

    # ─── Insurance Claims ─────────────────────────────────────────────────
    def create_insurance_claim(self, payload, headers):
        return self._request("POST", "/api/insurance-claims", payload, headers)

    def list_insurance_claims(self, headers, params=None):
        return self._request("GET", "/api/insurance-claims", headers=headers, params=params)

    def get_insurance_claim(self, claim_id, headers):
        return self._request("GET", f"/api/insurance-claims/{claim_id}", headers=headers)

    def submit_insurance_claim(self, claim_id, headers):
        return self._request("POST", f"/api/insurance-claims/{claim_id}/submit", {}, headers)

    def settle_insurance_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/api/insurance-claims/{claim_id}/settle", payload, headers,
        )

    def deny_insurance_claim(self, claim_id, headers):
        return self._request("POST", f"/api/insurance-claims/{claim_id}/deny", {}, headers)


api_client = ApiClient()
