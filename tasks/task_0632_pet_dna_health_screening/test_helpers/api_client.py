"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; only the PRD-specific endpoint
methods are defined here. The base _request() handles transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/dna/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/dna/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/dna/accounts/{account_id}", headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/dna/accounts/{account_id}", payload, headers)

    # ---- Pets ----
    def create_pet(self, payload, headers):
        return self._request("POST", "/dna/pets", payload, headers)

    def get_pet(self, pet_id, headers):
        return self._request("GET", f"/dna/pets/{pet_id}", headers=headers)

    def list_pets(self, headers, params=None):
        return self._request("GET", "/dna/pets", headers=headers, params=params)

    def update_pet(self, pet_id, payload, headers):
        return self._request("PATCH", f"/dna/pets/{pet_id}", payload, headers)

    # ---- Kits ----
    def create_kit(self, payload, headers):
        return self._request("POST", "/dna/kits", payload, headers)

    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/dna/kits/{kit_id}", headers=headers)

    def list_kits(self, headers, params=None):
        return self._request("GET", "/dna/kits", headers=headers, params=params)

    def activate_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/dna/kits/{kit_id}/activate", payload, headers)

    def void_kit(self, kit_id, headers):
        return self._request("POST", f"/dna/kits/{kit_id}/void", {}, headers)

    # ---- Samples ----
    def create_sample(self, payload, headers):
        return self._request("POST", "/dna/samples", payload, headers)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/dna/samples/{sample_id}", headers=headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/dna/samples", headers=headers, params=params)

    def create_genotyping_run(self, sample_id, payload, headers):
        return self._request("POST", f"/dna/samples/{sample_id}/genotyping-runs",
                             payload, headers)

    def list_genotyping_runs(self, sample_id, headers, params=None):
        return self._request("GET", f"/dna/samples/{sample_id}/genotyping-runs",
                             headers=headers, params=params)

    # ---- Reports ----
    def get_report(self, report_id, headers):
        return self._request("GET", f"/dna/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/dna/reports", headers=headers, params=params)

    def create_marker(self, report_id, payload, headers):
        return self._request("POST", f"/dna/reports/{report_id}/markers", payload, headers)

    def list_markers(self, report_id, headers, params=None):
        return self._request("GET", f"/dna/reports/{report_id}/markers",
                             headers=headers, params=params)

    def finalize_report(self, report_id, payload, headers):
        return self._request("POST", f"/dna/reports/{report_id}/finalize", payload, headers)

    def revoke_report(self, report_id, headers):
        return self._request("POST", f"/dna/reports/{report_id}/revoke", {}, headers)

    # ---- Share links ----
    def create_share_link(self, payload, headers):
        return self._request("POST", "/dna/share-links", payload, headers)

    def get_share_link(self, share_link_id, headers):
        return self._request("GET", f"/dna/share-links/{share_link_id}", headers=headers)

    def list_share_links(self, headers, params=None):
        return self._request("GET", "/dna/share-links", headers=headers, params=params)

    def get_shared_report(self, token, headers=None):
        return self._request("GET", f"/dna/shared-reports/{token}", headers=headers)

    def revoke_share_link(self, share_link_id, headers):
        return self._request("POST", f"/dna/share-links/{share_link_id}/revoke", {}, headers)

    # ---- Relative matches ----
    def create_relative_match(self, payload, headers):
        return self._request("POST", "/dna/relative-matches", payload, headers)

    def get_relative_match(self, match_id, headers):
        return self._request("GET", f"/dna/relative-matches/{match_id}", headers=headers)

    def list_relative_matches(self, headers, params=None):
        return self._request("GET", "/dna/relative-matches", headers=headers, params=params)

    def confirm_relative_match(self, match_id, headers):
        return self._request("POST", f"/dna/relative-matches/{match_id}/confirm", {}, headers)

    def withdraw_relative_match(self, match_id, headers):
        return self._request("POST", f"/dna/relative-matches/{match_id}/withdraw", {}, headers)

    # ---- Subscriptions ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/dna/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/dna/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/dna/subscriptions", headers=headers, params=params)

    def upgrade_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/dna/subscriptions/{subscription_id}/upgrade",
                             payload, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/dna/subscriptions/{subscription_id}/cancel", {}, headers)

    def expire_subscription(self, subscription_id, headers):
        return self._request("POST", f"/dna/subscriptions/{subscription_id}/expire", {}, headers)

    # ---- Data requests ----
    def create_data_request(self, payload, headers):
        return self._request("POST", "/dna/data-requests", payload, headers)

    def get_data_request(self, request_id, headers):
        return self._request("GET", f"/dna/data-requests/{request_id}", headers=headers)

    def list_data_requests(self, headers, params=None):
        return self._request("GET", "/dna/data-requests", headers=headers, params=params)

    def purge_data_request(self, request_id, headers):
        return self._request("POST", f"/dna/data-requests/{request_id}/purge", {}, headers)

    def purge_finalize_data_request(self, request_id, headers):
        return self._request("POST", f"/dna/data-requests/{request_id}/purge-finalize", {}, headers)

    def cancel_data_request(self, request_id, headers):
        return self._request("POST", f"/dna/data-requests/{request_id}/cancel", {}, headers)

    # ---- Marker catalog ----
    def create_marker_catalog_entry(self, payload, headers):
        return self._request("POST", "/dna/marker-catalog", payload, headers)

    def list_marker_catalog(self, headers, params=None):
        return self._request("GET", "/dna/marker-catalog", headers=headers, params=params)


api_client = ApiClient()
