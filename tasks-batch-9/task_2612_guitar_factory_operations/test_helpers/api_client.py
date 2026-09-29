"""
HTTP client for the guitar factory operations API.

One method per documented endpoint. Every method returns the raw
`requests.Response` so a test can assert on the status code as well as on the
body. Auth headers are always explicit, because who acts decides the outcome of
several rules — independent sign-off, measurement ownership and the
entity-backed shop identity among them.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .types import ApiResponse, Headers, JsonDict, Params


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the guitar factory API."""

    # ------------------------------------------------------------------
    # Logical shop clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload: JsonDict, headers: Headers = None) -> ApiResponse:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Storage rooms
    # ------------------------------------------------------------------
    def create_storage_room(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/storage-rooms", payload, headers)

    def get_storage_room(self, room_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/storage-rooms/{room_id}", headers=headers)

    def list_storage_rooms(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/storage-rooms", headers=headers, params=params)

    def create_climate_reading(self, room_id: str, payload: JsonDict,
                               headers: Headers) -> ApiResponse:
        return self._request("POST", f"/storage-rooms/{room_id}/climate-readings",
                             payload, headers)

    def certify_storage_room(self, room_id: str, headers: Headers,
                             payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/storage-rooms/{room_id}/certify",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Tonewood lots
    # ------------------------------------------------------------------
    def create_tonewood_lot(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/tonewood-lots", payload, headers)

    def get_tonewood_lot(self, lot_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/tonewood-lots/{lot_id}", headers=headers)

    def list_tonewood_lots(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/tonewood-lots", headers=headers, params=params)

    def attest_permit(self, lot_id: str, payload: JsonDict,
                      headers: Headers) -> ApiResponse:
        return self._request("POST", f"/tonewood-lots/{lot_id}/attest-permit",
                             payload, headers)

    def reject_tonewood_lot(self, lot_id: str, headers: Headers,
                            payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/tonewood-lots/{lot_id}/reject",
                             payload if payload is not None else {}, headers)

    def create_moisture_reading(self, lot_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request("POST", f"/tonewood-lots/{lot_id}/moisture-readings",
                             payload, headers)

    def condition_tonewood_lot(self, lot_id: str, headers: Headers,
                               payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/tonewood-lots/{lot_id}/condition",
                             payload if payload is not None else {}, headers)

    def release_tonewood_lot(self, lot_id: str, headers: Headers,
                             payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/tonewood-lots/{lot_id}/release",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Billets
    # ------------------------------------------------------------------
    def create_billet(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/billets", payload, headers)

    def get_billet(self, billet_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/billets/{billet_id}", headers=headers)

    def list_billets(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/billets", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Component specifications
    # ------------------------------------------------------------------
    def create_component_spec(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/component-specs", payload, headers)

    def get_component_spec(self, spec_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/component-specs/{spec_id}", headers=headers)

    def list_component_specs(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/component-specs", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Components
    # ------------------------------------------------------------------
    def create_component(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/components", payload, headers)

    def get_component(self, component_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/components/{component_id}", headers=headers)

    def list_components(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/components", headers=headers, params=params)

    def route_component(self, component_id: str, payload: JsonDict,
                        headers: Headers) -> ApiResponse:
        return self._request("POST", f"/components/{component_id}/route", payload, headers)

    def hand_shape_component(self, component_id: str, payload: JsonDict,
                             headers: Headers) -> ApiResponse:
        return self._request("POST", f"/components/{component_id}/hand-shape",
                             payload, headers)

    def qc_component(self, component_id: str, payload: JsonDict,
                     headers: Headers) -> ApiResponse:
        return self._request("POST", f"/components/{component_id}/qc", payload, headers)

    def disposition_component(self, component_id: str, payload: JsonDict,
                              headers: Headers) -> ApiResponse:
        return self._request("POST", f"/components/{component_id}/disposition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Stations and station reservations
    # ------------------------------------------------------------------
    def create_station(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/stations", headers=headers, params=params)

    def get_next_build_order(self, station_id: str, headers: Headers,
                             params: Params = None) -> ApiResponse:
        return self._request("GET", f"/stations/{station_id}/next-build-order",
                             headers=headers, params=params)

    def create_station_reservation(self, payload: JsonDict,
                                   headers: Headers) -> ApiResponse:
        return self._request("POST", "/station-reservations", payload, headers)

    def get_station_reservation(self, reservation_id: str,
                                headers: Headers) -> ApiResponse:
        return self._request("GET", f"/station-reservations/{reservation_id}",
                             headers=headers)

    def list_station_reservations(self, headers: Headers,
                                  params: Params = None) -> ApiResponse:
        return self._request("GET", "/station-reservations", headers=headers,
                             params=params)

    def release_station_reservation(self, reservation_id: str, headers: Headers,
                                    payload: JsonDict = None) -> ApiResponse:
        return self._request("POST",
                             f"/station-reservations/{reservation_id}/release",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Option catalog
    # ------------------------------------------------------------------
    def create_option(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/option-catalog", payload, headers)

    def get_option(self, option_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/option-catalog/{option_id}", headers=headers)

    def list_options(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/option-catalog", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Build orders
    # ------------------------------------------------------------------
    def create_build_order(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/build-orders", payload, headers)

    def get_build_order(self, build_order_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/build-orders/{build_order_id}", headers=headers)

    def list_build_orders(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/build-orders", headers=headers, params=params)

    def create_option_selection(self, build_order_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/build-orders/{build_order_id}/option-selections",
                             payload, headers)

    def confirm_build_order(self, build_order_id: str, payload: JsonDict,
                            headers: Headers) -> ApiResponse:
        return self._request("POST", f"/build-orders/{build_order_id}/confirm",
                             payload, headers)

    def lock_options(self, build_order_id: str, headers: Headers,
                     payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/build-orders/{build_order_id}/lock-options",
                             payload if payload is not None else {}, headers)

    def release_components(self, build_order_id: str, headers: Headers,
                           payload: JsonDict = None) -> ApiResponse:
        return self._request("POST",
                             f"/build-orders/{build_order_id}/release-components",
                             payload if payload is not None else {}, headers)

    def start_assembly(self, build_order_id: str, headers: Headers,
                       payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/build-orders/{build_order_id}/start-assembly",
                             payload if payload is not None else {}, headers)

    def record_fretwork(self, build_order_id: str, headers: Headers,
                        payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/build-orders/{build_order_id}/fretwork",
                             payload if payload is not None else {}, headers)

    def record_setup(self, build_order_id: str, headers: Headers,
                     payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/build-orders/{build_order_id}/setup",
                             payload if payload is not None else {}, headers)

    def open_setup_inspection(self, build_order_id: str, headers: Headers,
                              payload: JsonDict = None) -> ApiResponse:
        return self._request("POST",
                             f"/build-orders/{build_order_id}/setup-inspections",
                             payload if payload is not None else {}, headers)

    def assign_serial(self, build_order_id: str, headers: Headers,
                      payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/build-orders/{build_order_id}/assign-serial",
                             payload if payload is not None else {}, headers)

    def clear_compliance_hold(self, build_order_id: str, headers: Headers,
                              payload: JsonDict = None) -> ApiResponse:
        return self._request("POST",
                             f"/build-orders/{build_order_id}/clear-compliance-hold",
                             payload if payload is not None else {}, headers)

    def cancel_build_order(self, build_order_id: str, headers: Headers,
                           payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/build-orders/{build_order_id}/cancel",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Option selections
    # ------------------------------------------------------------------
    def get_option_selection(self, selection_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/option-selections/{selection_id}", headers=headers)

    def list_option_selections(self, headers: Headers,
                               params: Params = None) -> ApiResponse:
        return self._request("GET", "/option-selections", headers=headers, params=params)

    def approve_option_selection(self, selection_id: str, headers: Headers,
                                 payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/option-selections/{selection_id}/approve",
                             payload if payload is not None else {}, headers)

    def reject_option_selection(self, selection_id: str, headers: Headers,
                                payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/option-selections/{selection_id}/reject",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Finish runs
    # ------------------------------------------------------------------
    def create_finish_run(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/finish-runs", payload, headers)

    def get_finish_run(self, finish_run_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/finish-runs/{finish_run_id}", headers=headers)

    def list_finish_runs(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/finish-runs", headers=headers, params=params)

    def complete_spray(self, finish_run_id: str, headers: Headers,
                       payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/finish-runs/{finish_run_id}/complete-spray",
                             payload if payload is not None else {}, headers)

    def resume_cure(self, finish_run_id: str, headers: Headers,
                    payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/finish-runs/{finish_run_id}/resume-cure",
                             payload if payload is not None else {}, headers)

    def buff_finish_run(self, finish_run_id: str, headers: Headers,
                        payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/finish-runs/{finish_run_id}/buff",
                             payload if payload is not None else {}, headers)

    def complete_finish_run(self, finish_run_id: str, headers: Headers,
                            payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/finish-runs/{finish_run_id}/complete",
                             payload if payload is not None else {}, headers)

    def reject_finish_run(self, finish_run_id: str, headers: Headers,
                          payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/finish-runs/{finish_run_id}/reject",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Setup inspections
    # ------------------------------------------------------------------
    def get_setup_inspection(self, inspection_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/setup-inspections/{inspection_id}",
                             headers=headers)

    def list_setup_inspections(self, headers: Headers,
                               params: Params = None) -> ApiResponse:
        return self._request("GET", "/setup-inspections", headers=headers, params=params)

    def measure_setup_inspection(self, inspection_id: str, payload: JsonDict,
                                 headers: Headers) -> ApiResponse:
        return self._request("POST", f"/setup-inspections/{inspection_id}/measure",
                             payload, headers)

    def sign_setup_inspection(self, inspection_id: str, headers: Headers,
                              payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/setup-inspections/{inspection_id}/sign",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Repair shops
    # ------------------------------------------------------------------
    def create_repair_shop(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/repair-shops", payload, headers)

    def get_repair_shop(self, shop_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/repair-shops/{shop_id}", headers=headers)

    def list_repair_shops(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/repair-shops", headers=headers, params=params)

    def authorize_repair_shop(self, shop_id: str, payload: JsonDict,
                              headers: Headers) -> ApiResponse:
        return self._request("POST", f"/repair-shops/{shop_id}/authorize",
                             payload, headers)

    def suspend_repair_shop(self, shop_id: str, headers: Headers,
                            payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/repair-shops/{shop_id}/suspend",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Warranty registrations
    # ------------------------------------------------------------------
    def create_warranty_registration(self, payload: JsonDict,
                                     headers: Headers) -> ApiResponse:
        return self._request("POST", "/warranty-registrations", payload, headers)

    def get_warranty_registration(self, registration_id: str,
                                  headers: Headers) -> ApiResponse:
        return self._request("GET", f"/warranty-registrations/{registration_id}",
                             headers=headers)

    def list_warranty_registrations(self, headers: Headers,
                                    params: Params = None) -> ApiResponse:
        return self._request("GET", "/warranty-registrations", headers=headers,
                             params=params)

    def void_warranty_registration(self, registration_id: str, headers: Headers,
                                   payload: JsonDict = None) -> ApiResponse:
        return self._request("POST",
                             f"/warranty-registrations/{registration_id}/void",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Export shipments
    # ------------------------------------------------------------------
    def create_export_shipment(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/export-shipments", payload, headers)

    def get_export_shipment(self, shipment_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/export-shipments/{shipment_id}", headers=headers)

    def list_export_shipments(self, headers: Headers,
                              params: Params = None) -> ApiResponse:
        return self._request("GET", "/export-shipments", headers=headers, params=params)

    def attach_docs(self, shipment_id: str, headers: Headers,
                    payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/export-shipments/{shipment_id}/attach-docs",
                             payload if payload is not None else {}, headers)

    def reject_docs(self, shipment_id: str, payload: JsonDict,
                    headers: Headers) -> ApiResponse:
        return self._request("POST", f"/export-shipments/{shipment_id}/reject-docs",
                             payload, headers)

    def release_export_shipment(self, shipment_id: str, headers: Headers,
                                payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/export-shipments/{shipment_id}/release",
                             payload if payload is not None else {}, headers)

    def depart_export_shipment(self, shipment_id: str, headers: Headers,
                               payload: JsonDict = None) -> ApiResponse:
        return self._request("POST", f"/export-shipments/{shipment_id}/depart",
                             payload if payload is not None else {}, headers)
