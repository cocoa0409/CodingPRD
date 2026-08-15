"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- system clock (test-driving) ---
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/ltl/_clock/set_current_utc", payload, headers)

    # --- Terminal ---
    def create_terminal(self, payload, headers=None):
        return self._request("POST", "/ltl/terminals", payload, headers)

    def list_terminals(self, headers=None, params=None):
        return self._request("GET", "/ltl/terminals", headers=headers, params=params)

    def get_terminal(self, terminal_id, headers=None):
        return self._request("GET", f"/ltl/terminals/{terminal_id}", headers=headers)

    def close_terminal(self, terminal_id, headers=None):
        return self._request("POST", f"/ltl/terminals/{terminal_id}/close", {}, headers)

    # --- Shipment ---
    def create_shipment(self, payload, headers=None):
        return self._request("POST", "/ltl/shipments", payload, headers)

    def list_shipments(self, headers=None, params=None):
        return self._request("GET", "/ltl/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers=None):
        return self._request("GET", f"/ltl/shipments/{shipment_id}", headers=headers)

    def rate_shipment(self, shipment_id, headers=None):
        return self._request("POST", f"/ltl/shipments/{shipment_id}/rate", {}, headers)

    def bill_shipment(self, shipment_id, headers=None):
        return self._request("POST", f"/ltl/shipments/{shipment_id}/bill", {}, headers)

    def cancel_shipment(self, shipment_id, headers=None):
        return self._request("POST", f"/ltl/shipments/{shipment_id}/cancel", {}, headers)

    # --- PickupRoute / PickupStop ---
    def create_pickup_route(self, payload, headers=None):
        return self._request("POST", "/ltl/pickup-routes", payload, headers)

    def list_pickup_routes(self, headers=None, params=None):
        return self._request("GET", "/ltl/pickup-routes", headers=headers, params=params)

    def get_pickup_route(self, route_id, headers=None):
        return self._request("GET", f"/ltl/pickup-routes/{route_id}", headers=headers)

    def dispatch_route(self, route_id, headers=None):
        return self._request("POST", f"/ltl/pickup-routes/{route_id}/dispatch", {}, headers)

    def recall_route(self, route_id, headers=None):
        return self._request("POST", f"/ltl/pickup-routes/{route_id}/recall", {}, headers)

    def create_pickup_stop(self, payload, headers=None):
        return self._request("POST", "/ltl/pickup-stops", payload, headers)

    def list_route_stops(self, route_id, headers=None, params=None):
        return self._request(
            "GET", f"/ltl/pickup-routes/{route_id}/stops", headers=headers, params=params
        )

    def get_pickup_stop(self, stop_id, headers=None):
        return self._request("GET", f"/ltl/pickup-stops/{stop_id}", headers=headers)

    def list_pickup_stops(self, headers=None, params=None):
        return self._request("GET", "/ltl/pickup-stops", headers=headers, params=params)

    def arrive_stop(self, stop_id, headers=None):
        return self._request("POST", f"/ltl/pickup-stops/{stop_id}/arrive", {}, headers)

    def complete_stop(self, stop_id, headers=None):
        return self._request("POST", f"/ltl/pickup-stops/{stop_id}/complete", {}, headers)

    def skip_stop(self, stop_id, headers=None):
        return self._request("POST", f"/ltl/pickup-stops/{stop_id}/skip", {}, headers)

    # --- DockDoor ---
    def create_dock_door(self, payload, headers=None):
        return self._request("POST", "/ltl/dock-doors", payload, headers)

    def list_dock_doors(self, headers=None, params=None):
        return self._request("GET", "/ltl/dock-doors", headers=headers, params=params)

    def get_dock_door(self, door_id, headers=None):
        return self._request("GET", f"/ltl/dock-doors/{door_id}", headers=headers)

    def reserve_door(self, door_id, headers=None):
        return self._request("POST", f"/ltl/dock-doors/{door_id}/reserve", {}, headers)

    def occupy_door(self, door_id, headers=None):
        return self._request("POST", f"/ltl/dock-doors/{door_id}/occupy", {}, headers)

    def release_door(self, door_id, headers=None):
        return self._request("POST", f"/ltl/dock-doors/{door_id}/release", {}, headers)

    def take_door_out_of_service(self, door_id, headers=None):
        return self._request(
            "POST", f"/ltl/dock-doors/{door_id}/take-out-of-service", {}, headers
        )

    def return_door_to_service(self, door_id, headers=None):
        return self._request(
            "POST", f"/ltl/dock-doors/{door_id}/return-to-service", {}, headers
        )

    # --- SortationBatch ---
    def create_sortation_batch(self, payload, headers=None):
        return self._request("POST", "/ltl/sortation-batches", payload, headers)

    def list_sortation_batches(self, headers=None, params=None):
        return self._request("GET", "/ltl/sortation-batches", headers=headers, params=params)

    def get_sortation_batch(self, batch_id, headers=None):
        return self._request("GET", f"/ltl/sortation-batches/{batch_id}", headers=headers)

    def close_batch(self, batch_id, headers=None):
        return self._request("POST", f"/ltl/sortation-batches/{batch_id}/close", {}, headers)

    def disposition_batch(self, batch_id, headers=None):
        return self._request(
            "POST", f"/ltl/sortation-batches/{batch_id}/disposition", {}, headers
        )

    # --- OutboundTrailer / ManifestEntry ---
    def create_trailer(self, payload, headers=None):
        return self._request("POST", "/ltl/trailers", payload, headers)

    def list_trailers(self, headers=None, params=None):
        return self._request("GET", "/ltl/trailers", headers=headers, params=params)

    def get_trailer(self, trailer_id, headers=None):
        return self._request("GET", f"/ltl/trailers/{trailer_id}", headers=headers)

    def create_manifest_entry(self, trailer_id, payload, headers=None):
        return self._request(
            "POST", f"/ltl/trailers/{trailer_id}/manifest-entries", payload, headers
        )

    def list_trailer_manifest_entries(self, trailer_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/ltl/trailers/{trailer_id}/manifest-entries",
            headers=headers,
            params=params,
        )

    def list_manifest_entries(self, headers=None, params=None):
        return self._request("GET", "/ltl/manifest-entries", headers=headers, params=params)

    def get_manifest_entry(self, entry_id, headers=None):
        return self._request("GET", f"/ltl/manifest-entries/{entry_id}", headers=headers)

    def remove_manifest_entry(self, entry_id, headers=None):
        return self._request(
            "POST", f"/ltl/manifest-entries/{entry_id}/remove", {}, headers
        )

    def mark_trailer_ready(self, trailer_id, headers=None):
        return self._request("POST", f"/ltl/trailers/{trailer_id}/mark-ready", {}, headers)

    def seal_trailer(self, trailer_id, payload, headers=None):
        return self._request("POST", f"/ltl/trailers/{trailer_id}/seal", payload, headers)

    def reopen_trailer(self, trailer_id, headers=None):
        return self._request("POST", f"/ltl/trailers/{trailer_id}/reopen", {}, headers)

    def void_trailer(self, trailer_id, headers=None):
        return self._request("POST", f"/ltl/trailers/{trailer_id}/void", {}, headers)

    # --- LinehaulLeg ---
    def create_linehaul_leg(self, payload, headers=None):
        return self._request("POST", "/ltl/linehaul-legs", payload, headers)

    def list_linehaul_legs(self, headers=None, params=None):
        return self._request("GET", "/ltl/linehaul-legs", headers=headers, params=params)

    def get_linehaul_leg(self, leg_id, headers=None):
        return self._request("GET", f"/ltl/linehaul-legs/{leg_id}", headers=headers)

    def depart_leg(self, leg_id, headers=None):
        return self._request("POST", f"/ltl/linehaul-legs/{leg_id}/depart", {}, headers)

    def arrive_leg(self, leg_id, headers=None):
        return self._request("POST", f"/ltl/linehaul-legs/{leg_id}/arrive", {}, headers)

    def cancel_leg(self, leg_id, headers=None):
        return self._request("POST", f"/ltl/linehaul-legs/{leg_id}/cancel", {}, headers)

    # --- DimensionerScan / Inspection ---
    def create_dimensioner_scan(self, payload, headers=None):
        return self._request("POST", "/ltl/dimensioner-scans", payload, headers)

    def list_shipment_dimensioner_scans(self, shipment_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/ltl/shipments/{shipment_id}/dimensioner-scans",
            headers=headers,
            params=params,
        )

    def get_dimensioner_scan(self, scan_id, headers=None):
        return self._request("GET", f"/ltl/dimensioner-scans/{scan_id}", headers=headers)

    def list_dimensioner_scans(self, headers=None, params=None):
        return self._request("GET", "/ltl/dimensioner-scans", headers=headers, params=params)

    def create_inspection(self, payload, headers=None):
        return self._request("POST", "/ltl/inspections", payload, headers)

    def list_shipment_inspections(self, shipment_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/ltl/shipments/{shipment_id}/inspections",
            headers=headers,
            params=params,
        )

    def get_inspection(self, inspection_id, headers=None):
        return self._request("GET", f"/ltl/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers=None, params=None):
        return self._request("GET", "/ltl/inspections", headers=headers, params=params)

    def confirm_inspection(self, inspection_id, headers=None):
        return self._request(
            "POST", f"/ltl/inspections/{inspection_id}/confirm", {}, headers
        )

    def reject_inspection(self, inspection_id, headers=None):
        return self._request(
            "POST", f"/ltl/inspections/{inspection_id}/reject", {}, headers
        )

    # --- OsdCase ---
    def create_osd_case(self, payload, headers=None):
        return self._request("POST", "/ltl/osd-cases", payload, headers)

    def list_osd_cases(self, headers=None, params=None):
        return self._request("GET", "/ltl/osd-cases", headers=headers, params=params)

    def get_osd_case(self, case_id, headers=None):
        return self._request("GET", f"/ltl/osd-cases/{case_id}", headers=headers)

    def review_osd_case(self, case_id, headers=None):
        return self._request("POST", f"/ltl/osd-cases/{case_id}/review", {}, headers)

    def resolve_osd_case(self, case_id, headers=None):
        return self._request("POST", f"/ltl/osd-cases/{case_id}/resolve", {}, headers)

    def deny_osd_case(self, case_id, headers=None):
        return self._request("POST", f"/ltl/osd-cases/{case_id}/deny", {}, headers)

    # --- ServiceStandardReport ---
    def create_service_standard_report(self, terminal_id, payload, headers=None):
        return self._request(
            "POST",
            f"/ltl/terminals/{terminal_id}/service-standard-reports",
            payload,
            headers,
        )

    def list_terminal_service_standard_reports(self, terminal_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/ltl/terminals/{terminal_id}/service-standard-reports",
            headers=headers,
            params=params,
        )

    def get_service_standard_report(self, report_id, headers=None):
        return self._request(
            "GET", f"/ltl/service-standard-reports/{report_id}", headers=headers
        )

    def list_service_standard_reports(self, headers=None, params=None):
        return self._request(
            "GET", "/ltl/service-standard-reports", headers=headers, params=params
        )


api_client = ApiClient()
