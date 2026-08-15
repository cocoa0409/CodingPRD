"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Distributors
    # ------------------------------------------------------------------
    def create_distributor(self, payload, headers):
        return self._request("POST", "/dairy/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request(
            "GET", f"/dairy/distributors/{distributor_id}", headers=headers
        )

    def list_distributor_routes(self, distributor_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/distributors/{distributor_id}/routes",
            headers=headers, params=params,
        )

    def list_distributor_drivers(self, distributor_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/distributors/{distributor_id}/drivers",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    def create_route(self, payload, headers):
        return self._request("POST", "/dairy/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/dairy/routes/{route_id}", headers=headers)

    def activate_route(self, route_id, headers):
        return self._request(
            "POST", f"/dairy/routes/{route_id}/activate", {}, headers
        )

    def suspend_route(self, route_id, headers):
        return self._request(
            "POST", f"/dairy/routes/{route_id}/suspend", {}, headers
        )

    def retire_route(self, route_id, headers):
        return self._request(
            "POST", f"/dairy/routes/{route_id}/retire", {}, headers
        )

    def list_route_stores(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/routes/{route_id}/stores", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Drivers
    # ------------------------------------------------------------------
    def create_driver(self, payload, headers):
        return self._request("POST", "/dairy/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/dairy/drivers/{driver_id}", headers=headers)

    def get_weekly_settlement(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/drivers/{driver_id}/weekly-settlement",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Stores
    # ------------------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", "/dairy/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/dairy/stores/{store_id}", headers=headers)

    def patch_store(self, store_id, payload, headers):
        return self._request("PATCH", f"/dairy/stores/{store_id}", payload, headers)

    def deactivate_store(self, store_id, headers):
        return self._request(
            "POST", f"/dairy/stores/{store_id}/deactivate", {}, headers
        )

    def reactivate_store(self, store_id, headers):
        return self._request(
            "POST", f"/dairy/stores/{store_id}/reactivate", {}, headers
        )

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/dairy/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/dairy/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request(
            "POST", f"/dairy/products/{product_id}/discontinue", {}, headers
        )

    # ------------------------------------------------------------------
    # Standing pars
    # ------------------------------------------------------------------
    def upsert_standing_par(self, store_id, payload, headers):
        return self._request(
            "POST", f"/dairy/stores/{store_id}/standing-pars", payload, headers
        )

    def list_store_pars(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/stores/{store_id}/standing-pars",
            headers=headers, params=params,
        )

    def list_product_pars(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/products/{product_id}/standing-pars",
            headers=headers, params=params,
        )

    def get_standing_par(self, par_id, headers):
        return self._request(
            "GET", f"/dairy/standing-pars/{par_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Pricing periods / announcements
    # ------------------------------------------------------------------
    def create_pricing_period(self, payload, headers):
        return self._request("POST", "/dairy/pricing-periods", payload, headers)

    def get_pricing_period(self, period_id, headers):
        return self._request(
            "GET", f"/dairy/pricing-periods/{period_id}", headers=headers
        )

    def close_pricing_period(self, period_id, headers):
        return self._request(
            "POST", f"/dairy/pricing-periods/{period_id}/close", {}, headers
        )

    def publish_announcement(self, period_id, payload, headers):
        return self._request(
            "POST", f"/dairy/pricing-periods/{period_id}/announcements",
            payload, headers,
        )

    def list_period_announcements(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/pricing-periods/{period_id}/announcements",
            headers=headers, params=params,
        )

    def get_announcement(self, announcement_id, headers):
        return self._request(
            "GET", f"/dairy/price-announcements/{announcement_id}", headers=headers
        )

    def list_announcements(self, headers, params=None):
        return self._request(
            "GET", "/dairy/price-announcements", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Truck trips
    # ------------------------------------------------------------------
    def create_trip(self, payload, headers):
        return self._request("POST", "/dairy/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/dairy/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/dairy/trips", headers=headers, params=params)

    def depart_trip(self, trip_id, headers):
        return self._request("POST", f"/dairy/trips/{trip_id}/depart", {}, headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/dairy/trips/{trip_id}/complete", {}, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/dairy/trips/{trip_id}/cancel", {}, headers)

    def qa_review_trip(self, trip_id, headers):
        return self._request("POST", f"/dairy/trips/{trip_id}/qa-review", {}, headers)

    def adjudicate_trip(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/dairy/trips/{trip_id}/adjudicate", payload, headers
        )

    def reconcile_trip(self, trip_id, headers):
        return self._request(
            "POST", f"/dairy/trips/{trip_id}/reconcile", {}, headers
        )

    def generate_orders(self, trip_id, headers):
        return self._request(
            "POST", f"/dairy/trips/{trip_id}/generate-orders", {}, headers
        )

    # ------------------------------------------------------------------
    # Temperature readings
    # ------------------------------------------------------------------
    def add_temperature_reading(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/dairy/trips/{trip_id}/temperature-readings", payload, headers
        )

    def list_temperature_readings(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/trips/{trip_id}/temperature-readings",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/dairy/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/dairy/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/dairy/orders", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/dairy/orders/{order_id}/confirm", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/dairy/orders/{order_id}/cancel", {}, headers)

    def deliver_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/dairy/orders/{order_id}/deliver", payload, headers
        )

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/dairy/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/dairy/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/dairy/invoices/{invoice_id}/payments", payload, headers
        )

    def void_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/dairy/invoices/{invoice_id}/void", {}, headers
        )

    # ------------------------------------------------------------------
    # Returns
    # ------------------------------------------------------------------
    def create_return(self, payload, headers):
        return self._request("POST", "/dairy/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/dairy/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/dairy/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request(
            "POST", f"/dairy/returns/{return_id}/approve", {}, headers
        )

    def reject_return(self, return_id, headers):
        return self._request(
            "POST", f"/dairy/returns/{return_id}/reject", {}, headers
        )

    def dispute_return(self, return_id, headers):
        return self._request(
            "POST", f"/dairy/returns/{return_id}/dispute", {}, headers
        )

    # ------------------------------------------------------------------
    # Credit memos
    # ------------------------------------------------------------------
    def get_credit_memo(self, memo_id, headers):
        return self._request(
            "GET", f"/dairy/credit-memos/{memo_id}", headers=headers
        )

    def list_credit_memos(self, headers, params=None):
        return self._request(
            "GET", "/dairy/credit-memos", headers=headers, params=params
        )

    def apply_credit_memo(self, memo_id, payload, headers):
        return self._request(
            "POST", f"/dairy/credit-memos/{memo_id}/apply", payload, headers
        )

    def void_credit_memo(self, memo_id, headers):
        return self._request(
            "POST", f"/dairy/credit-memos/{memo_id}/void", {}, headers
        )

    # ------------------------------------------------------------------
    # Crate transactions
    # ------------------------------------------------------------------
    def create_crate_transaction(self, store_id, payload, headers):
        return self._request(
            "POST", f"/dairy/stores/{store_id}/crate-transactions", payload, headers
        )

    def list_crate_transactions(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/stores/{store_id}/crate-transactions",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Merchandising sessions
    # ------------------------------------------------------------------
    def check_in_merchandising_session(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/dairy/trips/{trip_id}/merchandising-sessions",
            payload, headers,
        )

    def close_merchandising_session(self, session_id, headers):
        return self._request(
            "POST", f"/dairy/merchandising-sessions/{session_id}/close", {}, headers
        )

    def get_merchandising_session(self, session_id, headers):
        return self._request(
            "GET", f"/dairy/merchandising-sessions/{session_id}", headers=headers
        )

    def list_merchandising_sessions(self, headers, params=None):
        return self._request(
            "GET", "/dairy/merchandising-sessions", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Route sale listings
    # ------------------------------------------------------------------
    def create_route_sale_listing(self, payload, headers):
        return self._request("POST", "/dairy/route-sale-listings", payload, headers)

    def get_route_sale_listing(self, listing_id, headers):
        return self._request(
            "GET", f"/dairy/route-sale-listings/{listing_id}", headers=headers
        )

    def list_route_sale_listings(self, headers, params=None):
        return self._request(
            "GET", "/dairy/route-sale-listings", headers=headers, params=params
        )

    def publish_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/dairy/route-sale-listings/{listing_id}/publish", {}, headers
        )

    def submit_offer(self, listing_id, payload, headers):
        return self._request(
            "POST", f"/dairy/route-sale-listings/{listing_id}/submit-offer",
            payload, headers,
        )

    def accept_offer(self, listing_id, headers):
        return self._request(
            "POST", f"/dairy/route-sale-listings/{listing_id}/accept-offer",
            {}, headers,
        )

    def reject_offer(self, listing_id, headers):
        return self._request(
            "POST", f"/dairy/route-sale-listings/{listing_id}/reject-offer",
            {}, headers,
        )

    def withdraw_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/dairy/route-sale-listings/{listing_id}/withdraw", {}, headers
        )

    def approve_transfer(self, listing_id, headers):
        return self._request(
            "POST", f"/dairy/route-sale-listings/{listing_id}/approve-transfer",
            {}, headers,
        )


api_client = ApiClient()
