"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/api/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/api/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/api/employees/{employee_id}", headers=headers)

    def lay_off_employee(self, employee_id, headers):
        return self._request("POST", f"/api/employees/{employee_id}/lay-off", {}, headers)

    def mark_up_employee(self, employee_id, headers):
        return self._request("POST", f"/api/employees/{employee_id}/mark-up", {}, headers)

    def return_from_leave(self, employee_id, headers):
        return self._request("POST", f"/api/employees/{employee_id}/return-from-leave", {}, headers)

    def suspend_employee(self, employee_id, headers):
        return self._request("POST", f"/api/employees/{employee_id}/suspend", {}, headers)

    def reinstate_employee(self, employee_id, headers):
        return self._request("POST", f"/api/employees/{employee_id}/reinstate", {}, headers)

    # --- extra boards / slots ---
    def create_extra_board(self, payload, headers):
        return self._request("POST", "/api/extra-boards", payload, headers)

    def get_extra_board(self, board_id, headers):
        return self._request("GET", f"/api/extra-boards/{board_id}", headers=headers)

    def list_board_slots(self, board_id, headers, params=None):
        return self._request("GET", f"/api/extra-boards/{board_id}/slots", headers=headers, params=params)

    def create_board_slot(self, board_id, payload, headers):
        return self._request("POST", f"/api/extra-boards/{board_id}/slots", payload, headers)

    def list_extra_board_slots(self, headers, params=None):
        return self._request("GET", "/api/extra-board-slots", headers=headers, params=params)

    def get_extra_board_slot(self, slot_id, headers):
        return self._request("GET", f"/api/extra-board-slots/{slot_id}", headers=headers)

    # --- jobs ---
    def create_job(self, payload, headers):
        return self._request("POST", "/api/jobs", payload, headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/api/jobs", headers=headers, params=params)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/api/jobs/{job_id}", headers=headers)

    # --- calls ---
    def issue_call(self, job_id, headers):
        return self._request("POST", f"/api/jobs/{job_id}/calls", {}, headers)

    def list_job_calls(self, job_id, headers, params=None):
        return self._request("GET", f"/api/jobs/{job_id}/calls", headers=headers, params=params)

    def list_calls(self, headers, params=None):
        return self._request("GET", "/api/calls", headers=headers, params=params)

    def get_call(self, call_id, headers):
        return self._request("GET", f"/api/calls/{call_id}", headers=headers)

    def accept_call(self, call_id, payload, headers):
        return self._request("POST", f"/api/calls/{call_id}/accept", payload, headers)

    def decline_call(self, call_id, headers):
        return self._request("POST", f"/api/calls/{call_id}/decline", {}, headers)

    def no_answer_call(self, call_id, headers):
        return self._request("POST", f"/api/calls/{call_id}/no-answer", {}, headers)

    def rescind_call(self, call_id, headers):
        return self._request("POST", f"/api/calls/{call_id}/rescind", {}, headers)

    # --- assignments ---
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/api/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/assignments/{assignment_id}", headers=headers)

    def assignment_on_duty(self, assignment_id, headers):
        return self._request("POST", f"/api/assignments/{assignment_id}/on-duty", {}, headers)

    def assignment_tie_up(self, assignment_id, headers):
        return self._request("POST", f"/api/assignments/{assignment_id}/tie-up", {}, headers)

    def assignment_lay_off(self, assignment_id, headers):
        return self._request("POST", f"/api/assignments/{assignment_id}/lay-off", {}, headers)

    def assignment_complete(self, assignment_id, headers):
        return self._request("POST", f"/api/assignments/{assignment_id}/complete", {}, headers)

    # --- rest periods ---
    def list_rest_periods(self, headers, params=None):
        return self._request("GET", "/api/rest-periods", headers=headers, params=params)

    def get_rest_period(self, rest_period_id, headers):
        return self._request("GET", f"/api/rest-periods/{rest_period_id}", headers=headers)

    # --- leave bids ---
    def create_leave_bid(self, payload, headers):
        return self._request("POST", "/api/leave-bids", payload, headers)

    def list_leave_bids(self, headers, params=None):
        return self._request("GET", "/api/leave-bids", headers=headers, params=params)

    def get_leave_bid(self, bid_id, headers):
        return self._request("GET", f"/api/leave-bids/{bid_id}", headers=headers)

    def award_leave_bid(self, bid_id, headers):
        return self._request("POST", f"/api/leave-bids/{bid_id}/award", {}, headers)

    def deny_leave_bid(self, bid_id, headers):
        return self._request("POST", f"/api/leave-bids/{bid_id}/deny", {}, headers)

    def cancel_leave_bid(self, bid_id, headers):
        return self._request("POST", f"/api/leave-bids/{bid_id}/cancel", {}, headers)

    # --- pay records ---
    def create_pay_record(self, payload, headers):
        return self._request("POST", "/api/pay-records", payload, headers)

    def list_pay_records(self, headers, params=None):
        return self._request("GET", "/api/pay-records", headers=headers, params=params)

    def get_pay_record(self, pay_record_id, headers):
        return self._request("GET", f"/api/pay-records/{pay_record_id}", headers=headers)

    def submit_pay_record(self, pay_record_id, headers):
        return self._request("POST", f"/api/pay-records/{pay_record_id}/submit", {}, headers)

    def dispute_pay_record(self, pay_record_id, headers):
        return self._request("POST", f"/api/pay-records/{pay_record_id}/dispute", {}, headers)

    def resubmit_pay_record(self, pay_record_id, payload, headers):
        return self._request("POST", f"/api/pay-records/{pay_record_id}/resubmit", payload, headers)

    def finalize_pay_record(self, pay_record_id, payload, headers):
        return self._request("POST", f"/api/pay-records/{pay_record_id}/finalize", payload, headers)

    # --- crew shortages ---
    def declare_crew_shortage(self, job_id, headers):
        return self._request("POST", f"/api/jobs/{job_id}/crew-shortages", {}, headers)

    def begin_recrew(self, shortage_id, headers):
        return self._request("POST", f"/api/crew-shortages/{shortage_id}/begin-recrew", {}, headers)

    def resolve_crew_shortage(self, shortage_id, payload, headers):
        return self._request("POST", f"/api/crew-shortages/{shortage_id}/resolve", payload, headers)

    def escalate_crew_shortage(self, shortage_id, headers):
        return self._request("POST", f"/api/crew-shortages/{shortage_id}/escalate", {}, headers)

    def list_crew_shortages(self, headers, params=None):
        return self._request("GET", "/api/crew-shortages", headers=headers, params=params)

    def get_crew_shortage(self, shortage_id, headers):
        return self._request("GET", f"/api/crew-shortages/{shortage_id}", headers=headers)


api_client = ApiClient()
