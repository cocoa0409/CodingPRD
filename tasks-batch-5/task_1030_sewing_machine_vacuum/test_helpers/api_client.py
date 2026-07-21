"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def recall_product(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/recall", payload, headers)

    # ---- InventoryItem ----
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    def scrap_inventory_item(self, item_id, headers):
        return self._request("POST", f"/inventory-items/{item_id}/scrap", {}, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def adjust_store_credit(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/store-credit/adjustments", payload, headers
        )

    # ---- SalesOrder ----
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def complete_sales_order(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/complete", payload, headers)

    def cancel_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel", {}, headers)

    # ---- RepairTicket ----
    def create_repair_ticket(self, payload, headers):
        return self._request("POST", "/repair-tickets", payload, headers)

    def list_repair_tickets(self, headers, params=None):
        return self._request("GET", "/repair-tickets", headers=headers, params=params)

    def get_repair_ticket(self, ticket_id, headers):
        return self._request("GET", f"/repair-tickets/{ticket_id}", headers=headers)

    def quote_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/quote", payload, headers)

    def approve_repair_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/approve", {}, headers)

    def reject_repair_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/reject", {}, headers)

    def consume_part(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/consume-part", payload, headers
        )

    def complete_repair_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/complete", {}, headers)

    def close_repair_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/close", {}, headers)

    def cancel_repair_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/cancel", {}, headers)

    # ---- RentalAgreement ----
    def create_rental(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rental-agreements", headers=headers, params=params)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rental-agreements/{rental_id}", headers=headers)

    def return_rental(self, rental_id, payload, headers):
        return self._request("POST", f"/rental-agreements/{rental_id}/return", payload, headers)

    def cancel_rental(self, rental_id, headers):
        return self._request("POST", f"/rental-agreements/{rental_id}/cancel", {}, headers)

    # ---- ClassSession ----
    def create_class_session(self, payload, headers):
        return self._request("POST", "/class-sessions", payload, headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/class-sessions", headers=headers, params=params)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/class-sessions/{session_id}", headers=headers)

    def complete_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/complete", {}, headers)

    def cancel_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/cancel", {}, headers)

    def create_enrollment(self, session_id, payload, headers):
        return self._request(
            "POST", f"/class-sessions/{session_id}/enrollments", payload, headers
        )

    # ---- ClassEnrollment ----
    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/class-enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/class-enrollments/{enrollment_id}", headers=headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/class-enrollments/{enrollment_id}/cancel", {}, headers)

    # ---- TuneUpSubscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/tune-up-subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/tune-up-subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/tune-up-subscriptions/{subscription_id}", headers=headers)

    def redeem_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/tune-up-subscriptions/{subscription_id}/redeem", {}, headers
        )

    def lapse_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/tune-up-subscriptions/{subscription_id}/lapse", {}, headers
        )

    def reinstate_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/tune-up-subscriptions/{subscription_id}/reinstate", {}, headers
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/tune-up-subscriptions/{subscription_id}/cancel", {}, headers
        )

    # ---- SpecialOrder ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def amend_special_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/special-orders/{order_id}", payload, headers)

    def receive_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/receive", {}, headers)

    def fulfill_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/fulfill", {}, headers)

    def cancel_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/cancel", {}, headers)


api_client = ApiClient()
