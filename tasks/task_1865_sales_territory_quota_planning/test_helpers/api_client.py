"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint; sits outside /sales-planning)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Plan years
    # ------------------------------------------------------------------
    def create_plan_year(self, payload, headers):
        return self._request("POST", "/sales-planning/plan-years", payload, headers)

    def list_plan_years(self, headers, params=None):
        return self._request("GET", "/sales-planning/plan-years",
                             headers=headers, params=params)

    def get_plan_year(self, plan_id, headers):
        return self._request("GET", f"/sales-planning/plan-years/{plan_id}",
                             headers=headers)

    def open_plan(self, plan_id, headers):
        return self._request("POST",
                             f"/sales-planning/plan-years/{plan_id}/open",
                             {}, headers)

    def close_submissions(self, plan_id, headers):
        return self._request(
            "POST", f"/sales-planning/plan-years/{plan_id}/close-submissions",
            {}, headers)

    def communicate_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/sales-planning/plan-years/{plan_id}/communicate",
            {}, headers)

    def lock_plan(self, plan_id, headers):
        return self._request("POST",
                             f"/sales-planning/plan-years/{plan_id}/lock",
                             {}, headers)

    def evaluate_assignments(self, plan_id, headers):
        return self._request(
            "POST",
            f"/sales-planning/plan-years/{plan_id}/evaluate-assignments",
            {}, headers)

    def get_coverage_report(self, plan_id, headers):
        return self._request(
            "GET", f"/sales-planning/plan-years/{plan_id}/coverage-report",
            headers=headers)

    def process_dispute_slas(self, plan_id, headers):
        return self._request(
            "POST",
            f"/sales-planning/plan-years/{plan_id}/process-dispute-slas",
            {}, headers)

    # ------------------------------------------------------------------
    # Territories
    # ------------------------------------------------------------------
    def create_territory(self, payload, headers):
        return self._request("POST", "/sales-planning/territories", payload,
                             headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", "/sales-planning/territories",
                             headers=headers, params=params)

    def get_territory(self, territory_id, headers):
        return self._request("GET",
                             f"/sales-planning/territories/{territory_id}",
                             headers=headers)

    def patch_territory(self, territory_id, payload, headers):
        return self._request("PATCH",
                             f"/sales-planning/territories/{territory_id}",
                             payload, headers)

    def activate_territory(self, territory_id, headers):
        return self._request(
            "POST", f"/sales-planning/territories/{territory_id}/activate",
            {}, headers)

    def deactivate_territory(self, territory_id, headers):
        return self._request(
            "POST", f"/sales-planning/territories/{territory_id}/deactivate",
            {}, headers)

    def retire_territory(self, territory_id, headers):
        return self._request(
            "POST", f"/sales-planning/territories/{territory_id}/retire",
            {}, headers)

    # ------------------------------------------------------------------
    # Assignment rules
    # ------------------------------------------------------------------
    def create_assignment_rule(self, payload, headers):
        return self._request("POST", "/sales-planning/assignment-rules",
                             payload, headers)

    def list_assignment_rules(self, headers, params=None):
        return self._request("GET", "/sales-planning/assignment-rules",
                             headers=headers, params=params)

    def get_assignment_rule(self, rule_id, headers):
        return self._request("GET",
                             f"/sales-planning/assignment-rules/{rule_id}",
                             headers=headers)

    def disable_assignment_rule(self, rule_id, headers):
        return self._request(
            "POST", f"/sales-planning/assignment-rules/{rule_id}/disable",
            {}, headers)

    def enable_assignment_rule(self, rule_id, headers):
        return self._request(
            "POST", f"/sales-planning/assignment-rules/{rule_id}/enable",
            {}, headers)

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/sales-planning/accounts", payload,
                             headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/sales-planning/accounts",
                             headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/sales-planning/accounts/{account_id}",
                             headers=headers)

    def patch_account(self, account_id, payload, headers):
        return self._request("PATCH",
                             f"/sales-planning/accounts/{account_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Sales reps
    # ------------------------------------------------------------------
    def create_rep(self, payload, headers):
        return self._request("POST", "/sales-planning/reps", payload, headers)

    def get_rep(self, rep_id, headers):
        return self._request("GET", f"/sales-planning/reps/{rep_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Ramp schedules
    # ------------------------------------------------------------------
    def create_ramp_schedule(self, payload, headers):
        return self._request("POST", "/sales-planning/ramp-schedules", payload,
                             headers)

    def get_ramp_schedule(self, schedule_id, headers):
        return self._request("GET",
                             f"/sales-planning/ramp-schedules/{schedule_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Rep assignments
    # ------------------------------------------------------------------
    def create_rep_assignment(self, payload, headers):
        return self._request("POST", "/sales-planning/rep-assignments",
                             payload, headers)

    def list_rep_assignments(self, headers, params=None):
        return self._request("GET", "/sales-planning/rep-assignments",
                             headers=headers, params=params)

    def get_rep_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/sales-planning/rep-assignments/{assignment_id}",
            headers=headers)

    def end_rep_assignment(self, assignment_id, effective_to, headers):
        return self._request(
            "POST", f"/sales-planning/rep-assignments/{assignment_id}/end",
            {"effective_to": effective_to}, headers)

    # ------------------------------------------------------------------
    # Top-down allocations
    # ------------------------------------------------------------------
    def create_allocation(self, payload, headers):
        return self._request("POST", "/sales-planning/allocations", payload,
                             headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/sales-planning/allocations",
                             headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET",
                             f"/sales-planning/allocations/{allocation_id}",
                             headers=headers)

    def apply_allocation(self, allocation_id, expected_plan_year_version,
                         headers):
        return self._request(
            "POST", f"/sales-planning/allocations/{allocation_id}/apply",
            {"expected_plan_year_version": expected_plan_year_version},
            headers)

    def discard_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/sales-planning/allocations/{allocation_id}/discard",
            {}, headers)

    # ------------------------------------------------------------------
    # Bottom-up submissions
    # ------------------------------------------------------------------
    def create_submission(self, payload, headers):
        return self._request("POST", "/sales-planning/submissions", payload,
                             headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/sales-planning/submissions",
                             headers=headers, params=params)

    def get_submission(self, submission_id, headers):
        return self._request("GET",
                             f"/sales-planning/submissions/{submission_id}",
                             headers=headers)

    def withdraw_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/sales-planning/submissions/{submission_id}/withdraw",
            {}, headers)

    # ------------------------------------------------------------------
    # Reconciliation runs
    # ------------------------------------------------------------------
    def create_reconciliation_run(self, payload, headers):
        return self._request("POST", "/sales-planning/reconciliation-runs",
                             payload, headers)

    def list_reconciliation_runs(self, headers, params=None):
        return self._request("GET", "/sales-planning/reconciliation-runs",
                             headers=headers, params=params)

    def get_reconciliation_run(self, run_id, headers):
        return self._request(
            "GET", f"/sales-planning/reconciliation-runs/{run_id}",
            headers=headers)

    def apply_reconciliation_run(self, run_id, expected_plan_year_version,
                                 headers):
        return self._request(
            "POST",
            f"/sales-planning/reconciliation-runs/{run_id}/apply",
            {"expected_plan_year_version": expected_plan_year_version},
            headers)

    def discard_reconciliation_run(self, run_id, headers):
        return self._request(
            "POST", f"/sales-planning/reconciliation-runs/{run_id}/discard",
            {}, headers)

    # ------------------------------------------------------------------
    # Territory change requests
    # ------------------------------------------------------------------
    def create_change_request(self, payload, headers):
        return self._request("POST", "/sales-planning/change-requests",
                             payload, headers)

    def list_change_requests(self, headers, params=None):
        return self._request("GET", "/sales-planning/change-requests",
                             headers=headers, params=params)

    def get_change_request(self, request_id, headers):
        return self._request("GET",
                             f"/sales-planning/change-requests/{request_id}",
                             headers=headers)

    def approve_change_request(self, request_id, expected_plan_year_version,
                               headers):
        return self._request(
            "POST", f"/sales-planning/change-requests/{request_id}/approve",
            {"expected_plan_year_version": expected_plan_year_version},
            headers)

    def reject_change_request(self, request_id, headers, rejection_reason=None):
        payload = {}
        if rejection_reason is not None:
            payload["rejection_reason"] = rejection_reason
        return self._request(
            "POST", f"/sales-planning/change-requests/{request_id}/reject",
            payload, headers)

    def return_change_request(self, request_id, headers, return_reason=None):
        payload = {}
        if return_reason is not None:
            payload["return_reason"] = return_reason
        return self._request(
            "POST", f"/sales-planning/change-requests/{request_id}/return",
            payload, headers)

    def cancel_change_request(self, request_id, headers):
        return self._request(
            "POST", f"/sales-planning/change-requests/{request_id}/cancel",
            {}, headers)

    def apply_change_request(self, request_id, headers):
        return self._request(
            "POST", f"/sales-planning/change-requests/{request_id}/apply",
            {}, headers)

    # ------------------------------------------------------------------
    # Credit events
    # ------------------------------------------------------------------
    def create_credit_event(self, payload, headers):
        return self._request("POST", "/sales-planning/credit-events", payload,
                             headers)

    def list_credit_events(self, headers, params=None):
        return self._request("GET", "/sales-planning/credit-events",
                             headers=headers, params=params)

    def get_credit_event(self, event_id, headers):
        return self._request("GET",
                             f"/sales-planning/credit-events/{event_id}",
                             headers=headers)

    def reverse_credit_event(self, event_id, headers):
        return self._request(
            "POST", f"/sales-planning/credit-events/{event_id}/reverse",
            {}, headers)

    # ------------------------------------------------------------------
    # Ownership disputes
    # ------------------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/sales-planning/disputes", payload,
                             headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/sales-planning/disputes",
                             headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/sales-planning/disputes/{dispute_id}",
                             headers=headers)

    def start_dispute_review(self, dispute_id, headers):
        return self._request(
            "POST", f"/sales-planning/disputes/{dispute_id}/start-review",
            {}, headers)

    def resolve_dispute(self, dispute_id, resolution, headers, note=None):
        payload = {"resolution": resolution}
        if note is not None:
            payload["note"] = note
        return self._request(
            "POST", f"/sales-planning/disputes/{dispute_id}/resolve",
            payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/sales-planning/disputes/{dispute_id}/withdraw",
            {}, headers)


api_client = ApiClient()
