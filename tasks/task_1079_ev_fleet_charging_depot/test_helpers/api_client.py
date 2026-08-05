"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # --- Depot ---
    def create_depot(self, payload, headers):
        return self._request("POST", "/fleet/depots", payload, headers=headers)

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"/fleet/depots/{depot_id}", headers=headers)

    def list_depots(self, headers, params=None):
        return self._request("GET", "/fleet/depots", headers=headers, params=params)

    # --- Charger ---
    def create_charger(self, payload, headers):
        return self._request("POST", "/fleet/chargers", payload, headers=headers)

    def get_charger(self, charger_id, headers):
        return self._request("GET", f"/fleet/chargers/{charger_id}", headers=headers)

    def list_chargers(self, headers, params=None):
        return self._request("GET", "/fleet/chargers", headers=headers, params=params)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/fleet/vehicles", payload, headers=headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/fleet/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/fleet/vehicles", headers=headers, params=params)

    def ingest_telemetry(self, vehicle_id, payload, headers):
        return self._request("POST", f"/fleet/vehicles/{vehicle_id}/telemetry", payload, headers=headers)

    def list_telemetry(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/fleet/vehicles/{vehicle_id}/telemetry", headers=headers, params=params)

    # --- Driver ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/fleet/drivers", payload, headers=headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/fleet/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/fleet/drivers", headers=headers, params=params)

    # --- ChargeSession ---
    def create_session(self, payload, headers):
        return self._request("POST", "/fleet/charge-sessions", payload, headers=headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/fleet/charge-sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/fleet/charge-sessions", headers=headers, params=params)

    def start_session(self, session_id, payload, headers):
        return self._request("POST", f"/fleet/charge-sessions/{session_id}/start", payload, headers=headers)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/fleet/charge-sessions/{session_id}/complete", payload, headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/fleet/charge-sessions/{session_id}/cancel", {}, headers=headers)

    # --- MaintenanceWorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/fleet/work-orders", payload, headers=headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/fleet/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/fleet/work-orders", headers=headers, params=params)

    def transition_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/fleet/work-orders/{wo_id}/transition", payload, headers=headers)

    # --- RouteAssignment ---
    def create_route(self, payload, headers):
        return self._request("POST", "/fleet/route-assignments", payload, headers=headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/fleet/route-assignments/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/fleet/route-assignments", headers=headers, params=params)

    def assign_route(self, route_id, headers):
        return self._request("POST", f"/fleet/route-assignments/{route_id}/assign", {}, headers=headers)

    def unassign_route(self, route_id, headers):
        return self._request("POST", f"/fleet/route-assignments/{route_id}/unassign", {}, headers=headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/fleet/route-assignments/{route_id}/complete", {}, headers=headers)

    # --- ReimbursementClaim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/fleet/reimbursement-claims", payload, headers=headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/fleet/reimbursement-claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/fleet/reimbursement-claims", headers=headers, params=params)

    def review_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fleet/reimbursement-claims/{claim_id}/review", payload, headers=headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/fleet/reimbursement-claims/{claim_id}/pay", {}, headers=headers)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/fleet/invoices", payload, headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fleet/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/fleet/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fleet/invoices/{invoice_id}/issue", {}, headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fleet/invoices/{invoice_id}/pay", {}, headers=headers)


api_client = ApiClient()
