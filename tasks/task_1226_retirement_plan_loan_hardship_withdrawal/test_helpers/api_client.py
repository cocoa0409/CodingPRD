"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def update_plan_policy(self, plan_id, payload, headers):
        return self._request("PUT", f"/plans/{plan_id}/policy", payload, headers)

    def freeze_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/freeze", {}, headers)

    def unfreeze_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/unfreeze", {}, headers)

    def list_plan_participants(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/plans/{plan_id}/participants", headers=headers, params=params
        )

    def list_plan_loans(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/plans/{plan_id}/loans", headers=headers, params=params
        )

    def list_plan_hardship_requests(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/plans/{plan_id}/hardship-requests", headers=headers, params=params
        )

    def list_plan_approval_tasks(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/plans/{plan_id}/approval-tasks", headers=headers, params=params
        )

    def list_plan_audit_events(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/plans/{plan_id}/audit-events", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def create_participant(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def patch_participant(self, participant_id, payload, headers):
        return self._request(
            "PATCH", f"/participants/{participant_id}", payload, headers
        )

    def put_contribution_election(self, participant_id, payload, headers):
        return self._request(
            "PUT", f"/participants/{participant_id}/contribution-election", payload, headers
        )

    def get_contribution_election(self, participant_id, headers):
        return self._request(
            "GET", f"/participants/{participant_id}/contribution-election", headers=headers
        )

    def restart_contribution_election(self, participant_id, headers):
        return self._request(
            "POST",
            f"/participants/{participant_id}/contribution-election/restart",
            {},
            headers,
        )

    def get_loan_eligibility(self, participant_id, headers):
        return self._request(
            "GET", f"/participants/{participant_id}/loan-eligibility", headers=headers
        )

    # ------------------------------------------------------------------
    # Loans
    # ------------------------------------------------------------------
    def create_loan(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/loans", payload, headers)

    def list_participant_loans(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/participants/{participant_id}/loans", headers=headers, params=params
        )

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def withdraw_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/withdraw", {}, headers)

    def disburse_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/disburse", {}, headers)

    def refinance_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/refinance", payload, headers)

    def rebuild_loan_schedule(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/schedule/rebuild", payload, headers
        )

    def list_loan_installments(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/installments", headers=headers, params=params
        )

    def list_loan_refinances(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/refinances", headers=headers, params=params
        )

    def list_loan_approval_tasks(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/approval-tasks", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Payroll remittances
    # ------------------------------------------------------------------
    def create_remittance(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/remittances", payload, headers
        )

    def list_participant_remittances(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/remittances",
            headers=headers,
            params=params,
        )

    def reverse_remittance(self, remittance_id, headers):
        return self._request("POST", f"/remittances/{remittance_id}/reverse", {}, headers)

    # ------------------------------------------------------------------
    # Hardship requests
    # ------------------------------------------------------------------
    def create_hardship_request(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/hardship-requests", payload, headers
        )

    def list_participant_hardship_requests(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/hardship-requests",
            headers=headers,
            params=params,
        )

    def get_hardship_request(self, request_id, headers):
        return self._request("GET", f"/hardship-requests/{request_id}", headers=headers)

    def upload_hardship_document(self, request_id, payload, headers):
        return self._request(
            "POST", f"/hardship-requests/{request_id}/documents", payload, headers
        )

    def list_hardship_documents(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"/hardship-requests/{request_id}/documents",
            headers=headers,
            params=params,
        )

    def withdraw_hardship_request(self, request_id, headers):
        return self._request(
            "POST", f"/hardship-requests/{request_id}/withdraw", {}, headers
        )

    def pay_hardship_request(self, request_id, headers):
        return self._request("POST", f"/hardship-requests/{request_id}/pay", {}, headers)

    def list_hardship_approval_tasks(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"/hardship-requests/{request_id}/approval-tasks",
            headers=headers,
            params=params,
        )

    def get_hardship_suspension_record(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"/hardship-requests/{request_id}/suspension-record",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Approval tasks
    # ------------------------------------------------------------------
    def get_approval_task(self, task_id, headers):
        return self._request("GET", f"/approval-tasks/{task_id}", headers=headers)

    def decide_approval_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/approval-tasks/{task_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Tax events
    # ------------------------------------------------------------------
    def list_participant_tax_events(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/tax-events",
            headers=headers,
            params=params,
        )

    def get_tax_event(self, tax_event_id, headers):
        return self._request("GET", f"/tax-events/{tax_event_id}", headers=headers)

    def mark_tax_event_reported(self, tax_event_id, headers):
        return self._request(
            "POST", f"/tax-events/{tax_event_id}/mark-reported", {}, headers
        )

    # ------------------------------------------------------------------
    # Suspension records
    # ------------------------------------------------------------------
    def list_participant_suspension_records(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/suspension-records",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
# Under per-test-server isolation the runner kills and re-spawns the server on
# the same port before every test. A session-scoped client that pools keep-alive
# connections would otherwise reuse a dead socket against the next process and
# flake with RemoteDisconnected; forcing Connection: close sidesteps that race.
api_client.session.headers["Connection"] = "close"
