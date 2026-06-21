"""API client: one method per endpoint defined in the PRD (§4).

Subclasses GenericApiClient; the base _request() handles the HTTP envelope.
For GET endpoints the framework passes the payload dict as query params.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Fare products ────────────────────────────────────────────────
    def create_fare_product(self, payload, headers):
        return self._request("POST", "/fare-products", payload, headers)

    def list_fare_products(self, headers, params=None):
        return self._request("GET", "/fare-products", headers=headers, params=params)

    def get_fare_product(self, product_id, headers):
        return self._request("GET", f"/fare-products/{product_id}", headers=headers)

    def retire_fare_product(self, product_id, headers):
        return self._request("POST", f"/fare-products/{product_id}/retire", {}, headers)

    # ─── Riders ───────────────────────────────────────────────────────
    def create_rider(self, payload, headers):
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/riders/{rider_id}", headers=headers)

    def get_rider_risk(self, rider_id, headers, params=None):
        return self._request("GET", f"/riders/{rider_id}/risk", headers=headers, params=params)

    def suspend_rider(self, rider_id, headers):
        return self._request("POST", f"/riders/{rider_id}/suspend", {}, headers)

    # ─── Funding sources ──────────────────────────────────────────────
    def create_funding_source(self, payload, headers):
        return self._request("POST", "/funding-sources", payload, headers)

    def list_funding_sources(self, headers, params=None):
        return self._request("GET", "/funding-sources", headers=headers, params=params)

    def get_funding_source(self, fs_id, headers):
        return self._request("GET", f"/funding-sources/{fs_id}", headers=headers)

    def load_funding_source(self, fs_id, payload, headers):
        return self._request("POST", f"/funding-sources/{fs_id}/load", payload, headers)

    # ─── Reduced-fare cards ───────────────────────────────────────────
    def create_reduced_fare_card(self, payload, headers):
        return self._request("POST", "/reduced-fare-cards", payload, headers)

    def list_reduced_fare_cards(self, headers, params=None):
        return self._request("GET", "/reduced-fare-cards", headers=headers, params=params)

    def get_reduced_fare_card(self, card_id, headers):
        return self._request("GET", f"/reduced-fare-cards/{card_id}", headers=headers)

    def patch_reduced_fare_card(self, card_id, payload, headers):
        return self._request("PATCH", f"/reduced-fare-cards/{card_id}", payload, headers)

    def verify_reduced_fare_card(self, card_id, payload, headers):
        return self._request("POST", f"/reduced-fare-cards/{card_id}/verify", payload, headers)

    def refresh_expiry_reduced_fare_card(self, card_id, headers):
        return self._request("POST", f"/reduced-fare-cards/{card_id}/refresh-expiry", {}, headers)

    def revoke_reduced_fare_card(self, card_id, headers):
        return self._request("POST", f"/reduced-fare-cards/{card_id}/revoke", {}, headers)

    # ─── Benefit allocations ──────────────────────────────────────────
    def create_benefit_allocation(self, payload, headers):
        return self._request("POST", "/benefit-allocations", payload, headers)

    def list_benefit_allocations(self, headers, params=None):
        return self._request("GET", "/benefit-allocations", headers=headers, params=params)

    def get_benefit_allocation(self, alloc_id, headers):
        return self._request("GET", f"/benefit-allocations/{alloc_id}", headers=headers)

    # ─── Fare weeks ───────────────────────────────────────────────────
    def create_fare_week(self, payload, headers):
        return self._request("POST", "/fare-weeks", payload, headers)

    def list_fare_weeks(self, headers, params=None):
        return self._request("GET", "/fare-weeks", headers=headers, params=params)

    def get_fare_week(self, week_id, headers):
        return self._request("GET", f"/fare-weeks/{week_id}", headers=headers)

    def close_fare_week(self, week_id, headers):
        return self._request("POST", f"/fare-weeks/{week_id}/close", {}, headers)

    # ─── Taps ─────────────────────────────────────────────────────────
    def create_tap(self, payload, headers):
        return self._request("POST", "/taps", payload, headers)

    def list_taps(self, headers, params=None):
        return self._request("GET", "/taps", headers=headers, params=params)

    def get_tap(self, tap_id, headers):
        return self._request("GET", f"/taps/{tap_id}", headers=headers)

    def quote_tap(self, headers, params):
        """GET /taps/quote — rider_id, fare_week_id, tapped_at carried as query params."""
        return self._request("GET", "/taps/quote", payload=params, headers=headers)

    def settle_tap(self, tap_id, headers):
        return self._request("POST", f"/taps/{tap_id}/settle", {}, headers)

    def reverse_tap(self, tap_id, headers):
        return self._request("POST", f"/taps/{tap_id}/reverse", {}, headers)

    # ─── Clock (test driving) ─────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
