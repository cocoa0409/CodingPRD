"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sign-up periods ---------------------------------------------------
    def create_sign_up_period(self, payload, headers):
        return self._request("POST", "/api/sign-up-periods", payload, headers)

    def list_sign_up_periods(self, headers, params=None):
        return self._request("GET", "/api/sign-up-periods", headers=headers, params=params)

    def get_sign_up_period(self, period_id, headers):
        return self._request("GET", f"/api/sign-up-periods/{period_id}", headers=headers)

    def create_run(self, period_id, payload, headers, params=None):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/runs", payload, headers, params=params)

    def list_runs(self, period_id, headers, params=None):
        return self._request("GET", f"/api/sign-up-periods/{period_id}/runs", headers=headers, params=params)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/api/runs/{run_id}", headers=headers)

    def list_run_bid_entries(self, run_id, headers, params=None):
        return self._request("GET", f"/api/runs/{run_id}/bid-entries", headers=headers, params=params)

    def cut_runs(self, period_id, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/cut-runs", {}, headers)

    def post_runs(self, period_id, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/post-runs", {}, headers)

    def open_picking(self, period_id, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/open-picking", {}, headers)

    def adjudicate_next(self, period_id, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/adjudicate-next", {}, headers)

    def lock_sign_up_period(self, period_id, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/lock", {}, headers)

    def implement_sign_up_period(self, period_id, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/implement", {}, headers)

    def create_schedule_revision(self, period_id, payload, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/schedule-revisions", payload, headers)

    def cancel_sign_up_period(self, period_id, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/cancel", {}, headers)

    # --- Operators ----------------------------------------------------------
    def create_operator(self, payload, headers):
        return self._request("POST", "/api/operators", payload, headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", "/api/operators", headers=headers, params=params)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/api/operators/{operator_id}", headers=headers)

    def suspend_operator(self, operator_id, headers):
        return self._request("POST", f"/api/operators/{operator_id}/suspend", {}, headers)

    def reinstate_operator(self, operator_id, headers):
        return self._request("POST", f"/api/operators/{operator_id}/reinstate", {}, headers)

    def retire_operator(self, operator_id, headers):
        return self._request("POST", f"/api/operators/{operator_id}/retire", {}, headers)

    def promote_operator(self, operator_id, headers):
        return self._request("POST", f"/api/operators/{operator_id}/promote", {}, headers)

    def list_operator_runs(self, operator_id, headers, params=None):
        return self._request("GET", f"/api/operators/{operator_id}/runs", headers=headers, params=params)

    def list_operator_bid_entries(self, operator_id, headers, params=None):
        return self._request("GET", f"/api/operators/{operator_id}/bid-entries", headers=headers, params=params)

    def list_operator_extra_board_slots(self, operator_id, headers, params=None):
        return self._request("GET", f"/api/operators/{operator_id}/extra-board-slots", headers=headers, params=params)

    def list_operator_absence_cases(self, operator_id, headers, params=None):
        return self._request("GET", f"/api/operators/{operator_id}/absence-cases", headers=headers, params=params)

    def list_operator_vacation_slots(self, operator_id, headers, params=None):
        return self._request("GET", f"/api/operators/{operator_id}/vacation-slots", headers=headers, params=params)

    def list_operator_grievance_cases(self, operator_id, headers, params=None):
        return self._request("GET", f"/api/operators/{operator_id}/grievance-cases", headers=headers, params=params)

    # --- Bid entries ---------------------------------------------------------
    def create_bid_entry(self, period_id, payload, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/bid-entries", payload, headers)

    def list_bid_entries(self, period_id, headers, params=None):
        return self._request("GET", f"/api/sign-up-periods/{period_id}/bid-entries", headers=headers, params=params)

    def withdraw_bid_entry(self, bid_entry_id, headers):
        return self._request("POST", f"/api/bid-entries/{bid_entry_id}/withdraw", {}, headers)

    # --- Extra board slots ----------------------------------------------------
    def list_extra_board_slots(self, period_id, headers, params=None):
        return self._request("GET", f"/api/sign-up-periods/{period_id}/extra-board-slots", headers=headers, params=params)

    # --- Daily assignments ----------------------------------------------------
    def list_daily_assignments(self, headers, params=None):
        return self._request("GET", "/api/daily-assignments", headers=headers, params=params)

    def get_daily_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/daily-assignments/{assignment_id}", headers=headers)

    def close_out_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/daily-assignments/{assignment_id}/close-out", payload, headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request("POST", f"/api/daily-assignments/{assignment_id}/mark-no-show", {}, headers)

    def finalize_pay(self, assignment_id, headers):
        return self._request("POST", f"/api/daily-assignments/{assignment_id}/finalize-pay", {}, headers)

    def dispute_pay(self, assignment_id, headers):
        return self._request("POST", f"/api/daily-assignments/{assignment_id}/dispute-pay", {}, headers)

    def list_pay_records(self, assignment_id, headers):
        return self._request("GET", f"/api/daily-assignments/{assignment_id}/pay-records", headers=headers)

    # --- Absence cases ---------------------------------------------------------
    def create_absence_case(self, payload, headers):
        return self._request("POST", "/api/absence-cases", payload, headers)

    def list_absence_cases(self, headers, params=None):
        return self._request("GET", "/api/absence-cases", headers=headers, params=params)

    def get_absence_case(self, case_id, headers):
        return self._request("GET", f"/api/absence-cases/{case_id}", headers=headers)

    def cover_absence_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/absence-cases/{case_id}/cover", payload, headers)

    def declare_absence_uncovered(self, case_id, headers):
        return self._request("POST", f"/api/absence-cases/{case_id}/declare-uncovered", {}, headers)

    def close_absence_case(self, case_id, headers):
        return self._request("POST", f"/api/absence-cases/{case_id}/close", {}, headers)

    # --- Vacation slots ---------------------------------------------------------
    def create_vacation_slot(self, period_id, payload, headers):
        return self._request("POST", f"/api/sign-up-periods/{period_id}/vacation-slots", payload, headers)

    def list_vacation_slots(self, period_id, headers, params=None):
        return self._request("GET", f"/api/sign-up-periods/{period_id}/vacation-slots", headers=headers, params=params)

    def grant_vacation_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/api/vacation-slots/{slot_id}/grant", payload, headers)

    def close_vacation_slot(self, slot_id, headers):
        return self._request("POST", f"/api/vacation-slots/{slot_id}/close", {}, headers)

    # --- Grievance cases ---------------------------------------------------------
    def create_grievance_case(self, payload, headers):
        return self._request("POST", "/api/grievance-cases", payload, headers)

    def list_grievance_cases(self, headers, params=None):
        return self._request("GET", "/api/grievance-cases", headers=headers, params=params)

    def get_grievance_case(self, case_id, headers):
        return self._request("GET", f"/api/grievance-cases/{case_id}", headers=headers)

    def uphold_grievance_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/grievance-cases/{case_id}/uphold", payload, headers)

    def dismiss_grievance_case(self, case_id, headers):
        return self._request("POST", f"/api/grievance-cases/{case_id}/dismiss", {}, headers)

    def withdraw_grievance_case(self, case_id, headers):
        return self._request("POST", f"/api/grievance-cases/{case_id}/withdraw", {}, headers)


api_client = ApiClient()
