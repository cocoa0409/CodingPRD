"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── CatalogItem ──────────────────────────────────
    def create_catalog_item(self, payload, headers):
        return self._request("POST", "/catalog-items", payload, headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", "/catalog-items", headers=headers, params=params)

    def get_catalog_item(self, item_id, headers):
        return self._request("GET", f"/catalog-items/{item_id}", headers=headers)

    def get_item_availability(self, item_id, window_start, window_end, headers):
        return self._request(
            "GET",
            f"/catalog-items/{item_id}/availability",
            headers=headers,
            params={"window_start": window_start, "window_end": window_end},
        )

    def list_item_reservations(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/catalog-items/{item_id}/reservations", headers=headers, params=params
        )

    def retire_catalog_item(self, item_id, headers):
        return self._request("POST", f"/catalog-items/{item_id}/retire", {}, headers)

    # ─── Customer ─────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Venue ────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    # ─── InsuranceCertificate ─────────────────────────
    def create_certificate(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/certificates", payload, headers)

    def list_certificates(self, venue_id, headers, params=None):
        return self._request(
            "GET", f"/venues/{venue_id}/certificates", headers=headers, params=params
        )

    def approve_certificate(self, venue_id, certificate_id, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/certificates/{certificate_id}/approve", {}, headers
        )

    def reject_certificate(self, venue_id, certificate_id, headers, payload=None):
        return self._request(
            "POST",
            f"/venues/{venue_id}/certificates/{certificate_id}/reject",
            payload or {},
            headers,
        )

    def revoke_certificate(self, venue_id, certificate_id, headers, payload=None):
        return self._request(
            "POST",
            f"/venues/{venue_id}/certificates/{certificate_id}/revoke",
            payload or {},
            headers,
        )

    # ─── RentalOrder ──────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def remove_line(self, order_id, line_id, headers):
        return self._request("DELETE", f"/orders/{order_id}/lines/{line_id}", headers=headers)

    def get_quote(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/quote", headers=headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def return_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/return", {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    def weather_cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/weather-cancel", {}, headers)

    # ─── Deposit ──────────────────────────────────────
    def settle_deposit(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/deposit/settle", payload, headers)

    def get_deposit_ledger(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/deposit-ledger", headers=headers, params=params
        )

    # ─── Crew & DeliveryRun ───────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def create_delivery_run(self, payload, headers):
        return self._request("POST", "/delivery-runs", payload, headers)

    def get_delivery_run(self, run_id, headers):
        return self._request("GET", f"/delivery-runs/{run_id}", headers=headers)

    def list_delivery_runs(self, headers, params=None):
        return self._request("GET", "/delivery-runs", headers=headers, params=params)

    def attempt_delivery_run(self, run_id, payload, headers):
        return self._request("POST", f"/delivery-runs/{run_id}/attempt", payload, headers)

    def reschedule_delivery_run(self, run_id, payload, headers):
        return self._request("POST", f"/delivery-runs/{run_id}/reschedule", payload, headers)

    def cancel_delivery_run(self, run_id, headers):
        return self._request("POST", f"/delivery-runs/{run_id}/cancel", {}, headers)

    # ─── WeatherEvent ─────────────────────────────────
    def create_weather_event(self, payload, headers):
        return self._request("POST", "/weather-events", payload, headers)

    def list_weather_events(self, headers, params=None):
        return self._request("GET", "/weather-events", headers=headers, params=params)


api_client = ApiClient()
