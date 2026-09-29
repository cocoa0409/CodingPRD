"""API client: one method per endpoint the PRD declares under `/colocation`."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/colocation"


class ApiClient(GenericApiClient):
    """Thin transport wrapper. Every method returns the raw response so tests can
    assert on status codes and on the error envelope."""

    # --- logical clock ----------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- customers --------------------------------------------------------

    def create_customer(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    # --- authorized contacts ---------------------------------------------

    def create_contact(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/contacts", payload, headers)

    def set_contact_biometric_state(self, contact_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/contacts/{contact_id}/biometric-state", payload, headers
        )

    def get_contact(self, contact_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/contacts/{contact_id}", headers=headers)

    def list_contacts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/contacts", headers=headers, params=params)

    # --- contracts --------------------------------------------------------

    def create_contract(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def set_contract_state(self, contract_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/contracts/{contract_id}/state", payload, headers)

    def set_credit_hold(self, contract_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/credit-hold", payload, headers
        )

    def close_billing_period(self, contract_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/billing-close", payload, headers
        )

    def create_invoice_adjustment(self, contract_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/invoice-adjustments", payload, headers
        )

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/contracts", headers=headers, params=params)

    # --- floor rows -------------------------------------------------------

    def create_row(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/rows", payload, headers)

    def update_row(self, row_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"{PREFIX}/rows/{row_id}", payload, headers)

    def get_row(self, row_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/rows/{row_id}", headers=headers)

    def list_rows(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/rows", headers=headers, params=params)

    # --- cabinets ---------------------------------------------------------

    def create_cabinet(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/cabinets", payload, headers)

    def set_cabinet_state(self, cabinet_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/cabinets/{cabinet_id}/state", payload, headers)

    def get_cabinet(self, cabinet_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/cabinets/{cabinet_id}", headers=headers)

    def list_cabinets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/cabinets", headers=headers, params=params)

    # --- power circuits ---------------------------------------------------

    def create_power_circuit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/power-circuits", payload, headers)

    def set_circuit_state(self, circuit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/power-circuits/{circuit_id}/state", payload, headers
        )

    def energize_circuit(self, circuit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/power-circuits/{circuit_id}/energize", payload, headers
        )

    def append_meter_reading(self, circuit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/power-circuits/{circuit_id}/readings", payload, headers
        )

    def get_power_circuit(self, circuit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/power-circuits/{circuit_id}", headers=headers)

    def list_power_circuits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/power-circuits", headers=headers, params=params)

    # --- patch panel ports ------------------------------------------------

    def create_patch_panel_port(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/patch-panel-ports", payload, headers)

    def get_patch_panel_port(self, port_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/patch-panel-ports/{port_id}", headers=headers)

    def list_patch_panel_ports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/patch-panel-ports", headers=headers, params=params)

    # --- cross-connect orders --------------------------------------------

    def create_cross_connect_order(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/cross-connect-orders", payload, headers)

    def propose_route(self, order_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/cross-connect-orders/{order_id}/propose-route", payload, headers
        )

    def request_route_changes(self, order_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/cross-connect-orders/{order_id}/request-changes", payload, headers
        )

    def set_cross_connect_order_state(self, order_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/cross-connect-orders/{order_id}/state", payload, headers
        )

    def get_cross_connect_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/cross-connect-orders/{order_id}", headers=headers)

    def list_cross_connect_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/cross-connect-orders", headers=headers, params=params
        )

    # --- remote-hands tickets --------------------------------------------

    def create_remote_hands_ticket(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/remote-hands-tickets", payload, headers)

    def set_ticket_authorization(self, ticket_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/remote-hands-tickets/{ticket_id}/authorization", payload, headers
        )

    def dispatch_ticket(self, ticket_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/remote-hands-tickets/{ticket_id}/dispatch", payload, headers
        )

    def complete_ticket(self, ticket_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/remote-hands-tickets/{ticket_id}/complete", payload, headers
        )

    def get_remote_hands_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/remote-hands-tickets/{ticket_id}", headers=headers)

    def list_remote_hands_tickets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/remote-hands-tickets", headers=headers, params=params)

    # --- access visits ----------------------------------------------------

    def create_access_visit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/access-visits", payload, headers)

    def set_access_visit_state(self, visit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/access-visits/{visit_id}/state", payload, headers)

    def get_access_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/access-visits/{visit_id}", headers=headers)

    def list_access_visits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/access-visits", headers=headers, params=params)

    # --- decommission orders ---------------------------------------------

    def create_decommission_order(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/decommission-orders", payload, headers)

    def set_decommission_order_state(self, order_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/decommission-orders/{order_id}/state", payload, headers
        )

    def record_decommission_step(self, order_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/decommission-orders/{order_id}/record-step", payload, headers
        )

    def release_ports(self, order_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/decommission-orders/{order_id}/release-ports", payload, headers
        )

    def get_decommission_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/decommission-orders/{order_id}", headers=headers)

    def list_decommission_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/decommission-orders", headers=headers, params=params)

    # --- invoice lines ----------------------------------------------------

    def get_invoice_line(self, invoice_line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/invoice-lines/{invoice_line_id}", headers=headers
        )

    def list_invoice_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/invoice-lines", headers=headers, params=params)


api_client = ApiClient()
