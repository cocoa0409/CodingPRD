"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ColdStorageUnit ----
    def create_cold_storage_unit(self, payload, headers):
        return self._request("POST", "/cold-storage-units", payload, headers)

    def get_cold_storage_unit(self, unit_id, headers):
        return self._request("GET", f"/cold-storage-units/{unit_id}", headers=headers)

    def list_cold_storage_units(self, headers, params=None):
        return self._request("GET", "/cold-storage-units", headers=headers, params=params)

    def list_unit_inventory_lots(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/cold-storage-units/{unit_id}/inventory-lots",
            headers=headers, params=params,
        )

    # ---- InventoryLot ----
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def dispose_inventory_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/inventory-lots/{lot_id}/dispose", payload, headers,
        )

    def list_lot_order_lines(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/inventory-lots/{lot_id}/order-lines",
            headers=headers, params=params,
        )

    # ---- Agency ----
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/agencies", headers=headers, params=params)

    def update_agency(self, agency_id, payload, headers):
        return self._request("PATCH", f"/agencies/{agency_id}", payload, headers)

    def list_agency_client_households(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"/agencies/{agency_id}/client-households",
            headers=headers, params=params,
        )

    def list_agency_orders_for_agency(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"/agencies/{agency_id}/agency-orders",
            headers=headers, params=params,
        )

    # ---- AllocationCycle ----
    def create_allocation_cycle(self, payload, headers):
        return self._request("POST", "/allocation-cycles", payload, headers)

    def get_allocation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/allocation-cycles/{cycle_id}", headers=headers)

    def open_allocation_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/allocation-cycles/{cycle_id}/open", {}, headers,
        )

    def close_allocation_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/allocation-cycles/{cycle_id}/close", {}, headers,
        )

    def list_cycle_agency_orders(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/allocation-cycles/{cycle_id}/agency-orders",
            headers=headers, params=params,
        )

    def get_cycle_poundage_report(self, cycle_id, headers):
        return self._request(
            "GET", f"/allocation-cycles/{cycle_id}/poundage-report", headers=headers,
        )

    # ---- AgencyOrder + OrderLine ----
    def create_agency_order(self, payload, headers):
        return self._request("POST", "/agency-orders", payload, headers)

    def get_agency_order(self, order_id, headers):
        return self._request("GET", f"/agency-orders/{order_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/agency-orders/{order_id}/order-lines",
            headers=headers, params=params,
        )

    def approve_agency_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/agency-orders/{order_id}/approve", payload, headers,
        )

    def reject_agency_order(self, order_id, headers):
        return self._request(
            "POST", f"/agency-orders/{order_id}/reject", {}, headers,
        )

    def recall_agency_order(self, order_id, headers):
        return self._request(
            "POST", f"/agency-orders/{order_id}/recall", {}, headers,
        )

    def cancel_agency_order(self, order_id, headers):
        return self._request(
            "POST", f"/agency-orders/{order_id}/cancel", {}, headers,
        )

    # ---- ClientHousehold ----
    def create_client_household(self, payload, headers):
        return self._request("POST", "/client-households", payload, headers)

    def get_client_household(self, hh_id, headers):
        return self._request("GET", f"/client-households/{hh_id}", headers=headers)

    def update_client_household(self, hh_id, payload, headers):
        return self._request("PATCH", f"/client-households/{hh_id}", payload, headers)

    def certify_client_household(self, hh_id, headers):
        return self._request(
            "POST", f"/client-households/{hh_id}/certify", {}, headers,
        )

    # ---- DistributionEvent ----
    def create_distribution_event(self, payload, headers):
        return self._request("POST", "/distribution-events", payload, headers)

    def get_distribution_event(self, event_id, headers):
        return self._request("GET", f"/distribution-events/{event_id}", headers=headers)

    def list_distribution_events(self, headers, params=None):
        return self._request("GET", "/distribution-events", headers=headers, params=params)

    def pack_distribution_event(self, event_id, headers):
        return self._request(
            "POST", f"/distribution-events/{event_id}/pack", {}, headers,
        )

    def finalize_distribution_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/distribution-events/{event_id}/finalize", payload, headers,
        )

    def void_distribution_event(self, event_id, headers):
        return self._request(
            "POST", f"/distribution-events/{event_id}/void", {}, headers,
        )

    # ---- PoundageReport ----
    def get_poundage_report(self, allocation_cycle_id, headers):
        return self._request(
            "GET", f"/poundage-reports/{allocation_cycle_id}", headers=headers,
        )

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
