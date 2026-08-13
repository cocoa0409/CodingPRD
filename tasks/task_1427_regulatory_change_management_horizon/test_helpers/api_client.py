"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/compliance/_clock/set_current_utc", payload, headers)

    # --- Business owners ---
    def create_business_owner(self, payload, headers):
        return self._request("POST", "/compliance/business-owners", payload, headers)

    def get_business_owner(self, owner_id, headers):
        return self._request("GET", f"/compliance/business-owners/{owner_id}", headers=headers)

    # --- Regulatory changes ---
    def create_regulatory_change(self, payload, headers):
        return self._request("POST", "/compliance/regulatory-changes", payload, headers)

    def list_regulatory_changes(self, headers, params=None):
        return self._request("GET", "/compliance/regulatory-changes", headers=headers, params=params)

    def get_regulatory_change(self, change_id, headers):
        return self._request("GET", f"/compliance/regulatory-changes/{change_id}", headers=headers)

    def triage_regulatory_change(self, change_id, payload, headers):
        return self._request("POST", f"/compliance/regulatory-changes/{change_id}/triage", payload, headers)

    def retriage_regulatory_change(self, change_id, payload, headers):
        return self._request("POST", f"/compliance/regulatory-changes/{change_id}/retriage", payload, headers)

    # --- Impact assessments ---
    def create_impact_assessment(self, payload, headers):
        return self._request("POST", "/compliance/impact-assessments", payload, headers)

    def list_impact_assessments(self, headers, params=None):
        return self._request("GET", "/compliance/impact-assessments", headers=headers, params=params)

    def get_impact_assessment(self, assessment_id, headers):
        return self._request("GET", f"/compliance/impact-assessments/{assessment_id}", headers=headers)

    def start_impact_assessment(self, assessment_id, headers):
        return self._request("POST", f"/compliance/impact-assessments/{assessment_id}/start", {}, headers)

    def submit_impact_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/compliance/impact-assessments/{assessment_id}/submit", payload, headers)

    def accept_impact_assessment(self, assessment_id, headers):
        return self._request("POST", f"/compliance/impact-assessments/{assessment_id}/accept", {}, headers)

    def return_impact_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/compliance/impact-assessments/{assessment_id}/return", payload, headers)

    # --- Gap analyses ---
    def list_gap_analyses(self, headers, params=None):
        return self._request("GET", "/compliance/gap-analyses", headers=headers, params=params)

    def get_gap_analysis(self, gap_id, headers):
        return self._request("GET", f"/compliance/gap-analyses/{gap_id}", headers=headers)

    def begin_review_gap_analysis(self, gap_id, headers):
        return self._request("POST", f"/compliance/gap-analyses/{gap_id}/begin-review", {}, headers)

    def confirm_gap_analysis(self, gap_id, headers):
        return self._request("POST", f"/compliance/gap-analyses/{gap_id}/confirm", {}, headers)

    # --- Obligations ---
    def create_obligation(self, payload, headers):
        return self._request("POST", "/compliance/obligations", payload, headers)

    def list_obligations(self, headers, params=None):
        return self._request("GET", "/compliance/obligations", headers=headers, params=params)

    def get_obligation(self, obligation_id, headers):
        return self._request("GET", f"/compliance/obligations/{obligation_id}", headers=headers)

    def activate_obligation(self, obligation_id, headers):
        return self._request("POST", f"/compliance/obligations/{obligation_id}/activate", {}, headers)

    def retire_obligation(self, obligation_id, headers):
        return self._request("POST", f"/compliance/obligations/{obligation_id}/retire", {}, headers)

    def reinstate_obligation(self, obligation_id, payload, headers):
        return self._request("POST", f"/compliance/obligations/{obligation_id}/reinstate", payload, headers)

    # --- Controls ---
    def create_control(self, payload, headers):
        return self._request("POST", "/compliance/controls", payload, headers)

    def list_controls(self, headers, params=None):
        return self._request("GET", "/compliance/controls", headers=headers, params=params)

    def get_control(self, control_id, headers):
        return self._request("GET", f"/compliance/controls/{control_id}", headers=headers)

    def record_control_review(self, control_id, headers):
        return self._request("POST", f"/compliance/controls/{control_id}/record-review", {}, headers)

    def retire_control(self, control_id, headers):
        return self._request("POST", f"/compliance/controls/{control_id}/retire", {}, headers)

    # --- Obligation-control mappings ---
    def create_mapping(self, payload, headers):
        return self._request("POST", "/compliance/obligation-control-mappings", payload, headers)

    def list_mappings(self, headers, params=None):
        return self._request("GET", "/compliance/obligation-control-mappings", headers=headers, params=params)

    def get_mapping(self, mapping_id, headers):
        return self._request("GET", f"/compliance/obligation-control-mappings/{mapping_id}", headers=headers)

    def approve_mapping(self, mapping_id, headers):
        return self._request("POST", f"/compliance/obligation-control-mappings/{mapping_id}/approve", {}, headers)

    def reject_mapping(self, mapping_id, payload, headers):
        return self._request("POST", f"/compliance/obligation-control-mappings/{mapping_id}/reject", payload, headers)

    def retire_mapping(self, mapping_id, headers):
        return self._request("POST", f"/compliance/obligation-control-mappings/{mapping_id}/retire", {}, headers)

    # --- Obligation register ---
    def get_obligation_register(self, headers):
        return self._request("GET", "/compliance/obligation-register", headers=headers)

    def publish_obligation_register(self, payload, headers):
        return self._request("POST", "/compliance/obligation-register/publish", payload, headers)

    def list_obligation_register_versions(self, headers, params=None):
        return self._request("GET", "/compliance/obligation-register-versions", headers=headers, params=params)

    # --- Implementation plans ---
    def create_implementation_plan(self, payload, headers):
        return self._request("POST", "/compliance/implementation-plans", payload, headers)

    def list_implementation_plans(self, headers, params=None):
        return self._request("GET", "/compliance/implementation-plans", headers=headers, params=params)

    def get_implementation_plan(self, plan_id, headers):
        return self._request("GET", f"/compliance/implementation-plans/{plan_id}", headers=headers)

    def submit_implementation_plan(self, plan_id, headers):
        return self._request("POST", f"/compliance/implementation-plans/{plan_id}/submit", {}, headers)

    def approve_implementation_plan(self, plan_id, headers):
        return self._request("POST", f"/compliance/implementation-plans/{plan_id}/approve", {}, headers)

    def reject_implementation_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/compliance/implementation-plans/{plan_id}/reject", payload, headers)

    def begin_execution_implementation_plan(self, plan_id, headers):
        return self._request("POST", f"/compliance/implementation-plans/{plan_id}/begin-execution", {}, headers)

    def complete_implementation_plan(self, plan_id, headers):
        return self._request("POST", f"/compliance/implementation-plans/{plan_id}/complete", {}, headers)

    def extend_deadline_implementation_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/compliance/implementation-plans/{plan_id}/extend-deadline", payload, headers)

    # --- Policy updates ---
    def create_policy_update(self, payload, headers):
        return self._request("POST", "/compliance/policy-updates", payload, headers)

    def list_policy_updates(self, headers, params=None):
        return self._request("GET", "/compliance/policy-updates", headers=headers, params=params)

    def get_policy_update(self, policy_update_id, headers):
        return self._request("GET", f"/compliance/policy-updates/{policy_update_id}", headers=headers)

    def submit_policy_update(self, policy_update_id, headers):
        return self._request("POST", f"/compliance/policy-updates/{policy_update_id}/submit", {}, headers)

    def approve_policy_update(self, policy_update_id, payload, headers):
        return self._request("POST", f"/compliance/policy-updates/{policy_update_id}/approve", payload, headers)

    def reject_policy_update(self, policy_update_id, payload, headers):
        return self._request("POST", f"/compliance/policy-updates/{policy_update_id}/reject", payload, headers)

    def revise_policy_update(self, policy_update_id, headers):
        return self._request("POST", f"/compliance/policy-updates/{policy_update_id}/revise", {}, headers)

    def publish_policy_update(self, policy_update_id, headers):
        return self._request("POST", f"/compliance/policy-updates/{policy_update_id}/publish", {}, headers)

    def retract_policy_update(self, policy_update_id, payload, headers):
        return self._request("POST", f"/compliance/policy-updates/{policy_update_id}/retract", payload, headers)

    # --- Training rollouts ---
    def list_training_rollouts(self, headers, params=None):
        return self._request("GET", "/compliance/training-rollouts", headers=headers, params=params)

    def get_training_rollout(self, rollout_id, headers):
        return self._request("GET", f"/compliance/training-rollouts/{rollout_id}", headers=headers)

    def upsert_attestations(self, rollout_id, payload, headers):
        return self._request("POST", f"/compliance/training-rollouts/{rollout_id}/attestations", payload, headers)

    def complete_training_rollout(self, rollout_id, headers):
        return self._request("POST", f"/compliance/training-rollouts/{rollout_id}/complete", {}, headers)

    def close_training_rollout_with_exceptions(self, rollout_id, payload, headers):
        return self._request("POST", f"/compliance/training-rollouts/{rollout_id}/close-with-exceptions", payload, headers)

    # --- Evidence packages ---
    def create_evidence_package(self, payload, headers):
        return self._request("POST", "/compliance/evidence-packages", payload, headers)

    def list_evidence_packages(self, headers, params=None):
        return self._request("GET", "/compliance/evidence-packages", headers=headers, params=params)

    def get_evidence_package(self, package_id, headers):
        return self._request("GET", f"/compliance/evidence-packages/{package_id}", headers=headers)

    def attach_artifact(self, package_id, payload, headers):
        return self._request("POST", f"/compliance/evidence-packages/{package_id}/artifacts", payload, headers)

    def remove_artifact(self, package_id, artifact_id, headers):
        return self._request(
            "DELETE", f"/compliance/evidence-packages/{package_id}/artifacts/{artifact_id}", headers=headers
        )

    def seal_evidence_package(self, package_id, headers):
        return self._request("POST", f"/compliance/evidence-packages/{package_id}/seal", {}, headers)

    def submit_evidence_package_to_examiner(self, package_id, payload, headers):
        return self._request("POST", f"/compliance/evidence-packages/{package_id}/submit-to-examiner", payload, headers)

    # --- Escalations ---
    def list_escalations(self, headers, params=None):
        return self._request("GET", "/compliance/escalations", headers=headers, params=params)

    def get_escalation(self, escalation_id, headers):
        return self._request("GET", f"/compliance/escalations/{escalation_id}", headers=headers)

    def acknowledge_escalation(self, escalation_id, headers):
        return self._request("POST", f"/compliance/escalations/{escalation_id}/acknowledge", {}, headers)

    def resolve_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"/compliance/escalations/{escalation_id}/resolve", payload, headers)

    # --- Committee reports ---
    def create_committee_report(self, payload, headers):
        return self._request("POST", "/compliance/committee-reports", payload, headers)

    def list_committee_reports(self, headers, params=None):
        return self._request("GET", "/compliance/committee-reports", headers=headers, params=params)

    def get_committee_report(self, report_id, headers):
        return self._request("GET", f"/compliance/committee-reports/{report_id}", headers=headers)

    def finalize_committee_report(self, report_id, headers):
        return self._request("POST", f"/compliance/committee-reports/{report_id}/finalize", {}, headers)

    def present_committee_report(self, report_id, headers):
        return self._request("POST", f"/compliance/committee-reports/{report_id}/present", {}, headers)

    # --- Audit trail ---
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/compliance/audit-events", headers=headers, params=params)

    def verify_audit_chain(self, headers):
        return self._request("GET", "/compliance/audit-events/verify", headers=headers)


api_client = ApiClient()
