"""API client: one method per endpoint defined in the PRD.

The whole API is mounted under the /traceability prefix. Each method delegates
to the inherited GenericApiClient._request().
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/traceability/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/traceability/facilities/{facility_id}", headers=headers)

    def advance_clock(self, facility_id, payload, headers):
        return self._request("POST", f"/traceability/facilities/{facility_id}/clock", payload, headers)

    # --- Supplier ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/traceability/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/traceability/suppliers/{supplier_id}", headers=headers)

    def list_facility_suppliers(self, facility_id, headers, params=None):
        return self._request("GET", f"/traceability/facilities/{facility_id}/suppliers", headers=headers, params=params)

    # --- Ingredient ---
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/traceability/ingredients", payload, headers)

    def list_facility_ingredients(self, facility_id, headers, params=None):
        return self._request("GET", f"/traceability/facilities/{facility_id}/ingredients", headers=headers, params=params)

    # --- AllergenProfile ---
    def create_allergen_profile(self, payload, headers):
        return self._request("POST", "/traceability/allergen-profiles", payload, headers)

    def list_facility_allergen_profiles(self, facility_id, headers, params=None):
        return self._request("GET", f"/traceability/facilities/{facility_id}/allergen-profiles", headers=headers, params=params)

    # --- Lot ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/traceability/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/traceability/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/traceability/lots", headers=headers, params=params)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/traceability/lots/{lot_id}/release", {}, headers)

    def reject_lot(self, lot_id, headers):
        return self._request("POST", f"/traceability/lots/{lot_id}/reject", {}, headers)

    def recall_trace(self, lot_id, headers):
        return self._request("GET", f"/traceability/lots/{lot_id}/recall-trace", headers=headers)

    def list_lot_ccp_readings(self, lot_id, headers, params=None):
        return self._request("GET", f"/traceability/lots/{lot_id}/ccp-readings", headers=headers, params=params)

    # --- Certificate of Analysis ---
    def create_coa(self, payload, headers):
        return self._request("POST", "/traceability/coa", payload, headers)

    def get_coa(self, coa_id, headers):
        return self._request("GET", f"/traceability/coa/{coa_id}", headers=headers)

    def list_coa(self, headers, params=None):
        return self._request("GET", "/traceability/coa", headers=headers, params=params)

    def decide_coa(self, coa_id, payload, headers):
        return self._request("POST", f"/traceability/coa/{coa_id}/decide", payload, headers)

    # --- Production Run + Consumed Lots ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/traceability/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/traceability/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/traceability/production-runs", headers=headers, params=params)

    def add_consumed_lot(self, run_id, payload, headers):
        return self._request("POST", f"/traceability/production-runs/{run_id}/consumed-lots", payload, headers)

    def get_consumed_lot(self, consumed_lot_id, headers):
        return self._request("GET", f"/traceability/consumed-lots/{consumed_lot_id}", headers=headers)

    def list_consumed_lots(self, headers, params=None):
        return self._request("GET", "/traceability/consumed-lots", headers=headers, params=params)

    def finalize_production_run(self, run_id, payload, headers):
        return self._request("POST", f"/traceability/production-runs/{run_id}/finalize", payload, headers)

    def abort_production_run(self, run_id, headers):
        return self._request("POST", f"/traceability/production-runs/{run_id}/abort", {}, headers)

    # --- CCP Readings ---
    def create_ccp_reading(self, payload, headers):
        return self._request("POST", "/traceability/ccp-readings", payload, headers)

    # --- Hold Orders ---
    def create_hold_order(self, payload, headers):
        return self._request("POST", "/traceability/hold-orders", payload, headers)

    def get_hold_order(self, hold_id, headers):
        return self._request("GET", f"/traceability/hold-orders/{hold_id}", headers=headers)

    def list_hold_orders(self, headers, params=None):
        return self._request("GET", "/traceability/hold-orders", headers=headers, params=params)

    def resolve_hold_order(self, hold_id, payload, headers):
        return self._request("POST", f"/traceability/hold-orders/{hold_id}/resolve", payload, headers)

    # --- Storage Zones + Bookings ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/traceability/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/traceability/zones/{zone_id}", headers=headers)

    def list_facility_zones(self, facility_id, headers, params=None):
        return self._request("GET", f"/traceability/facilities/{facility_id}/zones", headers=headers, params=params)

    def create_booking(self, zone_id, payload, headers):
        return self._request("POST", f"/traceability/zones/{zone_id}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/traceability/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/traceability/bookings", headers=headers, params=params)


api_client = ApiClient()
