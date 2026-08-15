"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, SystemAdmin only)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/suspend", {}, headers)

    def resume_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/resume", {}, headers)

    def close_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/close", {}, headers)

    def list_contract_availability_periods(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/availability-periods",
                             headers=headers, params=params)

    def list_contract_invoices(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/invoices",
                             headers=headers, params=params)

    def list_contract_agency_records(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/agency-records",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Aircraft
    # ------------------------------------------------------------------
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/aircraft", payload, headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}", headers=headers)

    def decard_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/aircraft/{aircraft_id}/decard", {}, headers)

    def list_aircraft_carding_inspections(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/aircraft/{aircraft_id}/carding-inspections",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Crew members
    # ------------------------------------------------------------------
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/crew-members", headers=headers, params=params)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}", headers=headers)

    def list_crew_duty_days(self, crew_member_id, headers, params=None):
        return self._request("GET", f"/crew-members/{crew_member_id}/duty-days",
                             headers=headers, params=params)

    def list_crew_member_carding_inspections(self, crew_member_id, headers, params=None):
        return self._request("GET", f"/crew-members/{crew_member_id}/carding-inspections",
                             headers=headers, params=params)

    def list_crew_member_flight_logs(self, crew_member_id, headers, params=None):
        return self._request("GET", f"/crew-members/{crew_member_id}/flight-logs",
                             headers=headers, params=params)

    def rest_release_crew_member(self, crew_member_id, headers):
        return self._request("POST", f"/crew-members/{crew_member_id}/rest-release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Carding inspections
    # ------------------------------------------------------------------
    def create_carding_inspection(self, payload, headers):
        return self._request("POST", "/carding-inspections", payload, headers)

    def complete_carding_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/carding-inspections/{inspection_id}/complete",
                             payload, headers)

    def reschedule_carding_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/carding-inspections/{inspection_id}/reschedule",
                             payload, headers)

    # ------------------------------------------------------------------
    # Availability periods
    # ------------------------------------------------------------------
    def create_availability_period(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/availability-periods",
                             payload, headers)

    def list_availability_periods(self, headers, params=None):
        return self._request("GET", "/availability-periods", headers=headers, params=params)

    def get_availability_period(self, period_id, headers):
        return self._request("GET", f"/availability-periods/{period_id}", headers=headers)

    def confirm_availability_period(self, period_id, headers):
        return self._request("POST", f"/availability-periods/{period_id}/confirm",
                             {}, headers)

    def excuse_availability_period(self, period_id, payload, headers):
        return self._request("POST", f"/availability-periods/{period_id}/excuse",
                             payload, headers)

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def advance_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/advance",
                             payload, headers)

    # ------------------------------------------------------------------
    # Dispatch orders
    # ------------------------------------------------------------------
    def create_dispatch_order(self, payload, headers):
        return self._request("POST", "/dispatch-orders", payload, headers)

    def list_dispatch_orders(self, headers, params=None):
        return self._request("GET", "/dispatch-orders", headers=headers, params=params)

    def get_dispatch_order(self, order_id, headers):
        return self._request("GET", f"/dispatch-orders/{order_id}", headers=headers)

    def accept_dispatch_order(self, order_id, headers):
        return self._request("POST", f"/dispatch-orders/{order_id}/accept", {}, headers)

    def decline_dispatch_order(self, order_id, payload, headers):
        return self._request("POST", f"/dispatch-orders/{order_id}/decline",
                             payload, headers)

    def cancel_dispatch_order(self, order_id, headers):
        return self._request("POST", f"/dispatch-orders/{order_id}/cancel", {}, headers)

    def list_order_assignments(self, order_id, headers, params=None):
        return self._request("GET", f"/dispatch-orders/{order_id}/assignments",
                             headers=headers, params=params)

    def create_assignment(self, order_id, payload, headers):
        return self._request("POST", f"/dispatch-orders/{order_id}/assignments",
                             payload, headers)

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def launch_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/launch", {}, headers)

    def arrive_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/arrive", {}, headers)

    def release_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/release",
                             payload, headers)

    def demobilize_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/demobilize",
                             {}, headers)

    def list_assignment_flight_logs(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/flight-logs",
                             headers=headers, params=params)

    def list_assignment_retardant_loads(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/retardant-loads",
                             headers=headers, params=params)

    def list_assignment_agency_records(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/agency-records",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Flight logs
    # ------------------------------------------------------------------
    def create_flight_log(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/flight-logs",
                             payload, headers)

    # ------------------------------------------------------------------
    # Retardant loads
    # ------------------------------------------------------------------
    def create_retardant_load(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/retardant-loads",
                             payload, headers)

    def load_retardant_load(self, load_id, payload, headers):
        return self._request("POST", f"/retardant-loads/{load_id}/load", payload, headers)

    def drop_retardant_load(self, load_id, payload, headers):
        return self._request("POST", f"/retardant-loads/{load_id}/drop", payload, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def create_invoice(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/invoices",
                             payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoice_line_items(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/line-items",
                             headers=headers, params=params)

    def submit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/submit", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", payload, headers)

    def resubmit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/resubmit", {}, headers)

    def reconcile_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/reconcile", {}, headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark-paid", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Agency records
    # ------------------------------------------------------------------
    def create_agency_record(self, payload, headers):
        return self._request("POST", "/agency-records", payload, headers)


api_client = ApiClient()
