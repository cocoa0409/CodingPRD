"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Program clock / program-level ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def get_program_status(self, headers):
        return self._request("GET", "/api/program/status", headers=headers)

    def publish_policy(self, payload, headers):
        return self._request("POST", "/api/program/policy/publish", payload, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/api/program/sweep", headers=headers)

    # --- SecretAsset ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/api/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/api/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/api/assets/{asset_id}", headers=headers)

    def patch_asset(self, asset_id, payload, headers):
        return self._request("PATCH", f"/api/assets/{asset_id}", payload, headers)

    def transition_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/api/assets/{asset_id}/state", payload, headers)

    def get_posture_report(self, asset_id, headers):
        return self._request("GET", f"/api/assets/{asset_id}/posture-report", headers=headers)

    # --- ReasonableMeasure ---
    def create_measure(self, payload, headers):
        return self._request("POST", "/api/measures", payload, headers)

    def list_measures(self, headers, params=None):
        return self._request("GET", "/api/measures", headers=headers, params=params)

    def get_measure(self, measure_id, headers):
        return self._request("GET", f"/api/measures/{measure_id}", headers=headers)

    def transition_measure(self, measure_id, payload, headers):
        return self._request("POST", f"/api/measures/{measure_id}/state", payload, headers)

    # --- Counterparty ---
    def create_counterparty(self, payload, headers):
        return self._request("POST", "/api/counterparties", payload, headers)

    def list_counterparties(self, headers, params=None):
        return self._request("GET", "/api/counterparties", headers=headers, params=params)

    def get_counterparty(self, counterparty_id, headers):
        return self._request("GET", f"/api/counterparties/{counterparty_id}", headers=headers)

    def transition_counterparty(self, counterparty_id, payload, headers):
        return self._request("POST", f"/api/counterparties/{counterparty_id}/state", payload, headers)

    # --- NdaAgreement ---
    def create_nda(self, payload, headers):
        return self._request("POST", "/api/ndas", payload, headers)

    def create_nda_amendment(self, nda_id, payload, headers):
        return self._request("POST", f"/api/ndas/{nda_id}/amendments", payload, headers)

    def list_ndas(self, headers, params=None):
        return self._request("GET", "/api/ndas", headers=headers, params=params)

    def get_nda(self, nda_id, headers):
        return self._request("GET", f"/api/ndas/{nda_id}", headers=headers)

    def transition_nda(self, nda_id, payload, headers):
        return self._request("POST", f"/api/ndas/{nda_id}/state", payload, headers)

    # --- NdaObligation ---
    def create_obligation(self, payload, headers):
        return self._request("POST", "/api/obligations", payload, headers)

    def list_obligations(self, headers, params=None):
        return self._request("GET", "/api/obligations", headers=headers, params=params)

    def get_obligation(self, obligation_id, headers):
        return self._request("GET", f"/api/obligations/{obligation_id}", headers=headers)

    def transition_obligation(self, obligation_id, payload, headers):
        return self._request("POST", f"/api/obligations/{obligation_id}/state", payload, headers)

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/api/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/api/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/api/employees/{employee_id}", headers=headers)

    def transition_employee(self, employee_id, payload, headers):
        return self._request("POST", f"/api/employees/{employee_id}/state", payload, headers)

    # --- Acknowledgment ---
    def create_acknowledgment(self, payload, headers):
        return self._request("POST", "/api/acknowledgments", payload, headers)

    def list_acknowledgments(self, headers, params=None):
        return self._request("GET", "/api/acknowledgments", headers=headers, params=params)

    def get_acknowledgment(self, acknowledgment_id, headers):
        return self._request("GET", f"/api/acknowledgments/{acknowledgment_id}", headers=headers)

    def sign_acknowledgment(self, acknowledgment_id, headers):
        return self._request("POST", f"/api/acknowledgments/{acknowledgment_id}/sign", headers=headers)

    # --- ExitInterview ---
    def create_exit_interview(self, payload, headers):
        return self._request("POST", "/api/exit-interviews", payload, headers)

    def list_exit_interviews(self, headers, params=None):
        return self._request("GET", "/api/exit-interviews", headers=headers, params=params)

    def get_exit_interview(self, interview_id, headers):
        return self._request("GET", f"/api/exit-interviews/{interview_id}", headers=headers)

    def patch_exit_interview(self, interview_id, payload, headers):
        return self._request("PATCH", f"/api/exit-interviews/{interview_id}", payload, headers)

    def transition_exit_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/api/exit-interviews/{interview_id}/state", payload, headers)

    # --- AccessGrant ---
    def create_grant(self, payload, headers):
        return self._request("POST", "/api/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/api/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/api/grants/{grant_id}", headers=headers)

    def transition_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/api/grants/{grant_id}/state", payload, headers)

    # --- DisclosureRequest ---
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/api/disclosures", payload, headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/api/disclosures", headers=headers, params=params)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/api/disclosures/{disclosure_id}", headers=headers)

    def endorse_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/api/disclosures/{disclosure_id}/endorse", headers=headers)

    def transition_disclosure(self, disclosure_id, payload, headers):
        return self._request("POST", f"/api/disclosures/{disclosure_id}/state", payload, headers)

    # --- ForensicReview ---
    def create_forensic_review(self, payload, headers):
        return self._request("POST", "/api/forensic-reviews", payload, headers)

    def list_forensic_reviews(self, headers, params=None):
        return self._request("GET", "/api/forensic-reviews", headers=headers, params=params)

    def get_forensic_review(self, review_id, headers):
        return self._request("GET", f"/api/forensic-reviews/{review_id}", headers=headers)

    def patch_forensic_review(self, review_id, payload, headers):
        return self._request("PATCH", f"/api/forensic-reviews/{review_id}", payload, headers)

    def transition_forensic_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/forensic-reviews/{review_id}/state", payload, headers)

    # --- DemandLetter ---
    def create_demand_letter(self, payload, headers):
        return self._request("POST", "/api/demand-letters", payload, headers)

    def list_demand_letters(self, headers, params=None):
        return self._request("GET", "/api/demand-letters", headers=headers, params=params)

    def get_demand_letter(self, letter_id, headers):
        return self._request("GET", f"/api/demand-letters/{letter_id}", headers=headers)

    def transition_demand_letter(self, letter_id, payload, headers):
        return self._request("POST", f"/api/demand-letters/{letter_id}/state", payload, headers)

    # --- PreservationNotice ---
    def create_preservation_notice(self, payload, headers):
        return self._request("POST", "/api/preservation-notices", payload, headers)

    def list_preservation_notices(self, headers, params=None):
        return self._request("GET", "/api/preservation-notices", headers=headers, params=params)

    def get_preservation_notice(self, notice_id, headers):
        return self._request("GET", f"/api/preservation-notices/{notice_id}", headers=headers)

    def transition_preservation_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/api/preservation-notices/{notice_id}/state", payload, headers)

    # --- EvidenceItem ---
    def create_evidence_item(self, payload, headers):
        return self._request("POST", "/api/evidence-items", payload, headers)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", "/api/evidence-items", headers=headers, params=params)

    def get_evidence_item(self, evidence_id, headers):
        return self._request("GET", f"/api/evidence-items/{evidence_id}", headers=headers)

    def transition_evidence_item(self, evidence_id, payload, headers):
        return self._request("POST", f"/api/evidence-items/{evidence_id}/state", payload, headers)

    # --- TrainingAssignment ---
    def create_training_assignment(self, payload, headers):
        return self._request("POST", "/api/training-assignments", payload, headers)

    def list_training_assignments(self, headers, params=None):
        return self._request("GET", "/api/training-assignments", headers=headers, params=params)

    def get_training_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/training-assignments/{assignment_id}", headers=headers)

    def transition_training_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/training-assignments/{assignment_id}/state", payload, headers)

    # --- CleanDeskAudit ---
    def create_clean_desk_audit(self, payload, headers):
        return self._request("POST", "/api/clean-desk-audits", payload, headers)

    def list_clean_desk_audits(self, headers, params=None):
        return self._request("GET", "/api/clean-desk-audits", headers=headers, params=params)

    def get_clean_desk_audit(self, audit_id, headers):
        return self._request("GET", f"/api/clean-desk-audits/{audit_id}", headers=headers)

    def transition_clean_desk_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/api/clean-desk-audits/{audit_id}/state", payload, headers)


api_client = ApiClient()
