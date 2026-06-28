"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # --- Agency ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers=headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/agencies", headers=headers, params=params)

    def set_agency_status(self, agency_id, status, headers):
        return self._request("PATCH", f"/agencies/{agency_id}/status",
                             {"status": status}, headers=headers)

    # --- Station ---
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers=headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    # --- Unit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers=headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def set_unit_status(self, unit_id, status, headers):
        return self._request("PATCH", f"/units/{unit_id}/status",
                             {"status": status}, headers=headers)

    # --- PremiseAlert ---
    def create_premise_alert(self, payload, headers):
        return self._request("POST", "/premise-alerts", payload, headers=headers)

    def get_premise_alert(self, alert_id, headers):
        return self._request("GET", f"/premise-alerts/{alert_id}", headers=headers)

    def list_premise_alerts(self, headers, params=None):
        return self._request("GET", "/premise-alerts", headers=headers, params=params)

    def update_premise_alert(self, alert_id, active, headers):
        return self._request("PATCH", f"/premise-alerts/{alert_id}",
                             {"active": active}, headers=headers)

    # --- Incident (intake + lifecycle) ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers=headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_recommendation(self, incident_id, headers, params=None):
        return self._request("GET", f"/incidents/{incident_id}/recommendation",
                             headers=headers, params=params)

    def create_assignment(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/assignments",
                             payload, headers=headers)

    def list_incident_assignments(self, incident_id, headers, params=None):
        return self._request("GET", f"/incidents/{incident_id}/assignments",
                             headers=headers, params=params)

    def escalate_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/escalate",
                             payload, headers=headers)

    def hold_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/hold",
                             payload, headers=headers)

    def resume_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/resume",
                             {}, headers=headers)

    def cancel_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/cancel",
                             payload, headers=headers)

    # --- Assignment status (field unit lifecycle) ---
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def set_assignment_status(self, assignment_id, status, headers):
        return self._request("PATCH", f"/assignments/{assignment_id}/status",
                             {"status": status}, headers=headers)

    # --- Disposition / close ---
    def create_disposition(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/dispositions",
                             payload, headers=headers)

    def list_dispositions(self, incident_id, headers, params=None):
        return self._request("GET", f"/incidents/{incident_id}/dispositions",
                             headers=headers, params=params)

    # --- Reports ---
    def create_report(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/reports",
                             payload, headers=headers)

    def list_reports(self, incident_id, headers, params=None):
        return self._request("GET", f"/incidents/{incident_id}/reports",
                             headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)


api_client = ApiClient()
