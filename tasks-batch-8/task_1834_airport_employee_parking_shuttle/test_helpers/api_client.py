"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- ParkingProgram ---
    def create_program(self, payload, headers=None):
        return self._request("POST", "/parking/programs", payload, headers)

    def get_program(self, program_id, headers=None):
        return self._request("GET", f"/parking/programs/{program_id}", headers=headers)

    def set_program_posture(self, program_id, posture, headers=None):
        return self._request(
            "POST", f"/parking/programs/{program_id}/posture",
            {"posture": posture}, headers,
        )

    def run_program_ops(self, program_id, headers=None):
        return self._request(
            "POST", f"/parking/programs/{program_id}/run-ops", {}, headers
        )

    def get_program_cost_report(self, program_id, headers=None):
        return self._request(
            "GET", f"/parking/programs/{program_id}/cost-report", headers=headers
        )

    # --- Employee ---
    def create_employee(self, payload, headers=None):
        return self._request("POST", "/parking/employees", payload, headers)

    def get_employee(self, employee_id, headers=None):
        return self._request("GET", f"/parking/employees/{employee_id}", headers=headers)

    def list_employees(self, headers=None, params=None):
        return self._request("GET", "/parking/employees", headers=headers, params=params)

    def terminate_employee(self, employee_id, headers=None):
        return self._request(
            "POST", f"/parking/employees/{employee_id}/terminate", {}, headers
        )

    # --- ParkingLot ---
    def create_lot(self, payload, headers=None):
        return self._request("POST", "/parking/lots", payload, headers)

    def get_lot(self, lot_id, headers=None):
        return self._request("GET", f"/parking/lots/{lot_id}", headers=headers)

    def list_lots(self, headers=None, params=None):
        return self._request("GET", "/parking/lots", headers=headers, params=params)

    def patch_lot(self, lot_id, payload, headers=None):
        return self._request("PATCH", f"/parking/lots/{lot_id}", payload, headers)

    # --- Permit / PermitRenewal ---
    def create_permit(self, payload, headers=None):
        return self._request("POST", "/parking/permits", payload, headers)

    def get_permit(self, permit_id, headers=None):
        return self._request("GET", f"/parking/permits/{permit_id}", headers=headers)

    def list_permits(self, headers=None, params=None):
        return self._request("GET", "/parking/permits", headers=headers, params=params)

    def permit_event(self, permit_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/permits/{permit_id}/events", payload, headers
        )

    def create_permit_renewal(self, permit_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/permits/{permit_id}/renewals", payload, headers
        )

    def list_permit_renewals(self, permit_id, headers=None, params=None):
        return self._request(
            "GET", f"/parking/permits/{permit_id}/renewals",
            headers=headers, params=params,
        )

    def decide_renewal(self, renewal_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/renewals/{renewal_id}/decide", payload, headers
        )

    # --- ShuttleRoute / ShuttleTrip ---
    def create_route(self, payload, headers=None):
        return self._request("POST", "/parking/routes", payload, headers)

    def get_route(self, route_id, headers=None):
        return self._request("GET", f"/parking/routes/{route_id}", headers=headers)

    def list_routes(self, headers=None, params=None):
        return self._request("GET", "/parking/routes", headers=headers, params=params)

    def route_event(self, route_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/routes/{route_id}/events", payload, headers
        )

    def get_route_service_level(self, route_id, headers=None, params=None):
        return self._request(
            "GET", f"/parking/routes/{route_id}/service-level",
            headers=headers, params=params,
        )

    def create_trip(self, payload, headers=None):
        return self._request("POST", "/parking/trips", payload, headers)

    def get_trip(self, trip_id, headers=None):
        return self._request("GET", f"/parking/trips/{trip_id}", headers=headers)

    def list_trips(self, headers=None, params=None):
        return self._request("GET", "/parking/trips", headers=headers, params=params)

    def trip_event(self, trip_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/trips/{trip_id}/events", payload, headers
        )

    # --- ServiceChangeNotice ---
    def create_notice(self, payload, headers=None):
        return self._request("POST", "/parking/notices", payload, headers)

    def get_notice(self, notice_id, headers=None):
        return self._request("GET", f"/parking/notices/{notice_id}", headers=headers)

    def list_notices(self, headers=None, params=None):
        return self._request("GET", "/parking/notices", headers=headers, params=params)

    def notice_event(self, notice_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/notices/{notice_id}/events", payload, headers
        )

    # --- Violation ---
    def create_violation(self, payload, headers=None):
        return self._request("POST", "/parking/violations", payload, headers)

    def get_violation(self, violation_id, headers=None):
        return self._request("GET", f"/parking/violations/{violation_id}", headers=headers)

    def list_violations(self, headers=None, params=None):
        return self._request("GET", "/parking/violations", headers=headers, params=params)

    def violation_event(self, violation_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/violations/{violation_id}/events", payload, headers
        )

    # --- TowEvent ---
    def create_tow_event(self, payload, headers=None):
        return self._request("POST", "/parking/tow-events", payload, headers)

    def get_tow_event(self, tow_event_id, headers=None):
        return self._request("GET", f"/parking/tow-events/{tow_event_id}", headers=headers)

    def list_tow_events(self, headers=None, params=None):
        return self._request("GET", "/parking/tow-events", headers=headers, params=params)

    def tow_event_action(self, tow_event_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/tow-events/{tow_event_id}/events", payload, headers
        )

    # --- BillingCycle / ChargeEntry ---
    def create_billing_cycle(self, payload, headers=None):
        return self._request("POST", "/parking/billing-cycles", payload, headers)

    def get_billing_cycle(self, cycle_id, headers=None):
        return self._request("GET", f"/parking/billing-cycles/{cycle_id}", headers=headers)

    def list_billing_cycles(self, headers=None, params=None):
        return self._request(
            "GET", "/parking/billing-cycles", headers=headers, params=params
        )

    def close_billing_cycle(self, cycle_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/billing-cycles/{cycle_id}/close", payload, headers
        )

    def billing_cycle_event(self, cycle_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/billing-cycles/{cycle_id}/events", payload, headers
        )

    def create_charge_entry(self, payload, headers=None):
        return self._request("POST", "/parking/charge-entries", payload, headers)

    def get_charge_entry(self, entry_id, headers=None):
        return self._request("GET", f"/parking/charge-entries/{entry_id}", headers=headers)

    def list_charge_entries(self, headers=None, params=None):
        return self._request(
            "GET", "/parking/charge-entries", headers=headers, params=params
        )

    def settle_charge_entry(self, entry_id, payload, headers=None):
        return self._request(
            "POST", f"/parking/charge-entries/{entry_id}/settle", payload, headers
        )

    # --- PeakWindow ---
    def create_peak_window(self, payload, headers=None):
        return self._request("POST", "/parking/peak-windows", payload, headers)

    def get_peak_window(self, peak_window_id, headers=None):
        return self._request(
            "GET", f"/parking/peak-windows/{peak_window_id}", headers=headers
        )

    def list_peak_windows(self, headers=None, params=None):
        return self._request(
            "GET", "/parking/peak-windows", headers=headers, params=params
        )

    def cancel_peak_window(self, peak_window_id, headers=None):
        return self._request(
            "POST", f"/parking/peak-windows/{peak_window_id}/cancel", {}, headers
        )


api_client = ApiClient()
