"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ContainerType ----
    def create_container_type(self, payload, headers):
        return self._request("POST", "/container-types", payload, headers)

    def list_container_types(self, headers, params=None):
        return self._request("GET", "/container-types", headers=headers, params=params)

    def get_container_type(self, type_id, headers):
        return self._request("GET", f"/container-types/{type_id}", headers=headers)

    def retire_container_type(self, type_id, headers):
        return self._request("POST", f"/container-types/{type_id}/retire", headers=headers)

    # ---- ContractorAccount ----
    def create_contractor_account(self, payload, headers):
        return self._request("POST", "/contractor-accounts", payload, headers)

    def list_contractor_accounts(self, headers, params=None):
        return self._request("GET", "/contractor-accounts", headers=headers, params=params)

    def get_contractor_account(self, account_id, headers):
        return self._request("GET", f"/contractor-accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/contractor-accounts/{account_id}/suspend", headers=headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/contractor-accounts/{account_id}/reinstate", headers=headers)

    def list_account_orders(self, account_id, headers, params=None):
        return self._request("GET", f"/contractor-accounts/{account_id}/orders", headers=headers, params=params)

    def list_account_invoices(self, account_id, headers, params=None):
        return self._request("GET", f"/contractor-accounts/{account_id}/invoices", headers=headers, params=params)

    # ---- Container ----
    def create_container(self, payload, headers):
        return self._request("POST", "/containers", payload, headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/containers", headers=headers, params=params)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/containers/{container_id}", headers=headers)

    def return_to_yard(self, container_id, headers):
        return self._request("POST", f"/containers/{container_id}/return-to-yard", headers=headers)

    def retire_asset(self, container_id, headers):
        return self._request("POST", f"/containers/{container_id}/retire-asset", headers=headers)

    def restore_asset(self, container_id, headers):
        return self._request("POST", f"/containers/{container_id}/restore-asset", headers=headers)

    # ---- RentalOrder ----
    def create_rental_order(self, payload, headers):
        return self._request("POST", "/rental-orders", payload, headers)

    def list_rental_orders(self, headers, params=None):
        return self._request("GET", "/rental-orders", headers=headers, params=params)

    def get_rental_order(self, order_id, headers):
        return self._request("GET", f"/rental-orders/{order_id}", headers=headers)

    def list_order_service_stops(self, order_id, headers, params=None):
        return self._request("GET", f"/rental-orders/{order_id}/service-stops", headers=headers, params=params)

    def list_order_weigh_tickets(self, order_id, headers, params=None):
        return self._request("GET", f"/rental-orders/{order_id}/weigh-tickets", headers=headers, params=params)

    def list_order_street_permits(self, order_id, headers, params=None):
        return self._request("GET", f"/rental-orders/{order_id}/street-permits", headers=headers, params=params)

    def list_order_invoice(self, order_id, headers, params=None):
        return self._request("GET", f"/rental-orders/{order_id}/invoice", headers=headers, params=params)

    def create_swap_stop(self, order_id, payload, headers):
        return self._request("POST", f"/rental-orders/{order_id}/swap-stop", payload, headers)

    def create_pickup_stop(self, order_id, payload, headers):
        return self._request("POST", f"/rental-orders/{order_id}/pickup-stop", payload, headers)

    def dispatch_delivery(self, order_id, payload, headers):
        return self._request("POST", f"/rental-orders/{order_id}/dispatch-delivery", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/rental-orders/{order_id}/cancel", headers=headers)

    # ---- Route ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    def append_stop(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/stops", payload, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", headers=headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", headers=headers)

    # ---- ServiceStop ----
    def list_service_stops(self, headers, params=None):
        return self._request("GET", "/service-stops", headers=headers, params=params)

    def get_service_stop(self, stop_id, headers):
        return self._request("GET", f"/service-stops/{stop_id}", headers=headers)

    def complete_stop(self, stop_id, headers):
        return self._request("POST", f"/service-stops/{stop_id}/complete", headers=headers)

    def cancel_stop(self, stop_id, headers):
        return self._request("POST", f"/service-stops/{stop_id}/cancel", headers=headers)

    # ---- WeighTicket ----
    def create_weigh_ticket(self, payload, headers):
        return self._request("POST", "/weigh-tickets", payload, headers)

    def list_weigh_tickets(self, headers, params=None):
        return self._request("GET", "/weigh-tickets", headers=headers, params=params)

    def get_weigh_ticket(self, ticket_id, headers):
        return self._request("GET", f"/weigh-tickets/{ticket_id}", headers=headers)

    # ---- StreetPermit ----
    def create_street_permit(self, payload, headers):
        return self._request("POST", "/street-permits", payload, headers)

    def list_street_permits(self, headers, params=None):
        return self._request("GET", "/street-permits", headers=headers, params=params)

    def get_street_permit(self, permit_id, headers):
        return self._request("GET", f"/street-permits/{permit_id}", headers=headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/street-permits/{permit_id}/approve", headers=headers)

    def deny_permit(self, permit_id, headers):
        return self._request("POST", f"/street-permits/{permit_id}/deny", headers=headers)

    def expire_check_permit(self, permit_id, headers):
        return self._request("POST", f"/street-permits/{permit_id}/expire-check", headers=headers)

    # ---- Invoice ----
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    # ---- Clock ----
    def set_current_date(self, payload, headers):
        return self._request("POST", "/_clock/set-current-date", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
