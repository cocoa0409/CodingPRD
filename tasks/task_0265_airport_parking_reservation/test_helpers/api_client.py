"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() is inherited and
handles the success/error envelope, headers, and base URL.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customers ───────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/reinstate", headers=headers)

    def list_customer_reservations(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/reservations",
                             headers=headers, params=params)

    def list_customer_vehicles(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/vehicles",
                             headers=headers, params=params)

    # ─── Vehicles ────────────────────────────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    # ─── Lots ────────────────────────────────────────────────────────────────
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def list_lot_rate_plans(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/rate-plans", headers=headers, params=params)

    def list_lot_cancellation_policies(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/cancellation-policies",
                             headers=headers, params=params)

    def list_lot_stall_holds(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/stall-holds", headers=headers, params=params)

    def list_lot_shuttle_trips(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/shuttle-trips", headers=headers, params=params)

    # ─── Rate Plans ──────────────────────────────────────────────────────────
    def create_rate_plan(self, payload, headers):
        return self._request("POST", "/rate-plans", payload, headers)

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request("GET", f"/rate-plans/{rate_plan_id}", headers=headers)

    def retire_rate_plan(self, rate_plan_id, headers):
        return self._request("POST", f"/rate-plans/{rate_plan_id}/retire", headers=headers)

    # ─── Cancellation Policies ───────────────────────────────────────────────
    def create_cancellation_policy(self, payload, headers):
        return self._request("POST", "/cancellation-policies", payload, headers)

    # ─── Shuttle Trips ───────────────────────────────────────────────────────
    def create_shuttle_trip(self, payload, headers):
        return self._request("POST", "/shuttle-trips", payload, headers)

    def get_shuttle_trip(self, trip_id, headers):
        return self._request("GET", f"/shuttle-trips/{trip_id}", headers=headers)

    def open_boarding_shuttle_trip(self, trip_id, headers):
        return self._request("POST", f"/shuttle-trips/{trip_id}/open-boarding", headers=headers)

    def depart_shuttle_trip(self, trip_id, headers):
        return self._request("POST", f"/shuttle-trips/{trip_id}/depart", headers=headers)

    def cancel_shuttle_trip(self, trip_id, headers):
        return self._request("POST", f"/shuttle-trips/{trip_id}/cancel", headers=headers)

    # ─── Reservations ────────────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def list_reservation_payment_txns(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/payment-txns",
                             headers=headers, params=params)

    def list_reservation_stall_holds(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/stall-holds",
                             headers=headers, params=params)

    def assign_shuttle(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/assign-shuttle",
                             payload, headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", headers=headers)

    def gate_exit_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/gate-exit", headers=headers)

    def gate_reentry_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/gate-reentry", headers=headers)

    def check_out_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-out", headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", headers=headers)

    def mark_no_show(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/mark-no-show", headers=headers)

    # ─── Clock (test-driving) ────────────────────────────────────────────────
    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
