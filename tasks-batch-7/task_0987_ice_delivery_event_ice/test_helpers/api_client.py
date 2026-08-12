"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Platform clock (PRD §2.4) -------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Depots ---------------------------------------------------------------
    def create_depot(self, payload, headers):
        return self._request("POST", "/depots", payload, headers)

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"/depots/{depot_id}", headers=headers)

    def run_ops(self, depot_id, headers):
        return self._request("POST", f"/depots/{depot_id}/run-ops", headers=headers)

    # --- Customers --------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Certifications ---------------------------------------------------------
    def create_certification(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/certifications", payload, headers
        )

    def list_certifications(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/certifications", headers=headers, params=params
        )

    def suspend_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/suspend", headers=headers)

    def reinstate_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/reinstate", headers=headers)

    # --- Price books --------------------------------------------------------------
    def create_price_book(self, payload, headers):
        return self._request("POST", "/price-books", payload, headers)

    def list_price_books(self, headers, params=None):
        return self._request("GET", "/price-books", headers=headers, params=params)

    # --- Surge windows --------------------------------------------------------------
    def create_surge_window(self, payload, headers):
        return self._request("POST", "/surge-windows", payload, headers)

    def list_surge_windows(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/depots/{depot_id}/surge-windows", headers=headers, params=params
        )

    # --- Recurring routes --------------------------------------------------------------
    def create_route(self, payload, headers):
        return self._request("POST", "/recurring-routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/recurring-routes/{route_id}", headers=headers)

    def list_customer_routes(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/routes", headers=headers, params=params
        )

    def list_depot_routes(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/depots/{depot_id}/routes", headers=headers, params=params
        )

    def patch_standing_order(self, route_id, payload, headers):
        return self._request(
            "PATCH", f"/recurring-routes/{route_id}/standing-order", payload, headers
        )

    def pause_route(self, route_id, headers):
        return self._request("POST", f"/recurring-routes/{route_id}/pause", headers=headers)

    def resume_route(self, route_id, headers):
        return self._request("POST", f"/recurring-routes/{route_id}/resume", headers=headers)

    def terminate_route(self, route_id, headers):
        return self._request("POST", f"/recurring-routes/{route_id}/terminate", headers=headers)

    # --- Orders --------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def quote_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/quote", headers=headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    def reprice_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/reprice", payload, headers)

    def reserve_slot(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/reserve-slot", payload, headers)

    def stage_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/stage", headers=headers)

    def mark_ready_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/mark-ready", headers=headers)

    def confirm_pickup(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm-pickup", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/lines", headers=headers, params=params
        )

    def list_order_holds(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/holds", headers=headers, params=params
        )

    def list_order_waitlist_entries(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/waitlist-entries", headers=headers, params=params
        )

    # --- Delivery slots / holds --------------------------------------------------------------
    def create_delivery_slot(self, payload, headers):
        return self._request("POST", "/delivery-slots", payload, headers)

    def list_delivery_slots(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/depots/{depot_id}/delivery-slots", headers=headers, params=params
        )

    def list_depot_holds(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/depots/{depot_id}/holds", headers=headers, params=params
        )

    def release_hold(self, hold_id, headers):
        return self._request(
            "POST", f"/cold-storage-holds/{hold_id}/release", headers=headers
        )

    # --- Dispatch runs --------------------------------------------------------------
    def create_dispatch_run(self, payload, headers):
        return self._request("POST", "/dispatch-runs", payload, headers)

    def get_dispatch_run(self, run_id, headers):
        return self._request("GET", f"/dispatch-runs/{run_id}", headers=headers)

    def list_dispatch_runs(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/depots/{depot_id}/dispatch-runs", headers=headers, params=params
        )

    def assign_run(self, run_id, payload, headers):
        return self._request("POST", f"/dispatch-runs/{run_id}/assign", payload, headers)

    def lock_run(self, run_id, headers):
        return self._request("POST", f"/dispatch-runs/{run_id}/lock", headers=headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/dispatch-runs/{run_id}/start", headers=headers)

    def complete_run(self, run_id, headers):
        return self._request("POST", f"/dispatch-runs/{run_id}/complete", headers=headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/dispatch-runs/{run_id}/cancel", headers=headers)

    def list_run_orders(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/dispatch-runs/{run_id}/orders", headers=headers, params=params
        )

    # --- Waitlist --------------------------------------------------------------
    def list_depot_waitlist_entries(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/depots/{depot_id}/waitlist-entries", headers=headers, params=params
        )

    def withdraw_waitlist_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/waitlist-entries/{entry_id}/withdraw", headers=headers
        )

    # --- Invoices --------------------------------------------------------------
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/invoices/generate", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_customer_invoices(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/invoices", headers=headers, params=params
        )

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    def list_invoice_orders(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/invoices/{invoice_id}/orders", headers=headers, params=params
        )

    # --- Payments --------------------------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_customer_payments(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/payments", headers=headers, params=params
        )


api_client = ApiClient()
