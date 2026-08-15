"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- RegulatorAgency ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/regulatory-exams/agencies", payload, headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/regulatory-exams/agencies", headers=headers, params=params)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/regulatory-exams/agencies/{agency_id}", headers=headers)

    # --- BankOfficer ---
    def create_officer(self, payload, headers):
        return self._request("POST", "/regulatory-exams/officers", payload, headers)

    def list_officers(self, headers, params=None):
        return self._request("GET", "/regulatory-exams/officers", headers=headers, params=params)

    def get_officer(self, officer_id, headers):
        return self._request("GET", f"/regulatory-exams/officers/{officer_id}", headers=headers)

    # --- ComplianceReviewer ---
    def create_reviewer(self, payload, headers):
        return self._request("POST", "/regulatory-exams/reviewers", payload, headers)

    def list_reviewers(self, headers, params=None):
        return self._request("GET", "/regulatory-exams/reviewers", headers=headers, params=params)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/regulatory-exams/reviewers/{reviewer_id}", headers=headers)

    # --- Examination ---
    def create_examination(self, payload, headers):
        return self._request("POST", "/regulatory-exams/examinations", payload, headers)

    def list_examinations(self, headers, params=None):
        return self._request("GET", "/regulatory-exams/examinations", headers=headers, params=params)

    def get_examination(self, exam_id, headers):
        return self._request("GET", f"/regulatory-exams/examinations/{exam_id}", headers=headers)

    def issue_first_day_letter(self, exam_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/issue-first-day-letter",
            {}, headers)

    def begin_fieldwork(self, exam_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/begin-fieldwork", {}, headers)

    def deliver_findings(self, exam_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/deliver-findings", {}, headers)

    def open_remediation(self, exam_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/open-remediation", {}, headers)

    def close_examination(self, exam_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/close", {}, headers)

    def cancel_examination(self, exam_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/cancel", payload, headers)

    # --- FirstDayLetterItem ---
    def create_first_day_item(self, exam_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/first-day-items", payload, headers)

    def list_first_day_items(self, exam_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/examinations/{exam_id}/first-day-items",
            headers=headers, params=params)

    def get_first_day_item(self, item_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/first-day-items/{item_id}", headers=headers)

    def waive_first_day_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/first-day-items/{item_id}/waive", payload, headers)

    # --- DocumentSubmission ---
    def create_document_submission(self, item_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/first-day-items/{item_id}/submissions", payload, headers)

    def list_document_submissions(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/first-day-items/{item_id}/submissions",
            headers=headers, params=params)

    def get_document_submission(self, submission_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/document-submissions/{submission_id}", headers=headers)

    def accept_document_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/document-submissions/{submission_id}/accept", {}, headers)

    def reject_document_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/document-submissions/{submission_id}/reject",
            payload, headers)

    # --- ExaminerMeeting ---
    def create_examiner_meeting(self, payload, headers):
        return self._request("POST", "/regulatory-exams/examiner-meetings", payload, headers)

    def list_examiner_meetings(self, headers, params=None):
        return self._request(
            "GET", "/regulatory-exams/examiner-meetings", headers=headers, params=params)

    def get_examiner_meeting(self, meeting_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/examiner-meetings/{meeting_id}", headers=headers)

    def finalize_examiner_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/examiner-meetings/{meeting_id}/finalize", {}, headers)

    # --- InformalFinding ---
    def create_informal_finding(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/examiner-meetings/{meeting_id}/informal-findings",
            payload, headers)

    def list_informal_findings(self, meeting_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/examiner-meetings/{meeting_id}/informal-findings",
            headers=headers, params=params)

    def get_informal_finding(self, finding_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/informal-findings/{finding_id}", headers=headers)

    def list_informal_findings_portfolio(self, headers, params=None):
        return self._request(
            "GET", "/regulatory-exams/informal-findings", headers=headers, params=params)

    # --- Issue ---
    def create_issue(self, exam_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/issues", payload, headers)

    def list_issues(self, exam_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/examinations/{exam_id}/issues",
            headers=headers, params=params)

    def get_issue(self, issue_id, headers):
        return self._request("GET", f"/regulatory-exams/issues/{issue_id}", headers=headers)

    def list_issues_portfolio(self, headers, params=None):
        return self._request("GET", "/regulatory-exams/issues", headers=headers, params=params)

    def submit_issue_validation(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/issues/{issue_id}/submit-validation", payload, headers)

    # --- RemediationPlan ---
    def create_remediation_plan(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/issues/{issue_id}/remediation-plans", payload, headers)

    def list_remediation_plans(self, issue_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/issues/{issue_id}/remediation-plans",
            headers=headers, params=params)

    def get_remediation_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/remediation-plans/{plan_id}", headers=headers)

    def list_remediation_plans_portfolio(self, headers, params=None):
        return self._request(
            "GET", "/regulatory-exams/remediation-plans", headers=headers, params=params)

    def submit_remediation_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/remediation-plans/{plan_id}/submit", {}, headers)

    def approve_remediation_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/remediation-plans/{plan_id}/approve", {}, headers)

    def reject_remediation_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/remediation-plans/{plan_id}/reject", payload, headers)

    def revise_remediation_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/remediation-plans/{plan_id}/revise", {}, headers)

    def activate_remediation_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/remediation-plans/{plan_id}/activate", {}, headers)

    # --- RemediationMilestone ---
    def create_remediation_milestone(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/remediation-plans/{plan_id}/milestones", payload, headers)

    def list_remediation_milestones(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/remediation-plans/{plan_id}/milestones",
            headers=headers, params=params)

    def get_remediation_milestone(self, milestone_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/remediation-milestones/{milestone_id}", headers=headers)

    def start_remediation_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/remediation-milestones/{milestone_id}/start", {}, headers)

    def complete_remediation_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/remediation-milestones/{milestone_id}/complete",
            {}, headers)

    # --- ValidationEvidence ---
    def create_validation_evidence(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/issues/{issue_id}/validation-evidence", payload, headers)

    def list_validation_evidence(self, issue_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/issues/{issue_id}/validation-evidence",
            headers=headers, params=params)

    def get_validation_evidence(self, evidence_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/validation-evidence/{evidence_id}", headers=headers)

    def list_validation_evidence_portfolio(self, headers, params=None):
        return self._request(
            "GET", "/regulatory-exams/validation-evidence", headers=headers, params=params)

    def mark_evidence_sufficient(self, evidence_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/validation-evidence/{evidence_id}/mark-sufficient",
            {}, headers)

    def mark_evidence_insufficient(self, evidence_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/validation-evidence/{evidence_id}/mark-insufficient",
            payload, headers)

    # --- ClosureRequest ---
    def list_closure_requests(self, issue_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/issues/{issue_id}/closure-requests",
            headers=headers, params=params)

    def get_closure_request(self, closure_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/closure-requests/{closure_id}", headers=headers)

    def list_closure_requests_portfolio(self, headers, params=None):
        return self._request(
            "GET", "/regulatory-exams/closure-requests", headers=headers, params=params)

    def approve_closure_request(self, closure_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/closure-requests/{closure_id}/approve", payload, headers)

    def reject_closure_request(self, closure_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/closure-requests/{closure_id}/reject", payload, headers)

    # --- BoardReport ---
    def create_board_report(self, payload, headers):
        return self._request("POST", "/regulatory-exams/board-reports", payload, headers)

    def list_board_reports(self, headers, params=None):
        return self._request(
            "GET", "/regulatory-exams/board-reports", headers=headers, params=params)

    def get_board_report(self, report_id, headers):
        return self._request("GET", f"/regulatory-exams/board-reports/{report_id}", headers=headers)

    def finalize_board_report(self, report_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/board-reports/{report_id}/finalize", {}, headers)

    # --- CommitmentLogEntry ---
    def create_commitment(self, exam_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-exams/examinations/{exam_id}/commitments", payload, headers)

    def list_commitments(self, exam_id, headers, params=None):
        return self._request(
            "GET", f"/regulatory-exams/examinations/{exam_id}/commitments",
            headers=headers, params=params)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/regulatory-exams/commitments/{commitment_id}", headers=headers)

    def list_commitments_portfolio(self, headers, params=None):
        return self._request(
            "GET", "/regulatory-exams/commitments", headers=headers, params=params)

    def fulfill_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"/regulatory-exams/commitments/{commitment_id}/fulfill", {}, headers)

    # --- Cross-exam computed read ---
    def get_risk_history(self, exam_id, headers):
        return self._request(
            "GET", f"/regulatory-exams/examinations/{exam_id}/risk-history", headers=headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request(
            "POST", "/regulatory-exams/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
