"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/customers/{customer_id}", payload, headers)

    def credit_hold_action(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-hold",
                             payload, headers)

    def apply_payment(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/payments",
                             payload, headers)

    # ---- Price books ----
    def create_price_book(self, payload, headers):
        return self._request("POST", "/price-books", payload, headers)

    def list_price_books(self, headers, params=None):
        return self._request("GET", "/price-books", headers=headers, params=params)

    def get_price_book(self, book_id, headers):
        return self._request("GET", f"/price-books/{book_id}", headers=headers)

    def activate_price_book(self, book_id, headers):
        return self._request("POST", f"/price-books/{book_id}/activate",
                             headers=headers)

    # ---- Products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def receive_stock(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/receive",
                             payload, headers)

    # ---- Cylinder assets / float ----
    def create_cylinder_asset(self, payload, headers):
        return self._request("POST", "/cylinder-assets", payload, headers)

    def list_cylinder_assets(self, headers, params=None):
        return self._request("GET", "/cylinder-assets", headers=headers,
                             params=params)

    def get_float_summary(self, headers):
        return self._request("GET", "/cylinder-assets/float-summary",
                             headers=headers)

    def get_cylinder_asset(self, asset_id, headers):
        return self._request("GET", f"/cylinder-assets/{asset_id}", headers=headers)

    def retire_cylinder_asset(self, asset_id, headers):
        return self._request("POST", f"/cylinder-assets/{asset_id}/retire",
                             headers=headers)

    # ---- Machines ----
    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    # ---- Rental agreements ----
    def create_rental_agreement(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def list_rental_agreements(self, headers, params=None):
        return self._request("GET", "/rental-agreements", headers=headers,
                             params=params)

    def get_rental_agreement(self, agreement_id, headers):
        return self._request("GET", f"/rental-agreements/{agreement_id}",
                             headers=headers)

    def suspend_rental_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/suspend",
                             headers=headers)

    def resume_rental_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/resume",
                             headers=headers)

    def close_rental_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/close",
                             headers=headers)

    def waive_rental_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/waive",
                             payload, headers)

    # ---- Delivery routes ----
    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/delivery-routes", payload, headers)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/delivery-routes/{route_id}", headers=headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/delivery-routes/{route_id}/dispatch",
                             headers=headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/delivery-routes/{route_id}/close",
                             headers=headers)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", headers=headers)

    def stage_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/stage", headers=headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def fulfill_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    # ---- Invoices / billing ----
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    def run_rental_billing_cycle(self, headers):
        return self._request("POST", "/billing/run-rental-cycle", headers=headers)

    # ---- Training classes / enrollments ----
    def create_training_class(self, payload, headers):
        return self._request("POST", "/training-classes", payload, headers)

    def get_training_class(self, class_id, headers):
        return self._request("GET", f"/training-classes/{class_id}", headers=headers)

    def advance_training_class(self, class_id, payload, headers):
        return self._request("POST", f"/training-classes/{class_id}/advance",
                             payload, headers)

    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def advance_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/advance",
                             payload, headers)

    # ---- Repair tickets ----
    def create_repair_ticket(self, payload, headers):
        return self._request("POST", "/repair-tickets", payload, headers)

    def list_repair_tickets(self, headers, params=None):
        return self._request("GET", "/repair-tickets", headers=headers,
                             params=params)

    def get_repair_ticket(self, ticket_id, headers):
        return self._request("GET", f"/repair-tickets/{ticket_id}", headers=headers)

    def advance_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/advance",
                             payload, headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
