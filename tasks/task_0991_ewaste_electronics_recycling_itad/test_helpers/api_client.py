"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Business accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/itad/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/itad/accounts/{account_id}", headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/itad/accounts/{account_id}", payload, headers)

    def list_account_manifests(self, account_id, headers, params=None):
        return self._request("GET", f"/itad/accounts/{account_id}/manifests", headers=headers, params=params)

    def list_account_ledger_entries(self, account_id, headers, params=None):
        return self._request("GET", f"/itad/accounts/{account_id}/ledger-entries", headers=headers, params=params)

    def get_sustainability_report(self, account_id, headers):
        return self._request("GET", f"/itad/accounts/{account_id}/sustainability-report", headers=headers)

    # --- Recyclers ---
    def create_recycler(self, payload, headers):
        return self._request("POST", "/itad/recyclers", payload, headers)

    def get_recycler(self, recycler_id, headers):
        return self._request("GET", f"/itad/recyclers/{recycler_id}", headers=headers)

    def list_recycler_batches(self, recycler_id, headers, params=None):
        return self._request("GET", f"/itad/recyclers/{recycler_id}/recycle-batches", headers=headers, params=params)

    # --- Compliance policies ---
    def create_compliance_policy(self, payload, headers):
        return self._request("POST", "/itad/compliance-policies", payload, headers)

    def list_compliance_policies(self, headers, params=None):
        return self._request("GET", "/itad/compliance-policies", headers=headers, params=params)

    # --- Manifests ---
    def create_manifest(self, payload, headers):
        return self._request("POST", "/itad/manifests", payload, headers)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/itad/manifests/{manifest_id}", headers=headers)

    def update_manifest(self, manifest_id, payload, headers):
        return self._request("PATCH", f"/itad/manifests/{manifest_id}", payload, headers)

    def schedule_manifest(self, manifest_id, headers):
        return self._request("POST", f"/itad/manifests/{manifest_id}/schedule", {}, headers)

    def receive_manifest(self, manifest_id, headers):
        return self._request("POST", f"/itad/manifests/{manifest_id}/receive", {}, headers)

    def reconcile_manifest(self, manifest_id, headers):
        return self._request("POST", f"/itad/manifests/{manifest_id}/reconcile", {}, headers)

    def close_manifest(self, manifest_id, headers):
        return self._request("POST", f"/itad/manifests/{manifest_id}/close", {}, headers)

    def cancel_manifest(self, manifest_id, headers):
        return self._request("POST", f"/itad/manifests/{manifest_id}/cancel", {}, headers)

    def add_manifest_item(self, manifest_id, payload, headers):
        return self._request("POST", f"/itad/manifests/{manifest_id}/items", payload, headers)

    def list_manifest_items(self, manifest_id, headers, params=None):
        return self._request("GET", f"/itad/manifests/{manifest_id}/items", headers=headers, params=params)

    def list_manifest_settlements(self, manifest_id, headers, params=None):
        return self._request("GET", f"/itad/manifests/{manifest_id}/settlements", headers=headers, params=params)

    # --- Items ---
    def get_item(self, item_id, headers):
        return self._request("GET", f"/itad/items/{item_id}", headers=headers)

    def triage_item(self, item_id, payload, headers):
        return self._request("POST", f"/itad/items/{item_id}/triage", payload, headers)

    def create_sanitization(self, item_id, payload, headers):
        return self._request("POST", f"/itad/items/{item_id}/sanitizations", payload, headers)

    def list_sanitizations(self, item_id, headers, params=None):
        return self._request("GET", f"/itad/items/{item_id}/sanitizations", headers=headers, params=params)

    def verify_sanitization(self, sanitization_id, payload, headers):
        return self._request("POST", f"/itad/sanitizations/{sanitization_id}/verify", payload, headers)

    def create_item_certificate(self, item_id, payload, headers):
        return self._request("POST", f"/itad/items/{item_id}/certificates", payload, headers)

    def list_item_certificates(self, item_id, headers, params=None):
        return self._request("GET", f"/itad/items/{item_id}/certificates", headers=headers, params=params)

    # --- Resale listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/itad/listings", payload, headers)

    def list_item_listings(self, item_id, headers, params=None):
        return self._request("GET", f"/itad/items/{item_id}/listings", headers=headers, params=params)

    def sell_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/itad/listings/{listing_id}/sell", payload, headers)

    def return_listing(self, listing_id, headers):
        return self._request("POST", f"/itad/listings/{listing_id}/return", {}, headers)

    def relist_listing(self, listing_id, headers):
        return self._request("POST", f"/itad/listings/{listing_id}/relist", {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/itad/listings/{listing_id}/withdraw", {}, headers)

    # --- Recycle batches ---
    def create_recycle_batch(self, payload, headers):
        return self._request("POST", "/itad/recycle-batches", payload, headers)

    def get_recycle_batch(self, batch_id, headers):
        return self._request("GET", f"/itad/recycle-batches/{batch_id}", headers=headers)

    def list_batch_items(self, batch_id, headers, params=None):
        return self._request("GET", f"/itad/recycle-batches/{batch_id}/items", headers=headers, params=params)

    def add_batch_item(self, batch_id, payload, headers):
        return self._request("POST", f"/itad/recycle-batches/{batch_id}/items", payload, headers)

    def remove_batch_item(self, batch_id, item_id, headers):
        return self._request("DELETE", f"/itad/recycle-batches/{batch_id}/items/{item_id}", headers=headers)

    def ship_batch(self, batch_id, headers):
        return self._request("POST", f"/itad/recycle-batches/{batch_id}/ship", {}, headers)

    def deliver_batch(self, batch_id, headers):
        return self._request("POST", f"/itad/recycle-batches/{batch_id}/deliver", {}, headers)

    def process_batch(self, batch_id, headers):
        return self._request("POST", f"/itad/recycle-batches/{batch_id}/process", {}, headers)

    def list_batch_certificates(self, batch_id, headers, params=None):
        return self._request("GET", f"/itad/recycle-batches/{batch_id}/certificates", headers=headers, params=params)

    # --- Settlements ---
    def create_settlement(self, manifest_id, payload, headers):
        return self._request("POST", f"/itad/manifests/{manifest_id}/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/itad/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/itad/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/itad/settlements/{settlement_id}/finalize", {}, headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/itad/settlements/{settlement_id}/pay", {}, headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST", f"/itad/settlements/{settlement_id}/void", {}, headers)

    def list_settlement_ledger_entries(self, settlement_id, headers, params=None):
        return self._request("GET", f"/itad/settlements/{settlement_id}/ledger-entries", headers=headers, params=params)

    # --- Certificates ---
    def void_certificate(self, certificate_id, headers):
        return self._request("POST", f"/itad/certificates/{certificate_id}/void", {}, headers)

    # --- Custody trail ---
    def list_custody_events(self, headers, params=None):
        return self._request("GET", "/itad/custody-events", headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/itad/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
