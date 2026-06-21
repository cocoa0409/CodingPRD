"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Carriers ----
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def patch_carrier(self, carrier_id, payload, headers):
        return self._request("PATCH", f"/carriers/{carrier_id}", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    # ---- ReeferUnits ----
    def create_reefer_unit(self, payload, headers):
        return self._request("POST", "/reefer-units", payload, headers)

    def get_reefer_unit(self, unit_id, headers):
        return self._request("GET", f"/reefer-units/{unit_id}", headers=headers)

    def list_reefer_units(self, headers, params=None):
        return self._request("GET", "/reefer-units", headers=headers, params=params)

    def patch_reefer_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/reefer-units/{unit_id}", payload, headers)

    def retire_reefer_unit(self, unit_id, headers):
        return self._request("DELETE", f"/reefer-units/{unit_id}", headers=headers)

    # ---- TempLanes ----
    def create_temp_lane(self, payload, headers):
        return self._request("POST", "/temp-lanes", payload, headers)

    def get_temp_lane(self, lane_id, headers):
        return self._request("GET", f"/temp-lanes/{lane_id}", headers=headers)

    def list_temp_lanes(self, headers, params=None):
        return self._request("GET", "/temp-lanes", headers=headers, params=params)

    # ---- Shipments ----
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def accept_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/accept", payload, headers)

    def reject_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/reject", {}, headers)

    def precool_verify_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/precool-verify", {}, headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/cancel", {}, headers)

    def get_integrity_report(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}/integrity-report", headers=headers)

    # ---- Compartments ----
    def create_compartment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/compartments", payload, headers)

    def get_compartment(self, compartment_id, headers):
        return self._request("GET", f"/compartments/{compartment_id}", headers=headers)

    def list_compartments(self, headers, params=None):
        return self._request("GET", "/compartments", headers=headers, params=params)

    def get_excursion_report(self, compartment_id, headers):
        return self._request("GET", f"/compartments/{compartment_id}/excursion-report", headers=headers)

    # ---- SensorReadings ----
    def create_reading(self, compartment_id, payload, headers):
        return self._request("POST", f"/compartments/{compartment_id}/readings", payload, headers)

    def get_reading(self, reading_id, headers):
        return self._request("GET", f"/sensor-readings/{reading_id}", headers=headers)

    def list_readings(self, headers, params=None):
        return self._request("GET", "/sensor-readings", headers=headers, params=params)

    # ---- ProductLots ----
    def create_lot(self, compartment_id, payload, headers):
        return self._request("POST", f"/compartments/{compartment_id}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/product-lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/product-lots", headers=headers, params=params)

    # ---- StopEvents ----
    def create_stop(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/stops", payload, headers)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}", headers=headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/stops", headers=headers, params=params)

    def arrive_stop(self, shipment_id, stop_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/stops/{stop_id}/arrive", payload, headers)

    def close_stop(self, shipment_id, stop_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/stops/{stop_id}/close", payload, headers)

    # ---- SpoilageClaims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/spoilage-claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/spoilage-claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/spoilage-claims", headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/spoilage-claims/{claim_id}/review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/spoilage-claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/spoilage-claims/{claim_id}/deny", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/spoilage-claims/{claim_id}/withdraw", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
