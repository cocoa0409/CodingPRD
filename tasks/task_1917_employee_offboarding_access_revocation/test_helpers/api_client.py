"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/offboarding/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/offboarding/_clock/current_utc", headers=headers)

    # --- OffboardingCase ---
    def create_case(self, payload, headers):
        return self._request("POST", "/offboarding/offboarding-cases", payload, headers)

    def list_cases(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/offboarding-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/offboarding/offboarding-cases/{case_id}", headers=headers)

    def get_case_summary(self, case_id, headers):
        return self._request("GET", f"/offboarding/offboarding-cases/{case_id}/summary", headers=headers)

    def approve_case(self, case_id, headers):
        return self._request("POST", f"/offboarding/offboarding-cases/{case_id}/approve", None, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/offboarding/offboarding-cases/{case_id}/close", payload, headers)

    def void_case(self, case_id, payload, headers):
        return self._request("POST", f"/offboarding/offboarding-cases/{case_id}/void", payload, headers)

    # --- AccessRevocationTask ---
    def create_revocation_task(self, payload, headers):
        return self._request("POST", "/offboarding/access-revocation-tasks", payload, headers)

    def list_revocation_tasks(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/access-revocation-tasks", headers=headers, params=params)

    def get_revocation_task(self, task_id, headers):
        return self._request("GET", f"/offboarding/access-revocation-tasks/{task_id}", headers=headers)

    def list_case_revocation_tasks(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/access-revocation-tasks",
            headers=headers, params=params,
        )

    def execute_revocation_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/access-revocation-tasks/{task_id}/execute", payload, headers
        )

    def verify_revocation_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/access-revocation-tasks/{task_id}/verify", payload, headers
        )

    def retry_revocation_task(self, task_id, headers):
        return self._request(
            "POST", f"/offboarding/access-revocation-tasks/{task_id}/retry", None, headers
        )

    def waive_revocation_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/access-revocation-tasks/{task_id}/waive", payload, headers
        )

    # --- ManagerNotification ---
    def list_notifications(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/manager-notifications", headers=headers, params=params)

    def list_case_notifications(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/manager-notifications",
            headers=headers, params=params,
        )

    # --- AssetReturnItem ---
    def create_asset_item(self, payload, headers):
        return self._request("POST", "/offboarding/asset-return-items", payload, headers)

    def list_asset_items(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/asset-return-items", headers=headers, params=params)

    def get_asset_item(self, item_id, headers):
        return self._request("GET", f"/offboarding/asset-return-items/{item_id}", headers=headers)

    def list_case_asset_items(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/asset-return-items",
            headers=headers, params=params,
        )

    def record_asset_return(self, item_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/asset-return-items/{item_id}/record-return", payload, headers
        )

    def mark_asset_defaulted(self, item_id, headers):
        return self._request(
            "POST", f"/offboarding/asset-return-items/{item_id}/mark-defaulted", None, headers
        )

    def waive_asset_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/asset-return-items/{item_id}/waive", payload, headers
        )

    # --- FinalPayStatement ---
    def list_statements(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/final-pay-statements", headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/offboarding/final-pay-statements/{statement_id}", headers=headers)

    def list_case_statements(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/final-pay-statements",
            headers=headers, params=params,
        )

    def calculate_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/final-pay-statements/{statement_id}/calculate", payload, headers
        )

    def recalculate_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/final-pay-statements/{statement_id}/recalculate", payload, headers
        )

    def approve_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/offboarding/final-pay-statements/{statement_id}/approve", None, headers
        )

    def disburse_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/offboarding/final-pay-statements/{statement_id}/disburse", None, headers
        )

    # --- ExitInterview ---
    def create_exit_interview(self, payload, headers):
        return self._request("POST", "/offboarding/exit-interviews", payload, headers)

    def list_exit_interviews(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/exit-interviews", headers=headers, params=params)

    def get_exit_interview(self, interview_id, headers):
        return self._request("GET", f"/offboarding/exit-interviews/{interview_id}", headers=headers)

    def list_case_exit_interviews(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/exit-interviews",
            headers=headers, params=params,
        )

    def request_reschedule_interview(self, interview_id, headers):
        return self._request(
            "POST", f"/offboarding/exit-interviews/{interview_id}/request-reschedule", None, headers
        )

    def reschedule_interview(self, interview_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/exit-interviews/{interview_id}/reschedule", payload, headers
        )

    def complete_interview(self, interview_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/exit-interviews/{interview_id}/complete", payload, headers
        )

    def decline_interview(self, interview_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/exit-interviews/{interview_id}/decline", payload, headers
        )

    def cancel_interview(self, interview_id, headers):
        return self._request(
            "POST", f"/offboarding/exit-interviews/{interview_id}/cancel", None, headers
        )

    # --- KnowledgeTransferPlan / Session ---
    def list_kt_plans(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/knowledge-transfer-plans", headers=headers, params=params)

    def get_kt_plan(self, plan_id, headers):
        return self._request("GET", f"/offboarding/knowledge-transfer-plans/{plan_id}", headers=headers)

    def list_case_kt_plans(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/knowledge-transfer-plans",
            headers=headers, params=params,
        )

    def activate_kt_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/offboarding/knowledge-transfer-plans/{plan_id}/activate", None, headers
        )

    def complete_kt_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/offboarding/knowledge-transfer-plans/{plan_id}/complete", None, headers
        )

    def waive_kt_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/knowledge-transfer-plans/{plan_id}/waive", payload, headers
        )

    def create_kt_session(self, payload, headers):
        return self._request("POST", "/offboarding/knowledge-transfer-sessions", payload, headers)

    def list_kt_sessions(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/knowledge-transfer-sessions", headers=headers, params=params)

    def list_plan_kt_sessions(self, plan_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/knowledge-transfer-plans/{plan_id}/knowledge-transfer-sessions",
            headers=headers, params=params,
        )

    def complete_kt_session(self, session_id, headers):
        return self._request(
            "POST", f"/offboarding/knowledge-transfer-sessions/{session_id}/complete", None, headers
        )

    def cancel_kt_session(self, session_id, headers):
        return self._request(
            "POST", f"/offboarding/knowledge-transfer-sessions/{session_id}/cancel", None, headers
        )

    # --- BenefitsNotice ---
    def create_benefits_notice(self, payload, headers):
        return self._request("POST", "/offboarding/benefits-notices", payload, headers)

    def list_benefits_notices(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/benefits-notices", headers=headers, params=params)

    def get_benefits_notice(self, notice_id, headers):
        return self._request("GET", f"/offboarding/benefits-notices/{notice_id}", headers=headers)

    def list_case_benefits_notices(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/benefits-notices",
            headers=headers, params=params,
        )

    def send_benefits_notice(self, notice_id, headers):
        return self._request("POST", f"/offboarding/benefits-notices/{notice_id}/send", None, headers)

    def acknowledge_benefits_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/offboarding/benefits-notices/{notice_id}/acknowledge", None, headers
        )

    def report_failure_benefits_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/offboarding/benefits-notices/{notice_id}/report-failure", None, headers
        )

    def requeue_benefits_notice(self, notice_id, headers):
        return self._request("POST", f"/offboarding/benefits-notices/{notice_id}/requeue", None, headers)

    def escalate_benefits_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/offboarding/benefits-notices/{notice_id}/escalate", None, headers
        )

    # --- RestrictiveCovenantAck ---
    def create_covenant_ack(self, payload, headers):
        return self._request("POST", "/offboarding/restrictive-covenant-acks", payload, headers)

    def list_covenant_acks(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/restrictive-covenant-acks", headers=headers, params=params)

    def list_case_covenant_acks(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/restrictive-covenant-acks",
            headers=headers, params=params,
        )

    def acknowledge_covenant(self, ack_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/restrictive-covenant-acks/{ack_id}/acknowledge", payload, headers
        )

    def mark_covenant_not_applicable(self, ack_id, headers):
        return self._request(
            "POST", f"/offboarding/restrictive-covenant-acks/{ack_id}/mark-not-applicable", None, headers
        )

    # --- RehireEligibilityReview ---
    def list_rehire_reviews(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/offboarding/rehire-eligibility-reviews", headers=headers, params=params)

    def get_rehire_review(self, review_id, headers):
        return self._request("GET", f"/offboarding/rehire-eligibility-reviews/{review_id}", headers=headers)

    def list_case_rehire_reviews(self, case_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/offboarding/offboarding-cases/{case_id}/rehire-eligibility-reviews",
            headers=headers, params=params,
        )

    def submit_rehire_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/rehire-eligibility-reviews/{review_id}/submit", payload, headers
        )

    def finalize_rehire_review(self, review_id, headers):
        return self._request(
            "POST", f"/offboarding/rehire-eligibility-reviews/{review_id}/finalize", None, headers
        )

    def return_rehire_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/offboarding/rehire-eligibility-reviews/{review_id}/return", payload, headers
        )


api_client = ApiClient()
