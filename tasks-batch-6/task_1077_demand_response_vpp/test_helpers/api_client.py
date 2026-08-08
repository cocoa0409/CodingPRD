"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving logical clock) ---
    def set_clock(self, iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": iso8601}, headers=headers)

    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/dr/programs", payload, headers=headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/dr/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/dr/programs", headers=headers, params=params)

    def update_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/dr/programs/{program_id}", payload, headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/dr/programs/{program_id}/activate", {}, headers=headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/dr/programs/{program_id}/close", {}, headers=headers)

    # --- Aggregator ---
    def create_aggregator(self, payload, headers):
        return self._request("POST", "/dr/aggregators", payload, headers=headers)

    def get_aggregator(self, aggregator_id, headers):
        return self._request("GET", f"/dr/aggregators/{aggregator_id}", headers=headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/dr/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/dr/customers/{customer_id}", headers=headers)

    # --- Device ---
    def create_device(self, payload, headers):
        return self._request("POST", "/dr/devices", payload, headers=headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/dr/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/dr/devices", headers=headers, params=params)

    def decommission_device(self, device_id, headers):
        return self._request("POST", f"/dr/devices/{device_id}/decommission", {}, headers=headers)

    def create_meter_reading(self, device_id, payload, headers):
        return self._request("POST", f"/dr/devices/{device_id}/meter-readings", payload, headers=headers)

    def list_device_meter_readings(self, device_id, headers, params=None):
        return self._request("GET", f"/dr/devices/{device_id}/meter-readings", headers=headers, params=params)

    def get_meter_reading(self, reading_id, headers):
        return self._request("GET", f"/dr/meter-readings/{reading_id}", headers=headers)

    def list_meter_readings(self, headers, params=None):
        return self._request("GET", "/dr/meter-readings", headers=headers, params=params)

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/dr/enrollments", payload, headers=headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/dr/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/dr/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/dr/enrollments/{enrollment_id}/activate", {}, headers=headers)

    def opt_out_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/dr/enrollments/{enrollment_id}/opt-out", {}, headers=headers)

    def re_enroll_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/dr/enrollments/{enrollment_id}/re-enroll", {}, headers=headers)

    def terminate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/dr/enrollments/{enrollment_id}/terminate", {}, headers=headers)

    # --- DispatchEvent ---
    def create_dispatch_event(self, payload, headers):
        return self._request("POST", "/dr/dispatch-events", payload, headers=headers)

    def get_dispatch_event(self, event_id, headers):
        return self._request("GET", f"/dr/dispatch-events/{event_id}", headers=headers)

    def list_dispatch_events(self, headers, params=None):
        return self._request("GET", "/dr/dispatch-events", headers=headers, params=params)

    def notify_dispatch_event(self, event_id, headers):
        return self._request("POST", f"/dr/dispatch-events/{event_id}/notify", {}, headers=headers)

    def start_dispatch_event(self, event_id, headers):
        return self._request("POST", f"/dr/dispatch-events/{event_id}/start", {}, headers=headers)

    def complete_dispatch_event(self, event_id, headers):
        return self._request("POST", f"/dr/dispatch-events/{event_id}/complete", {}, headers=headers)

    def cancel_dispatch_event(self, event_id, headers):
        return self._request("POST", f"/dr/dispatch-events/{event_id}/cancel", {}, headers=headers)

    def list_event_dispatches(self, event_id, headers, params=None):
        return self._request("GET", f"/dr/dispatch-events/{event_id}/dispatches", headers=headers, params=params)

    def get_event_settlement(self, event_id, headers):
        return self._request("GET", f"/dr/dispatch-events/{event_id}/settlement", headers=headers)

    # --- Dispatch ---
    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/dr/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/dr/dispatches", headers=headers, params=params)

    def acknowledge_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dr/dispatches/{dispatch_id}/acknowledge", {}, headers=headers)

    def start_curtailment(self, dispatch_id, headers):
        return self._request("POST", f"/dr/dispatches/{dispatch_id}/start-curtailment", {}, headers=headers)

    def override_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dr/dispatches/{dispatch_id}/override", {}, headers=headers)

    # --- Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/dr/settlements", payload, headers=headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/dr/settlements/{settlement_id}", headers=headers)

    def submit_settlement(self, settlement_id, headers):
        return self._request("POST", f"/dr/settlements/{settlement_id}/submit", {}, headers=headers)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/dr/settlements/{settlement_id}/approve", {}, headers=headers)

    def dispute_settlement(self, settlement_id, headers):
        return self._request("POST", f"/dr/settlements/{settlement_id}/dispute", {}, headers=headers)

    def revise_settlement(self, settlement_id, headers):
        return self._request("POST", f"/dr/settlements/{settlement_id}/revise", {}, headers=headers)

    def mark_paid_settlement(self, settlement_id, headers):
        return self._request("POST", f"/dr/settlements/{settlement_id}/mark-paid", {}, headers=headers)

    def list_settlement_payments(self, settlement_id, headers, params=None):
        return self._request("GET", f"/dr/settlements/{settlement_id}/payments", headers=headers, params=params)

    # --- Payment ---
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/dr/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/dr/payments", headers=headers, params=params)


api_client = ApiClient()
