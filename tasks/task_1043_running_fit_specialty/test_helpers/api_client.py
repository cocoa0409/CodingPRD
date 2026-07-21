"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Stores ----
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def list_store_staff(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/staff", headers=headers, params=params)

    # ---- Staff ----
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def get_member_loyalty(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/loyalty", headers=headers)

    def list_member_subscriptions(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/subscriptions", headers=headers, params=params)

    def create_subscription(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/subscription", payload, headers)

    # ---- Subscriptions ----
    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def activate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/activate", headers=headers)

    def renew_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/renew", payload, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    # ---- Products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def adjust_inventory(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/inventory-adjustments", payload, headers)

    # ---- Fitting appointments ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/fitting-appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/fitting-appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/fitting-appointments", headers=headers, params=params)

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/fitting-appointments/{appointment_id}/complete", payload, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/fitting-appointments/{appointment_id}/cancel", headers=headers)

    # ---- Training sessions ----
    def create_session(self, payload, headers):
        return self._request("POST", "/training-sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/training-sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/training-sessions", headers=headers, params=params)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/training-sessions/{session_id}/cancel", headers=headers)

    def create_enrollment(self, session_id, payload, headers):
        return self._request("POST", f"/training-sessions/{session_id}/enrollments", payload, headers)

    # ---- Session enrollments ----
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/session-enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/session-enrollments", headers=headers, params=params)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/session-enrollments/{enrollment_id}/cancel", headers=headers)

    # ---- Race events ----
    def create_event(self, payload, headers):
        return self._request("POST", "/race-events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/race-events/{event_id}", headers=headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/race-events/{event_id}/close", headers=headers)

    def create_registration(self, event_id, payload, headers):
        return self._request("POST", f"/race-events/{event_id}/registrations", payload, headers)

    # ---- Race registrations ----
    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/race-registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/race-registrations", headers=headers, params=params)

    def pay_registration(self, registration_id, headers):
        return self._request("POST", f"/race-registrations/{registration_id}/pay", headers=headers)

    def allocate_registration(self, registration_id, headers):
        return self._request("POST", f"/race-registrations/{registration_id}/allocate", headers=headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/race-registrations/{registration_id}/cancel", headers=headers)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def place_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/place", headers=headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    def return_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/return", payload, headers)

    # ---- Shoe pairs ----
    def create_shoe_pair(self, payload, headers):
        return self._request("POST", "/shoe-pairs", payload, headers)

    def get_shoe_pair(self, shoe_pair_id, headers):
        return self._request("GET", f"/shoe-pairs/{shoe_pair_id}", headers=headers)

    def list_shoe_pairs(self, headers, params=None):
        return self._request("GET", "/shoe-pairs", headers=headers, params=params)

    def add_run_log(self, shoe_pair_id, payload, headers):
        return self._request("POST", f"/shoe-pairs/{shoe_pair_id}/run-logs", payload, headers)


api_client = ApiClient()
