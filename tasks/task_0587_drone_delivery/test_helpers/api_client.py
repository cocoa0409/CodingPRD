"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- simulators
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def laanc_decision(self, payload, headers):
        return self._request("POST", "/_laanc/decision", payload, headers)

    # ------------------------------------------------------------- service areas
    def create_service_area(self, payload, headers):
        return self._request("POST", "/service-areas", payload, headers)

    def get_service_area(self, service_area_id, headers):
        return self._request("GET", f"/service-areas/{service_area_id}", headers=headers)

    def suspend_service_area(self, service_area_id, headers):
        return self._request(
            "POST", f"/service-areas/{service_area_id}/suspend", {}, headers
        )

    # --------------------------------------------------------------------- nests
    def create_nest(self, payload, headers):
        return self._request("POST", "/nests", payload, headers)

    def list_nests(self, headers, params=None):
        return self._request("GET", "/nests", headers=headers, params=params)

    def get_nest(self, nest_id, headers):
        return self._request("GET", f"/nests/{nest_id}", headers=headers)

    # -------------------------------------------------------------------- drones
    def create_drone(self, payload, headers):
        return self._request("POST", "/drones", payload, headers)

    def list_drones(self, headers, params=None):
        return self._request("GET", "/drones", headers=headers, params=params)

    def get_drone(self, drone_id, headers):
        return self._request("GET", f"/drones/{drone_id}", headers=headers)

    def install_battery(self, drone_id, battery_id, headers):
        return self._request(
            "POST",
            f"/drones/{drone_id}/install-battery",
            {"battery_id": battery_id},
            headers,
        )

    # ----------------------------------------------------------------- batteries
    def create_battery(self, payload, headers):
        return self._request("POST", "/batteries", payload, headers)

    def list_batteries(self, headers, params=None):
        return self._request("GET", "/batteries", headers=headers, params=params)

    def get_battery(self, battery_id, headers):
        return self._request("GET", f"/batteries/{battery_id}", headers=headers)

    def charge_battery(self, battery_id, target_charge_pct, headers):
        return self._request(
            "POST",
            f"/batteries/{battery_id}/charge",
            {"target_charge_pct": target_charge_pct},
            headers,
        )

    # ----------------------------------------------------------------- customers
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # -------------------------------------------------------------------- orders
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def dispatch_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/dispatch", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------- flights
    def list_flights(self, headers, params=None):
        return self._request("GET", "/flights", headers=headers, params=params)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/flights/{flight_id}", headers=headers)

    def file_authorization(self, flight_id, payload, headers):
        return self._request(
            "POST", f"/flights/{flight_id}/file-authorization", payload, headers
        )

    def release_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/release", {}, headers)

    def launch_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/launch", {}, headers)

    def arrive_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/arrive", {}, headers)

    def drop_flight(self, flight_id, payload, headers):
        return self._request("POST", f"/flights/{flight_id}/drop", payload, headers)

    def recover_flight(self, flight_id, actual_route_km, headers):
        return self._request(
            "POST",
            f"/flights/{flight_id}/recover",
            {"actual_route_km": actual_route_km},
            headers,
        )

    def abort_flight(self, flight_id, headers, payload=None):
        return self._request(
            "POST", f"/flights/{flight_id}/abort", payload if payload is not None else {}, headers
        )

    def list_flight_delivery_drops(self, flight_id, headers, params=None):
        return self._request(
            "GET", f"/flights/{flight_id}/delivery-drops", headers=headers, params=params
        )

    # ------------------------------------------------------------ delivery drops
    def get_delivery_drop(self, drop_id, headers):
        return self._request("GET", f"/delivery-drops/{drop_id}", headers=headers)

    # ---------------------------------------------------- airspace authorizations
    def list_airspace_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/airspace-authorizations", headers=headers, params=params
        )

    def get_airspace_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"/airspace-authorizations/{authorization_id}", headers=headers
        )

    # ------------------------------------------------------------ geofence zones
    def create_geofence_zone(self, payload, headers):
        return self._request("POST", "/geofence-zones", payload, headers)

    def list_geofence_zones(self, headers, params=None):
        return self._request("GET", "/geofence-zones", headers=headers, params=params)

    def get_geofence_zone(self, zone_id, headers):
        return self._request("GET", f"/geofence-zones/{zone_id}", headers=headers)

    def lift_geofence_zone(self, zone_id, headers):
        return self._request("POST", f"/geofence-zones/{zone_id}/lift", {}, headers)

    # ------------------------------------------------------ weather observations
    def create_weather_observation(self, payload, headers):
        return self._request("POST", "/weather-observations", payload, headers)

    def list_weather_observations(self, headers, params=None):
        return self._request(
            "GET", "/weather-observations", headers=headers, params=params
        )

    def get_weather_observation(self, observation_id, headers):
        return self._request(
            "GET", f"/weather-observations/{observation_id}", headers=headers
        )

    # ----------------------------------------------------------------- incidents
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def review_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/review", {}, headers)

    def record_incident_outcome(self, incident_id, outcome, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/outcome", {"outcome": outcome}, headers
        )

    # ---------------------------------------------------------- maintenance logs
    def create_maintenance_log(self, payload, headers):
        return self._request("POST", "/maintenance-logs", payload, headers)

    def list_maintenance_logs(self, headers, params=None):
        return self._request("GET", "/maintenance-logs", headers=headers, params=params)

    def get_maintenance_log(self, log_id, headers):
        return self._request("GET", f"/maintenance-logs/{log_id}", headers=headers)

    def complete_maintenance_log(self, log_id, headers):
        return self._request(
            "POST", f"/maintenance-logs/{log_id}/complete", {}, headers
        )


api_client = ApiClient()
