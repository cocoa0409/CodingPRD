"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- platform / community config ---
    def create_community(self, payload, headers):
        return self._request("POST", "/api/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/api/communities/{community_id}", headers=headers)

    def update_community(self, community_id, payload, headers):
        return self._request("PATCH", f"/api/communities/{community_id}", payload, headers)

    def list_communities(self, headers, params=None):
        return self._request("GET", "/api/communities", headers=headers, params=params)

    # --- permit holders ---
    def create_permit_holder(self, payload, headers):
        return self._request("POST", "/api/permit-holders", payload, headers)

    def get_permit_holder(self, holder_id, headers):
        return self._request("GET", f"/api/permit-holders/{holder_id}", headers=headers)

    def list_permit_holders(self, headers, params=None):
        return self._request("GET", "/api/permit-holders", headers=headers, params=params)

    def verify_eligibility(self, holder_id, headers):
        return self._request("POST", f"/api/permit-holders/{holder_id}/verify-eligibility", {}, headers)

    def suspend_permit_holder(self, holder_id, headers):
        return self._request("POST", f"/api/permit-holders/{holder_id}/suspend", {}, headers)

    def reinstate_permit_holder(self, holder_id, headers):
        return self._request("POST", f"/api/permit-holders/{holder_id}/reinstate", {}, headers)

    def revoke_permit_holder(self, holder_id, headers):
        return self._request("POST", f"/api/permit-holders/{holder_id}/revoke", {}, headers)

    def deposit_wallet(self, holder_id, payload, headers):
        return self._request("POST", f"/api/permit-holders/{holder_id}/wallet/deposits", payload, headers)

    # --- vehicles ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/api/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/api/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/api/vehicles", headers=headers, params=params)

    def retire_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/api/vehicles/{vehicle_id}/retire", {}, headers)

    # --- registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/api/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/api/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/api/registrations", headers=headers, params=params)

    def activate_registration(self, registration_id, headers):
        return self._request("POST", f"/api/registrations/{registration_id}/activate", {}, headers)

    def renew_registration(self, registration_id, headers):
        return self._request("POST", f"/api/registrations/{registration_id}/renew", {}, headers)

    def finalize_renewal(self, registration_id, headers):
        return self._request("POST", f"/api/registrations/{registration_id}/finalize-renewal", {}, headers)

    def suspend_registration(self, registration_id, headers):
        return self._request("POST", f"/api/registrations/{registration_id}/suspend", {}, headers)

    def reinstate_registration(self, registration_id, headers):
        return self._request("POST", f"/api/registrations/{registration_id}/reinstate", {}, headers)

    def revoke_registration(self, registration_id, headers):
        return self._request("POST", f"/api/registrations/{registration_id}/revoke", {}, headers)

    # --- inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/api/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/api/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/api/inspections", headers=headers, params=params)

    def finalize_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/api/inspections/{inspection_id}/finalize", payload, headers)

    # --- insurance ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/api/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/api/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/api/insurance-policies", headers=headers, params=params)

    def cancel_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/api/insurance-policies/{policy_id}/cancel", {}, headers)

    # --- routes & route passes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/api/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/api/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/api/routes", headers=headers, params=params)

    def decommission_route(self, route_id, headers):
        return self._request("POST", f"/api/routes/{route_id}/decommission", {}, headers)

    def create_route_pass(self, payload, headers):
        return self._request("POST", "/api/route-passes", payload, headers)

    def get_route_pass(self, pass_id, headers):
        return self._request("GET", f"/api/route-passes/{pass_id}", headers=headers)

    def list_route_passes(self, headers, params=None):
        return self._request("GET", "/api/route-passes", headers=headers, params=params)

    def cancel_route_pass(self, pass_id, headers):
        return self._request("POST", f"/api/route-passes/{pass_id}/cancel", {}, headers)

    # --- charging infrastructure ---
    def create_charging_station(self, payload, headers):
        return self._request("POST", "/api/charging-stations", payload, headers)

    def get_charging_station(self, station_id, headers):
        return self._request("GET", f"/api/charging-stations/{station_id}", headers=headers)

    def list_charging_stations(self, headers, params=None):
        return self._request("GET", "/api/charging-stations", headers=headers, params=params)

    def set_station_offline(self, station_id, headers):
        return self._request("POST", f"/api/charging-stations/{station_id}/set-offline", {}, headers)

    def set_station_online(self, station_id, headers):
        return self._request("POST", f"/api/charging-stations/{station_id}/set-online", {}, headers)

    def create_charging_reservation(self, payload, headers):
        return self._request("POST", "/api/charging-reservations", payload, headers)

    def get_charging_reservation(self, reservation_id, headers):
        return self._request("GET", f"/api/charging-reservations/{reservation_id}", headers=headers)

    def list_charging_reservations(self, headers, params=None):
        return self._request("GET", "/api/charging-reservations", headers=headers, params=params)

    def cancel_charging_reservation(self, reservation_id, headers):
        return self._request("POST", f"/api/charging-reservations/{reservation_id}/cancel", {}, headers)

    # --- shared fleet ---
    def create_fleet_vehicle(self, payload, headers):
        return self._request("POST", "/api/fleet-vehicles", payload, headers)

    def get_fleet_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/api/fleet-vehicles/{vehicle_id}", headers=headers)

    def list_fleet_vehicles(self, headers, params=None):
        return self._request("GET", "/api/fleet-vehicles", headers=headers, params=params)

    def set_fleet_vehicle_maintenance(self, vehicle_id, headers):
        return self._request("POST", f"/api/fleet-vehicles/{vehicle_id}/set-maintenance", {}, headers)

    def set_fleet_vehicle_available(self, vehicle_id, headers):
        return self._request("POST", f"/api/fleet-vehicles/{vehicle_id}/set-available", {}, headers)

    def create_fleet_dispatch(self, payload, headers):
        return self._request("POST", "/api/fleet-dispatches", payload, headers)

    def get_fleet_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/api/fleet-dispatches/{dispatch_id}", headers=headers)

    def list_fleet_dispatches(self, headers, params=None):
        return self._request("GET", "/api/fleet-dispatches", headers=headers, params=params)

    def checkout_fleet_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/api/fleet-dispatches/{dispatch_id}/checkout", {}, headers)

    def return_fleet_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/api/fleet-dispatches/{dispatch_id}/return", {}, headers)

    def cancel_fleet_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/api/fleet-dispatches/{dispatch_id}/cancel", {}, headers)

    # --- violations / enforcement ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/api/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/api/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/api/violations", headers=headers, params=params)

    def uphold_violation(self, violation_id, headers):
        return self._request("POST", f"/api/violations/{violation_id}/uphold", {}, headers)

    def dismiss_violation(self, violation_id, headers):
        return self._request("POST", f"/api/violations/{violation_id}/dismiss", {}, headers)

    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
