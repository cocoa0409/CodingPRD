"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc", payload, headers)

    # ---- PricingConfig ----
    def create_pricing_config(self, payload, headers):
        return self._request("POST", "/api/v1/pricing-configs", payload, headers)

    def list_pricing_configs(self, headers, params=None):
        return self._request("GET", "/api/v1/pricing-configs", headers=headers, params=params)

    def get_pricing_config(self, config_id, headers):
        return self._request("GET", f"/api/v1/pricing-configs/{config_id}", headers=headers)

    # ---- DeliveryZone ----
    def create_delivery_zone(self, payload, headers):
        return self._request("POST", "/api/v1/delivery-zones", payload, headers)

    def list_delivery_zones(self, headers, params=None):
        return self._request("GET", "/api/v1/delivery-zones", headers=headers, params=params)

    def get_delivery_zone(self, zone_id, headers):
        return self._request("GET", f"/api/v1/delivery-zones/{zone_id}", headers=headers)

    def list_zone_customers(self, zone_id, headers, params=None):
        return self._request("GET", f"/api/v1/delivery-zones/{zone_id}/customers", headers=headers, params=params)

    def list_zone_routes(self, zone_id, headers, params=None):
        return self._request("GET", f"/api/v1/delivery-zones/{zone_id}/routes", headers=headers, params=params)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/v1/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/v1/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/v1/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/api/v1/customers/{customer_id}", payload, headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/api/v1/customers/{customer_id}/suspend", {}, headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/api/v1/customers/{customer_id}/reinstate", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/api/v1/customers/{customer_id}/close", {}, headers)

    def list_customer_cooler_rentals(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/cooler-rentals", headers=headers, params=params)

    def list_customer_addons(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/addons", headers=headers, params=params)

    def list_customer_invoices(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/invoices", headers=headers, params=params)

    def list_customer_work_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/work-orders", headers=headers, params=params)

    def list_customer_bottle_custody_ledger(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/bottle-custody-ledger", headers=headers, params=params)

    def list_customer_skip_credits(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/skip-credits", headers=headers, params=params)

    # ---- Route ----
    def create_route(self, payload, headers):
        return self._request("POST", "/api/v1/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/api/v1/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/api/v1/routes/{route_id}", headers=headers)

    def publish_route(self, route_id, headers):
        return self._request("POST", f"/api/v1/routes/{route_id}/publish", {}, headers)

    def start_route(self, route_id, headers):
        return self._request("POST", f"/api/v1/routes/{route_id}/start", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/api/v1/routes/{route_id}/complete", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/api/v1/routes/{route_id}/cancel", {}, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/api/v1/routes/{route_id}/stops", headers=headers, params=params)

    # ---- Stop ----
    def create_stop(self, route_id, payload, headers):
        return self._request("POST", f"/api/v1/routes/{route_id}/stops", payload, headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/api/v1/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/api/v1/stops/{stop_id}", headers=headers)

    def list_stop_bottle_custody_ledger(self, stop_id, headers, params=None):
        return self._request("GET", f"/api/v1/stops/{stop_id}/bottle-custody-ledger", headers=headers, params=params)

    def list_stop_skip_credits(self, stop_id, headers, params=None):
        return self._request("GET", f"/api/v1/stops/{stop_id}/skip-credits", headers=headers, params=params)

    def arrive_stop(self, stop_id, headers):
        return self._request("POST", f"/api/v1/stops/{stop_id}/arrive", {}, headers)

    def deliver_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/api/v1/stops/{stop_id}/deliver", payload, headers)

    def skip_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/api/v1/stops/{stop_id}/skip", payload, headers)

    def fail_stop(self, stop_id, headers):
        return self._request("POST", f"/api/v1/stops/{stop_id}/fail", {}, headers)

    # ---- WorkOrder ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/api/v1/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/api/v1/work-orders", headers=headers, params=params)

    def get_work_order(self, order_id, headers):
        return self._request("GET", f"/api/v1/work-orders/{order_id}", headers=headers)

    def schedule_work_order(self, order_id, headers):
        return self._request("POST", f"/api/v1/work-orders/{order_id}/schedule", {}, headers)

    def cancel_work_order(self, order_id, headers):
        return self._request("POST", f"/api/v1/work-orders/{order_id}/cancel", {}, headers)

    def reject_work_order(self, order_id, headers):
        return self._request("POST", f"/api/v1/work-orders/{order_id}/reject", {}, headers)

    # ---- CoolerRental ----
    def create_cooler_rental(self, payload, headers):
        return self._request("POST", "/api/v1/cooler-rentals", payload, headers)

    def get_cooler_rental(self, rental_id, headers):
        return self._request("GET", f"/api/v1/cooler-rentals/{rental_id}", headers=headers)

    def install_cooler_rental(self, rental_id, headers):
        return self._request("POST", f"/api/v1/cooler-rentals/{rental_id}/install", {}, headers)

    def suspend_cooler_rental(self, rental_id, headers):
        return self._request("POST", f"/api/v1/cooler-rentals/{rental_id}/suspend", {}, headers)

    def resume_cooler_rental(self, rental_id, headers):
        return self._request("POST", f"/api/v1/cooler-rentals/{rental_id}/resume", {}, headers)

    def request_return_cooler_rental(self, rental_id, headers):
        return self._request("POST", f"/api/v1/cooler-rentals/{rental_id}/request-return", {}, headers)

    def confirm_return_cooler_rental(self, rental_id, headers):
        return self._request("POST", f"/api/v1/cooler-rentals/{rental_id}/confirm-return", {}, headers)

    def close_cooler_rental(self, rental_id, headers):
        return self._request("POST", f"/api/v1/cooler-rentals/{rental_id}/close", {}, headers)

    # ---- AddOn ----
    def create_addon(self, payload, headers):
        return self._request("POST", "/api/v1/addons", payload, headers)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/api/v1/addons/{addon_id}", headers=headers)

    def pause_addon(self, addon_id, headers):
        return self._request("POST", f"/api/v1/addons/{addon_id}/pause", {}, headers)

    def resume_addon(self, addon_id, headers):
        return self._request("POST", f"/api/v1/addons/{addon_id}/resume", {}, headers)

    def cancel_addon(self, addon_id, headers):
        return self._request("POST", f"/api/v1/addons/{addon_id}/cancel", {}, headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/api/v1/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/v1/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/v1/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/v1/invoices/{invoice_id}/issue", {}, headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/v1/invoices/{invoice_id}/dispute", {}, headers)

    def resolve_dispute(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/v1/invoices/{invoice_id}/resolve-dispute", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/v1/invoices/{invoice_id}/void", {}, headers)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/api/v1/invoices/{invoice_id}/payments", headers=headers, params=params)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/api/v1/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/api/v1/payments/{payment_id}", headers=headers)

    def apply_payment(self, payment_id, headers):
        return self._request("POST", f"/api/v1/payments/{payment_id}/apply", {}, headers)

    def mark_payment_failed(self, payment_id, headers):
        return self._request("POST", f"/api/v1/payments/{payment_id}/mark-failed", {}, headers)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/api/v1/payments/{payment_id}/refund", {}, headers)

    # ---- SkipCredit ----
    def get_skip_credit(self, credit_id, headers):
        return self._request("GET", f"/api/v1/skip-credits/{credit_id}", headers=headers)

    def apply_skip_credit(self, credit_id, headers):
        return self._request("POST", f"/api/v1/skip-credits/{credit_id}/apply", {}, headers)

    def revoke_skip_credit(self, credit_id, headers):
        return self._request("POST", f"/api/v1/skip-credits/{credit_id}/revoke", {}, headers)


api_client = ApiClient()
