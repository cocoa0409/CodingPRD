"""API client: one method per endpoint defined in PRD §4 (mounted under /vsa)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/vsa/_clock/set_current_utc", payload, headers)

    # --- tier policies ---
    def create_tier_policy(self, payload, headers):
        return self._request("POST", "/vsa/tier-policies", payload, headers)

    def list_tier_policies(self, headers, params=None):
        return self._request("GET", "/vsa/tier-policies", headers=headers, params=params)

    def get_tier_policy(self, policy_id, headers):
        return self._request("GET", f"/vsa/tier-policies/{policy_id}", headers=headers)

    # --- questionnaire templates ---
    def create_template(self, payload, headers):
        return self._request("POST", "/vsa/questionnaire-templates", payload, headers)

    def list_templates(self, headers, params=None):
        return self._request("GET", "/vsa/questionnaire-templates", headers=headers, params=params)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/vsa/questionnaire-templates/{template_id}", headers=headers)

    def publish_template(self, template_id, headers):
        return self._request("POST", f"/vsa/questionnaire-templates/{template_id}/publish", {}, headers)

    def retire_template(self, template_id, headers):
        return self._request("POST", f"/vsa/questionnaire-templates/{template_id}/retire", {}, headers)

    def revise_template(self, template_id, headers):
        return self._request("POST", f"/vsa/questionnaire-templates/{template_id}/revise", {}, headers)

    def list_template_cycles(self, template_id, headers, params=None):
        return self._request("GET", f"/vsa/questionnaire-templates/{template_id}/cycles", headers=headers, params=params)

    # --- vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vsa/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vsa/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vsa/vendors/{vendor_id}", headers=headers)

    def patch_vendor(self, vendor_id, payload, headers):
        return self._request("PATCH", f"/vsa/vendors/{vendor_id}", payload, headers)

    def offboard_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/offboard", {}, headers)

    # --- vendor contacts ---
    def create_contact(self, vendor_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/contacts", payload, headers)

    def list_contacts(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vsa/vendors/{vendor_id}/contacts", headers=headers, params=params)

    # --- assessment cycles ---
    def create_cycle(self, vendor_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles", payload, headers)

    def list_cycles(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vsa/vendors/{vendor_id}/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/vsa/cycles/{cycle_id}", headers=headers)

    def list_cycle_responses(self, cycle_id, headers, params=None):
        return self._request("GET", f"/vsa/cycles/{cycle_id}/responses", headers=headers, params=params)

    def list_cycle_evidence(self, cycle_id, headers, params=None):
        return self._request("GET", f"/vsa/cycles/{cycle_id}/evidence", headers=headers, params=params)

    def list_cycle_exceptions(self, cycle_id, headers, params=None):
        return self._request("GET", f"/vsa/cycles/{cycle_id}/exceptions", headers=headers, params=params)

    def list_cycle_remediation_plans(self, cycle_id, headers, params=None):
        return self._request("GET", f"/vsa/cycles/{cycle_id}/remediation-plans", headers=headers, params=params)

    def list_cycle_risk_acceptances(self, cycle_id, headers, params=None):
        return self._request("GET", f"/vsa/cycles/{cycle_id}/risk-acceptances", headers=headers, params=params)

    def issue_cycle(self, vendor_id, cycle_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/issue", {}, headers)

    def score_cycle(self, vendor_id, cycle_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/score", {}, headers)

    def complete_evidence_review(self, vendor_id, cycle_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/evidence-review/complete", {}, headers)

    def resolve_remediation(self, vendor_id, cycle_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/remediation/resolve", {}, headers)

    def approve_cycle(self, vendor_id, cycle_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/approve", {}, headers)

    def reject_cycle(self, vendor_id, cycle_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/reject", {}, headers)

    # --- questionnaire responses ---
    def create_response(self, vendor_id, cycle_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/responses", payload, headers)

    def submit_response(self, vendor_id, cycle_id, response_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/responses/{response_id}/submit", {}, headers)

    def return_response(self, vendor_id, cycle_id, response_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/responses/{response_id}/return", {}, headers)

    # --- evidence artifacts ---
    def upload_evidence(self, vendor_id, cycle_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/evidence", payload, headers)

    def start_evidence_review(self, vendor_id, cycle_id, evidence_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/evidence/{evidence_id}/start-review", {}, headers)

    def complete_artifact_review(self, vendor_id, cycle_id, evidence_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/evidence/{evidence_id}/complete-review", {}, headers)

    def reject_evidence(self, vendor_id, cycle_id, evidence_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/evidence/{evidence_id}/reject", {}, headers)

    # --- exception findings ---
    def get_exception(self, exception_id, headers):
        return self._request("GET", f"/vsa/exceptions/{exception_id}", headers=headers)

    def list_exceptions(self, headers, params=None):
        return self._request("GET", "/vsa/exceptions", headers=headers, params=params)

    def create_exception(self, vendor_id, cycle_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/exceptions", payload, headers)

    def mark_false_positive(self, vendor_id, cycle_id, exception_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/exceptions/{exception_id}/mark-false-positive", payload, headers)

    # --- remediation plans ---
    def create_remediation_plan(self, vendor_id, cycle_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/remediation-plans", payload, headers)

    def accept_plan(self, vendor_id, cycle_id, plan_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/remediation-plans/{plan_id}/accept", {}, headers)

    def reject_plan(self, vendor_id, cycle_id, plan_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/remediation-plans/{plan_id}/reject", {}, headers)

    def progress_plan(self, vendor_id, cycle_id, plan_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/remediation-plans/{plan_id}/progress", payload, headers)

    def verify_plan(self, vendor_id, cycle_id, plan_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/remediation-plans/{plan_id}/verify", payload, headers)

    # --- risk acceptances ---
    def create_risk_acceptance(self, vendor_id, cycle_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/risk-acceptances", payload, headers)

    def approve_risk_acceptance(self, vendor_id, cycle_id, acceptance_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/risk-acceptances/{acceptance_id}/approve", payload, headers)

    def reject_risk_acceptance(self, vendor_id, cycle_id, acceptance_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/cycles/{cycle_id}/risk-acceptances/{acceptance_id}/reject", {}, headers)

    # --- contract addenda ---
    def list_addenda(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vsa/vendors/{vendor_id}/addenda", headers=headers, params=params)

    def list_cycle_addenda(self, cycle_id, headers, params=None):
        return self._request("GET", f"/vsa/cycles/{cycle_id}/addenda", headers=headers, params=params)

    def draft_addendum(self, vendor_id, addendum_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/addenda/{addendum_id}/draft", {}, headers)

    def sign_addendum(self, vendor_id, addendum_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/addenda/{addendum_id}/sign", payload, headers)

    def waive_addendum(self, vendor_id, addendum_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/addenda/{addendum_id}/waive", payload, headers)

    # --- monitoring alerts ---
    def create_alert(self, vendor_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/monitoring-alerts", payload, headers)

    def list_alerts(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vsa/vendors/{vendor_id}/monitoring-alerts", headers=headers, params=params)

    def acknowledge_alert(self, vendor_id, alert_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/monitoring-alerts/{alert_id}/acknowledge", payload, headers)

    def dismiss_alert(self, vendor_id, alert_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/monitoring-alerts/{alert_id}/dismiss", payload, headers)

    def escalate_alert(self, vendor_id, alert_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/monitoring-alerts/{alert_id}/escalate", payload, headers)

    # --- subprocessor disclosures ---
    def create_subprocessor(self, vendor_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/subprocessors", payload, headers)

    def list_subprocessors(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vsa/vendors/{vendor_id}/subprocessors", headers=headers, params=params)

    def start_subprocessor_review(self, vendor_id, disclosure_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/subprocessors/{disclosure_id}/start-review", {}, headers)

    def approve_subprocessor(self, vendor_id, disclosure_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/subprocessors/{disclosure_id}/approve", {}, headers)

    def reject_subprocessor(self, vendor_id, disclosure_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/subprocessors/{disclosure_id}/reject", {}, headers)

    def withdraw_subprocessor(self, vendor_id, disclosure_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/subprocessors/{disclosure_id}/withdraw", {}, headers)

    # --- offboarding attestations ---
    def list_attestations(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vsa/vendors/{vendor_id}/offboarding-attestations", headers=headers, params=params)

    def submit_attestation(self, vendor_id, attestation_id, payload, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/offboarding-attestations/{attestation_id}/submit", payload, headers)

    def verify_attestation(self, vendor_id, attestation_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/offboarding-attestations/{attestation_id}/verify", {}, headers)

    def reject_attestation(self, vendor_id, attestation_id, headers):
        return self._request("POST", f"/vsa/vendors/{vendor_id}/offboarding-attestations/{attestation_id}/reject", {}, headers)

    # --- reassessment schedule (audit log) ---
    def list_reassessment_schedule(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vsa/vendors/{vendor_id}/reassessment-schedule", headers=headers, params=params)


api_client = ApiClient()
