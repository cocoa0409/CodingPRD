"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    # ---- Subscriptions ----
    def create_subscription(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/subscriptions", payload, headers)

    def get_account_subscription(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}/subscription", headers=headers)

    def change_tier(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/change-tier", payload, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    # ---- Credit ledger ----
    def create_credit_adjustment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/credit-adjustments", payload, headers)

    def list_credit_transactions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/credit-transactions", headers=headers, params=params)

    # ---- Contacts ----
    def create_contact(self, payload, headers):
        return self._request("POST", "/contacts", payload, headers)

    def list_account_contacts(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/contacts", headers=headers, params=params)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"/contacts/{contact_id}", headers=headers)

    def bulk_import_contacts(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/contacts/bulk-import", payload, headers)

    def verify_address(self, contact_id, payload, headers):
        return self._request("POST", f"/contacts/{contact_id}/verify-address", payload, headers)

    # ---- Important dates ----
    def create_important_date(self, contact_id, payload, headers):
        return self._request("POST", f"/contacts/{contact_id}/important-dates", payload, headers)

    def get_important_date(self, important_date_id, headers):
        return self._request("GET", f"/important-dates/{important_date_id}", headers=headers)

    def list_important_dates(self, headers, params=None):
        return self._request("GET", "/important-dates", headers=headers, params=params)

    def archive_important_date(self, important_date_id, headers):
        return self._request("POST", f"/important-dates/{important_date_id}/archive", headers=headers)

    # ---- Cards ----
    def create_card(self, payload, headers):
        return self._request("POST", "/cards", payload, headers)

    def get_card(self, card_id, headers):
        return self._request("GET", f"/cards/{card_id}", headers=headers)

    def retire_card(self, card_id, headers):
        return self._request("POST", f"/cards/{card_id}/retire", headers=headers)

    # ---- Gift items ----
    def create_gift_item(self, payload, headers):
        return self._request("POST", "/gift-items", payload, headers)

    def retire_gift_item(self, gift_item_id, headers):
        return self._request("POST", f"/gift-items/{gift_item_id}/retire", headers=headers)

    # ---- Artists ----
    def create_artist(self, payload, headers):
        return self._request("POST", "/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/artists/{artist_id}", headers=headers)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/submit", payload, headers)

    def assign_artist(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/assign-artist", payload, headers)

    def schedule_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/schedule", headers=headers)

    def produce_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/produce", headers=headers)

    def mail_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/mail", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    # ---- Artist assignments ----
    def get_artist_assignment(self, assignment_id, headers):
        return self._request("GET", f"/artist-assignments/{assignment_id}", headers=headers)

    def list_artist_assignments(self, headers, params=None):
        return self._request("GET", "/artist-assignments", headers=headers, params=params)

    # ---- Proofs ----
    def list_order_proofs(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/proofs", headers=headers)

    def approve_proof(self, proof_id, headers):
        return self._request("POST", f"/proofs/{proof_id}/approve", headers=headers)

    def request_changes(self, proof_id, payload, headers):
        return self._request("POST", f"/proofs/{proof_id}/request-changes", payload, headers)

    def revise_proof(self, proof_id, payload, headers):
        return self._request("POST", f"/proofs/{proof_id}/revise", payload, headers)

    # ---- Shipments ----
    def get_order_shipment(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/shipment", headers=headers)

    def advance_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/advance", payload, headers)

    # ---- Test-driving controls ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_scheduler(self, headers):
        return self._request("POST", "/_scheduler/run", headers=headers)


api_client = ApiClient()
