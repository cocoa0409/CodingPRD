"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Location ----
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, loc_id, headers):
        return self._request("GET", f"/locations/{loc_id}", headers=headers)

    # ---- Worker ----
    def create_worker(self, loc_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/workers", payload, headers)

    def list_workers(self, loc_id, headers, params=None):
        return self._request("GET", f"/locations/{loc_id}/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/workers/{worker_id}", headers=headers)

    # ---- Availability ----
    def create_availability(self, worker_id, payload, headers):
        return self._request("POST", f"/workers/{worker_id}/availability", payload, headers)

    def list_availability(self, worker_id, headers, params=None):
        return self._request("GET", f"/workers/{worker_id}/availability", headers=headers, params=params)

    # ---- TimeOff ----
    def create_time_off(self, worker_id, payload, headers):
        return self._request("POST", f"/workers/{worker_id}/time-off", payload, headers)

    def list_time_off(self, worker_id, headers, params=None):
        return self._request("GET", f"/workers/{worker_id}/time-off", headers=headers, params=params)

    def approve_time_off(self, loc_id, to_id, headers):
        return self._request("POST", f"/locations/{loc_id}/time-off/{to_id}/approve", {}, headers)

    def deny_time_off(self, loc_id, to_id, headers):
        return self._request("POST", f"/locations/{loc_id}/time-off/{to_id}/deny", {}, headers)

    def cancel_time_off(self, loc_id, to_id, headers):
        return self._request("POST", f"/locations/{loc_id}/time-off/{to_id}/cancel", {}, headers)

    # ---- ShiftTemplate ----
    def create_shift_template(self, loc_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/shift-templates", payload, headers)

    def list_shift_templates(self, loc_id, headers, params=None):
        return self._request("GET", f"/locations/{loc_id}/shift-templates", headers=headers, params=params)

    def generate_shift(self, loc_id, tpl_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/shift-templates/{tpl_id}/generate", payload, headers)

    # ---- Shift ----
    def create_shift(self, loc_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def post_shift(self, loc_id, shift_id, headers):
        return self._request("POST", f"/locations/{loc_id}/shifts/{shift_id}/post", {}, headers)

    def cancel_shift(self, loc_id, shift_id, headers):
        return self._request("POST", f"/locations/{loc_id}/shifts/{shift_id}/cancel", {}, headers)

    def complete_shift(self, loc_id, shift_id, headers):
        return self._request("POST", f"/locations/{loc_id}/shifts/{shift_id}/complete", {}, headers)

    def award_shift(self, loc_id, shift_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/shifts/{shift_id}/award", payload, headers)

    # ---- Assignment ----
    def create_assignment(self, loc_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, asg_id, headers):
        return self._request("GET", f"/assignments/{asg_id}", headers=headers)

    def confirm_assignment(self, loc_id, asg_id, headers):
        return self._request("POST", f"/locations/{loc_id}/assignments/{asg_id}/confirm", {}, headers)

    def cancel_assignment(self, loc_id, asg_id, headers):
        return self._request("POST", f"/locations/{loc_id}/assignments/{asg_id}/cancel", {}, headers)

    def no_show_assignment(self, loc_id, asg_id, headers):
        return self._request("POST", f"/locations/{loc_id}/assignments/{asg_id}/no-show", {}, headers)

    # ---- Open-shift bidding ----
    def create_bid(self, loc_id, shift_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/shifts/{shift_id}/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def withdraw_bid(self, loc_id, bid_id, headers):
        return self._request("POST", f"/locations/{loc_id}/bids/{bid_id}/withdraw", {}, headers)

    # ---- Swap ----
    def create_swap(self, loc_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/swaps", payload, headers)

    def list_swaps(self, headers, params=None):
        return self._request("GET", "/swaps", headers=headers, params=params)

    def get_swap(self, swap_id, headers):
        return self._request("GET", f"/swaps/{swap_id}", headers=headers)

    def counter_swap(self, loc_id, swap_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/swaps/{swap_id}/counter", payload, headers)

    def repropose_swap(self, loc_id, swap_id, headers):
        return self._request("POST", f"/locations/{loc_id}/swaps/{swap_id}/repropose", {}, headers)

    def accept_swap(self, loc_id, swap_id, headers):
        return self._request("POST", f"/locations/{loc_id}/swaps/{swap_id}/accept", {}, headers)

    def reject_swap(self, loc_id, swap_id, headers):
        return self._request("POST", f"/locations/{loc_id}/swaps/{swap_id}/reject", {}, headers)

    def cancel_swap(self, loc_id, swap_id, headers):
        return self._request("POST", f"/locations/{loc_id}/swaps/{swap_id}/cancel", {}, headers)

    def approve_swap(self, loc_id, swap_id, headers):
        return self._request("POST", f"/locations/{loc_id}/swaps/{swap_id}/approve", {}, headers)

    # ---- PayPeriod ----
    def create_pay_period(self, loc_id, payload, headers):
        return self._request("POST", f"/locations/{loc_id}/pay-periods", payload, headers)

    def list_pay_periods(self, loc_id, headers, params=None):
        return self._request("GET", f"/locations/{loc_id}/pay-periods", headers=headers, params=params)

    def get_pay_period(self, pp_id, headers):
        return self._request("GET", f"/pay-periods/{pp_id}", headers=headers)

    def lock_pay_period(self, loc_id, pp_id, headers):
        return self._request("POST", f"/locations/{loc_id}/pay-periods/{pp_id}/lock", {}, headers)

    # ---- Predictability ledger ----
    def list_predictability_ledger(self, headers, params=None):
        return self._request("GET", "/predictability-ledger", headers=headers, params=params)

    def get_predictability_ledger_entry(self, ledger_id, headers):
        return self._request("GET", f"/predictability-ledger/{ledger_id}", headers=headers)


api_client = ApiClient()
