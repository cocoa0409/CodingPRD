"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

CC = "/central-casting"


class ApiClient(GenericApiClient):
    # --- productions ---
    def create_production(self, payload, headers):
        return self._request("POST", f"{CC}/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", f"{CC}/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"{CC}/productions/{production_id}", headers=headers)

    def activate_production(self, production_id, headers):
        return self._request(
            "POST", f"{CC}/productions/{production_id}/activate", {}, headers
        )

    def wrap_production(self, production_id, headers):
        return self._request("POST", f"{CC}/productions/{production_id}/wrap", {}, headers)

    # --- actors ---
    def create_actor(self, payload, headers):
        return self._request("POST", f"{CC}/actors", payload, headers)

    def list_actors(self, headers, params=None):
        return self._request("GET", f"{CC}/actors", headers=headers, params=params)

    def get_actor(self, actor_id, headers):
        return self._request("GET", f"{CC}/actors/{actor_id}", headers=headers)

    def verify_actor(self, actor_id, headers):
        return self._request("POST", f"{CC}/actors/{actor_id}/verify", {}, headers)

    def suspend_actor(self, actor_id, headers):
        return self._request("POST", f"{CC}/actors/{actor_id}/suspend", {}, headers)

    def reinstate_actor(self, actor_id, headers):
        return self._request("POST", f"{CC}/actors/{actor_id}/reinstate", {}, headers)

    # --- casting calls ---
    def create_casting_call(self, payload, headers):
        return self._request("POST", f"{CC}/casting-calls", payload, headers)

    def list_casting_calls(self, headers, params=None):
        return self._request("GET", f"{CC}/casting-calls", headers=headers, params=params)

    def get_casting_call(self, call_id, headers):
        return self._request("GET", f"{CC}/casting-calls/{call_id}", headers=headers)

    def publish_casting_call(self, call_id, headers):
        return self._request("POST", f"{CC}/casting-calls/{call_id}/publish", {}, headers)

    def lock_casting_call(self, call_id, headers):
        return self._request("POST", f"{CC}/casting-calls/{call_id}/lock", {}, headers)

    def start_shooting(self, call_id, headers):
        return self._request(
            "POST", f"{CC}/casting-calls/{call_id}/start-shooting", {}, headers
        )

    def wrap_casting_call(self, call_id, headers):
        return self._request("POST", f"{CC}/casting-calls/{call_id}/wrap", {}, headers)

    def cancel_casting_call(self, call_id, payload, headers):
        return self._request("POST", f"{CC}/casting-calls/{call_id}/cancel", payload, headers)

    # --- look requirements ---
    def create_look_requirement(self, payload, headers):
        return self._request("POST", f"{CC}/look-requirements", payload, headers)

    def list_look_requirements(self, headers, params=None):
        return self._request("GET", f"{CC}/look-requirements", headers=headers, params=params)

    def get_look_requirement(self, requirement_id, headers):
        return self._request(
            "GET", f"{CC}/look-requirements/{requirement_id}", headers=headers
        )

    # --- holding areas ---
    def create_holding_area(self, payload, headers):
        return self._request("POST", f"{CC}/holding-areas", payload, headers)

    def list_holding_areas(self, headers, params=None):
        return self._request("GET", f"{CC}/holding-areas", headers=headers, params=params)

    def get_holding_area(self, area_id, headers):
        return self._request("GET", f"{CC}/holding-areas/{area_id}", headers=headers)

    # --- bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", f"{CC}/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{CC}/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{CC}/bookings/{booking_id}", headers=headers)

    def accept_booking(self, booking_id, headers):
        return self._request("POST", f"{CC}/bookings/{booking_id}/accept", {}, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"{CC}/bookings/{booking_id}/decline", {}, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"{CC}/bookings/{booking_id}/cancel", payload, headers)

    def check_in_booking(self, booking_id, payload, headers):
        return self._request("POST", f"{CC}/bookings/{booking_id}/check-in", payload, headers)

    def mark_no_show(self, booking_id, headers):
        return self._request("POST", f"{CC}/bookings/{booking_id}/mark-no-show", {}, headers)

    def wrap_out_booking(self, booking_id, headers):
        return self._request("POST", f"{CC}/bookings/{booking_id}/wrap-out", {}, headers)

    # --- time events ---
    def create_time_event(self, payload, headers):
        return self._request("POST", f"{CC}/time-events", payload, headers)

    def list_time_events(self, headers, params=None):
        return self._request("GET", f"{CC}/time-events", headers=headers, params=params)

    def get_time_event(self, event_id, headers):
        return self._request("GET", f"{CC}/time-events/{event_id}", headers=headers)

    # --- vouchers ---
    def list_vouchers(self, headers, params=None):
        return self._request("GET", f"{CC}/vouchers", headers=headers, params=params)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"{CC}/vouchers/{voucher_id}", headers=headers)

    def get_voucher_estimate(self, voucher_id, headers):
        return self._request("GET", f"{CC}/vouchers/{voucher_id}/estimate", headers=headers)

    def issue_voucher(self, voucher_id, headers):
        return self._request("POST", f"{CC}/vouchers/{voucher_id}/issue", {}, headers)

    def dispute_voucher(self, voucher_id, payload, headers):
        return self._request("POST", f"{CC}/vouchers/{voucher_id}/dispute", payload, headers)

    def adjust_voucher(self, voucher_id, payload, headers):
        return self._request("POST", f"{CC}/vouchers/{voucher_id}/adjust", payload, headers)

    # --- bump adjustments ---
    def create_bump_adjustment(self, payload, headers):
        return self._request("POST", f"{CC}/bump-adjustments", payload, headers)

    def list_bump_adjustments(self, headers, params=None):
        return self._request("GET", f"{CC}/bump-adjustments", headers=headers, params=params)

    def get_bump_adjustment(self, bump_id, headers):
        return self._request("GET", f"{CC}/bump-adjustments/{bump_id}", headers=headers)

    def approve_bump(self, bump_id, headers):
        return self._request("POST", f"{CC}/bump-adjustments/{bump_id}/approve", {}, headers)

    def reject_bump(self, bump_id, headers):
        return self._request("POST", f"{CC}/bump-adjustments/{bump_id}/reject", {}, headers)

    # --- payroll batches ---
    def create_payroll_batch(self, payload, headers):
        return self._request("POST", f"{CC}/payroll-batches", payload, headers)

    def list_payroll_batches(self, headers, params=None):
        return self._request("GET", f"{CC}/payroll-batches", headers=headers, params=params)

    def get_payroll_batch(self, batch_id, headers):
        return self._request("GET", f"{CC}/payroll-batches/{batch_id}", headers=headers)

    def add_batch_item(self, batch_id, payload, headers):
        return self._request("POST", f"{CC}/payroll-batches/{batch_id}/items", payload, headers)

    def remove_batch_item(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{CC}/payroll-batches/{batch_id}/remove-item", payload, headers
        )

    def submit_batch(self, batch_id, headers):
        return self._request("POST", f"{CC}/payroll-batches/{batch_id}/submit", {}, headers)

    def acknowledge_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{CC}/payroll-batches/{batch_id}/acknowledge", payload, headers
        )

    # --- replacement cases ---
    def list_replacement_cases(self, headers, params=None):
        return self._request(
            "GET", f"{CC}/replacement-cases", headers=headers, params=params
        )

    def get_replacement_case(self, case_id, headers):
        return self._request("GET", f"{CC}/replacement-cases/{case_id}", headers=headers)

    def offer_next(self, case_id, headers):
        return self._request(
            "POST", f"{CC}/replacement-cases/{case_id}/offer-next", {}, headers
        )

    def expire_case(self, case_id, headers):
        return self._request("POST", f"{CC}/replacement-cases/{case_id}/expire", {}, headers)

    # --- standby entries ---
    def create_standby_entry(self, payload, headers):
        return self._request("POST", f"{CC}/standby-entries", payload, headers)

    def list_standby_entries(self, headers, params=None):
        return self._request("GET", f"{CC}/standby-entries", headers=headers, params=params)

    def get_standby_entry(self, entry_id, headers):
        return self._request("GET", f"{CC}/standby-entries/{entry_id}", headers=headers)

    def withdraw_standby_entry(self, entry_id, headers):
        return self._request(
            "POST", f"{CC}/standby-entries/{entry_id}/withdraw", {}, headers
        )

    # --- ratio waivers ---
    def create_ratio_waiver(self, payload, headers):
        return self._request("POST", f"{CC}/ratio-waivers", payload, headers)

    def list_ratio_waivers(self, headers, params=None):
        return self._request("GET", f"{CC}/ratio-waivers", headers=headers, params=params)

    def get_ratio_waiver(self, waiver_id, headers):
        return self._request("GET", f"{CC}/ratio-waivers/{waiver_id}", headers=headers)

    def approve_waiver(self, waiver_id, headers):
        return self._request("POST", f"{CC}/ratio-waivers/{waiver_id}/approve", {}, headers)

    def deny_waiver(self, waiver_id, headers):
        return self._request("POST", f"{CC}/ratio-waivers/{waiver_id}/deny", {}, headers)

    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
