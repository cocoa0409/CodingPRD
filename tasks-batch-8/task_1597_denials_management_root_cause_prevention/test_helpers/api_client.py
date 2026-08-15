"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/rcm/_clock/set_current_utc", payload, headers)

    # --- Payers ---
    def create_payer(self, payload, headers):
        return self._request("POST", "/rcm/payers", payload, headers)

    def list_payers(self, headers, params=None):
        return self._request("GET", "/rcm/payers", headers=headers, params=params)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/rcm/payers/{payer_id}", headers=headers)

    def update_payer(self, payer_id, payload, headers):
        return self._request("PATCH", f"/rcm/payers/{payer_id}", payload, headers)

    # --- Payer appeal policies ---
    def create_payer_appeal_policy(self, payload, headers):
        return self._request("POST", "/rcm/payer-appeal-policies", payload, headers)

    def list_payer_appeal_policies(self, headers, params=None):
        return self._request("GET", "/rcm/payer-appeal-policies", headers=headers, params=params)

    def get_payer_appeal_policy(self, policy_id, headers):
        return self._request("GET", f"/rcm/payer-appeal-policies/{policy_id}", headers=headers)

    # --- Remittance codes ---
    def create_remittance_code(self, payload, headers):
        return self._request("POST", "/rcm/remittance-codes", payload, headers)

    def list_remittance_codes(self, headers, params=None):
        return self._request("GET", "/rcm/remittance-codes", headers=headers, params=params)

    # --- Denial cases ---
    def create_denial_case(self, payload, headers):
        return self._request("POST", "/rcm/denial-cases", payload, headers)

    def list_denial_cases(self, headers, params=None):
        return self._request("GET", "/rcm/denial-cases", headers=headers, params=params)

    def get_denial_case(self, denial_id, headers):
        return self._request("GET", f"/rcm/denial-cases/{denial_id}", headers=headers)

    def correct_denial_case(self, denial_id, payload, headers):
        return self._request("PATCH", f"/rcm/denial-cases/{denial_id}", payload, headers)

    def triage_denial(self, denial_id, payload, headers):
        return self._request("POST", f"/rcm/denial-cases/{denial_id}/triage", payload, headers)

    def assign_denial(self, denial_id, payload, headers):
        return self._request("POST", f"/rcm/denial-cases/{denial_id}/assign", payload, headers)

    def get_recovery_projection(self, denial_id, headers, params=None):
        return self._request(
            "GET", f"/rcm/denial-cases/{denial_id}/recovery-projection",
            headers=headers, params=params,
        )

    def get_work_queue(self, headers, params=None):
        return self._request("GET", "/rcm/work-queue", headers=headers, params=params)

    # --- Appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/rcm/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/rcm/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/rcm/appeals/{appeal_id}", headers=headers)

    def generate_letter(self, appeal_id, headers):
        return self._request("POST", f"/rcm/appeals/{appeal_id}/generate-letter", {}, headers)

    def revise_appeal(self, appeal_id, headers):
        return self._request("POST", f"/rcm/appeals/{appeal_id}/revise", {}, headers)

    def submit_appeal(self, appeal_id, headers):
        return self._request("POST", f"/rcm/appeals/{appeal_id}/submit", {}, headers)

    def record_outcome(self, appeal_id, payload, headers):
        return self._request("POST", f"/rcm/appeals/{appeal_id}/record-outcome", payload, headers)

    def reverse_outcome(self, appeal_id, payload, headers):
        return self._request("POST", f"/rcm/appeals/{appeal_id}/reverse-outcome", payload, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/rcm/appeals/{appeal_id}/withdraw", {}, headers)

    # --- Appeal attachments ---
    def create_appeal_attachment(self, payload, headers):
        return self._request("POST", "/rcm/appeal-attachments", payload, headers)

    def list_appeal_attachments(self, headers, params=None):
        return self._request("GET", "/rcm/appeal-attachments", headers=headers, params=params)

    def get_appeal_attachment(self, attachment_id, headers):
        return self._request("GET", f"/rcm/appeal-attachments/{attachment_id}", headers=headers)

    def void_appeal_attachment(self, attachment_id, payload, headers):
        return self._request("POST", f"/rcm/appeal-attachments/{attachment_id}/void", payload, headers)

    # --- Root-cause tasks ---
    def create_root_cause_task(self, payload, headers):
        return self._request("POST", "/rcm/root-cause-tasks", payload, headers)

    def list_root_cause_tasks(self, headers, params=None):
        return self._request("GET", "/rcm/root-cause-tasks", headers=headers, params=params)

    def get_root_cause_task(self, task_id, headers):
        return self._request("GET", f"/rcm/root-cause-tasks/{task_id}", headers=headers)

    def acknowledge_task(self, task_id, headers):
        return self._request("POST", f"/rcm/root-cause-tasks/{task_id}/acknowledge", {}, headers)

    def implement_fix(self, task_id, payload, headers):
        return self._request("POST", f"/rcm/root-cause-tasks/{task_id}/implement-fix", payload, headers)

    def verify_task(self, task_id, headers):
        return self._request("POST", f"/rcm/root-cause-tasks/{task_id}/verify", {}, headers)

    def close_task(self, task_id, headers):
        return self._request("POST", f"/rcm/root-cause-tasks/{task_id}/close", {}, headers)

    # --- Write-off requests ---
    def create_write_off_request(self, payload, headers):
        return self._request("POST", "/rcm/write-off-requests", payload, headers)

    def list_write_off_requests(self, headers, params=None):
        return self._request("GET", "/rcm/write-off-requests", headers=headers, params=params)

    def get_write_off_request(self, request_id, headers):
        return self._request("GET", f"/rcm/write-off-requests/{request_id}", headers=headers)

    def approve_write_off(self, request_id, headers):
        return self._request("POST", f"/rcm/write-off-requests/{request_id}/approve", {}, headers)

    def reject_write_off(self, request_id, payload, headers):
        return self._request("POST", f"/rcm/write-off-requests/{request_id}/reject", payload, headers)

    def revise_write_off(self, request_id, payload, headers):
        return self._request("POST", f"/rcm/write-off-requests/{request_id}/revise", payload, headers)

    def rescind_write_off(self, request_id, payload, headers):
        return self._request("POST", f"/rcm/write-off-requests/{request_id}/rescind", payload, headers)

    # --- Department scorecards ---
    def create_department_scorecard(self, payload, headers):
        return self._request("POST", "/rcm/department-scorecards", payload, headers)

    def list_department_scorecards(self, headers, params=None):
        return self._request("GET", "/rcm/department-scorecards", headers=headers, params=params)

    def get_department_scorecard(self, scorecard_id, headers):
        return self._request("GET", f"/rcm/department-scorecards/{scorecard_id}", headers=headers)

    def finalize_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"/rcm/department-scorecards/{scorecard_id}/finalize", {}, headers)

    # --- Prevention programs ---
    def create_prevention_program(self, payload, headers):
        return self._request("POST", "/rcm/prevention-programs", payload, headers)

    def list_prevention_programs(self, headers, params=None):
        return self._request("GET", "/rcm/prevention-programs", headers=headers, params=params)

    def get_prevention_program(self, program_id, headers):
        return self._request("GET", f"/rcm/prevention-programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/rcm/prevention-programs/{program_id}/activate", {}, headers)

    def complete_program(self, program_id, headers):
        return self._request("POST", f"/rcm/prevention-programs/{program_id}/complete", {}, headers)

    # --- Analytics ---
    def get_overturn_rates(self, headers, params=None):
        return self._request("GET", "/rcm/analytics/overturn-rates", headers=headers, params=params)

    # --- Audit events ---
    def list_denial_events(self, headers, params=None):
        return self._request("GET", "/rcm/denial-events", headers=headers, params=params)

    def get_denial_event(self, event_id, headers):
        return self._request("GET", f"/rcm/denial-events/{event_id}", headers=headers)


api_client = ApiClient()
