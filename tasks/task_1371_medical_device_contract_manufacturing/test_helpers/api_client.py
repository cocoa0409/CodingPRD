"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- DeviceMasterRecord ---
    def create_dmr(self, payload, headers):
        return self._request("POST", "/api/device-master-records", payload, headers)

    def list_dmrs(self, headers, params=None):
        return self._request("GET", "/api/device-master-records", headers=headers, params=params)

    def get_dmr(self, dmr_id, headers):
        return self._request("GET", f"/api/device-master-records/{dmr_id}", headers=headers)

    def approve_dmr(self, dmr_id, headers):
        return self._request("POST", f"/api/device-master-records/{dmr_id}/approve", {}, headers)

    def obsolete_dmr(self, dmr_id, headers):
        return self._request("POST", f"/api/device-master-records/{dmr_id}/obsolete", {}, headers)

    def create_dmr_revision(self, dmr_id, payload, headers):
        return self._request("POST", f"/api/device-master-records/{dmr_id}/revisions", payload, headers)

    # --- ManufacturingLine ---
    def create_line(self, payload, headers):
        return self._request("POST", "/api/manufacturing-lines", payload, headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/api/manufacturing-lines", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/api/manufacturing-lines/{line_id}", headers=headers)

    # --- Supplier ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/api/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/api/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/api/suppliers/{supplier_id}", headers=headers)

    def qualify_supplier(self, supplier_id, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/qualify", {}, headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/suspend", {}, headers)

    def reinstate_supplier(self, supplier_id, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/reinstate", {}, headers)

    def disqualify_supplier(self, supplier_id, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/disqualify", {}, headers)

    # --- QualityAgreement ---
    def create_agreement(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/quality-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/api/quality-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/quality-agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/quality-agreements/{agreement_id}/activate", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/quality-agreements/{agreement_id}/terminate", {}, headers)

    # --- SupplierPart ---
    def create_part(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/api/supplier-parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/api/supplier-parts/{part_id}", headers=headers)

    def receive_part(self, part_id, payload, headers):
        return self._request("POST", f"/api/supplier-parts/{part_id}/receive", payload, headers)

    def reinstate_part(self, part_id, headers):
        return self._request("POST", f"/api/supplier-parts/{part_id}/reinstate", {}, headers)

    # --- SupplierChangeNotification ---
    def create_scn(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/change-notifications", payload, headers)

    def list_scns(self, headers, params=None):
        return self._request("GET", "/api/change-notifications", headers=headers, params=params)

    def get_scn(self, scn_id, headers):
        return self._request("GET", f"/api/change-notifications/{scn_id}", headers=headers)

    def start_scn_review(self, scn_id, headers):
        return self._request("POST", f"/api/change-notifications/{scn_id}/start-review", {}, headers)

    def accept_scn(self, scn_id, headers):
        return self._request("POST", f"/api/change-notifications/{scn_id}/accept", {}, headers)

    def reject_scn(self, scn_id, headers):
        return self._request("POST", f"/api/change-notifications/{scn_id}/reject", {}, headers)

    # --- SupplierAudit ---
    def create_audit(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/api/supplier-audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/api/supplier-audits/{audit_id}", headers=headers)

    def complete_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/api/supplier-audits/{audit_id}/complete", payload, headers)

    def cancel_audit(self, audit_id, headers):
        return self._request("POST", f"/api/supplier-audits/{audit_id}/cancel", {}, headers)

    # --- ValidationProtocol ---
    def create_protocol(self, payload, headers):
        return self._request("POST", "/api/validation-protocols", payload, headers)

    def list_protocols(self, headers, params=None):
        return self._request("GET", "/api/validation-protocols", headers=headers, params=params)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"/api/validation-protocols/{protocol_id}", headers=headers)

    def execute_phase(self, protocol_id, headers):
        return self._request("POST", f"/api/validation-protocols/{protocol_id}/execute-phase", {}, headers)

    def submit_phase_review(self, protocol_id, headers):
        return self._request("POST", f"/api/validation-protocols/{protocol_id}/submit-phase-review", {}, headers)

    def approve_phase(self, protocol_id, headers):
        return self._request("POST", f"/api/validation-protocols/{protocol_id}/approve-phase", {}, headers)

    def reject_phase(self, protocol_id, headers):
        return self._request("POST", f"/api/validation-protocols/{protocol_id}/reject-phase", {}, headers)

    # --- SterileBarrierStudy ---
    def create_study(self, payload, headers):
        return self._request("POST", "/api/sterile-barrier-studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/api/sterile-barrier-studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/api/sterile-barrier-studies/{study_id}", headers=headers)

    def complete_study(self, study_id, payload, headers):
        return self._request("POST", f"/api/sterile-barrier-studies/{study_id}/complete", payload, headers)

    # --- DeviceLot ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/api/device-lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/api/device-lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/api/device-lots/{lot_id}", headers=headers)

    def complete_lot(self, lot_id, headers):
        return self._request("POST", f"/api/device-lots/{lot_id}/complete", {}, headers)

    def place_hold(self, lot_id, headers):
        return self._request("POST", f"/api/device-lots/{lot_id}/place-hold", {}, headers)

    def release_hold(self, lot_id, headers):
        return self._request("POST", f"/api/device-lots/{lot_id}/release-hold", {}, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/api/device-lots/{lot_id}/release", {}, headers)

    def scrap_lot(self, lot_id, headers):
        return self._request("POST", f"/api/device-lots/{lot_id}/scrap", {}, headers)

    def record_sterility_result(self, lot_id, payload, headers):
        return self._request("POST", f"/api/device-lots/{lot_id}/record-sterility-result", payload, headers)

    # --- LotComponent ---
    def create_component(self, lot_id, payload, headers):
        return self._request("POST", f"/api/device-lots/{lot_id}/components", payload, headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/api/lot-components", headers=headers, params=params)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/api/lot-components/{component_id}", headers=headers)

    def delete_component(self, component_id, headers):
        return self._request("DELETE", f"/api/lot-components/{component_id}", None, headers)

    # --- UDILabel ---
    def create_label(self, lot_id, payload, headers):
        return self._request("POST", f"/api/device-lots/{lot_id}/udi-labels", payload, headers)

    def list_labels(self, headers, params=None):
        return self._request("GET", "/api/udi-labels", headers=headers, params=params)

    def get_label(self, label_id, headers):
        return self._request("GET", f"/api/udi-labels/{label_id}", headers=headers)

    def approve_label(self, label_id, headers):
        return self._request("POST", f"/api/udi-labels/{label_id}/approve", {}, headers)

    def print_label(self, label_id, headers):
        return self._request("POST", f"/api/udi-labels/{label_id}/print", {}, headers)

    def void_label(self, label_id, headers):
        return self._request("POST", f"/api/udi-labels/{label_id}/void", {}, headers)

    # --- NonconformanceReport ---
    def create_ncr(self, payload, headers):
        return self._request("POST", "/api/nonconformance-reports", payload, headers)

    def list_ncrs(self, headers, params=None):
        return self._request("GET", "/api/nonconformance-reports", headers=headers, params=params)

    def get_ncr(self, ncr_id, headers):
        return self._request("GET", f"/api/nonconformance-reports/{ncr_id}", headers=headers)

    def contain_ncr(self, ncr_id, headers):
        return self._request("POST", f"/api/nonconformance-reports/{ncr_id}/contain", {}, headers)

    def disposition_ncr(self, ncr_id, payload, headers):
        return self._request("POST", f"/api/nonconformance-reports/{ncr_id}/disposition", payload, headers)

    def close_ncr(self, ncr_id, headers):
        return self._request("POST", f"/api/nonconformance-reports/{ncr_id}/close", {}, headers)

    def reopen_ncr(self, ncr_id, headers):
        return self._request("POST", f"/api/nonconformance-reports/{ncr_id}/reopen", {}, headers)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/api/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/api/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/api/complaints/{complaint_id}", headers=headers)

    def start_complaint_investigation(self, complaint_id, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/start-investigation", {}, headers)

    def complete_complaint_investigation(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/complete-investigation", payload, headers)

    def reopen_complaint(self, complaint_id, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/reopen", {}, headers)

    def close_complaint(self, complaint_id, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/close", {}, headers)

    # --- CAPA ---
    def create_capa(self, payload, headers):
        return self._request("POST", "/api/capas", payload, headers)

    def list_capas(self, headers, params=None):
        return self._request("GET", "/api/capas", headers=headers, params=params)

    def get_capa(self, capa_id, headers):
        return self._request("GET", f"/api/capas/{capa_id}", headers=headers)

    def begin_capa_investigation(self, capa_id, headers):
        return self._request("POST", f"/api/capas/{capa_id}/begin-investigation", {}, headers)

    def plan_capa_actions(self, capa_id, payload, headers):
        return self._request("POST", f"/api/capas/{capa_id}/plan-actions", payload, headers)

    def implement_capa(self, capa_id, headers):
        return self._request("POST", f"/api/capas/{capa_id}/implement", {}, headers)

    def complete_capa_implementation(self, capa_id, headers):
        return self._request("POST", f"/api/capas/{capa_id}/complete-implementation", {}, headers)

    def verify_capa_effectiveness(self, capa_id, payload, headers):
        return self._request("POST", f"/api/capas/{capa_id}/verify-effectiveness", payload, headers)

    def restart_capa_investigation(self, capa_id, headers):
        return self._request("POST", f"/api/capas/{capa_id}/restart-investigation", {}, headers)

    # --- FieldAction ---
    def create_field_action(self, payload, headers):
        return self._request("POST", "/api/field-actions", payload, headers)

    def list_field_actions(self, headers, params=None):
        return self._request("GET", "/api/field-actions", headers=headers, params=params)

    def get_field_action(self, action_id, headers):
        return self._request("GET", f"/api/field-actions/{action_id}", headers=headers)

    def issue_field_action(self, action_id, headers):
        return self._request("POST", f"/api/field-actions/{action_id}/issue", {}, headers)

    def close_field_action(self, action_id, headers):
        return self._request("POST", f"/api/field-actions/{action_id}/close", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
