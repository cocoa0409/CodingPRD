"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
envelope, headers, and HTTP plumbing. All endpoint paths use the root prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def advance_clock(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/clock/advance", payload, headers)

    # --- LockerUnit ---
    def create_locker_unit(self, payload, headers):
        return self._request("POST", "/locker-units", payload, headers)

    def get_locker_unit(self, locker_id, headers):
        return self._request("GET", f"/locker-units/{locker_id}", headers=headers)

    def list_locker_units(self, headers, params=None):
        return self._request("GET", "/locker-units", headers=headers, params=params)

    def locker_out_of_service(self, locker_id, headers):
        return self._request("POST", f"/locker-units/{locker_id}/out-of-service", {}, headers)

    def locker_restore(self, locker_id, headers):
        return self._request("POST", f"/locker-units/{locker_id}/restore", {}, headers)

    # --- MailboxUnit ---
    def create_mailbox_unit(self, payload, headers):
        return self._request("POST", "/mailbox-units", payload, headers)

    def get_mailbox_unit(self, mailbox_id, headers):
        return self._request("GET", f"/mailbox-units/{mailbox_id}", headers=headers)

    def list_mailbox_units(self, headers, params=None):
        return self._request("GET", "/mailbox-units", headers=headers, params=params)

    def mailbox_out_of_service(self, mailbox_id, headers):
        return self._request("POST", f"/mailbox-units/{mailbox_id}/out-of-service", {}, headers)

    def mailbox_restore(self, mailbox_id, headers):
        return self._request("POST", f"/mailbox-units/{mailbox_id}/restore", {}, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    # --- Form1583 + AuthorizedRecipient ---
    def create_form_1583(self, payload, headers):
        return self._request("POST", "/forms-1583", payload, headers)

    def get_form_1583(self, form_id, headers):
        return self._request("GET", f"/forms-1583/{form_id}", headers=headers)

    def list_forms_1583(self, headers, params=None):
        return self._request("GET", "/forms-1583", headers=headers, params=params)

    def add_recipient(self, form_id, payload, headers):
        return self._request("POST", f"/forms-1583/{form_id}/recipients", payload, headers)

    def list_recipients(self, form_id, headers):
        return self._request("GET", f"/forms-1583/{form_id}/recipients", headers=headers)

    def submit_form_1583(self, form_id, headers):
        return self._request("POST", f"/forms-1583/{form_id}/submit", {}, headers)

    def verify_form_1583(self, form_id, headers):
        return self._request("POST", f"/forms-1583/{form_id}/verify", {}, headers)

    def reject_form_1583(self, form_id, payload, headers):
        return self._request("POST", f"/forms-1583/{form_id}/reject", payload, headers)

    # --- RentalAgreement ---
    def create_rental_agreement(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def get_rental_agreement(self, agreement_id, headers):
        return self._request("GET", f"/rental-agreements/{agreement_id}", headers=headers)

    def list_rental_agreements(self, headers, params=None):
        return self._request("GET", "/rental-agreements", headers=headers, params=params)

    def refund_quote(self, agreement_id, headers, params=None):
        return self._request("GET", f"/rental-agreements/{agreement_id}/refund-quote", headers=headers, params=params)

    def activate_rental_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/activate", {}, headers)

    def renew_rental_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/renew", payload, headers)

    def suspend_rental_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/suspend", {}, headers)

    def reactivate_rental_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/reactivate", {}, headers)

    def close_rental_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/close", {}, headers)

    # --- Package ---
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    def notify_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/notify", {}, headers)

    def pickup_package(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/pickup", payload, headers)

    def forward_package(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/forward", payload, headers)

    def return_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/return-to-sender", {}, headers)

    # --- MailItem ---
    def create_mail_item(self, payload, headers):
        return self._request("POST", "/mail-items", payload, headers)

    def get_mail_item(self, mail_item_id, headers):
        return self._request("GET", f"/mail-items/{mail_item_id}", headers=headers)

    def list_mail_items(self, headers, params=None):
        return self._request("GET", "/mail-items", headers=headers, params=params)

    # --- ForwardingRequest ---
    def create_forwarding_request(self, payload, headers):
        return self._request("POST", "/forwarding-requests", payload, headers)

    def get_forwarding_request(self, request_id, headers):
        return self._request("GET", f"/forwarding-requests/{request_id}", headers=headers)

    def list_forwarding_requests(self, headers, params=None):
        return self._request("GET", "/forwarding-requests", headers=headers, params=params)

    def complete_forwarding_request(self, request_id, headers):
        return self._request("POST", f"/forwarding-requests/{request_id}/complete", {}, headers)

    def cancel_forwarding_request(self, request_id, headers):
        return self._request("POST", f"/forwarding-requests/{request_id}/cancel", {}, headers)

    # --- Invoice / LedgerEntry / Payment ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def list_ledger_entries(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}/ledger-entries", headers=headers)

    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)


api_client = ApiClient()
