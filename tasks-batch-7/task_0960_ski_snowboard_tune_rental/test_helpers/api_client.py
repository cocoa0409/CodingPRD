"""API client: one method per endpoint defined in the PRD (Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/shop/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/shop/customers/{customer_id}", headers=headers)

    # --- equipment ---
    def create_equipment_item(self, payload, headers):
        return self._request("POST", "/shop/equipment-items", payload, headers)

    def get_equipment_item(self, item_id, headers):
        return self._request("GET", f"/shop/equipment-items/{item_id}", headers=headers)

    def list_equipment_items(self, headers, params=None):
        return self._request("GET", "/shop/equipment-items", headers=headers, params=params)

    def retire_equipment_item(self, item_id, headers):
        return self._request("POST", f"/shop/equipment-items/{item_id}/retire", {}, headers)

    def inspect_equipment_item(self, item_id, payload, headers):
        return self._request("POST", f"/shop/equipment-items/{item_id}/inspect", payload, headers)

    def service_complete_equipment_item(self, item_id, headers):
        return self._request("POST", f"/shop/equipment-items/{item_id}/service-complete", {}, headers)

    # --- reservations & items ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/shop/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/shop/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/shop/reservations", headers=headers, params=params)

    def add_reservation_item(self, reservation_id, payload, headers):
        return self._request("POST", f"/shop/reservations/{reservation_id}/items", payload, headers)

    def get_reservation_item(self, item_id, headers):
        return self._request("GET", f"/shop/reservation-items/{item_id}", headers=headers)

    def list_reservation_items(self, headers, params=None):
        return self._request("GET", "/shop/reservation-items", headers=headers, params=params)

    def assign_reservation_item(self, item_id, payload, headers):
        return self._request("POST", f"/shop/reservation-items/{item_id}/assign", payload, headers)

    def release_reservation_item(self, item_id, headers):
        return self._request("POST", f"/shop/reservation-items/{item_id}/release", {}, headers)

    def confirm_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/shop/reservations/{reservation_id}/confirm", payload, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/shop/reservations/{reservation_id}/cancel", {}, headers)

    def pickup_reservation(self, reservation_id, headers):
        return self._request("POST", f"/shop/reservations/{reservation_id}/pickup", {}, headers)

    def return_reservation(self, reservation_id, headers):
        return self._request("POST", f"/shop/reservations/{reservation_id}/return", {}, headers)

    def close_reservation(self, reservation_id, headers):
        return self._request("POST", f"/shop/reservations/{reservation_id}/close", {}, headers)

    # --- tune tickets ---
    def create_tune_ticket(self, payload, headers):
        return self._request("POST", "/shop/tune-tickets", payload, headers)

    def get_tune_ticket(self, ticket_id, headers):
        return self._request("GET", f"/shop/tune-tickets/{ticket_id}", headers=headers)

    def list_tune_tickets(self, headers, params=None):
        return self._request("GET", "/shop/tune-tickets", headers=headers, params=params)

    def quote_tune_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/shop/tune-tickets/{ticket_id}/quote", payload, headers)

    def approve_tune_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/shop/tune-tickets/{ticket_id}/approve", payload, headers)

    def start_tune_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/tune-tickets/{ticket_id}/start", {}, headers)

    def complete_tune_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/tune-tickets/{ticket_id}/complete", {}, headers)

    def qc_pass_tune_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/tune-tickets/{ticket_id}/qc-pass", {}, headers)

    def qc_fail_tune_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/tune-tickets/{ticket_id}/qc-fail", {}, headers)

    def pickup_tune_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/tune-tickets/{ticket_id}/pickup", {}, headers)

    def cancel_tune_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/tune-tickets/{ticket_id}/cancel", {}, headers)

    # --- season leases ---
    def create_season_lease(self, payload, headers):
        return self._request("POST", "/shop/season-leases", payload, headers)

    def get_season_lease(self, lease_id, headers):
        return self._request("GET", f"/shop/season-leases/{lease_id}", headers=headers)

    def list_season_leases(self, headers, params=None):
        return self._request("GET", "/shop/season-leases", headers=headers, params=params)

    def activate_season_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/shop/season-leases/{lease_id}/activate", payload, headers)

    def swap_season_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/shop/season-leases/{lease_id}/swap", payload, headers)

    def close_season_lease(self, lease_id, headers):
        return self._request("POST", f"/shop/season-leases/{lease_id}/close", {}, headers)

    def reinstate_season_lease(self, lease_id, headers):
        return self._request("POST", f"/shop/season-leases/{lease_id}/reinstate", {}, headers)

    # --- demo credits ---
    def create_demo_credit(self, payload, headers):
        return self._request("POST", "/shop/demo-credits", payload, headers)

    def get_demo_credit(self, credit_id, headers):
        return self._request("GET", f"/shop/demo-credits/{credit_id}", headers=headers)

    def list_demo_credits(self, headers, params=None):
        return self._request("GET", "/shop/demo-credits", headers=headers, params=params)

    # --- purchase orders ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/shop/purchase-orders", payload, headers)

    def get_purchase_order(self, order_id, headers):
        return self._request("GET", f"/shop/purchase-orders/{order_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/shop/purchase-orders", headers=headers, params=params)

    def pay_purchase_order(self, order_id, headers):
        return self._request("POST", f"/shop/purchase-orders/{order_id}/pay", {}, headers)

    def fulfill_purchase_order(self, order_id, headers):
        return self._request("POST", f"/shop/purchase-orders/{order_id}/fulfill", {}, headers)

    def cancel_purchase_order(self, order_id, headers):
        return self._request("POST", f"/shop/purchase-orders/{order_id}/cancel", {}, headers)

    # --- damage assessments ---
    def create_damage_assessment(self, payload, headers):
        return self._request("POST", "/shop/damage-assessments", payload, headers)

    def get_damage_assessment(self, assessment_id, headers):
        return self._request("GET", f"/shop/damage-assessments/{assessment_id}", headers=headers)

    def list_damage_assessments(self, headers, params=None):
        return self._request("GET", "/shop/damage-assessments", headers=headers, params=params)

    def invoice_damage_assessment(self, assessment_id, headers):
        return self._request("POST", f"/shop/damage-assessments/{assessment_id}/invoice", {}, headers)

    def pay_damage_assessment(self, assessment_id, headers):
        return self._request("POST", f"/shop/damage-assessments/{assessment_id}/pay", {}, headers)

    def dispute_damage_assessment(self, assessment_id, headers):
        return self._request("POST", f"/shop/damage-assessments/{assessment_id}/dispute", {}, headers)

    def resolve_damage_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/shop/damage-assessments/{assessment_id}/resolve", payload, headers)

    # --- pickup windows & bookings ---
    def create_pickup_window(self, payload, headers):
        return self._request("POST", "/shop/pickup-windows", payload, headers)

    def get_pickup_window(self, window_id, headers):
        return self._request("GET", f"/shop/pickup-windows/{window_id}", headers=headers)

    def list_pickup_windows(self, headers, params=None):
        return self._request("GET", "/shop/pickup-windows", headers=headers, params=params)

    def create_pickup_booking(self, payload, headers):
        return self._request("POST", "/shop/pickup-bookings", payload, headers)

    def get_pickup_booking(self, booking_id, headers):
        return self._request("GET", f"/shop/pickup-bookings/{booking_id}", headers=headers)

    def list_pickup_bookings(self, headers, params=None):
        return self._request("GET", "/shop/pickup-bookings", headers=headers, params=params)

    def cancel_pickup_booking(self, booking_id, headers):
        return self._request("POST", f"/shop/pickup-bookings/{booking_id}/cancel", {}, headers)

    def complete_pickup_booking(self, booking_id, headers):
        return self._request("POST", f"/shop/pickup-bookings/{booking_id}/complete", {}, headers)

    # --- shop day capacity ---
    def create_shop_day_capacity(self, payload, headers):
        return self._request("POST", "/shop/shop-day-capacity", payload, headers)

    def get_shop_day_capacity(self, capacity_id, headers):
        return self._request("GET", f"/shop/shop-day-capacity/{capacity_id}", headers=headers)

    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
