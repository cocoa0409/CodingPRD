"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
List endpoints accept a `params` dict for query filters and pagination.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- ServiceType ----
    def create_service_type(self, payload, headers):
        return self._request("POST", "/service-types", payload, headers)

    def list_service_types(self, headers, params=None):
        return self._request("GET", "/service-types", headers=headers, params=params)

    def get_service_type(self, service_type_id, headers):
        return self._request("GET", f"/service-types/{service_type_id}", headers=headers)

    def retire_service_type(self, service_type_id, headers):
        return self._request("POST", f"/service-types/{service_type_id}/retire", headers=headers)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # ---- RepairTicket ----
    def create_repair_ticket(self, payload, headers):
        return self._request("POST", "/repair-tickets", payload, headers)

    def list_repair_tickets(self, headers, params=None):
        return self._request("GET", "/repair-tickets", headers=headers, params=params)

    def get_repair_ticket(self, ticket_id, headers):
        return self._request("GET", f"/repair-tickets/{ticket_id}", headers=headers)

    def patch_repair_ticket(self, ticket_id, payload, headers):
        return self._request("PATCH", f"/repair-tickets/{ticket_id}", payload, headers)

    def start_repair(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/start-repair", headers=headers)

    def mark_ready(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/mark-ready", headers=headers)

    def notify_ready(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/notify-ready", headers=headers)

    def pickup(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/pickup", headers=headers)

    def flag_unclaimed(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/flag-unclaimed", headers=headers)

    def dispose(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/dispose", headers=headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/cancel", headers=headers)

    # ---- TicketItem ----
    def create_ticket_item(self, payload, headers):
        return self._request("POST", "/ticket-items", payload, headers)

    def list_ticket_items(self, headers, params=None):
        return self._request("GET", "/ticket-items", headers=headers, params=params)

    def get_ticket_item(self, item_id, headers):
        return self._request("GET", f"/ticket-items/{item_id}", headers=headers)

    # ---- ServiceLine ----
    def create_service_line(self, payload, headers):
        return self._request("POST", "/service-lines", payload, headers)

    def list_service_lines(self, headers, params=None):
        return self._request("GET", "/service-lines", headers=headers, params=params)

    def get_service_line(self, line_id, headers):
        return self._request("GET", f"/service-lines/{line_id}", headers=headers)

    def patch_service_line(self, line_id, payload, headers):
        return self._request("PATCH", f"/service-lines/{line_id}", payload, headers)

    # ---- Estimate ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def present_estimate(self, estimate_id, payload, headers):
        return self._request("POST", f"/estimates/{estimate_id}/present", payload, headers)

    def approve_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/approve", headers=headers)

    def reject_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/reject", headers=headers)

    # ---- PartsOrder ----
    def create_parts_order(self, payload, headers):
        return self._request("POST", "/parts-orders", payload, headers)

    def list_parts_orders(self, headers, params=None):
        return self._request("GET", "/parts-orders", headers=headers, params=params)

    def get_parts_order(self, parts_order_id, headers):
        return self._request("GET", f"/parts-orders/{parts_order_id}", headers=headers)

    def order_part(self, parts_order_id, headers):
        return self._request("POST", f"/parts-orders/{parts_order_id}/order", headers=headers)

    def receive_part(self, parts_order_id, headers):
        return self._request("POST", f"/parts-orders/{parts_order_id}/receive", headers=headers)

    def cancel_part(self, parts_order_id, headers):
        return self._request("POST", f"/parts-orders/{parts_order_id}/cancel", headers=headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", headers=headers)

    # ---- Notification ----
    def list_notifications(self, headers, params=None):
        return self._request("GET", "/notifications", headers=headers, params=params)

    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/notifications/{notification_id}", headers=headers)

    # ---- WarrantyClaim ----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def approve_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", payload, headers)

    def deny_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", payload, headers)


api_client = ApiClient()
