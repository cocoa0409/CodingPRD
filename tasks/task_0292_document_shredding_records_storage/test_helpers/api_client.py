"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
All paths are top-level collections (flat topology); foreign-key parents are
reached by filtering list endpoints, never by nested URLs.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- ServiceAccount -----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def credit_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/credit", payload, headers)

    def advance_period(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/advance-period", {}, headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    def reactivate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/reactivate", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    # ----- ServiceLocation -----
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    # ----- RateCard -----
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/rate-cards", headers=headers, params=params)

    def activate_rate_card(self, rate_card_id, headers):
        return self._request("POST", f"/rate-cards/{rate_card_id}/activate", {}, headers)

    # ----- Container -----
    def create_container(self, payload, headers):
        return self._request("POST", "/containers", payload, headers)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/containers/{container_id}", headers=headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/containers", headers=headers, params=params)

    def retire_container(self, container_id, headers):
        return self._request("POST", f"/containers/{container_id}/retire", {}, headers)

    # ----- ServiceOrder -----
    def create_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def reschedule_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/reschedule", payload, headers)

    def dispatch_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/dispatch", {}, headers)

    def weigh_in_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/weigh-in", payload, headers)

    def shred_on_site(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/shred-on-site", {}, headers)

    def confirm_pickup(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/confirm-pickup", {}, headers)

    def receive_at_plant(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/receive-at-plant", {}, headers)

    def destroy_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/destroy", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/cancel", {}, headers)

    # ----- WeightTicket -----
    def get_weight_ticket(self, ticket_id, headers):
        return self._request("GET", f"/weight-tickets/{ticket_id}", headers=headers)

    def list_weight_tickets(self, headers, params=None):
        return self._request("GET", "/weight-tickets", headers=headers, params=params)

    # ----- CustodyEvent -----
    def get_custody_event(self, event_id, headers):
        return self._request("GET", f"/custody-events/{event_id}", headers=headers)

    def list_custody_events(self, headers, params=None):
        return self._request("GET", "/custody-events", headers=headers, params=params)

    # ----- DestructionCertificate -----
    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def void_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/void", {}, headers)

    # ----- DestructionInvoice -----
    def get_destruction_invoice(self, invoice_id, headers):
        return self._request("GET", f"/destruction-invoices/{invoice_id}", headers=headers)

    def list_destruction_invoices(self, headers, params=None):
        return self._request("GET", "/destruction-invoices", headers=headers, params=params)

    def pay_destruction_invoice(self, invoice_id, headers):
        return self._request("POST", f"/destruction-invoices/{invoice_id}/pay", {}, headers)

    # ----- RetentionBox -----
    def create_retention_box(self, payload, headers):
        return self._request("POST", "/retention-boxes", payload, headers)

    def get_retention_box(self, box_id, headers):
        return self._request("GET", f"/retention-boxes/{box_id}", headers=headers)

    def list_retention_boxes(self, headers, params=None):
        return self._request("GET", "/retention-boxes", headers=headers, params=params)

    def shelve_box(self, box_id, headers):
        return self._request("POST", f"/retention-boxes/{box_id}/shelve", {}, headers)

    def purge_box(self, box_id, headers):
        return self._request("POST", f"/retention-boxes/{box_id}/purge", {}, headers)

    # ----- RetrievalRequest -----
    def create_retrieval_request(self, payload, headers):
        return self._request("POST", "/retrieval-requests", payload, headers)

    def get_retrieval_request(self, request_id, headers):
        return self._request("GET", f"/retrieval-requests/{request_id}", headers=headers)

    def list_retrieval_requests(self, headers, params=None):
        return self._request("GET", "/retrieval-requests", headers=headers, params=params)

    def fulfill_retrieval(self, request_id, headers):
        return self._request("POST", f"/retrieval-requests/{request_id}/fulfill", {}, headers)

    def start_return(self, request_id, headers):
        return self._request("POST", f"/retrieval-requests/{request_id}/start-return", {}, headers)

    def return_retrieval(self, request_id, headers):
        return self._request("POST", f"/retrieval-requests/{request_id}/return", {}, headers)

    def refuse_return(self, request_id, headers):
        return self._request("POST", f"/retrieval-requests/{request_id}/refuse-return", {}, headers)

    def cancel_retrieval(self, request_id, headers):
        return self._request("POST", f"/retrieval-requests/{request_id}/cancel", {}, headers)

    # ----- ComplianceHold -----
    def create_compliance_hold(self, payload, headers):
        return self._request("POST", "/compliance-holds", payload, headers)

    def get_compliance_hold(self, hold_id, headers):
        return self._request("GET", f"/compliance-holds/{hold_id}", headers=headers)

    def list_compliance_holds(self, headers, params=None):
        return self._request("GET", "/compliance-holds", headers=headers, params=params)

    def release_hold(self, hold_id, headers):
        return self._request("POST", f"/compliance-holds/{hold_id}/release", {}, headers)

    # ----- StorageInvoice -----
    def get_storage_invoice(self, invoice_id, headers):
        return self._request("GET", f"/storage-invoices/{invoice_id}", headers=headers)

    def list_storage_invoices(self, headers, params=None):
        return self._request("GET", "/storage-invoices", headers=headers, params=params)

    def pay_storage_invoice(self, invoice_id, headers):
        return self._request("POST", f"/storage-invoices/{invoice_id}/pay", {}, headers)


api_client = ApiClient()
