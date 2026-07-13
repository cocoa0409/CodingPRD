"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Clock (test-driving) -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- Publisher -----
    def create_publisher(self, payload, headers):
        return self._request("POST", "/publishers", payload, headers)

    def get_publisher(self, publisher_id, headers):
        return self._request("GET", f"/publishers/{publisher_id}", headers=headers)

    def create_isbn(self, publisher_id, payload, headers):
        return self._request("POST", f"/publishers/{publisher_id}/isbns", payload, headers)

    def create_statement(self, publisher_id, payload, headers):
        return self._request("POST", f"/publishers/{publisher_id}/royalty-statements",
                             payload, headers)

    # ----- Title -----
    def create_title(self, payload, headers):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/titles", headers=headers, params=params)

    # ----- Format -----
    def create_format(self, title_id, payload, headers):
        return self._request("POST", f"/titles/{title_id}/formats", payload, headers)

    def get_format(self, format_id, headers):
        return self._request("GET", f"/formats/{format_id}", headers=headers)

    def list_formats(self, headers, params=None):
        return self._request("GET", "/formats", headers=headers, params=params)

    def lock_format(self, format_id, headers):
        return self._request("POST", f"/formats/{format_id}/lock", {}, headers)

    def publish_format(self, format_id, headers):
        return self._request("POST", f"/formats/{format_id}/publish", {}, headers)

    def assign_isbn(self, format_id, payload, headers):
        return self._request("POST", f"/formats/{format_id}/assign-isbn", payload, headers)

    def release_isbn(self, format_id, headers):
        return self._request("POST", f"/formats/{format_id}/release-isbn", {}, headers)

    def create_price(self, format_id, payload, headers):
        return self._request("POST", f"/formats/{format_id}/prices", payload, headers)

    def create_proof(self, format_id, headers):
        return self._request("POST", f"/formats/{format_id}/proofs", {}, headers)

    def create_distribution_request(self, format_id, payload, headers):
        return self._request("POST", f"/formats/{format_id}/distribution-requests",
                             payload, headers)

    # ----- Asset -----
    def create_asset(self, format_id, payload, headers):
        return self._request("POST", f"/formats/{format_id}/assets", payload, headers)

    def validate_asset(self, asset_id, headers):
        return self._request("POST", f"/assets/{asset_id}/validate", {}, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    # ----- Isbn -----
    def get_isbn(self, isbn_id, headers):
        return self._request("GET", f"/isbns/{isbn_id}", headers=headers)

    def list_isbns(self, headers, params=None):
        return self._request("GET", "/isbns", headers=headers, params=params)

    # ----- Channel -----
    def create_channel(self, payload, headers):
        return self._request("POST", "/channels", payload, headers)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/channels/{channel_id}", headers=headers)

    # ----- ChannelPrice -----
    def get_price(self, price_id, headers):
        return self._request("GET", f"/prices/{price_id}", headers=headers)

    def list_prices(self, headers, params=None):
        return self._request("GET", "/prices", headers=headers, params=params)

    # ----- Proof -----
    def approve_proof(self, proof_id, headers):
        return self._request("POST", f"/proofs/{proof_id}/approve", {}, headers)

    def request_revision(self, proof_id, payload, headers):
        return self._request("POST", f"/proofs/{proof_id}/request-revision", payload, headers)

    def get_proof(self, proof_id, headers):
        return self._request("GET", f"/proofs/{proof_id}", headers=headers)

    def list_proofs(self, headers, params=None):
        return self._request("GET", "/proofs", headers=headers, params=params)

    # ----- DistributionRequest -----
    def approve_distribution(self, dr_id, headers):
        return self._request("POST", f"/distribution-requests/{dr_id}/approve", {}, headers)

    def reject_distribution(self, dr_id, payload, headers):
        return self._request("POST", f"/distribution-requests/{dr_id}/reject", payload, headers)

    def withdraw_distribution(self, dr_id, headers):
        return self._request("POST", f"/distribution-requests/{dr_id}/withdraw", {}, headers)

    def get_distribution(self, dr_id, headers):
        return self._request("GET", f"/distribution-requests/{dr_id}", headers=headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/distribution-requests", headers=headers, params=params)

    # ----- Sales & Royalty -----
    def create_sales_line(self, payload, headers):
        return self._request("POST", "/sales-lines", payload, headers)

    def get_sales_line(self, sales_line_id, headers):
        return self._request("GET", f"/sales-lines/{sales_line_id}", headers=headers)

    def list_sales_lines(self, headers, params=None):
        return self._request("GET", "/sales-lines", headers=headers, params=params)

    def issue_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/issue", {}, headers)

    def pay_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/pay", {}, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/royalty-statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/royalty-statements", headers=headers, params=params)


api_client = ApiClient()
