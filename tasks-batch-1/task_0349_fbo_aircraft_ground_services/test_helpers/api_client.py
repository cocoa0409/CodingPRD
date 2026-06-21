"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Operators ───────────────────────────────────────────────
    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}", headers=headers)

    # ─── Aircraft ────────────────────────────────────────────────
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/aircraft", headers=headers, params=params)

    # ─── Fuel contracts ──────────────────────────────────────────
    def create_fuel_contract(self, payload, headers):
        return self._request("POST", "/fuel-contracts", payload, headers)

    def get_fuel_contract(self, contract_id, headers):
        return self._request("GET", f"/fuel-contracts/{contract_id}", headers=headers)

    def list_fuel_contracts(self, headers, params=None):
        return self._request("GET", "/fuel-contracts", headers=headers, params=params)

    def expire_fuel_contract(self, contract_id, headers):
        return self._request("POST", f"/fuel-contracts/{contract_id}/expire", headers=headers)

    # ─── Service visits ──────────────────────────────────────────
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/service-visits/{visit_id}", headers=headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/service-visits", headers=headers, params=params)

    def arrive_service_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/service-visits/{visit_id}/arrive", payload or {}, headers)

    def start_servicing_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/start-servicing", headers=headers)

    def mark_ready_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/mark-ready", headers=headers)

    def depart_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/depart", headers=headers)

    def cancel_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/cancel", headers=headers)

    # ─── Parking spots ───────────────────────────────────────────
    def create_parking_spot(self, payload, headers):
        return self._request("POST", "/parking-spots", payload, headers)

    def get_parking_spot(self, spot_id, headers):
        return self._request("GET", f"/parking-spots/{spot_id}", headers=headers)

    def list_parking_spots(self, headers, params=None):
        return self._request("GET", "/parking-spots", headers=headers, params=params)

    def out_of_service_parking_spot(self, spot_id, headers):
        return self._request("POST", f"/parking-spots/{spot_id}/out-of-service", headers=headers)

    # ─── Parking assignments ─────────────────────────────────────
    def create_parking_assignment(self, payload, headers):
        return self._request("POST", "/parking-assignments", payload, headers)

    def get_parking_assignment(self, assignment_id, headers):
        return self._request("GET", f"/parking-assignments/{assignment_id}", headers=headers)

    def list_parking_assignments(self, headers, params=None):
        return self._request("GET", "/parking-assignments", headers=headers, params=params)

    def occupy_parking_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/parking-assignments/{assignment_id}/occupy", payload, headers)

    def release_parking_assignment(self, assignment_id, headers):
        return self._request("POST", f"/parking-assignments/{assignment_id}/release", headers=headers)

    # ─── Fuel orders ─────────────────────────────────────────────
    def create_fuel_order(self, payload, headers):
        return self._request("POST", "/fuel-orders", payload, headers)

    def get_fuel_order(self, order_id, headers):
        return self._request("GET", f"/fuel-orders/{order_id}", headers=headers)

    def list_fuel_orders(self, headers, params=None):
        return self._request("GET", "/fuel-orders", headers=headers, params=params)

    def dispatch_fuel_order(self, order_id, headers):
        return self._request("POST", f"/fuel-orders/{order_id}/dispatch", headers=headers)

    def complete_fueling_fuel_order(self, order_id, headers):
        return self._request("POST", f"/fuel-orders/{order_id}/complete-fueling", headers=headers)

    def cancel_fuel_order(self, order_id, headers):
        return self._request("POST", f"/fuel-orders/{order_id}/cancel", headers=headers)

    def adjust_billing_fuel_order(self, order_id, headers):
        return self._request("POST", f"/fuel-orders/{order_id}/adjust-billing", headers=headers)

    # ─── Into-plane tickets ──────────────────────────────────────
    def create_into_plane_ticket(self, payload, headers):
        return self._request("POST", "/into-plane-tickets", payload, headers)

    def get_into_plane_ticket(self, ticket_id, headers):
        return self._request("GET", f"/into-plane-tickets/{ticket_id}", headers=headers)

    def list_into_plane_tickets(self, headers, params=None):
        return self._request("GET", "/into-plane-tickets", headers=headers, params=params)

    # ─── Ramp services ───────────────────────────────────────────
    def create_ramp_service(self, payload, headers):
        return self._request("POST", "/ramp-services", payload, headers)

    def get_ramp_service(self, service_id, headers):
        return self._request("GET", f"/ramp-services/{service_id}", headers=headers)

    def list_ramp_services(self, headers, params=None):
        return self._request("GET", "/ramp-services", headers=headers, params=params)

    def start_ramp_service(self, service_id, headers):
        return self._request("POST", f"/ramp-services/{service_id}/start", headers=headers)

    def complete_ramp_service(self, service_id, headers):
        return self._request("POST", f"/ramp-services/{service_id}/complete", headers=headers)

    def cancel_ramp_service(self, service_id, headers):
        return self._request("POST", f"/ramp-services/{service_id}/cancel", headers=headers)

    # ─── Ramp slots ──────────────────────────────────────────────
    def create_ramp_slot(self, payload, headers):
        return self._request("POST", "/ramp-slots", payload, headers)

    def get_ramp_slot(self, slot_id, headers):
        return self._request("GET", f"/ramp-slots/{slot_id}", headers=headers)

    def list_ramp_slots(self, headers, params=None):
        return self._request("GET", "/ramp-slots", headers=headers, params=params)

    def approve_ramp_slot(self, slot_id, headers):
        return self._request("POST", f"/ramp-slots/{slot_id}/approve", headers=headers)

    def revoke_ramp_slot(self, slot_id, headers):
        return self._request("POST", f"/ramp-slots/{slot_id}/revoke", headers=headers)

    def re_request_ramp_slot(self, slot_id, headers):
        return self._request("POST", f"/ramp-slots/{slot_id}/re-request", headers=headers)

    def use_ramp_slot(self, slot_id, headers):
        return self._request("POST", f"/ramp-slots/{slot_id}/use", headers=headers)

    # ─── Invoices ────────────────────────────────────────────────
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def mark_past_due_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark-past-due", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    # ─── Test-driving clock ──────────────────────────────────────
    def advance_month(self, headers):
        return self._request("POST", "/_clock/advance_month", headers=headers)


api_client = ApiClient()
