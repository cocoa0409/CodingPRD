"""API client: one method per endpoint defined in the Medical Courier PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/med-courier"


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.9) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- RateCard ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"{PREFIX}/rate-cards/{rate_card_id}", headers=headers)

    # --- LabClient ---
    def create_lab_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lab-clients", payload, headers)

    def get_lab_client(self, lab_client_id, headers):
        return self._request("GET", f"{PREFIX}/lab-clients/{lab_client_id}", headers=headers)

    # --- Driver ---
    def create_driver(self, payload, headers):
        return self._request("POST", f"{PREFIX}/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"{PREFIX}/drivers/{driver_id}", headers=headers)

    def driver_credential(self, driver_id, payload, headers):
        return self._request("POST", f"{PREFIX}/drivers/{driver_id}/credential", payload, headers)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"{PREFIX}/vehicles/{vehicle_id}", headers=headers)

    # --- RouteTemplate ---
    def create_route_template(self, payload, headers):
        return self._request("POST", f"{PREFIX}/route-templates", payload, headers)

    def list_route_templates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/route-templates", headers=headers, params=params)

    def get_route_template(self, template_id, headers):
        return self._request("GET", f"{PREFIX}/route-templates/{template_id}", headers=headers)

    def generate_route(self, template_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/route-templates/{template_id}/generate-route", payload, headers
        )

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", f"{PREFIX}/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"{PREFIX}/routes/{route_id}", headers=headers)

    def add_stop(self, route_id, payload, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/stops", payload, headers)

    def add_specimen(self, route_id, payload, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/specimens", payload, headers)

    def assign_route(self, route_id, payload, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/assign", payload, headers)

    def unassign_route(self, route_id, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/unassign", {}, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/dispatch", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/complete", {}, headers)

    def create_billing(self, route_id, payload, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/billing", payload, headers)

    # --- Stop / scans ---
    def list_stops(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"{PREFIX}/stops/{stop_id}", headers=headers)

    def scan_stop(self, stop_id, payload, headers):
        return self._request("POST", f"{PREFIX}/stops/{stop_id}/scan", payload, headers)

    def miss_stop(self, stop_id, headers):
        return self._request("POST", f"{PREFIX}/stops/{stop_id}/miss", {}, headers)

    def reschedule_stop(self, stop_id, headers):
        return self._request("POST", f"{PREFIX}/stops/{stop_id}/reschedule", {}, headers)

    # --- Specimen ---
    def list_specimens(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/specimens", headers=headers, params=params)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"{PREFIX}/specimens/{specimen_id}", headers=headers)

    # --- ScanEvent ---
    def list_scan_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/scan-events", headers=headers, params=params)

    def get_scan_event(self, scan_event_id, headers):
        return self._request("GET", f"{PREFIX}/scan-events/{scan_event_id}", headers=headers)

    # --- RouteException ---
    def list_exceptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/exceptions", headers=headers, params=params)

    def get_exception(self, exception_id, headers):
        return self._request("GET", f"{PREFIX}/exceptions/{exception_id}", headers=headers)

    def resolve_exception(self, exception_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exceptions/{exception_id}/resolve", payload or {}, headers
        )

    # --- RunBilling ---
    def list_billings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/billings", headers=headers, params=params)

    def get_billing(self, billing_id, headers):
        return self._request("GET", f"{PREFIX}/billings/{billing_id}", headers=headers)

    def issue_billing(self, billing_id, headers):
        return self._request("POST", f"{PREFIX}/billings/{billing_id}/issue", {}, headers)

    def void_billing(self, billing_id, headers):
        return self._request("POST", f"{PREFIX}/billings/{billing_id}/void", {}, headers)


api_client = ApiClient()
