"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/vms/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/vms/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/vms/programs", headers=headers, params=params)

    def advance_clock(self, program_id, payload, headers):
        return self._request("POST", f"/vms/programs/{program_id}/advance_clock", payload, headers)

    def set_clock(self, program_id, payload, headers):
        return self._request("POST", f"/vms/programs/{program_id}/_clock/set", payload, headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/vms/programs/{program_id}/suspend", {}, headers)

    # --- Supplier ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/vms/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/vms/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/vms/suppliers", headers=headers, params=params)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/vms/suppliers/{supplier_id}/suspend", {}, headers)

    # --- WorkerProfile ---
    def create_worker(self, payload, headers):
        return self._request("POST", "/vms/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/vms/workers/{worker_id}", headers=headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/vms/workers", headers=headers, params=params)

    # --- Requisition ---
    def create_requisition(self, payload, headers):
        return self._request("POST", "/vms/requisitions", payload, headers)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/vms/requisitions/{requisition_id}", headers=headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/vms/requisitions", headers=headers, params=params)

    def distribute_requisition(self, requisition_id, payload, headers):
        return self._request("POST", f"/vms/requisitions/{requisition_id}/distribute", payload, headers)

    def close_requisition(self, requisition_id, headers):
        return self._request("POST", f"/vms/requisitions/{requisition_id}/close", {}, headers)

    def cancel_requisition(self, requisition_id, headers):
        return self._request("POST", f"/vms/requisitions/{requisition_id}/cancel", {}, headers)

    # --- Distribution ---
    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/vms/distributions/{distribution_id}", headers=headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/vms/distributions", headers=headers, params=params)

    # --- Submittal ---
    def create_submittal(self, payload, headers):
        return self._request("POST", "/vms/submittals", payload, headers)

    def get_submittal(self, submittal_id, headers):
        return self._request("GET", f"/vms/submittals/{submittal_id}", headers=headers)

    def list_submittals(self, headers, params=None):
        return self._request("GET", "/vms/submittals", headers=headers, params=params)

    def shortlist_submittal(self, submittal_id, headers):
        return self._request("POST", f"/vms/submittals/{submittal_id}/shortlist", {}, headers)

    def start_interview(self, submittal_id, headers):
        return self._request("POST", f"/vms/submittals/{submittal_id}/start_interview", {}, headers)

    def propose_rate(self, submittal_id, payload, headers):
        return self._request("POST", f"/vms/submittals/{submittal_id}/propose_rate", payload, headers)

    def counter_rate(self, submittal_id, headers):
        return self._request("POST", f"/vms/submittals/{submittal_id}/counter_rate", {}, headers)

    def offer_submittal(self, submittal_id, headers):
        return self._request("POST", f"/vms/submittals/{submittal_id}/offer", {}, headers)

    def hire_submittal(self, submittal_id, payload, headers):
        return self._request("POST", f"/vms/submittals/{submittal_id}/hire", payload, headers)

    def reject_submittal(self, submittal_id, headers):
        return self._request("POST", f"/vms/submittals/{submittal_id}/reject", {}, headers)

    def withdraw_submittal(self, submittal_id, headers):
        return self._request("POST", f"/vms/submittals/{submittal_id}/withdraw", {}, headers)

    # --- Assignment ---
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/vms/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/vms/assignments", headers=headers, params=params)

    def hold_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vms/assignments/{assignment_id}/hold", {}, headers)

    def resume_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vms/assignments/{assignment_id}/resume", {}, headers)

    def offboard_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vms/assignments/{assignment_id}/offboard", {}, headers)

    # --- Timesheet ---
    def create_timesheet(self, payload, headers):
        return self._request("POST", "/vms/timesheets", payload, headers)

    def get_timesheet(self, timesheet_id, headers):
        return self._request("GET", f"/vms/timesheets/{timesheet_id}", headers=headers)

    def list_timesheets(self, headers, params=None):
        return self._request("GET", "/vms/timesheets", headers=headers, params=params)

    def submit_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/vms/timesheets/{timesheet_id}/submit", {}, headers)

    def approve_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/vms/timesheets/{timesheet_id}/approve", {}, headers)

    def reject_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/vms/timesheets/{timesheet_id}/reject", {}, headers)

    def reopen_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/vms/timesheets/{timesheet_id}/reopen", {}, headers)

    def invoice_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/vms/timesheets/{timesheet_id}/invoice", {}, headers)

    # --- Expense ---
    def create_expense(self, payload, headers):
        return self._request("POST", "/vms/expenses", payload, headers)

    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/vms/expenses/{expense_id}", headers=headers)

    def list_expenses(self, headers, params=None):
        return self._request("GET", "/vms/expenses", headers=headers, params=params)

    def submit_expense(self, expense_id, headers):
        return self._request("POST", f"/vms/expenses/{expense_id}/submit", {}, headers)

    def approve_expense(self, expense_id, headers):
        return self._request("POST", f"/vms/expenses/{expense_id}/approve", {}, headers)

    def reject_expense(self, expense_id, headers):
        return self._request("POST", f"/vms/expenses/{expense_id}/reject", {}, headers)

    def reopen_expense(self, expense_id, headers):
        return self._request("POST", f"/vms/expenses/{expense_id}/reopen", {}, headers)

    def invoice_expense(self, expense_id, headers):
        return self._request("POST", f"/vms/expenses/{expense_id}/invoice", {}, headers)

    # --- StatementOfWork ---
    def create_sow(self, payload, headers):
        return self._request("POST", "/vms/statements-of-work", payload, headers)

    def get_sow(self, sow_id, headers):
        return self._request("GET", f"/vms/statements-of-work/{sow_id}", headers=headers)

    def list_sows(self, headers, params=None):
        return self._request("GET", "/vms/statements-of-work", headers=headers, params=params)

    def activate_sow(self, sow_id, headers):
        return self._request("POST", f"/vms/statements-of-work/{sow_id}/activate", {}, headers)

    def close_sow(self, sow_id, headers):
        return self._request("POST", f"/vms/statements-of-work/{sow_id}/close", {}, headers)

    def cancel_sow(self, sow_id, headers):
        return self._request("POST", f"/vms/statements-of-work/{sow_id}/cancel", {}, headers)

    # --- Milestone ---
    def create_milestone(self, payload, headers):
        return self._request("POST", "/vms/milestones", payload, headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/vms/milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/vms/milestones", headers=headers, params=params)

    def start_milestone(self, milestone_id, headers):
        return self._request("POST", f"/vms/milestones/{milestone_id}/start", {}, headers)

    def submit_milestone(self, milestone_id, headers):
        return self._request("POST", f"/vms/milestones/{milestone_id}/submit", {}, headers)

    def accept_milestone(self, milestone_id, headers):
        return self._request("POST", f"/vms/milestones/{milestone_id}/accept", {}, headers)

    def reject_milestone(self, milestone_id, headers):
        return self._request("POST", f"/vms/milestones/{milestone_id}/reject", {}, headers)

    def invoice_milestone(self, milestone_id, headers):
        return self._request("POST", f"/vms/milestones/{milestone_id}/invoice", {}, headers)


api_client = ApiClient()
