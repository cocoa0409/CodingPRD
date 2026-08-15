"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Enrollments
    # ------------------------------------------------------------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/treasury/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/treasury/enrollments/{enrollment_id}",
                             headers=headers)

    def patch_enrollment(self, enrollment_id, payload, headers):
        return self._request("PATCH", f"/treasury/enrollments/{enrollment_id}",
                             payload, headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/treasury/enrollments/{enrollment_id}/activate",
                             {}, headers)

    def suspend_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/treasury/enrollments/{enrollment_id}/suspend",
                             {}, headers)

    def terminate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/treasury/enrollments/{enrollment_id}/terminate",
                             {}, headers)

    def change_tier(self, enrollment_id, payload, headers):
        return self._request("POST", f"/treasury/enrollments/{enrollment_id}/change-tier",
                             payload, headers)

    def get_adoption_report(self, enrollment_id, headers):
        return self._request("GET",
                             f"/treasury/enrollments/{enrollment_id}/adoption-report",
                             headers=headers)

    def get_fee_statement(self, enrollment_id, period, headers):
        return self._request("GET",
                             f"/treasury/enrollments/{enrollment_id}/fee-statement",
                             headers=headers, params={"period": period})

    # ------------------------------------------------------------------
    # Enrollment users
    # ------------------------------------------------------------------
    def create_enrollment_user(self, payload, headers):
        return self._request("POST", "/treasury/enrollment-users", payload, headers)

    def get_enrollment_user(self, user_id, headers):
        return self._request("GET", f"/treasury/enrollment-users/{user_id}",
                             headers=headers)

    def list_enrollment_users(self, headers, params=None):
        return self._request("GET", "/treasury/enrollment-users",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/treasury/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/treasury/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/treasury/accounts", headers=headers, params=params)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/treasury/accounts/{account_id}/close",
                             {}, headers)

    def clear_review_hold(self, account_id, headers):
        return self._request("POST", f"/treasury/accounts/{account_id}/clear-review-hold",
                             {}, headers)

    # ------------------------------------------------------------------
    # Issue files and issued checks
    # ------------------------------------------------------------------
    def upload_issue_file(self, payload, headers):
        return self._request("POST", "/treasury/issue-files", payload, headers)

    def get_issue_file(self, upload_id, headers):
        return self._request("GET", f"/treasury/issue-files/{upload_id}", headers=headers)

    def list_issue_files(self, headers, params=None):
        return self._request("GET", "/treasury/issue-files", headers=headers, params=params)

    def get_issued_check(self, check_id, headers):
        return self._request("GET", f"/treasury/issued-checks/{check_id}", headers=headers)

    def list_issued_checks(self, headers, params=None):
        return self._request("GET", "/treasury/issued-checks", headers=headers, params=params)

    def void_issued_check(self, check_id, headers):
        return self._request("POST", f"/treasury/issued-checks/{check_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Presented items
    # ------------------------------------------------------------------
    def ingest_presented_item(self, payload, headers):
        return self._request("POST", "/treasury/presented-items", payload, headers)

    def get_presented_item(self, item_id, headers):
        return self._request("GET", f"/treasury/presented-items/{item_id}", headers=headers)

    def list_presented_items(self, headers, params=None):
        return self._request("GET", "/treasury/presented-items", headers=headers, params=params)

    def reverse_presented_item(self, item_id, reason, headers):
        return self._request("POST", f"/treasury/presented-items/{item_id}/reverse",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Exception queue
    # ------------------------------------------------------------------
    def get_exception(self, exception_id, headers):
        return self._request("GET", f"/treasury/exceptions/{exception_id}", headers=headers)

    def list_exceptions(self, headers, params=None):
        return self._request("GET", "/treasury/exceptions", headers=headers, params=params)

    def decide_exception(self, exception_id, decision, headers):
        return self._request("POST", f"/treasury/exceptions/{exception_id}/decision",
                             {"decision": decision}, headers)

    def extend_exception_deadline(self, exception_id, new_deadline_at, headers):
        return self._request("POST",
                             f"/treasury/exceptions/{exception_id}/extend-deadline",
                             {"new_deadline_at": new_deadline_at}, headers)

    # ------------------------------------------------------------------
    # ACH debit rules
    # ------------------------------------------------------------------
    def create_ach_rule(self, payload, headers):
        return self._request("POST", "/treasury/ach-rules", payload, headers)

    def get_ach_rule(self, rule_id, headers):
        return self._request("GET", f"/treasury/ach-rules/{rule_id}", headers=headers)

    def list_ach_rules(self, headers, params=None):
        return self._request("GET", "/treasury/ach-rules", headers=headers, params=params)

    def patch_ach_rule(self, rule_id, payload, headers):
        return self._request("PATCH", f"/treasury/ach-rules/{rule_id}", payload, headers)

    def suspend_ach_rule(self, rule_id, headers):
        return self._request("POST", f"/treasury/ach-rules/{rule_id}/suspend", {}, headers)

    def resume_ach_rule(self, rule_id, headers):
        return self._request("POST", f"/treasury/ach-rules/{rule_id}/resume", {}, headers)

    def retire_ach_rule(self, rule_id, headers):
        return self._request("POST", f"/treasury/ach-rules/{rule_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Liability cases
    # ------------------------------------------------------------------
    def file_liability_case(self, payload, headers):
        return self._request("POST", "/treasury/liability-cases", payload, headers)

    def get_liability_case(self, case_id, headers):
        return self._request("GET", f"/treasury/liability-cases/{case_id}", headers=headers)

    def list_liability_cases(self, headers, params=None):
        return self._request("GET", "/treasury/liability-cases", headers=headers, params=params)

    def start_case_review(self, case_id, headers):
        return self._request("POST", f"/treasury/liability-cases/{case_id}/start-review",
                             {}, headers)

    def resolve_case(self, case_id, resolution, headers):
        return self._request("POST", f"/treasury/liability-cases/{case_id}/resolve",
                             {"resolution": resolution}, headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/treasury/liability-cases/{case_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Fee ledger
    # ------------------------------------------------------------------
    def get_fee_entry(self, entry_id, headers):
        return self._request("GET", f"/treasury/fee-entries/{entry_id}", headers=headers)

    def list_fee_entries(self, headers, params=None):
        return self._request("GET", "/treasury/fee-entries", headers=headers, params=params)

    def waive_fee_entry(self, entry_id, reason, headers):
        return self._request("POST", f"/treasury/fee-entries/{entry_id}/waive",
                             {"reason": reason}, headers)

    def reinstate_fee_entry(self, entry_id, headers):
        return self._request("POST", f"/treasury/fee-entries/{entry_id}/reinstate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Training sessions
    # ------------------------------------------------------------------
    def create_training_session(self, payload, headers):
        return self._request("POST", "/treasury/training-sessions", payload, headers)

    def get_training_session(self, session_id, headers):
        return self._request("GET", f"/treasury/training-sessions/{session_id}",
                             headers=headers)

    def list_training_sessions(self, headers, params=None):
        return self._request("GET", "/treasury/training-sessions",
                             headers=headers, params=params)

    def complete_training_session(self, session_id, attendee_user_ids, headers):
        return self._request("POST",
                             f"/treasury/training-sessions/{session_id}/complete",
                             {"attendee_user_ids": attendee_user_ids}, headers)

    def cancel_training_session(self, session_id, headers):
        return self._request("POST", f"/treasury/training-sessions/{session_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Ops runs
    # ------------------------------------------------------------------
    def create_ops_run(self, payload, headers):
        return self._request("POST", "/treasury/ops-runs", payload, headers)

    def get_ops_run(self, run_id, headers):
        return self._request("GET", f"/treasury/ops-runs/{run_id}", headers=headers)

    def list_ops_runs(self, headers, params=None):
        return self._request("GET", "/treasury/ops-runs", headers=headers, params=params)


api_client = ApiClient()
