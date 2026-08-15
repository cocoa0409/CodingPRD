"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Driver ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def patch_driver(self, driver_id, payload, headers):
        return self._request("PATCH", f"/drivers/{driver_id}", payload, headers)

    def suspend_driver(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/suspend", {}, headers)

    def reinstate_driver(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/reinstate", {}, headers)

    def terminate_driver(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/terminate", {}, headers)

    def get_hos_status(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}/hos-status", headers=headers)

    def list_duty_events(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/duty-events",
                             headers=headers, params=params)

    def create_duty_event(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/duty-events", payload, headers)

    def list_safety_events(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/safety-events",
                             headers=headers, params=params)

    def create_safety_event(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/safety-events", payload, headers)

    def get_safety_event(self, safety_event_id, headers):
        return self._request("GET", f"/safety-events/{safety_event_id}", headers=headers)

    def void_safety_event(self, safety_event_id, headers):
        return self._request("POST", f"/safety-events/{safety_event_id}/void", {}, headers)

    def list_driver_fuel_purchases(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/fuel-purchases",
                             headers=headers, params=params)

    def list_driver_settlements(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/settlements",
                             headers=headers, params=params)

    # --- Tractor ---
    def create_tractor(self, payload, headers):
        return self._request("POST", "/tractors", payload, headers)

    def list_tractors(self, headers, params=None):
        return self._request("GET", "/tractors", headers=headers, params=params)

    def get_tractor(self, tractor_id, headers):
        return self._request("GET", f"/tractors/{tractor_id}", headers=headers)

    def out_of_service_tractor(self, tractor_id, headers):
        return self._request("POST", f"/tractors/{tractor_id}/out-of-service", {}, headers)

    def return_to_service_tractor(self, tractor_id, headers):
        return self._request("POST", f"/tractors/{tractor_id}/return-to-service", {}, headers)

    def list_tractor_trips(self, tractor_id, headers, params=None):
        return self._request("GET", f"/tractors/{tractor_id}/trips",
                             headers=headers, params=params)

    # --- CustomerAccount ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def credit_hold_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-hold", {}, headers)

    def release_credit_hold_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/release-credit-hold",
                             {}, headers)

    def list_customer_loads(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/loads",
                             headers=headers, params=params)

    # --- Lane ---
    def create_lane(self, payload, headers):
        return self._request("POST", "/lanes", payload, headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/lanes", headers=headers, params=params)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/lanes/{lane_id}", headers=headers)

    # --- StateFuelRate ---
    def create_state_fuel_rate(self, payload, headers):
        return self._request("POST", "/state-fuel-rates", payload, headers)

    def list_state_fuel_rates(self, headers, params=None):
        return self._request("GET", "/state-fuel-rates", headers=headers, params=params)

    def get_state_fuel_rate(self, rate_id, headers):
        return self._request("GET", f"/state-fuel-rates/{rate_id}", headers=headers)

    # --- Load ---
    def create_load(self, payload, headers):
        return self._request("POST", "/loads", payload, headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/loads", headers=headers, params=params)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/loads/{load_id}", headers=headers)

    def screen_load(self, load_id, headers):
        return self._request("POST", f"/loads/{load_id}/screen", {}, headers)

    def accept_load(self, load_id, headers):
        return self._request("POST", f"/loads/{load_id}/accept", {}, headers)

    def reject_load(self, load_id, headers):
        return self._request("POST", f"/loads/{load_id}/reject", {}, headers)

    def cancel_load(self, load_id, headers):
        return self._request("POST", f"/loads/{load_id}/cancel", {}, headers)

    def get_load_margin(self, load_id, headers):
        return self._request("GET", f"/loads/{load_id}/margin", headers=headers)

    def list_load_trips(self, load_id, headers, params=None):
        return self._request("GET", f"/loads/{load_id}/trips", headers=headers, params=params)

    def list_load_accessorials(self, load_id, headers, params=None):
        return self._request("GET", f"/loads/{load_id}/accessorials",
                             headers=headers, params=params)

    def create_load_accessorial(self, load_id, payload, headers):
        return self._request("POST", f"/loads/{load_id}/accessorials", payload, headers)

    def get_load_invoice(self, load_id, headers):
        return self._request("GET", f"/loads/{load_id}/invoice", headers=headers)

    def create_load_invoice(self, load_id, headers):
        return self._request("POST", f"/loads/{load_id}/invoice", {}, headers)

    # --- Trip ---
    def create_trip(self, payload, headers):
        return self._request("POST", "/trips", payload, headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trips", headers=headers, params=params)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def patch_trip(self, trip_id, payload, headers):
        return self._request("PATCH", f"/trips/{trip_id}", payload, headers)

    def dispatch_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/dispatch", {}, headers)

    def cancel_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/cancel", payload, headers)

    def get_trip_eta(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}/eta", headers=headers)

    def get_trip_fuel_plan(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}/fuel-plan", headers=headers)

    def list_trip_check_calls(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/check-calls",
                             headers=headers, params=params)

    def create_trip_check_call(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/check-calls", payload, headers)

    def list_trip_duty_events(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/duty-events",
                             headers=headers, params=params)

    def list_trip_accessorials(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/accessorials",
                             headers=headers, params=params)

    def create_trip_fuel_purchase(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/fuel-purchases", payload, headers)

    def list_trip_fuel_purchases(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/fuel-purchases",
                             headers=headers, params=params)

    # --- AccessorialCharge (flat actions) ---
    def get_accessorial(self, accessorial_id, headers):
        return self._request("GET", f"/accessorials/{accessorial_id}", headers=headers)

    def submit_accessorial(self, accessorial_id, headers):
        return self._request("POST", f"/accessorials/{accessorial_id}/submit", {}, headers)

    def approve_accessorial(self, accessorial_id, headers):
        return self._request("POST", f"/accessorials/{accessorial_id}/approve", {}, headers)

    def dispute_accessorial(self, accessorial_id, headers):
        return self._request("POST", f"/accessorials/{accessorial_id}/dispute", {}, headers)

    def reject_accessorial(self, accessorial_id, headers):
        return self._request("POST", f"/accessorials/{accessorial_id}/reject", {}, headers)

    # --- Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def recalculate_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/recalculate",
                             payload, headers)

    def submit_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/submit", {}, headers)

    def reject_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/reject", {}, headers)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/approve", {}, headers)

    def mark_settlement_paid(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/mark-paid", {}, headers)

    # --- Invoice ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark-paid", {}, headers)

    # --- Dispatch ---
    def get_backhaul_candidates(self, headers, params=None):
        return self._request("GET", "/dispatch/backhaul-candidates",
                             headers=headers, params=params)


api_client = ApiClient()
