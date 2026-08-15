"""API client: one method per endpoint defined in PRD §4.

All paths live under the /api prefix. The base _request() method is
inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Grower ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/api/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/api/growers/{grower_id}", headers=headers)

    def suspend_grower(self, grower_id, headers):
        return self._request("POST", f"/api/growers/{grower_id}/suspend", headers=headers)

    # --- Field ---
    def create_field(self, payload, headers):
        return self._request("POST", "/api/fields", payload, headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/api/fields", headers=headers, params=params)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/api/fields/{field_id}", headers=headers)

    # --- Cutting ---
    def create_cutting(self, payload, headers):
        return self._request("POST", "/api/cuttings", payload, headers)

    def list_cuttings(self, headers, params=None):
        return self._request("GET", "/api/cuttings", headers=headers, params=params)

    def get_cutting(self, cutting_id, headers):
        return self._request("GET", f"/api/cuttings/{cutting_id}", headers=headers)

    def mark_cut(self, cutting_id, payload, headers):
        return self._request(
            "POST", f"/api/cuttings/{cutting_id}/mark-cut", payload, headers,
        )

    def abandon_cutting(self, cutting_id, headers):
        return self._request("POST", f"/api/cuttings/{cutting_id}/abandon", headers=headers)

    # --- WeatherReport ---
    def create_weather_report(self, payload, headers):
        return self._request("POST", "/api/weather-reports", payload, headers)

    # --- StorageSite ---
    def create_storage_site(self, payload, headers):
        return self._request("POST", "/api/storage-sites", payload, headers)

    def list_storage_sites(self, headers, params=None):
        return self._request("GET", "/api/storage-sites", headers=headers, params=params)

    def get_storage_site(self, site_id, headers):
        return self._request("GET", f"/api/storage-sites/{site_id}", headers=headers)

    def get_site_occupancy(self, site_id, headers):
        return self._request(
            "GET", f"/api/storage-sites/{site_id}/occupancy", headers=headers,
        )

    # --- BaleLot ---
    def create_bale_lot(self, payload, headers):
        return self._request("POST", "/api/bale-lots", payload, headers)

    def list_bale_lots(self, headers, params=None):
        return self._request("GET", "/api/bale-lots", headers=headers, params=params)

    def get_bale_lot(self, lot_id, headers):
        return self._request("GET", f"/api/bale-lots/{lot_id}", headers=headers)

    def condemn_lot(self, lot_id, headers):
        return self._request("POST", f"/api/bale-lots/{lot_id}/condemn", headers=headers)

    def transfer_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/bale-lots/{lot_id}/transfer", payload, headers)

    # --- SpoilageEvent ---
    def create_spoilage_event(self, payload, headers):
        return self._request("POST", "/api/spoilage-events", payload, headers)

    def list_spoilage_events(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/api/bale-lots/{lot_id}/spoilage-events",
            headers=headers, params=params,
        )

    # --- ForageTest ---
    def create_forage_test(self, payload, headers):
        return self._request("POST", "/api/forage-tests", payload, headers)

    def list_forage_tests(self, headers, params=None):
        return self._request("GET", "/api/forage-tests", headers=headers, params=params)

    def get_forage_test(self, test_id, headers):
        return self._request("GET", f"/api/forage-tests/{test_id}", headers=headers)

    def submit_forage_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/api/forage-tests/{test_id}/submit", payload, headers,
        )

    def record_forage_result(self, test_id, payload, headers):
        return self._request(
            "POST", f"/api/forage-tests/{test_id}/record-result", payload, headers,
        )

    def certify_forage_test(self, test_id, headers):
        return self._request(
            "POST", f"/api/forage-tests/{test_id}/certify", headers=headers,
        )

    def invalidate_forage_test(self, test_id, headers):
        return self._request(
            "POST", f"/api/forage-tests/{test_id}/invalidate", headers=headers,
        )

    # --- MarketIndex ---
    def create_market_index(self, payload, headers):
        return self._request("POST", "/api/market-indices", payload, headers)

    def list_market_indices(self, headers, params=None):
        return self._request("GET", "/api/market-indices", headers=headers, params=params)

    # --- Buyer ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/api/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/api/buyers/{buyer_id}", headers=headers)

    def suspend_buyer(self, buyer_id, headers):
        return self._request("POST", f"/api/buyers/{buyer_id}/suspend", headers=headers)

    # --- FreightLane ---
    def create_freight_lane(self, payload, headers):
        return self._request("POST", "/api/freight-lanes", payload, headers)

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/api/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/api/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/api/quotes/{quote_id}", headers=headers)

    def patch_quote(self, quote_id, payload, headers):
        return self._request("PATCH", f"/api/quotes/{quote_id}", payload, headers)

    def issue_quote(self, quote_id, headers):
        return self._request("POST", f"/api/quotes/{quote_id}/issue", headers=headers)

    def revise_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/api/quotes/{quote_id}/revise", payload, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/api/quotes/{quote_id}/accept", payload, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/api/quotes/{quote_id}/decline", headers=headers)

    # --- Contract ---
    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def cancel_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/cancel", headers=headers,
        )

    def declare_default(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/declare-default", headers=headers,
        )

    # --- DeliveryLoad ---
    def create_delivery_load(self, payload, headers):
        return self._request("POST", "/api/delivery-loads", payload, headers)

    def get_delivery_load(self, load_id, headers):
        return self._request("GET", f"/api/delivery-loads/{load_id}", headers=headers)

    def start_loading(self, load_id, headers):
        return self._request(
            "POST", f"/api/delivery-loads/{load_id}/start-loading", headers=headers,
        )

    def depart_load(self, load_id, headers):
        return self._request(
            "POST", f"/api/delivery-loads/{load_id}/depart", headers=headers,
        )

    def deliver_load(self, load_id, headers):
        return self._request(
            "POST", f"/api/delivery-loads/{load_id}/deliver", headers=headers,
        )

    def settle_load(self, load_id, headers):
        return self._request(
            "POST", f"/api/delivery-loads/{load_id}/settle", headers=headers,
        )

    def auto_allocate(self, load_id, headers):
        return self._request(
            "POST", f"/api/delivery-loads/{load_id}/auto-allocate", headers=headers,
        )

    # --- LoadAllocation ---
    def create_load_allocation(self, payload, headers):
        return self._request("POST", "/api/load-allocations", payload, headers)

    def list_load_allocations(self, headers, params=None):
        return self._request("GET", "/api/load-allocations", headers=headers, params=params)

    def get_load_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/api/load-allocations/{allocation_id}", headers=headers,
        )

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/api/load-allocations/{allocation_id}/release", headers=headers,
        )

    # --- BalingServiceOrder ---
    def create_baling_service_order(self, payload, headers):
        return self._request("POST", "/api/baling-service-orders", payload, headers)

    def list_baling_service_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/baling-service-orders", headers=headers, params=params,
        )

    def get_baling_service_order(self, order_id, headers):
        return self._request(
            "GET", f"/api/baling-service-orders/{order_id}", headers=headers,
        )

    def schedule_baling_service_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/baling-service-orders/{order_id}/schedule", payload, headers,
        )

    def start_baling_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/baling-service-orders/{order_id}/start", headers=headers,
        )

    def complete_baling_service_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/baling-service-orders/{order_id}/complete", payload, headers,
        )

    def dispute_baling_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/baling-service-orders/{order_id}/dispute", headers=headers,
        )

    def resolve_baling_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/baling-service-orders/{order_id}/resolve", headers=headers,
        )

    def invoice_baling_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/baling-service-orders/{order_id}/invoice", headers=headers,
        )

    def cancel_baling_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/baling-service-orders/{order_id}/cancel", headers=headers,
        )


api_client = ApiClient()
# The runner's per-test-server isolation SIGKILLs and respawns the API server
# before every test on the same port. A default keep-alive session pools the
# connection to the now-dead server; on a rare race the kernel's RST has not
# been processed when the connection is reused, surfacing as ECONNRESET on
# the first request after a restart. Forcing `Connection: close` makes every
# request open a fresh TCP connection, eliminating stale-pool reuse entirely.
api_client.session.headers["Connection"] = "close"
