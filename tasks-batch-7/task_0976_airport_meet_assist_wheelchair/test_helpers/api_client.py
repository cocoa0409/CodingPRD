"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (PRD §2.4) ---
    def set_current_utc(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST", "/maa/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Airports ---
    def create_airport(self, payload: dict, headers: dict):
        return self._request("POST", "/maa/airports", payload, headers)

    def get_airport(self, airport_id: str, headers: dict):
        return self._request("GET", f"/maa/airports/{airport_id}", headers=headers)

    def set_airport_posture(self, airport_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/airports/{airport_id}/posture", payload, headers,
        )

    def run_ops(self, airport_id: str, headers: dict):
        return self._request(
            "POST", f"/maa/airports/{airport_id}/run_ops", {}, headers,
        )

    # --- Terminals ---
    def create_terminal(self, airport_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/airports/{airport_id}/terminals", payload, headers,
        )

    def list_terminals(self, airport_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/airports/{airport_id}/terminals",
            headers=headers, params=params,
        )

    def get_terminal(self, terminal_id: str, headers: dict):
        return self._request("GET", f"/maa/terminals/{terminal_id}", headers=headers)

    def list_terminal_segments(self, terminal_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/terminals/{terminal_id}/segments",
            headers=headers, params=params,
        )

    # --- FlightSegments ---
    def create_segment(self, airport_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/airports/{airport_id}/segments", payload, headers,
        )

    def list_segments(self, airport_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/airports/{airport_id}/segments",
            headers=headers, params=params,
        )

    def get_segment(self, segment_id: str, headers: dict):
        return self._request("GET", f"/maa/segments/{segment_id}", headers=headers)

    def list_segment_legs(self, segment_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/segments/{segment_id}/legs",
            headers=headers, params=params,
        )

    def post_segment_event(self, segment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/segments/{segment_id}/events", payload, headers,
        )

    # --- Passengers ---
    def create_passenger(self, payload: dict, headers: dict):
        return self._request("POST", "/maa/passengers", payload, headers)

    def get_passenger(self, passenger_id: str, headers: dict):
        return self._request("GET", f"/maa/passengers/{passenger_id}", headers=headers)

    # --- Agents ---
    def create_agent(self, airport_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/airports/{airport_id}/agents", payload, headers,
        )

    def list_agents(self, airport_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/airports/{airport_id}/agents",
            headers=headers, params=params,
        )

    def get_agent(self, agent_id: str, headers: dict):
        return self._request("GET", f"/maa/agents/{agent_id}", headers=headers)

    def list_agent_assignments(self, agent_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/agents/{agent_id}/assignments",
            headers=headers, params=params,
        )

    def post_agent_event(self, agent_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/agents/{agent_id}/events", payload, headers,
        )

    # --- WheelchairAssets ---
    def create_wheelchair(self, airport_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/airports/{airport_id}/wheelchairs", payload, headers,
        )

    def list_wheelchairs(self, airport_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/airports/{airport_id}/wheelchairs",
            headers=headers, params=params,
        )

    def get_wheelchair(self, wheelchair_id: str, headers: dict):
        return self._request("GET", f"/maa/wheelchairs/{wheelchair_id}", headers=headers)

    def list_wheelchair_assignments(self, wheelchair_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/wheelchairs/{wheelchair_id}/assignments",
            headers=headers, params=params,
        )

    def post_wheelchair_event(self, wheelchair_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/wheelchairs/{wheelchair_id}/events", payload, headers,
        )

    # --- AssistRequests / ServiceLegs ---
    def create_assist_request(self, payload: dict, headers: dict):
        return self._request("POST", "/maa/assist-requests", payload, headers)

    def get_assist_request(self, request_id: str, headers: dict):
        return self._request(
            "GET", f"/maa/assist-requests/{request_id}", headers=headers,
        )

    def list_assist_requests(self, headers: dict, params: dict = None):
        return self._request(
            "GET", "/maa/assist-requests", headers=headers, params=params,
        )

    def create_leg(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/assist-requests/{request_id}/legs", payload, headers,
        )

    def list_legs(self, request_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/assist-requests/{request_id}/legs",
            headers=headers, params=params,
        )

    def get_leg(self, leg_id: str, headers: dict):
        return self._request("GET", f"/maa/legs/{leg_id}", headers=headers)

    def list_onward_legs(self, leg_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/legs/{leg_id}/onward-legs",
            headers=headers, params=params,
        )

    def post_assist_request_event(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/assist-requests/{request_id}/events", payload, headers,
        )

    # --- Dispatch / Assignments ---
    def dispatch_leg(self, leg_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/legs/{leg_id}/dispatch", payload, headers,
        )

    def get_assignment(self, assignment_id: str, headers: dict):
        return self._request("GET", f"/maa/assignments/{assignment_id}", headers=headers)

    def list_assignment_incidents(self, assignment_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/assignments/{assignment_id}/incidents",
            headers=headers, params=params,
        )

    def list_request_assignments(self, request_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/assist-requests/{request_id}/assignments",
            headers=headers, params=params,
        )

    def list_leg_assignments(self, leg_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/legs/{leg_id}/assignments",
            headers=headers, params=params,
        )

    def post_assignment_event(self, assignment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/assignments/{assignment_id}/events", payload, headers,
        )

    # --- Incidents ---
    def create_incident(self, payload: dict, headers: dict):
        return self._request("POST", "/maa/incidents", payload, headers)

    def get_incident(self, incident_id: str, headers: dict):
        return self._request("GET", f"/maa/incidents/{incident_id}", headers=headers)

    def list_request_incidents(self, request_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/assist-requests/{request_id}/incidents",
            headers=headers, params=params,
        )

    def post_incident_event(self, incident_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/incidents/{incident_id}/events", payload, headers,
        )

    # --- Invoices ---
    def get_invoice(self, invoice_id: str, headers: dict):
        return self._request("GET", f"/maa/invoices/{invoice_id}", headers=headers)

    def list_invoice_adjustments(self, invoice_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/invoices/{invoice_id}/adjustments",
            headers=headers, params=params,
        )

    def list_request_invoices(self, request_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/assist-requests/{request_id}/invoices",
            headers=headers, params=params,
        )

    def post_invoice_event(self, invoice_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maa/invoices/{invoice_id}/events", payload, headers,
        )

    # --- Tracking ---
    def post_tracking_event(self, payload: dict, headers: dict):
        return self._request("POST", "/maa/tracking", payload, headers)

    def list_assignment_tracking(self, assignment_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/maa/assignments/{assignment_id}/tracking",
            headers=headers, params=params,
        )


api_client = ApiClient()
