"""Typed HTTP client: one method per documented endpoint.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as the body.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint of the assembly plant API."""

    # =========================================================================
    # Logical clock
    # =========================================================================
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # =========================================================================
    # Lines
    # =========================================================================
    def create_line(self, payload: dict, headers: dict):
        return self._request("POST", "/lines", payload, headers)

    def get_line(self, line_id: str, headers: dict):
        return self._request("GET", f"/lines/{line_id}", headers=headers)

    def stop_line(self, line_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/lines/{line_id}/stop", payload, headers)

    def start_line(self, line_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/lines/{line_id}/start", payload, headers)

    def run_checkpoint(self, line_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/lines/{line_id}/run-checkpoint", payload or {}, headers
        )

    # =========================================================================
    # Stations
    # =========================================================================
    def create_station(self, payload: dict, headers: dict):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id: str, headers: dict):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_line_stations(self, line_id: str, headers: dict,
                           params: Optional[dict] = None):
        return self._request(
            "GET", f"/lines/{line_id}/stations", headers=headers, params=params
        )

    # =========================================================================
    # Model variants
    # =========================================================================
    def create_model_variant(self, payload: dict, headers: dict):
        return self._request("POST", "/model-variants", payload, headers)

    def get_model_variant(self, variant_id: str, headers: dict):
        return self._request("GET", f"/model-variants/{variant_id}", headers=headers)

    def release_model_variant(self, variant_id: str, headers: dict,
                              payload: Optional[dict] = None):
        return self._request(
            "POST", f"/model-variants/{variant_id}/release", payload or {}, headers
        )

    def obsolete_model_variant(self, variant_id: str, headers: dict,
                               payload: Optional[dict] = None):
        return self._request(
            "POST", f"/model-variants/{variant_id}/obsolete", payload or {}, headers
        )

    # =========================================================================
    # Suppliers
    # =========================================================================
    def create_supplier(self, payload: dict, headers: dict):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id: str, headers: dict):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    # =========================================================================
    # Parts
    # =========================================================================
    def create_part(self, payload: dict, headers: dict):
        return self._request("POST", "/parts", payload, headers)

    def get_part(self, part_id: str, headers: dict):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def list_parts(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def obsolete_part(self, part_id: str, headers: dict,
                      payload: Optional[dict] = None):
        return self._request(
            "POST", f"/parts/{part_id}/obsolete", payload or {}, headers
        )

    def get_warranty_metrics(self, part_id: str, headers: dict):
        return self._request(
            "GET", f"/parts/{part_id}/warranty-metrics", headers=headers
        )

    # =========================================================================
    # Bill-of-materials lines
    # =========================================================================
    def create_bom_line(self, payload: dict, headers: dict):
        return self._request("POST", "/bom-lines", payload, headers)

    def get_bom_line(self, bom_line_id: str, headers: dict):
        return self._request("GET", f"/bom-lines/{bom_line_id}", headers=headers)

    def list_bom_lines(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/bom-lines", headers=headers, params=params)

    # =========================================================================
    # Delivery calls
    # =========================================================================
    def create_delivery_call(self, payload: dict, headers: dict):
        return self._request("POST", "/delivery-calls", payload, headers)

    def get_delivery_call(self, call_id: str, headers: dict):
        return self._request("GET", f"/delivery-calls/{call_id}", headers=headers)

    def list_delivery_calls(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/delivery-calls", headers=headers, params=params)

    def record_arrival(self, call_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/delivery-calls/{call_id}/record-arrival", payload, headers
        )

    def cancel_delivery_call(self, call_id: str, headers: dict,
                             payload: Optional[dict] = None):
        return self._request(
            "POST", f"/delivery-calls/{call_id}/cancel", payload or {}, headers
        )

    # =========================================================================
    # Shift plans
    # =========================================================================
    def create_shift_plan(self, payload: dict, headers: dict):
        return self._request("POST", "/shift-plans", payload, headers)

    def get_shift_plan(self, plan_id: str, headers: dict):
        return self._request("GET", f"/shift-plans/{plan_id}", headers=headers)

    def list_line_shift_plans(self, line_id: str, headers: dict,
                              params: Optional[dict] = None):
        return self._request(
            "GET", f"/lines/{line_id}/shift-plans", headers=headers, params=params
        )

    # =========================================================================
    # Build slots
    # =========================================================================
    def create_build_slot(self, payload: dict, headers: dict):
        return self._request("POST", "/build-slots", payload, headers)

    def get_build_slot(self, slot_id: str, headers: dict):
        return self._request("GET", f"/build-slots/{slot_id}", headers=headers)

    def list_build_slots(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/build-slots", headers=headers, params=params)

    def sequence_build_slot(self, slot_id: str, headers: dict,
                            payload: Optional[dict] = None):
        return self._request(
            "POST", f"/build-slots/{slot_id}/sequence", payload or {}, headers
        )

    def de_sequence_build_slot(self, slot_id: str, headers: dict,
                               payload: Optional[dict] = None):
        return self._request(
            "POST", f"/build-slots/{slot_id}/de-sequence", payload or {}, headers
        )

    def release_build_slot(self, slot_id: str, headers: dict,
                           payload: Optional[dict] = None):
        return self._request(
            "POST", f"/build-slots/{slot_id}/release", payload or {}, headers
        )

    # =========================================================================
    # Production units
    # =========================================================================
    def get_production_unit(self, unit_id: str, headers: dict):
        return self._request("GET", f"/production-units/{unit_id}", headers=headers)

    def list_production_units(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", "/production-units", headers=headers, params=params
        )

    def record_quality_test(self, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/production-units/{unit_id}/quality-tests", payload, headers
        )

    def list_quality_tests(self, unit_id: str, headers: dict,
                           params: Optional[dict] = None):
        return self._request(
            "GET", f"/production-units/{unit_id}/quality-tests",
            headers=headers, params=params,
        )

    def clear_quarantine(self, unit_id: str, headers: dict,
                         payload: Optional[dict] = None):
        return self._request(
            "POST", f"/production-units/{unit_id}/clear-quarantine",
            payload or {}, headers,
        )

    def certify_unit(self, unit_id: str, headers: dict,
                     payload: Optional[dict] = None):
        return self._request(
            "POST", f"/production-units/{unit_id}/certify", payload or {}, headers
        )

    def complete_assembly(self, unit_id: str, headers: dict,
                          payload: Optional[dict] = None):
        return self._request(
            "POST", f"/production-units/{unit_id}/complete-assembly",
            payload or {}, headers,
        )

    def ship_unit(self, unit_id: str, headers: dict,
                  payload: Optional[dict] = None):
        return self._request(
            "POST", f"/production-units/{unit_id}/ship", payload or {}, headers
        )

    # =========================================================================
    # Engineering changes
    # =========================================================================
    def create_engineering_change(self, payload: dict, headers: dict):
        return self._request("POST", "/engineering-changes", payload, headers)

    def get_engineering_change(self, change_id: str, headers: dict):
        return self._request(
            "GET", f"/engineering-changes/{change_id}", headers=headers
        )

    def list_engineering_changes(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", "/engineering-changes", headers=headers, params=params
        )

    def submit_engineering_change(self, change_id: str, headers: dict,
                                  payload: Optional[dict] = None):
        return self._request(
            "POST", f"/engineering-changes/{change_id}/submit", payload or {}, headers
        )

    def start_review_engineering_change(self, change_id: str, headers: dict,
                                        payload: Optional[dict] = None):
        return self._request(
            "POST", f"/engineering-changes/{change_id}/start-review",
            payload or {}, headers,
        )

    def decide_engineering_change(self, change_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/engineering-changes/{change_id}/decide", payload, headers
        )

    def cut_in_engineering_change(self, change_id: str, headers: dict,
                                  payload: Optional[dict] = None):
        return self._request(
            "POST", f"/engineering-changes/{change_id}/cut-in", payload or {}, headers
        )

    # =========================================================================
    # Warranty returns
    # =========================================================================
    def create_warranty_return(self, payload: dict, headers: dict):
        return self._request("POST", "/warranty-returns", payload, headers)

    def get_warranty_return(self, return_id: str, headers: dict):
        return self._request("GET", f"/warranty-returns/{return_id}", headers=headers)

    def list_warranty_returns(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", "/warranty-returns", headers=headers, params=params
        )

    def teardown_warranty_return(self, return_id: str, headers: dict,
                                 payload: Optional[dict] = None):
        return self._request(
            "POST", f"/warranty-returns/{return_id}/teardown", payload or {}, headers
        )

    def analyze_warranty_return(self, return_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/warranty-returns/{return_id}/analyze", payload, headers
        )

    def close_warranty_return(self, return_id: str, headers: dict,
                              payload: Optional[dict] = None):
        return self._request(
            "POST", f"/warranty-returns/{return_id}/close", payload or {}, headers
        )

    def withdraw_warranty_return(self, return_id: str, headers: dict,
                                 payload: Optional[dict] = None):
        return self._request(
            "POST", f"/warranty-returns/{return_id}/withdraw", payload or {}, headers
        )


#: Shared module-level client instance.
api_client = ApiClient()
