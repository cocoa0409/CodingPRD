"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Styles ---
    def create_style(self, payload, headers):
        return self._request("POST", "/styles", payload, headers)

    def get_style(self, style_id, headers):
        return self._request("GET", f"/styles/{style_id}", headers=headers)

    def list_styles(self, headers, params=None):
        return self._request("GET", "/styles", headers=headers, params=params)

    def certify_content_claim(self, style_id, headers):
        return self._request("POST", f"/styles/{style_id}/certify-content-claim", {}, headers)

    # --- Tech packs ---
    def create_tech_pack(self, payload, headers):
        return self._request("POST", "/tech-packs", payload, headers)

    def list_tech_packs(self, headers, params=None):
        return self._request("GET", "/tech-packs", headers=headers, params=params)

    def get_tech_pack(self, tech_pack_id, headers):
        return self._request("GET", f"/tech-packs/{tech_pack_id}", headers=headers)

    def get_graded_measurements(self, tech_pack_id, headers):
        return self._request("GET", f"/tech-packs/{tech_pack_id}/graded-measurements", headers=headers)

    def submit_tech_pack(self, tech_pack_id, headers):
        return self._request("POST", f"/tech-packs/{tech_pack_id}/submit", {}, headers)

    def review_tech_pack(self, tech_pack_id, payload, headers):
        return self._request("POST", f"/tech-packs/{tech_pack_id}/review", payload, headers)

    def revise_tech_pack(self, tech_pack_id, headers):
        return self._request("POST", f"/tech-packs/{tech_pack_id}/revise", {}, headers)

    # --- Operation specs ---
    def create_operation_spec(self, payload, headers):
        return self._request("POST", "/operation-specs", payload, headers)

    def list_operation_specs(self, headers, params=None):
        return self._request("GET", "/operation-specs", headers=headers, params=params)

    def get_operation_spec(self, operation_spec_id, headers):
        return self._request("GET", f"/operation-specs/{operation_spec_id}", headers=headers)

    # --- Trim items ---
    def create_trim_item(self, payload, headers):
        return self._request("POST", "/trim-items", payload, headers)

    def get_trim_item(self, trim_item_id, headers):
        return self._request("GET", f"/trim-items/{trim_item_id}", headers=headers)

    def receive_trim_item(self, trim_item_id, payload, headers):
        return self._request("POST", f"/trim-items/{trim_item_id}/receive", payload, headers)

    # --- Trim requirements ---
    def create_trim_requirement(self, payload, headers):
        return self._request("POST", "/trim-requirements", payload, headers)

    def list_trim_requirements(self, headers, params=None):
        return self._request("GET", "/trim-requirements", headers=headers, params=params)

    def get_trim_requirement(self, trim_requirement_id, headers):
        return self._request("GET", f"/trim-requirements/{trim_requirement_id}", headers=headers)

    # --- Fabric rolls ---
    def create_fabric_roll(self, payload, headers):
        return self._request("POST", "/fabric-rolls", payload, headers)

    def get_fabric_roll(self, fabric_roll_id, headers):
        return self._request("GET", f"/fabric-rolls/{fabric_roll_id}", headers=headers)

    def record_fabric_qc(self, fabric_roll_id, payload, headers):
        return self._request("POST", f"/fabric-rolls/{fabric_roll_id}/record-qc", payload, headers)

    # --- Production orders ---
    def create_production_order(self, payload, headers):
        return self._request("POST", "/production-orders", payload, headers)

    def list_production_orders(self, headers, params=None):
        return self._request("GET", "/production-orders", headers=headers, params=params)

    def get_production_order(self, production_order_id, headers):
        return self._request("GET", f"/production-orders/{production_order_id}", headers=headers)

    def get_production_order_wip(self, production_order_id, headers):
        return self._request("GET", f"/production-orders/{production_order_id}/wip", headers=headers)

    def plan_production_order(self, production_order_id, payload, headers):
        return self._request("POST", f"/production-orders/{production_order_id}/plan", payload, headers)

    def start_cutting(self, production_order_id, headers):
        return self._request("POST", f"/production-orders/{production_order_id}/start-cutting", {}, headers)

    def finish_production_order(self, production_order_id, headers):
        return self._request("POST", f"/production-orders/{production_order_id}/finish", {}, headers)

    # --- Markers ---
    def create_marker(self, payload, headers):
        return self._request("POST", "/markers", payload, headers)

    def list_markers(self, headers, params=None):
        return self._request("GET", "/markers", headers=headers, params=params)

    def get_marker(self, marker_id, headers):
        return self._request("GET", f"/markers/{marker_id}", headers=headers)

    def approve_marker(self, marker_id, payload, headers):
        return self._request("POST", f"/markers/{marker_id}/approve", payload, headers)

    def cut_marker(self, marker_id, payload, headers):
        return self._request("POST", f"/markers/{marker_id}/cut", payload, headers)

    def cancel_marker(self, marker_id, headers):
        return self._request("POST", f"/markers/{marker_id}/cancel", {}, headers)

    # --- Bundles ---
    def list_bundles(self, headers, params=None):
        return self._request("GET", "/bundles", headers=headers, params=params)

    def get_bundle(self, bundle_id, headers):
        return self._request("GET", f"/bundles/{bundle_id}", headers=headers)

    def release_bundle(self, bundle_id, headers):
        return self._request("POST", f"/bundles/{bundle_id}/release", {}, headers)

    # --- Sewing lines / assignments / operators ---
    def create_sewing_line(self, payload, headers):
        return self._request("POST", "/sewing-lines", payload, headers)

    def get_line_balance(self, sewing_line_id, headers, params=None):
        return self._request("GET", f"/sewing-lines/{sewing_line_id}/balance", headers=headers, params=params)

    def create_line_assignment(self, payload, headers):
        return self._request("POST", "/line-assignments", payload, headers)

    def list_line_assignments(self, headers, params=None):
        return self._request("GET", "/line-assignments", headers=headers, params=params)

    def get_line_assignment(self, line_assignment_id, headers):
        return self._request("GET", f"/line-assignments/{line_assignment_id}", headers=headers)

    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}", headers=headers)

    def get_operator_efficiency(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}/efficiency", headers=headers)

    # --- Piece work ---
    def create_piece_work_entry(self, payload, headers):
        return self._request("POST", "/piece-work-entries", payload, headers)

    def list_piece_work_entries(self, headers, params=None):
        return self._request("GET", "/piece-work-entries", headers=headers, params=params)

    def get_piece_work_entry(self, entry_id, headers):
        return self._request("GET", f"/piece-work-entries/{entry_id}", headers=headers)

    def review_piece_work_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/piece-work-entries/{entry_id}/review", payload, headers)

    # --- Payroll ---
    def create_payroll_run(self, payload, headers):
        return self._request("POST", "/payroll-runs", payload, headers)

    def get_payroll_run(self, payroll_run_id, headers):
        return self._request("GET", f"/payroll-runs/{payroll_run_id}", headers=headers)

    def calculate_payroll_run(self, payroll_run_id, payload, headers):
        return self._request("POST", f"/payroll-runs/{payroll_run_id}/calculate", payload, headers)

    def decide_payroll_run(self, payroll_run_id, payload, headers):
        return self._request("POST", f"/payroll-runs/{payroll_run_id}/decide", payload, headers)

    def pay_payroll_run(self, payroll_run_id, headers):
        return self._request("POST", f"/payroll-runs/{payroll_run_id}/pay", {}, headers)

    # --- Quality audits ---
    def create_quality_audit(self, payload, headers):
        return self._request("POST", "/quality-audits", payload, headers)

    def list_quality_audits(self, headers, params=None):
        return self._request("GET", "/quality-audits", headers=headers, params=params)

    def get_quality_audit(self, audit_id, headers):
        return self._request("GET", f"/quality-audits/{audit_id}", headers=headers)

    def record_quality_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/quality-audits/{audit_id}/record", payload, headers)

    def rework_complete_quality_audit(self, audit_id, headers):
        return self._request("POST", f"/quality-audits/{audit_id}/rework-complete", {}, headers)


api_client = ApiClient()
