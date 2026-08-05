"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # --- HostSite ---
    def create_host_site(self, payload, headers):
        return self._request("POST", "/host-sites", payload, headers=headers)

    def get_host_site(self, site_id, headers):
        return self._request("GET", f"/host-sites/{site_id}", headers=headers)

    # --- HostAgreement ---
    def create_host_agreement(self, payload, headers):
        return self._request("POST", "/host-agreements", payload, headers=headers)

    def get_host_agreement(self, agreement_id, headers):
        return self._request("GET", f"/host-agreements/{agreement_id}", headers=headers)

    def list_host_agreements(self, headers, params=None):
        return self._request("GET", "/host-agreements", headers=headers, params=params)

    def propose_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/host-agreements/{agreement_id}/propose", payload, headers=headers)

    def counter_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/host-agreements/{agreement_id}/counter", payload, headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/host-agreements/{agreement_id}/activate", {}, headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/host-agreements/{agreement_id}/terminate", {}, headers=headers)

    # --- GrantProgram ---
    def create_grant_program(self, payload, headers):
        return self._request("POST", "/grant-programs", payload, headers=headers)

    def get_grant_program(self, grant_id, headers):
        return self._request("GET", f"/grant-programs/{grant_id}", headers=headers)

    # --- Station ---
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers=headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def list_station_ports(self, station_id, headers, params=None):
        return self._request("GET", f"/stations/{station_id}/ports", headers=headers, params=params)

    def commission_station(self, station_id, headers):
        return self._request("POST", f"/stations/{station_id}/commission", {}, headers=headers)

    def decommission_station(self, station_id, headers):
        return self._request("POST", f"/stations/{station_id}/decommission", {}, headers=headers)

    # --- Port ---
    def create_port(self, payload, headers):
        return self._request("POST", "/ports", payload, headers=headers)

    def get_port(self, port_id, headers):
        return self._request("GET", f"/ports/{port_id}", headers=headers)

    def port_out_of_service(self, port_id, headers):
        return self._request("POST", f"/ports/{port_id}/out-of-service", {}, headers=headers)

    def port_in_service(self, port_id, headers):
        return self._request("POST", f"/ports/{port_id}/in-service", {}, headers=headers)

    # --- ChargingSession ---
    def create_session(self, payload, headers):
        return self._request("POST", "/charging-sessions", payload, headers=headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/charging-sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/charging-sessions", headers=headers, params=params)

    def stop_session(self, session_id, payload, headers):
        return self._request("POST", f"/charging-sessions/{session_id}/stop", payload, headers=headers)

    def finalize_session(self, session_id, headers):
        return self._request("POST", f"/charging-sessions/{session_id}/finalize", {}, headers=headers)

    def void_session(self, session_id, headers):
        return self._request("POST", f"/charging-sessions/{session_id}/void", {}, headers=headers)

    # --- Reservation ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", {}, headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers=headers)

    def checkin_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", {}, headers=headers)

    # --- MaintenanceWindow ---
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/maintenance-windows", payload, headers=headers)

    def get_maintenance_window(self, mw_id, headers):
        return self._request("GET", f"/maintenance-windows/{mw_id}", headers=headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request("GET", "/maintenance-windows", headers=headers, params=params)

    def start_maintenance_window(self, mw_id, headers):
        return self._request("POST", f"/maintenance-windows/{mw_id}/start", {}, headers=headers)

    def complete_maintenance_window(self, mw_id, headers):
        return self._request("POST", f"/maintenance-windows/{mw_id}/complete", {}, headers=headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers=headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def resolve_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/resolve", {}, headers=headers)

    # --- RebateClaim ---
    def create_rebate_claim(self, payload, headers):
        return self._request("POST", "/rebate-claims", payload, headers=headers)

    def get_rebate_claim(self, claim_id, headers):
        return self._request("GET", f"/rebate-claims/{claim_id}", headers=headers)

    def list_rebate_claims(self, headers, params=None):
        return self._request("GET", "/rebate-claims", headers=headers, params=params)

    def submit_rebate_claim(self, claim_id, headers):
        return self._request("POST", f"/rebate-claims/{claim_id}/submit", {}, headers=headers)

    def audit_rebate_claim(self, claim_id, headers):
        return self._request("POST", f"/rebate-claims/{claim_id}/audit", {}, headers=headers)

    def approve_rebate_claim(self, claim_id, headers):
        return self._request("POST", f"/rebate-claims/{claim_id}/approve", {}, headers=headers)

    def reject_rebate_claim(self, claim_id, headers):
        return self._request("POST", f"/rebate-claims/{claim_id}/reject", {}, headers=headers)

    # --- RevenueStatement ---
    def create_revenue_statement(self, payload, headers):
        return self._request("POST", "/revenue-statements", payload, headers=headers)

    def get_revenue_statement(self, statement_id, headers):
        return self._request("GET", f"/revenue-statements/{statement_id}", headers=headers)

    def list_revenue_statements(self, headers, params=None):
        return self._request("GET", "/revenue-statements", headers=headers, params=params)

    def finalize_revenue_statement(self, statement_id, headers):
        return self._request("POST", f"/revenue-statements/{statement_id}/finalize", {}, headers=headers)


api_client = ApiClient()
