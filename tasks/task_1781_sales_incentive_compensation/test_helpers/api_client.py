"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # CompProgram
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def close_period(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/close-period",
                             payload, headers)

    def list_payroll_exports(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/payroll-exports",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # CompPlan
    # ------------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def publish_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/publish", {}, headers)

    def revise_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/revise", payload, headers)

    def archive_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/archive", {}, headers)

    def get_plan_effectiveness(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}/effectiveness",
                             headers=headers)

    # ------------------------------------------------------------------
    # Rep
    # ------------------------------------------------------------------
    def create_rep(self, payload, headers):
        return self._request("POST", "/reps", payload, headers)

    def get_rep(self, rep_id, headers):
        return self._request("GET", f"/reps/{rep_id}", headers=headers)

    def update_rep(self, rep_id, payload, headers):
        return self._request("PUT", f"/reps/{rep_id}", payload, headers)

    def list_reps(self, headers, params=None):
        return self._request("GET", "/reps", headers=headers, params=params)

    # ------------------------------------------------------------------
    # PlanAssignment
    # ------------------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}",
                             headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept",
                             {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline",
                             {}, headers)

    def terminate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # SalesTransaction
    # ------------------------------------------------------------------
    def create_transaction(self, payload, headers):
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}",
                             headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers,
                             params=params)

    def cancel_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # CreditEntry
    # ------------------------------------------------------------------
    def get_credit_entry(self, credit_entry_id, headers):
        return self._request("GET", f"/credit-entries/{credit_entry_id}",
                             headers=headers)

    def list_credit_entries(self, headers, params=None):
        return self._request("GET", "/credit-entries", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Adjustment
    # ------------------------------------------------------------------
    def create_adjustment(self, payload, headers):
        return self._request("POST", "/adjustments", payload, headers)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/adjustments/{adjustment_id}",
                             headers=headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/adjustments", headers=headers,
                             params=params)

    def approve_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/approve",
                             {}, headers)

    def reject_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Dispute
    # ------------------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def start_review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/start-review",
                             {}, headers)

    def approve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/approve",
                             payload, headers)

    def reject_dispute(self, dispute_id, headers, note=None):
        payload = {}
        if note is not None:
            payload["note"] = note
        return self._request("POST", f"/disputes/{dispute_id}/reject",
                             payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # PayoutStatement
    # ------------------------------------------------------------------
    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}",
                             headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers,
                             params=params)

    def approve_statement(self, statement_id, headers):
        return self._request("POST", f"/statements/{statement_id}/approve",
                             {}, headers)

    # ------------------------------------------------------------------
    # PayrollExport
    # ------------------------------------------------------------------
    def create_payroll_export(self, payload, headers):
        return self._request("POST", "/payroll-exports", payload, headers)


api_client = ApiClient()
