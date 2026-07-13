"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Municipality ---
    def create_municipality(self, payload, headers):
        return self._request("POST", "/mrf/municipalities", payload, headers)

    def get_municipality(self, municipality_id, headers):
        return self._request("GET", f"/mrf/municipalities/{municipality_id}",
                             headers=headers)

    # --- Mill ---
    def create_mill(self, payload, headers):
        return self._request("POST", "/mrf/mills", payload, headers)

    def get_mill(self, mill_id, headers):
        return self._request("GET", f"/mrf/mills/{mill_id}", headers=headers)

    # --- CommodityIndex ---
    def create_commodity_index(self, payload, headers):
        return self._request("POST", "/mrf/commodity-indices", payload, headers)

    def list_commodity_indices(self, headers, params=None):
        return self._request("GET", "/mrf/commodity-indices",
                             headers=headers, params=params)

    def get_commodity_index(self, index_id, headers):
        return self._request("GET", f"/mrf/commodity-indices/{index_id}",
                             headers=headers)

    def publish_commodity_index(self, index_id, headers):
        return self._request("POST", f"/mrf/commodity-indices/{index_id}/publish",
                             {}, headers)

    # --- SortLine ---
    def create_sort_line(self, payload, headers):
        return self._request("POST", "/mrf/sort-lines", payload, headers)

    def get_sort_line(self, sort_line_id, headers):
        return self._request("GET", f"/mrf/sort-lines/{sort_line_id}",
                             headers=headers)

    # --- DowntimeEvent ---
    def create_downtime_event(self, payload, headers):
        return self._request("POST", "/mrf/downtime-events", payload, headers)

    def list_downtime_events(self, headers, params=None):
        return self._request("GET", "/mrf/downtime-events",
                             headers=headers, params=params)

    def get_downtime_event(self, downtime_event_id, headers):
        return self._request("GET", f"/mrf/downtime-events/{downtime_event_id}",
                             headers=headers)

    # --- InboundLoad ---
    def create_inbound_load(self, payload, headers):
        return self._request("POST", "/mrf/inbound-loads", payload, headers)

    def list_inbound_loads(self, headers, params=None):
        return self._request("GET", "/mrf/inbound-loads",
                             headers=headers, params=params)

    def get_inbound_load(self, load_id, headers):
        return self._request("GET", f"/mrf/inbound-loads/{load_id}",
                             headers=headers)

    def audit_inbound_load(self, load_id, payload, headers):
        return self._request("POST", f"/mrf/inbound-loads/{load_id}/audit",
                             payload, headers)

    def request_reaudit_inbound_load(self, load_id, payload, headers):
        return self._request("POST",
                             f"/mrf/inbound-loads/{load_id}/request-reaudit",
                             payload, headers)

    def close_inbound_load(self, load_id, payload, headers):
        return self._request("POST", f"/mrf/inbound-loads/{load_id}/close",
                             payload, headers)

    # --- Bale ---
    def create_bale(self, payload, headers):
        return self._request("POST", "/mrf/bales", payload, headers)

    def list_bales(self, headers, params=None):
        return self._request("GET", "/mrf/bales", headers=headers, params=params)

    def get_bale(self, bale_id, headers):
        return self._request("GET", f"/mrf/bales/{bale_id}", headers=headers)

    def void_bale(self, bale_id, headers):
        return self._request("POST", f"/mrf/bales/{bale_id}/void", {}, headers)

    # --- MillShipment ---
    def create_mill_shipment(self, payload, headers):
        return self._request("POST", "/mrf/mill-shipments", payload, headers)

    def list_mill_shipments(self, headers, params=None):
        return self._request("GET", "/mrf/mill-shipments",
                             headers=headers, params=params)

    def get_mill_shipment(self, shipment_id, headers):
        return self._request("GET", f"/mrf/mill-shipments/{shipment_id}",
                             headers=headers)

    def assign_bale_to_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/mrf/mill-shipments/{shipment_id}/bales",
                             payload, headers)

    def ship_mill_shipment(self, shipment_id, headers):
        return self._request("POST", f"/mrf/mill-shipments/{shipment_id}/ship",
                             {}, headers)

    def settle_mill_shipment(self, shipment_id, headers):
        return self._request("POST", f"/mrf/mill-shipments/{shipment_id}/settle",
                             {}, headers)

    def dispute_mill_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/mrf/mill-shipments/{shipment_id}/dispute",
                             payload, headers)

    # --- MunicipalStatement ---
    def create_municipal_statement(self, payload, headers):
        return self._request("POST", "/mrf/municipal-statements", payload, headers)

    def list_municipal_statements(self, headers, params=None):
        return self._request("GET", "/mrf/municipal-statements",
                             headers=headers, params=params)

    def get_municipal_statement(self, statement_id, headers):
        return self._request("GET", f"/mrf/municipal-statements/{statement_id}",
                             headers=headers)

    def finalize_municipal_statement(self, statement_id, headers):
        return self._request("POST",
                             f"/mrf/municipal-statements/{statement_id}/finalize",
                             {}, headers)

    # --- RevenueSharePosting ---
    def list_revenue_postings(self, headers, params=None):
        return self._request("GET", "/mrf/revenue-postings",
                             headers=headers, params=params)

    def get_revenue_posting(self, posting_id, headers):
        return self._request("GET", f"/mrf/revenue-postings/{posting_id}",
                             headers=headers)


api_client = ApiClient()
