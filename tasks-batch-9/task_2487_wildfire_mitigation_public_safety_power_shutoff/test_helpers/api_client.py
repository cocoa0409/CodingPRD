"""API client: one method per endpoint defined by the PRD (§4).

Every path is rooted at the API base with no version or namespace prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Circuits and the feeder chain
    # ------------------------------------------------------------------
    def create_circuit(self, payload, headers):
        return self._request("POST", "/circuits", payload, headers)

    def list_circuits(self, headers, params=None):
        return self._request("GET", "/circuits", headers=headers, params=params)

    def get_circuit(self, circuit_id, headers):
        return self._request("GET", f"/circuits/{circuit_id}", headers=headers)

    def list_circuit_weather_stations(self, circuit_id, headers, params=None):
        return self._request(
            "GET",
            f"/circuits/{circuit_id}/weather-stations",
            headers=headers,
            params=params,
        )

    def list_circuit_customers(self, circuit_id, headers, params=None):
        return self._request(
            "GET", f"/circuits/{circuit_id}/customers", headers=headers, params=params
        )

    def list_circuit_fire_potential_indices(self, circuit_id, headers, params=None):
        return self._request(
            "GET",
            f"/circuits/{circuit_id}/fire-potential-indices",
            headers=headers,
            params=params,
        )

    def list_circuit_mitigation_projects(self, circuit_id, headers, params=None):
        return self._request(
            "GET",
            f"/circuits/{circuit_id}/mitigation-projects",
            headers=headers,
            params=params,
        )

    def list_circuit_event_scopes(self, circuit_id, headers, params=None):
        return self._request(
            "GET",
            f"/circuits/{circuit_id}/event-scopes",
            headers=headers,
            params=params,
        )

    def re_energize_circuit(self, circuit_id, headers, payload=None):
        return self._request(
            "POST", f"/circuits/{circuit_id}/re-energize", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # The weather desk
    # ------------------------------------------------------------------
    def create_weather_station(self, payload, headers):
        return self._request("POST", "/weather-stations", payload, headers)

    def get_weather_station(self, station_id, headers):
        return self._request("GET", f"/weather-stations/{station_id}", headers=headers)

    def list_station_observations(self, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/weather-stations/{station_id}/observations",
            headers=headers,
            params=params,
        )

    def create_weather_observation(self, payload, headers):
        return self._request("POST", "/weather-observations", payload, headers)

    def create_fire_potential_index(self, payload, headers):
        return self._request("POST", "/fire-potential-indices", payload, headers)

    # ------------------------------------------------------------------
    # Shutoff events
    # ------------------------------------------------------------------
    def create_psps_event(self, payload, headers):
        return self._request("POST", "/psps-events", payload, headers)

    def list_psps_events(self, headers, params=None):
        return self._request("GET", "/psps-events", headers=headers, params=params)

    def get_psps_event(self, event_id, headers):
        return self._request("GET", f"/psps-events/{event_id}", headers=headers)

    def scope_psps_event(self, event_id, payload, headers):
        return self._request("POST", f"/psps-events/{event_id}/scope", payload, headers)

    def list_event_scopes(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/psps-events/{event_id}/scopes", headers=headers, params=params
        )

    def exclude_event_scope(self, scope_id, payload, headers):
        return self._request(
            "POST", f"/event-scopes/{scope_id}/exclude", payload, headers
        )

    def arm_psps_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/psps-events/{event_id}/arm", payload or {}, headers
        )

    def de_energize_psps_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/psps-events/{event_id}/de-energize", payload or {}, headers
        )

    def all_clear_psps_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/psps-events/{event_id}/all-clear", payload or {}, headers
        )

    def close_psps_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/psps-events/{event_id}/close", payload or {}, headers
        )

    def cancel_psps_event(self, event_id, payload, headers):
        return self._request("POST", f"/psps-events/{event_id}/cancel", payload, headers)

    def activate_resource_centers(self, event_id, payload, headers):
        return self._request(
            "POST",
            f"/psps-events/{event_id}/activate-resource-centers",
            payload or {},
            headers,
        )

    def list_event_resource_centers(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/psps-events/{event_id}/resource-centers",
            headers=headers,
            params=params,
        )

    def list_event_notification_batches(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/psps-events/{event_id}/notification-batches",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Served accounts
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def create_notification_batch(self, payload, headers):
        return self._request("POST", "/notification-batches", payload, headers)

    def get_notification_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/notification-batches/{batch_id}", headers=headers
        )

    def dispatch_notification_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/notification-batches/{batch_id}/dispatch", payload or {}, headers
        )

    def list_notification_records(self, headers, params=None):
        return self._request(
            "GET", "/notification-records", headers=headers, params=params
        )

    def get_notification_record(self, record_id, headers):
        return self._request(
            "GET", f"/notification-records/{record_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Mitigation portfolio
    # ------------------------------------------------------------------
    def create_mitigation_project(self, payload, headers):
        return self._request("POST", "/mitigation-projects", payload, headers)

    def get_mitigation_project(self, project_id, headers):
        return self._request(
            "GET", f"/mitigation-projects/{project_id}", headers=headers
        )

    def submit_mitigation_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/submit", payload or {}, headers
        )

    def review_mitigation_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/mitigation-projects/{project_id}/review", payload, headers
        )

    def record_project_completion(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/mitigation-projects/{project_id}/record-completion",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Patrols and damage assessment
    # ------------------------------------------------------------------
    def create_patrol_assignment(self, payload, headers):
        return self._request("POST", "/patrol-assignments", payload, headers)

    def list_patrol_assignments(self, headers, params=None):
        return self._request(
            "GET", "/patrol-assignments", headers=headers, params=params
        )

    def get_patrol_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/patrol-assignments/{assignment_id}", headers=headers
        )

    def start_patrol(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/patrol-assignments/{assignment_id}/start", payload or {}, headers
        )

    def complete_patrol(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/patrol-assignments/{assignment_id}/complete", payload, headers
        )

    def create_damage_finding(self, payload, headers):
        return self._request("POST", "/damage-findings", payload, headers)

    def list_patrol_damage_findings(self, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"/patrol-assignments/{assignment_id}/damage-findings",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Community resource centers
    # ------------------------------------------------------------------
    def create_resource_center(self, payload, headers):
        return self._request("POST", "/community-resource-centers", payload, headers)

    def get_resource_center(self, center_id, headers):
        return self._request(
            "GET", f"/community-resource-centers/{center_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Regulatory plan filings
    # ------------------------------------------------------------------
    def create_plan_filing(self, payload, headers):
        return self._request("POST", "/plan-filings", payload, headers)

    def get_plan_filing(self, filing_id, headers):
        return self._request("GET", f"/plan-filings/{filing_id}", headers=headers)

    def submit_plan_filing(self, filing_id, headers, payload=None):
        return self._request(
            "POST", f"/plan-filings/{filing_id}/submit", payload or {}, headers
        )

    def review_plan_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/plan-filings/{filing_id}/reviews", payload, headers
        )


api_client = ApiClient()
