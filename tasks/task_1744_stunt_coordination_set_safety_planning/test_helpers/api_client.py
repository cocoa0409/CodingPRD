"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving capability, PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Productions ---
    def create_production(self, payload, headers):
        return self._request("POST", "/api/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/api/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/api/productions/{production_id}", headers=headers)

    def get_production_summary(self, production_id, headers):
        return self._request("GET", f"/api/productions/{production_id}/summary", headers=headers)

    def amend_budget(self, production_id, payload, headers):
        return self._request("PATCH", f"/api/productions/{production_id}/budget", payload, headers)

    def file_insurance(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/file-insurance", payload, headers)

    def acknowledge_insurance(self, production_id, headers):
        return self._request("POST", f"/api/productions/{production_id}/acknowledge-insurance", None, headers)

    def activate_production(self, production_id, headers):
        return self._request("POST", f"/api/productions/{production_id}/activate", None, headers)

    def stop_production(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/stop", payload, headers)

    def lift_stoppage(self, production_id, headers):
        return self._request("POST", f"/api/productions/{production_id}/lift-stoppage", None, headers)

    def wrap_production(self, production_id, headers):
        return self._request("POST", f"/api/productions/{production_id}/wrap", None, headers)

    # --- Stunt sequences ---
    def create_sequence(self, payload, headers):
        return self._request("POST", "/api/stunt-sequences", payload, headers)

    def list_sequences(self, headers, params=None):
        return self._request("GET", "/api/stunt-sequences", headers=headers, params=params)

    def get_sequence(self, sequence_id, headers):
        return self._request("GET", f"/api/stunt-sequences/{sequence_id}", headers=headers)

    def lock_design(self, sequence_id, headers):
        return self._request("POST", f"/api/stunt-sequences/{sequence_id}/lock-design", None, headers)

    def mark_ready(self, sequence_id, headers):
        return self._request("POST", f"/api/stunt-sequences/{sequence_id}/mark-ready", None, headers)

    def reverify_readiness(self, sequence_id, headers):
        return self._request("POST", f"/api/stunt-sequences/{sequence_id}/reverify-readiness", None, headers)

    def cancel_sequence(self, sequence_id, headers, payload=None):
        return self._request("POST", f"/api/stunt-sequences/{sequence_id}/cancel", payload or {}, headers)

    # --- Risk assessments ---
    def create_risk_assessment(self, payload, headers):
        return self._request("POST", "/api/risk-assessments", payload, headers)

    def list_risk_assessments(self, headers, params=None):
        return self._request("GET", "/api/risk-assessments", headers=headers, params=params)

    def get_risk_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/risk-assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, assessment_id, headers):
        return self._request("POST", f"/api/risk-assessments/{assessment_id}/submit", None, headers)

    def approve_assessment(self, assessment_id, headers):
        return self._request("POST", f"/api/risk-assessments/{assessment_id}/approve", None, headers)

    def reject_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/api/risk-assessments/{assessment_id}/reject", payload, headers)

    def revise_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/api/risk-assessments/{assessment_id}/revise", payload, headers)

    # --- Performers ---
    def create_performer(self, payload, headers):
        return self._request("POST", "/api/performers", payload, headers)

    def list_performers(self, headers, params=None):
        return self._request("GET", "/api/performers", headers=headers, params=params)

    def get_performer(self, performer_id, headers):
        return self._request("GET", f"/api/performers/{performer_id}", headers=headers)

    def suspend_performer(self, performer_id, payload, headers):
        return self._request("POST", f"/api/performers/{performer_id}/suspend", payload, headers)

    def reinstate_performer(self, performer_id, headers):
        return self._request("POST", f"/api/performers/{performer_id}/reinstate", None, headers)

    # --- Certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/api/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/api/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/api/certifications/{certification_id}", headers=headers)

    def revoke_certification(self, certification_id, headers, payload=None):
        return self._request("POST", f"/api/certifications/{certification_id}/revoke", payload or {}, headers)

    # --- Rehearsals ---
    def create_rehearsal(self, payload, headers):
        return self._request("POST", "/api/rehearsals", payload, headers)

    def list_rehearsals(self, headers, params=None):
        return self._request("GET", "/api/rehearsals", headers=headers, params=params)

    def get_rehearsal(self, rehearsal_id, headers):
        return self._request("GET", f"/api/rehearsals/{rehearsal_id}", headers=headers)

    def complete_rehearsal(self, rehearsal_id, headers):
        return self._request("POST", f"/api/rehearsals/{rehearsal_id}/complete", None, headers)

    def mark_rehearsal_missed(self, rehearsal_id, headers):
        return self._request("POST", f"/api/rehearsals/{rehearsal_id}/mark-missed", None, headers)

    def cancel_rehearsal(self, rehearsal_id, headers):
        return self._request("POST", f"/api/rehearsals/{rehearsal_id}/cancel", None, headers)

    def void_rehearsal_completion(self, rehearsal_id, payload, headers):
        return self._request("POST", f"/api/rehearsals/{rehearsal_id}/void-completion", payload, headers)

    # --- Safety meetings ---
    def create_safety_meeting(self, payload, headers):
        return self._request("POST", "/api/safety-meetings", payload, headers)

    def list_safety_meetings(self, headers, params=None):
        return self._request("GET", "/api/safety-meetings", headers=headers, params=params)

    def get_safety_meeting(self, meeting_id, headers):
        return self._request("GET", f"/api/safety-meetings/{meeting_id}", headers=headers)

    def start_meeting(self, meeting_id, headers):
        return self._request("POST", f"/api/safety-meetings/{meeting_id}/start", None, headers)

    def complete_meeting(self, meeting_id, headers):
        return self._request("POST", f"/api/safety-meetings/{meeting_id}/complete", None, headers)

    def adjourn_meeting(self, meeting_id, headers):
        return self._request("POST", f"/api/safety-meetings/{meeting_id}/adjourn", None, headers)

    # --- Department signoffs ---
    def list_signoffs(self, headers, params=None):
        return self._request("GET", "/api/department-signoffs", headers=headers, params=params)

    def get_signoff(self, signoff_id, headers):
        return self._request("GET", f"/api/department-signoffs/{signoff_id}", headers=headers)

    def sign_signoff(self, signoff_id, headers, payload=None):
        return self._request("POST", f"/api/department-signoffs/{signoff_id}/sign", payload or {}, headers)

    def refuse_signoff(self, signoff_id, payload, headers):
        return self._request("POST", f"/api/department-signoffs/{signoff_id}/refuse", payload, headers)

    # --- Equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/api/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/api/equipment", headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/api/equipment/{equipment_id}", headers=headers)

    def retire_equipment(self, equipment_id, headers):
        return self._request("POST", f"/api/equipment/{equipment_id}/retire", None, headers)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/api/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/api/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/api/inspections/{inspection_id}", headers=headers)

    # --- Permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/api/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/api/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/api/permits/{permit_id}", headers=headers)

    def grant_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/grant", None, headers)

    def deny_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/deny", None, headers)

    def revoke_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/api/permits/{permit_id}/revoke", payload, headers)

    # --- Pay adjustments ---
    def create_pay_adjustment(self, payload, headers):
        return self._request("POST", "/api/pay-adjustments", payload, headers)

    def list_pay_adjustments(self, headers, params=None):
        return self._request("GET", "/api/pay-adjustments", headers=headers, params=params)

    def get_pay_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/api/pay-adjustments/{adjustment_id}", headers=headers)

    def counter_pay_adjustment(self, adjustment_id, payload, headers):
        return self._request("POST", f"/api/pay-adjustments/{adjustment_id}/counter", payload, headers)

    def agree_pay_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/api/pay-adjustments/{adjustment_id}/agree", None, headers)

    def withdraw_pay_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/api/pay-adjustments/{adjustment_id}/withdraw", None, headers)

    # --- Incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/api/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/api/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/api/incidents/{incident_id}", headers=headers)

    def open_investigation(self, incident_id, headers):
        return self._request("POST", f"/api/incidents/{incident_id}/open-investigation", None, headers)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/api/incidents/{incident_id}/close", payload, headers)

    # --- Stunt executions ---
    def create_execution(self, payload, headers):
        return self._request("POST", "/api/stunt-executions", payload, headers)

    def list_executions(self, headers, params=None):
        return self._request("GET", "/api/stunt-executions", headers=headers, params=params)

    def get_execution(self, execution_id, headers):
        return self._request("GET", f"/api/stunt-executions/{execution_id}", headers=headers)

    def complete_execution(self, execution_id, headers):
        return self._request("POST", f"/api/stunt-executions/{execution_id}/complete", None, headers)

    def abort_execution(self, execution_id, payload, headers):
        return self._request("POST", f"/api/stunt-executions/{execution_id}/abort", payload, headers)

    # --- Post-stunt reviews ---
    def create_review(self, payload, headers):
        return self._request("POST", "/api/post-stunt-reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/api/post-stunt-reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/api/post-stunt-reviews/{review_id}", headers=headers)

    def close_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/post-stunt-reviews/{review_id}/close", payload, headers)


api_client = ApiClient()
