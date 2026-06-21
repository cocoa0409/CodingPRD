"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def place_hold(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/place-hold", headers=headers)

    def release_hold(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/release-hold", headers=headers)

    # ---- Wearers ----
    def create_wearer(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/wearers", payload, headers)

    def list_wearers(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/wearers", headers=headers, params=params)

    def get_wearer(self, wearer_id, headers):
        return self._request("GET", f"/wearers/{wearer_id}", headers=headers)

    def ramp_down_wearer(self, wearer_id, headers):
        return self._request("POST", f"/wearers/{wearer_id}/ramp-down", headers=headers)

    def reinstate_wearer(self, wearer_id, headers):
        return self._request("POST", f"/wearers/{wearer_id}/reinstate", headers=headers)

    def remove_wearer(self, wearer_id, headers):
        return self._request("POST", f"/wearers/{wearer_id}/remove", headers=headers)

    # ---- Garment Types ----
    def create_garment_type(self, payload, headers):
        return self._request("POST", "/garment-types", payload, headers)

    def get_garment_type(self, garment_type_id, headers):
        return self._request("GET", f"/garment-types/{garment_type_id}", headers=headers)

    def list_garments_of_type(self, garment_type_id, headers, params=None):
        return self._request("GET", f"/garment-types/{garment_type_id}/garments", headers=headers, params=params)

    # ---- Wash Stations ----
    def create_wash_station(self, payload, headers):
        return self._request("POST", "/wash-stations", payload, headers)

    def get_wash_station(self, wash_station_id, headers):
        return self._request("GET", f"/wash-stations/{wash_station_id}", headers=headers)

    def list_station_garments(self, wash_station_id, headers, params=None):
        return self._request("GET", f"/wash-stations/{wash_station_id}/garments", headers=headers, params=params)

    # ---- Garments ----
    def create_garment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/garments", payload, headers)

    def list_account_garments(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/garments", headers=headers, params=params)

    def get_garment(self, garment_id, headers):
        return self._request("GET", f"/garments/{garment_id}", headers=headers)

    def apply_emblem(self, garment_id, payload, headers):
        return self._request("POST", f"/garments/{garment_id}/apply-emblem", payload, headers)

    def start_wash(self, garment_id, payload, headers):
        return self._request("POST", f"/garments/{garment_id}/start-wash", payload, headers)

    def finish_wash(self, garment_id, headers):
        return self._request("POST", f"/garments/{garment_id}/finish-wash", headers=headers)

    def retire_garment(self, garment_id, headers):
        return self._request("POST", f"/garments/{garment_id}/retire", headers=headers)

    # ---- Assignments ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def return_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/return", headers=headers)

    def declare_loss(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/declare-loss", headers=headers)

    def declare_damage(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/declare-damage", headers=headers)

    # ---- Routes & Stops ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def create_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    def get_route_stop(self, route_stop_id, headers):
        return self._request("GET", f"/route-stops/{route_stop_id}", headers=headers)

    def list_route_stops_filtered(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    # ---- Service Visits ----
    def create_service_visit(self, route_stop_id, payload, headers):
        return self._request("POST", f"/route-stops/{route_stop_id}/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/service-visits/{visit_id}", headers=headers)

    def list_stop_visits(self, route_stop_id, headers, params=None):
        return self._request("GET", f"/route-stops/{route_stop_id}/service-visits", headers=headers, params=params)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/service-visits", headers=headers, params=params)

    def pickup_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/service-visits/{visit_id}/pickup", payload, headers)

    def deliver_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/deliver", headers=headers)

    def reconcile_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/service-visits/{visit_id}/reconcile", payload, headers)

    # ---- Service Charges ----
    def list_visit_charges(self, visit_id, headers, params=None):
        return self._request("GET", f"/service-visits/{visit_id}/charges", headers=headers, params=params)

    def get_service_charge(self, charge_id, headers):
        return self._request("GET", f"/service-charges/{charge_id}", headers=headers)

    def list_service_charges(self, headers, params=None):
        return self._request("GET", "/service-charges", headers=headers, params=params)

    def settle_charge(self, charge_id, headers):
        return self._request("POST", f"/service-charges/{charge_id}/settle", headers=headers)


api_client = ApiClient()
