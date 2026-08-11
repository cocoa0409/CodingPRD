"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/psm/_clock/set_current_utc", payload, headers)

    # --- PlantUnit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/psm/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/psm/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/psm/units/{unit_id}", headers=headers)

    def update_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/psm/units/{unit_id}", payload, headers)

    # --- Personnel ---
    def create_personnel(self, payload, headers):
        return self._request("POST", "/psm/personnel", payload, headers)

    def list_personnel(self, headers, params=None):
        return self._request("GET", "/psm/personnel", headers=headers, params=params)

    def get_personnel(self, personnel_id, headers):
        return self._request("GET", f"/psm/personnel/{personnel_id}", headers=headers)

    # --- MocRequest ---
    def create_moc(self, unit_id, payload, headers):
        return self._request("POST", f"/psm/units/{unit_id}/moc-requests", payload, headers)

    def get_moc(self, moc_id, headers):
        return self._request("GET", f"/psm/moc-requests/{moc_id}", headers=headers)

    def list_unit_mocs(self, unit_id, headers, params=None):
        return self._request("GET", f"/psm/units/{unit_id}/moc-requests", headers=headers, params=params)

    def list_personnel_mocs(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/moc-requests", headers=headers, params=params)

    def classify_moc(self, moc_id, payload, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/classify", payload, headers)

    def submit_moc(self, moc_id, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/submit", {}, headers)

    def resubmit_moc(self, moc_id, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/resubmit", {}, headers)

    def approve_moc(self, moc_id, payload, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/approve", payload, headers)

    def reject_moc(self, moc_id, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/reject", {}, headers)

    def withdraw_moc(self, moc_id, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/withdraw", {}, headers)

    def mark_implemented(self, moc_id, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/mark-implemented", {}, headers)

    def authorize_startup(self, moc_id, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/authorize-startup", {}, headers)

    def activate_moc(self, moc_id, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/activate", {}, headers)

    def close_moc(self, moc_id, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/close", {}, headers)

    # --- TechnicalReview ---
    def list_moc_reviews(self, moc_id, headers, params=None):
        return self._request("GET", f"/psm/moc-requests/{moc_id}/technical-reviews", headers=headers, params=params)

    def list_personnel_reviews(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/technical-reviews", headers=headers, params=params)

    def submit_verdict(self, review_id, payload, headers):
        return self._request("POST", f"/psm/technical-reviews/{review_id}/submit-verdict", payload, headers)

    # --- PhaStudy / PhaRevalidation ---
    def create_pha_study(self, unit_id, payload, headers):
        return self._request("POST", f"/psm/units/{unit_id}/pha-studies", payload, headers)

    def list_unit_pha_studies(self, unit_id, headers, params=None):
        return self._request("GET", f"/psm/units/{unit_id}/pha-studies", headers=headers, params=params)

    def get_pha_study(self, study_id, headers):
        return self._request("GET", f"/psm/pha-studies/{study_id}", headers=headers)

    def open_revalidation(self, study_id, payload, headers):
        return self._request("POST", f"/psm/pha-studies/{study_id}/open-revalidation", payload, headers)

    def list_study_revalidations(self, study_id, headers, params=None):
        return self._request("GET", f"/psm/pha-studies/{study_id}/revalidations", headers=headers, params=params)

    def list_personnel_revalidations(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/pha-revalidations", headers=headers, params=params)

    def complete_revalidation(self, revalidation_id, payload, headers):
        return self._request("POST", f"/psm/pha-revalidations/{revalidation_id}/complete", payload, headers)

    def abandon_revalidation(self, revalidation_id, headers):
        return self._request("POST", f"/psm/pha-revalidations/{revalidation_id}/abandon", {}, headers)

    # --- PSSR ---
    def create_pssr(self, moc_id, payload, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/pssrs", payload, headers)

    def list_moc_pssrs(self, moc_id, headers, params=None):
        return self._request("GET", f"/psm/moc-requests/{moc_id}/pssrs", headers=headers, params=params)

    def list_personnel_pssrs(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/pssrs", headers=headers, params=params)

    def get_pssr(self, pssr_id, headers):
        return self._request("GET", f"/psm/pssrs/{pssr_id}", headers=headers)

    def begin_pssr_fieldwork(self, pssr_id, headers):
        return self._request("POST", f"/psm/pssrs/{pssr_id}/begin-fieldwork", {}, headers)

    def create_punch_item(self, pssr_id, payload, headers):
        return self._request("POST", f"/psm/pssrs/{pssr_id}/punch-items", payload, headers)

    def approve_pssr(self, pssr_id, headers):
        return self._request("POST", f"/psm/pssrs/{pssr_id}/approve", {}, headers)

    def reject_pssr(self, pssr_id, headers):
        return self._request("POST", f"/psm/pssrs/{pssr_id}/reject", {}, headers)

    # --- ActionItem / Evidence ---
    def create_action_item(self, unit_id, payload, headers):
        return self._request("POST", f"/psm/units/{unit_id}/action-items", payload, headers)

    def list_unit_action_items(self, unit_id, headers, params=None):
        return self._request("GET", f"/psm/units/{unit_id}/action-items", headers=headers, params=params)

    def list_personnel_action_items(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/action-items", headers=headers, params=params)

    def get_action_item(self, item_id, headers):
        return self._request("GET", f"/psm/action-items/{item_id}", headers=headers)

    def start_action_item(self, item_id, headers):
        return self._request("POST", f"/psm/action-items/{item_id}/start", {}, headers)

    def submit_verification(self, item_id, headers):
        return self._request("POST", f"/psm/action-items/{item_id}/submit-verification", {}, headers)

    def verify_action_item(self, item_id, headers):
        return self._request("POST", f"/psm/action-items/{item_id}/verify", {}, headers)

    def reject_verification(self, item_id, headers):
        return self._request("POST", f"/psm/action-items/{item_id}/reject-verification", {}, headers)

    def reopen_action_item(self, item_id, payload, headers):
        return self._request("POST", f"/psm/action-items/{item_id}/reopen", payload, headers)

    def void_action_item(self, item_id, headers):
        return self._request("POST", f"/psm/action-items/{item_id}/void", {}, headers)

    def add_evidence(self, item_id, payload, headers):
        return self._request("POST", f"/psm/action-items/{item_id}/evidence-items", payload, headers)

    def list_evidence_items(self, item_id, headers, params=None):
        return self._request("GET", f"/psm/action-items/{item_id}/evidence-items", headers=headers, params=params)

    def list_personnel_evidence(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/evidence-items", headers=headers, params=params)

    def list_item_audit_findings(self, item_id, headers, params=None):
        return self._request("GET", f"/psm/action-items/{item_id}/audit-findings", headers=headers, params=params)

    # --- IncidentInvestigation ---
    def create_incident(self, unit_id, payload, headers):
        return self._request("POST", f"/psm/units/{unit_id}/incident-investigations", payload, headers)

    def list_unit_incidents(self, unit_id, headers, params=None):
        return self._request("GET", f"/psm/units/{unit_id}/incident-investigations", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/psm/incident-investigations/{incident_id}", headers=headers)

    def list_personnel_incidents(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/incident-investigations", headers=headers, params=params)

    def begin_rca(self, incident_id, headers):
        return self._request("POST", f"/psm/incident-investigations/{incident_id}/begin-rca", {}, headers)

    def submit_findings(self, incident_id, payload, headers):
        return self._request("POST", f"/psm/incident-investigations/{incident_id}/submit-findings", payload, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/psm/incident-investigations/{incident_id}/close", {}, headers)

    # --- Audit / AuditFinding ---
    def create_audit(self, unit_id, payload, headers):
        return self._request("POST", f"/psm/units/{unit_id}/audits", payload, headers)

    def list_unit_audits(self, unit_id, headers, params=None):
        return self._request("GET", f"/psm/units/{unit_id}/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/psm/audits/{audit_id}", headers=headers)

    def list_personnel_audits(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/audits", headers=headers, params=params)

    def list_audit_findings(self, audit_id, headers, params=None):
        return self._request("GET", f"/psm/audits/{audit_id}/findings", headers=headers, params=params)

    def begin_audit_fieldwork(self, audit_id, headers):
        return self._request("POST", f"/psm/audits/{audit_id}/begin-fieldwork", {}, headers)

    def report_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/psm/audits/{audit_id}/report", payload, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/psm/audits/{audit_id}/close", {}, headers)

    # --- ProcedureUpdate / TrainingAssignment ---
    def create_procedure_update(self, moc_id, payload, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/procedure-updates", payload, headers)

    def list_moc_procedure_updates(self, moc_id, headers, params=None):
        return self._request("GET", f"/psm/moc-requests/{moc_id}/procedure-updates", headers=headers, params=params)

    def get_procedure_update(self, update_id, headers):
        return self._request("GET", f"/psm/procedure-updates/{update_id}", headers=headers)

    def publish_procedure_update(self, update_id, headers):
        return self._request("POST", f"/psm/procedure-updates/{update_id}/publish", {}, headers)

    def create_training_assignment(self, update_id, payload, headers):
        return self._request("POST", f"/psm/procedure-updates/{update_id}/training-assignments", payload, headers)

    def list_update_assignments(self, update_id, headers, params=None):
        return self._request("GET", f"/psm/procedure-updates/{update_id}/training-assignments", headers=headers, params=params)

    def list_personnel_assignments(self, personnel_id, headers, params=None):
        return self._request("GET", f"/psm/personnel/{personnel_id}/training-assignments", headers=headers, params=params)

    def complete_training_assignment(self, assignment_id, headers):
        return self._request("POST", f"/psm/training-assignments/{assignment_id}/complete", {}, headers)

    # --- ExtensionRequest ---
    def create_extension_request(self, moc_id, payload, headers):
        return self._request("POST", f"/psm/moc-requests/{moc_id}/extension-requests", payload, headers)

    def list_extension_requests(self, moc_id, headers, params=None):
        return self._request("GET", f"/psm/moc-requests/{moc_id}/extension-requests", headers=headers, params=params)

    def approve_extension(self, extension_id, headers):
        return self._request("POST", f"/psm/extension-requests/{extension_id}/approve", {}, headers)

    def deny_extension(self, extension_id, headers):
        return self._request("POST", f"/psm/extension-requests/{extension_id}/deny", {}, headers)


api_client = ApiClient()
