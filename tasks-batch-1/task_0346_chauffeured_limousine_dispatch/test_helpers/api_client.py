"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- CorporateAccount ----
    def create_corporate_account(self, payload, headers):
        return self._request("POST", "/corporate-accounts", payload, headers=headers)

    def get_corporate_account(self, account_id, headers):
        return self._request("GET", f"/corporate-accounts/{account_id}", headers=headers)

    def suspend_corporate_account(self, account_id, headers):
        return self._request("POST", f"/corporate-accounts/{account_id}/suspend", {}, headers=headers)

    # ---- Affiliate ----
    def create_affiliate(self, payload, headers):
        return self._request("POST", "/affiliates", payload, headers=headers)

    def get_affiliate(self, affiliate_id, headers):
        return self._request("GET", f"/affiliates/{affiliate_id}", headers=headers)

    def suspend_affiliate(self, affiliate_id, headers):
        return self._request("POST", f"/affiliates/{affiliate_id}/suspend", {}, headers=headers)

    # ---- VehicleClass ----
    def create_vehicle_class(self, payload, headers):
        return self._request("POST", "/vehicle-classes", payload, headers=headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers=headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ---- Chauffeur ----
    def create_chauffeur(self, payload, headers):
        return self._request("POST", "/chauffeurs", payload, headers=headers)

    def get_chauffeur(self, chauffeur_id, headers):
        return self._request("GET", f"/chauffeurs/{chauffeur_id}", headers=headers)

    def create_duty_event(self, chauffeur_id, payload, headers):
        return self._request("POST", f"/chauffeurs/{chauffeur_id}/duty-events", payload, headers=headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def create_trip_event(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/trip-events", payload, headers=headers)

    def create_wait_event(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/wait-events", payload, headers=headers)

    def list_wait_events(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/wait-events", headers=headers, params=params)

    def create_billing_event(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/billing-events", payload, headers=headers)

    def get_cancellation_record(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/cancellation-record", headers=headers, params=params)

    # ---- Assignment ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers=headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    # ---- FarmOutOrder ----
    def create_farm_out_order(self, payload, headers):
        return self._request("POST", "/farm-out-orders", payload, headers=headers)

    def get_farm_out_order(self, order_id, headers):
        return self._request("GET", f"/farm-out-orders/{order_id}", headers=headers)

    def list_farm_out_orders(self, headers, params=None):
        return self._request("GET", "/farm-out-orders", headers=headers, params=params)

    def create_decision_event(self, order_id, payload, headers):
        return self._request("POST", f"/farm-out-orders/{order_id}/decision-events", payload, headers=headers)

    # ---- FlightTracking ----
    def create_flight_tracking(self, payload, headers):
        return self._request("POST", "/flight-trackings", payload, headers=headers)

    def list_flight_trackings(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/flight-trackings", headers=headers, params=params)

    def create_flight_update(self, flight_tracking_id, payload, headers):
        return self._request("POST", f"/flight-trackings/{flight_tracking_id}/flight-updates", payload, headers=headers)

    # ---- Deterministic clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
