"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5; outside the /audit mount) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- AuditableEntity (PRD §3.1) ---
    def create_auditable_entity(self, payload, headers):
        return self._request("POST", "/audit/auditable-entities", payload, headers)

    def get_auditable_entity(self, entity_id, headers):
        return self._request("GET", f"/audit/auditable-entities/{entity_id}", headers=headers)

    def retire_auditable_entity(self, entity_id, headers):
        return self._request("POST", f"/audit/auditable-entities/{entity_id}/retire", headers=headers)

    # --- RiskAssessment (PRD §3.1) ---
    def create_risk_assessment(self, payload, headers):
        return self._request("POST", "/audit/risk-assessments", payload, headers)

    def list_risk_assessments(self, headers, params=None):
        return self._request("GET", "/audit/risk-assessments", headers=headers, params=params)

    def get_risk_assessment(self, assessment_id, headers):
        return self._request("GET", f"/audit/risk-assessments/{assessment_id}", headers=headers)

    def finalize_risk_assessment(self, assessment_id, headers):
        return self._request("POST", f"/audit/risk-assessments/{assessment_id}/finalize", headers=headers)

    # --- RatingCriteriaConfig (PRD §3.2) ---
    def create_rating_criteria_config(self, payload, headers):
        return self._request("POST", "/audit/rating-criteria-configs", payload, headers)

    def get_rating_criteria_config(self, config_id, headers):
        return self._request("GET", f"/audit/rating-criteria-configs/{config_id}", headers=headers)

    def activate_rating_criteria_config(self, config_id, headers):
        return self._request("POST", f"/audit/rating-criteria-configs/{config_id}/activate", headers=headers)

    # --- AuditPlan (PRD §3.3) ---
    def create_audit_plan(self, payload, headers):
        return self._request("POST", "/audit/audit-plans", payload, headers)

    def get_audit_plan(self, plan_id, headers):
        return self._request("GET", f"/audit/audit-plans/{plan_id}", headers=headers)

    def submit_audit_plan(self, plan_id, headers):
        return self._request("POST", f"/audit/audit-plans/{plan_id}/submit", headers=headers)

    def approve_audit_plan(self, plan_id, headers):
        return self._request("POST", f"/audit/audit-plans/{plan_id}/approve", headers=headers)

    def return_audit_plan(self, plan_id, headers):
        return self._request("POST", f"/audit/audit-plans/{plan_id}/return", headers=headers)

    def close_audit_plan(self, plan_id, headers):
        return self._request("POST", f"/audit/audit-plans/{plan_id}/close", headers=headers)

    # --- Engagement (PRD §3.4) ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/audit/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/audit/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/audit/engagements/{engagement_id}", headers=headers)

    def scope_engagement(self, engagement_id, headers):
        return self._request("POST", f"/audit/engagements/{engagement_id}/scope", headers=headers)

    def begin_fieldwork(self, engagement_id, headers):
        return self._request("POST", f"/audit/engagements/{engagement_id}/begin-fieldwork", headers=headers)

    def begin_reporting(self, engagement_id, headers):
        return self._request("POST", f"/audit/engagements/{engagement_id}/begin-reporting", headers=headers)

    def close_engagement(self, engagement_id, headers):
        return self._request("POST", f"/audit/engagements/{engagement_id}/close", headers=headers)

    def cancel_engagement(self, engagement_id, headers):
        return self._request("POST", f"/audit/engagements/{engagement_id}/cancel", headers=headers)

    # --- Auditor (PRD §3.4) ---
    def create_auditor(self, payload, headers):
        return self._request("POST", "/audit/auditors", payload, headers)

    def get_auditor(self, auditor_id, headers):
        return self._request("GET", f"/audit/auditors/{auditor_id}", headers=headers)

    def deactivate_auditor(self, auditor_id, headers):
        return self._request("POST", f"/audit/auditors/{auditor_id}/deactivate", headers=headers)

    # --- EngagementAssignment (PRD §3.4) ---
    def create_engagement_assignment(self, payload, headers):
        return self._request("POST", "/audit/engagement-assignments", payload, headers)

    def list_engagement_assignments(self, headers, params=None):
        return self._request("GET", "/audit/engagement-assignments", headers=headers, params=params)

    def get_engagement_assignment(self, assignment_id, headers):
        return self._request("GET", f"/audit/engagement-assignments/{assignment_id}", headers=headers)

    def cancel_engagement_assignment(self, assignment_id, headers):
        return self._request("POST", f"/audit/engagement-assignments/{assignment_id}/cancel", headers=headers)

    # --- Workpaper (PRD §3.5) ---
    def create_workpaper(self, payload, headers):
        return self._request("POST", "/audit/workpapers", payload, headers)

    def list_workpapers(self, headers, params=None):
        return self._request("GET", "/audit/workpapers", headers=headers, params=params)

    def get_workpaper(self, workpaper_id, headers):
        return self._request("GET", f"/audit/workpapers/{workpaper_id}", headers=headers)

    def submit_workpaper(self, workpaper_id, headers):
        return self._request("POST", f"/audit/workpapers/{workpaper_id}/submit", headers=headers)

    def sign_off_workpaper(self, workpaper_id, headers):
        return self._request("POST", f"/audit/workpapers/{workpaper_id}/sign-off", headers=headers)

    def return_workpaper(self, workpaper_id, payload, headers):
        return self._request("POST", f"/audit/workpapers/{workpaper_id}/return", payload, headers)

    def revise_workpaper(self, workpaper_id, headers):
        return self._request("POST", f"/audit/workpapers/{workpaper_id}/revise", headers=headers)

    # --- Finding (PRD §3.6) ---
    def create_finding(self, payload, headers):
        return self._request("POST", "/audit/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/audit/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/audit/findings/{finding_id}", headers=headers)

    def issue_finding(self, finding_id, headers):
        return self._request("POST", f"/audit/findings/{finding_id}/issue", headers=headers)

    def escalate_finding(self, finding_id, headers):
        return self._request("POST", f"/audit/findings/{finding_id}/escalate", headers=headers)

    # --- ManagementResponse (PRD §3.6) ---
    def create_management_response(self, payload, headers):
        return self._request("POST", "/audit/management-responses", payload, headers)

    def list_management_responses(self, headers, params=None):
        return self._request("GET", "/audit/management-responses", headers=headers, params=params)

    def get_management_response(self, response_id, headers):
        return self._request("GET", f"/audit/management-responses/{response_id}", headers=headers)

    def accept_management_response(self, response_id, headers):
        return self._request("POST", f"/audit/management-responses/{response_id}/accept", headers=headers)

    def rebut_management_response(self, response_id, payload, headers):
        return self._request("POST", f"/audit/management-responses/{response_id}/rebut", payload, headers)

    # --- ActionPlan (PRD §3.7) ---
    def create_action_plan(self, payload, headers):
        return self._request("POST", "/audit/action-plans", payload, headers)

    def list_action_plans(self, headers, params=None):
        return self._request("GET", "/audit/action-plans", headers=headers, params=params)

    def get_action_plan(self, action_plan_id, headers):
        return self._request("GET", f"/audit/action-plans/{action_plan_id}", headers=headers)

    def start_action_plan(self, action_plan_id, headers):
        return self._request("POST", f"/audit/action-plans/{action_plan_id}/start", headers=headers)

    def submit_action_plan_validation(self, action_plan_id, headers):
        return self._request("POST", f"/audit/action-plans/{action_plan_id}/submit-validation", headers=headers)

    def validate_action_plan(self, action_plan_id, headers):
        return self._request("POST", f"/audit/action-plans/{action_plan_id}/validate", headers=headers)

    def reject_action_plan_validation(self, action_plan_id, payload, headers):
        return self._request("POST", f"/audit/action-plans/{action_plan_id}/reject-validation", payload, headers)

    # --- ExtensionRequest (PRD §3.7) ---
    def create_extension_request(self, payload, headers):
        return self._request("POST", "/audit/extension-requests", payload, headers)

    def list_extension_requests(self, headers, params=None):
        return self._request("GET", "/audit/extension-requests", headers=headers, params=params)

    def get_extension_request(self, request_id, headers):
        return self._request("GET", f"/audit/extension-requests/{request_id}", headers=headers)

    def approve_extension_request(self, request_id, headers):
        return self._request("POST", f"/audit/extension-requests/{request_id}/approve", headers=headers)

    def deny_extension_request(self, request_id, headers):
        return self._request("POST", f"/audit/extension-requests/{request_id}/deny", headers=headers)

    # --- AuditReport (PRD §3.8) ---
    def create_audit_report(self, payload, headers):
        return self._request("POST", "/audit/audit-reports", payload, headers)

    def list_audit_reports(self, headers, params=None):
        return self._request("GET", "/audit/audit-reports", headers=headers, params=params)

    def get_audit_report(self, report_id, headers):
        return self._request("GET", f"/audit/audit-reports/{report_id}", headers=headers)

    def submit_audit_report(self, report_id, headers):
        return self._request("POST", f"/audit/audit-reports/{report_id}/submit", headers=headers)

    def approve_audit_report(self, report_id, headers):
        return self._request("POST", f"/audit/audit-reports/{report_id}/approve", headers=headers)

    def return_audit_report(self, report_id, headers):
        return self._request("POST", f"/audit/audit-reports/{report_id}/return", headers=headers)

    def issue_audit_report(self, report_id, headers):
        return self._request("POST", f"/audit/audit-reports/{report_id}/issue", headers=headers)

    def distribute_audit_report(self, report_id, payload, headers):
        return self._request("POST", f"/audit/audit-reports/{report_id}/distribute", payload, headers)

    # --- QAReview (PRD §3.9) ---
    def create_qa_review(self, payload, headers):
        return self._request("POST", "/audit/qa-reviews", payload, headers)

    def list_qa_reviews(self, headers, params=None):
        return self._request("GET", "/audit/qa-reviews", headers=headers, params=params)

    def get_qa_review(self, review_id, headers):
        return self._request("GET", f"/audit/qa-reviews/{review_id}", headers=headers)

    def begin_qa_review(self, review_id, headers):
        return self._request("POST", f"/audit/qa-reviews/{review_id}/begin", headers=headers)

    def complete_qa_review(self, review_id, payload, headers):
        return self._request("POST", f"/audit/qa-reviews/{review_id}/complete", payload, headers)

    # --- CommitteePack (PRD §3.9) ---
    def create_committee_pack(self, payload, headers):
        return self._request("POST", "/audit/committee-packs", payload, headers)

    def list_committee_packs(self, headers, params=None):
        return self._request("GET", "/audit/committee-packs", headers=headers, params=params)

    def get_committee_pack(self, pack_id, headers):
        return self._request("GET", f"/audit/committee-packs/{pack_id}", headers=headers)

    def finalize_committee_pack(self, pack_id, headers):
        return self._request("POST", f"/audit/committee-packs/{pack_id}/finalize", headers=headers)

    def present_committee_pack(self, pack_id, headers):
        return self._request("POST", f"/audit/committee-packs/{pack_id}/present", headers=headers)


api_client = ApiClient()
