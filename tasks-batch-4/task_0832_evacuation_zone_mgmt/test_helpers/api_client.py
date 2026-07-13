"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/evac/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Incident ----------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/evac/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/evac/incidents/{incident_id}", headers=headers)

    def set_incident_phase(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/evac/incidents/{incident_id}/phase", payload, headers
        )

    # ---- Zone --------------------------------------------------------------
    def create_zone(self, payload, headers):
        return self._request("POST", "/evac/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/evac/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/evac/zones", headers=headers, params=params)

    def set_zone_order(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/evac/zones/{zone_id}/order", payload, headers
        )

    # ---- Shelter -----------------------------------------------------------
    def create_shelter(self, payload, headers):
        return self._request("POST", "/evac/shelters", payload, headers)

    def get_shelter(self, shelter_id, headers):
        return self._request("GET", f"/evac/shelters/{shelter_id}", headers=headers)

    def list_shelters(self, headers, params=None):
        return self._request("GET", "/evac/shelters", headers=headers, params=params)

    def set_shelter_status(self, shelter_id, payload, headers):
        return self._request(
            "POST", f"/evac/shelters/{shelter_id}/status", payload, headers
        )

    def list_shelter_staff_shifts(self, shelter_id, headers, params=None):
        return self._request(
            "GET", f"/evac/shelters/{shelter_id}/staff-shifts", headers=headers, params=params
        )

    # ---- StaffShift --------------------------------------------------------
    def create_staff_shift(self, payload, headers):
        return self._request("POST", "/evac/staff-shifts", payload, headers)

    def cancel_staff_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/evac/staff-shifts/{shift_id}/cancel", {}, headers
        )

    # ---- EvacuationRoute ---------------------------------------------------
    def create_route(self, payload, headers):
        return self._request("POST", "/evac/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/evac/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/evac/routes", headers=headers, params=params)

    def set_route_status(self, route_id, payload, headers):
        return self._request(
            "POST", f"/evac/routes/{route_id}/status", payload, headers
        )

    def list_route_contraflow_segments(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/evac/routes/{route_id}/contraflow-segments", headers=headers, params=params
        )

    # ---- ContraflowSegment -------------------------------------------------
    def create_contraflow_segment(self, payload, headers):
        return self._request("POST", "/evac/contraflow-segments", payload, headers)

    def set_contraflow_segment_status(self, segment_id, payload, headers):
        return self._request(
            "POST", f"/evac/contraflow-segments/{segment_id}/status", payload, headers
        )

    # ---- Registrant --------------------------------------------------------
    def create_registrant(self, payload, headers):
        return self._request("POST", "/evac/registrants", payload, headers)

    def get_registrant(self, registrant_id, headers):
        return self._request("GET", f"/evac/registrants/{registrant_id}", headers=headers)

    def list_registrants(self, headers, params=None):
        return self._request("GET", "/evac/registrants", headers=headers, params=params)

    # ---- ShelterAssignment -------------------------------------------------
    def create_shelter_assignment(self, payload, headers):
        return self._request("POST", "/evac/shelter-assignments", payload, headers)

    def get_shelter_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/evac/shelter-assignments/{assignment_id}", headers=headers
        )

    def list_shelter_assignments(self, headers, params=None):
        return self._request(
            "GET", "/evac/shelter-assignments", headers=headers, params=params
        )

    def set_shelter_assignment_status(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/evac/shelter-assignments/{assignment_id}/status", payload, headers
        )

    # ---- AccessCredential --------------------------------------------------
    def create_access_credential(self, payload, headers):
        return self._request("POST", "/evac/access-credentials", payload, headers)

    def get_access_credential(self, credential_id, headers):
        return self._request(
            "GET", f"/evac/access-credentials/{credential_id}", headers=headers
        )

    def list_access_credentials(self, headers, params=None):
        return self._request(
            "GET", "/evac/access-credentials", headers=headers, params=params
        )

    def set_access_credential_status(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/evac/access-credentials/{credential_id}/status", payload, headers
        )

    # ---- AlertDispatch -----------------------------------------------------
    def create_alert(self, payload, headers):
        return self._request("POST", "/evac/alerts", payload, headers)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/evac/alerts/{alert_id}", headers=headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/evac/alerts", headers=headers, params=params)

    def set_alert_status(self, alert_id, payload, headers):
        return self._request(
            "POST", f"/evac/alerts/{alert_id}/status", payload, headers
        )

    def record_alert_channel_result(self, alert_id, payload, headers):
        return self._request(
            "POST", f"/evac/alerts/{alert_id}/channel-result", payload, headers
        )


api_client = ApiClient()
