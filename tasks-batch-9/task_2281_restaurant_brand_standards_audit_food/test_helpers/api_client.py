"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Brands ----------------
    def create_brand(self, payload, headers):
        return self._request("POST", "/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def get_brand_risk_index(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}/risk-index", headers=headers)

    # ---------------- Franchisees ----------------
    def create_franchisee(self, payload, headers):
        return self._request("POST", "/franchisees", payload, headers)

    def get_franchisee(self, franchisee_id, headers):
        return self._request("GET", f"/franchisees/{franchisee_id}", headers=headers)

    def list_franchisees(self, headers, params=None):
        return self._request("GET", "/franchisees", headers=headers, params=params)

    # ---------------- Auditors ----------------
    def create_auditor(self, payload, headers):
        return self._request("POST", "/auditors", payload, headers)

    def get_auditor(self, auditor_id, headers):
        return self._request("GET", f"/auditors/{auditor_id}", headers=headers)

    def certify_auditor(self, auditor_id, headers, payload=None):
        return self._request("POST", f"/auditors/{auditor_id}/certify", payload, headers)

    def suspend_auditor(self, auditor_id, headers, payload=None):
        return self._request("POST", f"/auditors/{auditor_id}/suspend", payload, headers)

    def list_auditor_calibration_records(self, auditor_id, headers, params=None):
        return self._request(
            "GET", f"/auditors/{auditor_id}/calibration-records",
            headers=headers, params=params,
        )

    # ---------------- Locations ----------------
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def list_location_health_inspections(self, location_id, headers, params=None):
        return self._request(
            "GET", f"/locations/{location_id}/health-inspections",
            headers=headers, params=params,
        )

    def list_location_escalation_events(self, location_id, headers, params=None):
        return self._request(
            "GET", f"/locations/{location_id}/escalation-events",
            headers=headers, params=params,
        )

    def accept_cure(self, location_id, headers, payload=None):
        return self._request(
            "POST", f"/locations/{location_id}/cure-acceptance", payload, headers,
        )

    # ---------------- Rubric versions and items ----------------
    def create_rubric_version(self, payload, headers):
        return self._request("POST", "/rubric-versions", payload, headers)

    def get_rubric_version(self, rubric_version_id, headers):
        return self._request("GET", f"/rubric-versions/{rubric_version_id}", headers=headers)

    def list_rubric_versions(self, headers, params=None):
        return self._request("GET", "/rubric-versions", headers=headers, params=params)

    def create_rubric_item(self, rubric_version_id, payload, headers):
        return self._request(
            "POST", f"/rubric-versions/{rubric_version_id}/rubric-items", payload, headers,
        )

    def list_rubric_items(self, rubric_version_id, headers, params=None):
        return self._request(
            "GET", f"/rubric-versions/{rubric_version_id}/rubric-items",
            headers=headers, params=params,
        )

    def publish_rubric_version(self, rubric_version_id, headers, payload=None):
        return self._request(
            "POST", f"/rubric-versions/{rubric_version_id}/publish", payload, headers,
        )

    # ---------------- Audit visits ----------------
    def create_audit_visit(self, payload, headers):
        return self._request("POST", "/audit-visits", payload, headers)

    def get_audit_visit(self, visit_id, headers):
        return self._request("GET", f"/audit-visits/{visit_id}", headers=headers)

    def list_audit_visits(self, headers, params=None):
        return self._request("GET", "/audit-visits", headers=headers, params=params)

    def start_audit_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/audit-visits/{visit_id}/start", payload, headers)

    def create_scored_item(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/audit-visits/{visit_id}/scored-items", payload, headers,
        )

    def submit_audit_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/audit-visits/{visit_id}/submit", payload, headers)

    def rescore_audit_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/audit-visits/{visit_id}/rescore", payload, headers)

    def finalize_audit_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/audit-visits/{visit_id}/finalize", payload, headers)

    def void_audit_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/audit-visits/{visit_id}/void", payload, headers)

    def list_visit_calibration_records(self, visit_id, headers, params=None):
        return self._request(
            "GET", f"/audit-visits/{visit_id}/calibration-records",
            headers=headers, params=params,
        )

    def list_visit_escalation_events(self, visit_id, headers, params=None):
        return self._request(
            "GET", f"/audit-visits/{visit_id}/escalation-events",
            headers=headers, params=params,
        )

    # ---------------- Scored items ----------------
    def get_scored_item(self, scored_item_id, headers):
        return self._request("GET", f"/scored-items/{scored_item_id}", headers=headers)

    def list_scored_items(self, headers, params=None):
        return self._request("GET", "/scored-items", headers=headers, params=params)

    # ---------------- Corrective actions ----------------
    def get_corrective_action(self, corrective_action_id, headers):
        return self._request(
            "GET", f"/corrective-actions/{corrective_action_id}", headers=headers,
        )

    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/corrective-actions", headers=headers, params=params)

    def submit_corrective_action(self, corrective_action_id, headers, payload=None):
        return self._request(
            "POST", f"/corrective-actions/{corrective_action_id}/submit", payload, headers,
        )

    def verify_corrective_action(self, corrective_action_id, payload, headers):
        return self._request(
            "POST", f"/corrective-actions/{corrective_action_id}/verify", payload, headers,
        )

    def list_corrective_action_evidence_photos(self, corrective_action_id, headers, params=None):
        return self._request(
            "GET", f"/corrective-actions/{corrective_action_id}/evidence-photos",
            headers=headers, params=params,
        )

    def list_corrective_action_escalation_events(self, corrective_action_id, headers, params=None):
        return self._request(
            "GET", f"/corrective-actions/{corrective_action_id}/escalation-events",
            headers=headers, params=params,
        )

    # ---------------- Evidence photos ----------------
    def create_evidence_photo(self, payload, headers):
        return self._request("POST", "/evidence-photos", payload, headers)

    # ---------------- Disputes ----------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def list_dispute_evidence_photos(self, dispute_id, headers, params=None):
        return self._request(
            "GET", f"/disputes/{dispute_id}/evidence-photos", headers=headers, params=params,
        )

    def request_dispute_info(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/request-info", payload, headers)

    def supplement_dispute(self, dispute_id, headers, payload=None):
        return self._request("POST", f"/disputes/{dispute_id}/supplement", payload, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers, payload=None):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", payload, headers)

    # ---------------- Health inspections ----------------
    def create_health_inspection(self, payload, headers):
        return self._request("POST", "/health-inspections", payload, headers)

    def get_health_inspection(self, health_inspection_id, headers):
        return self._request(
            "GET", f"/health-inspections/{health_inspection_id}", headers=headers,
        )

    def disregard_health_inspection(self, health_inspection_id, payload, headers):
        return self._request(
            "POST", f"/health-inspections/{health_inspection_id}/disregard", payload, headers,
        )

    # ---------------- Calibration ----------------
    def create_calibration_record(self, payload, headers):
        return self._request("POST", "/calibration-records", payload, headers)

    # ---------------- Administrative ----------------
    def run_overdue_sweep(self, headers, payload=None):
        return self._request("POST", "/overdue-sweeps", payload, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
