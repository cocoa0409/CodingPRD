"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Contractor ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/distributor/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/distributor/contractors",
                             headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/distributor/contractors/{contractor_id}",
                             headers=headers)

    def record_payment(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/distributor/contractors/{contractor_id}/payments",
            payload, headers)

    # --- CatalogItem ---
    def create_catalog_item(self, payload, headers):
        return self._request("POST", "/distributor/catalog-items", payload, headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", "/distributor/catalog-items",
                             headers=headers, params=params)

    def get_catalog_item(self, item_id, headers):
        return self._request("GET", f"/distributor/catalog-items/{item_id}",
                             headers=headers)

    def receive_stock(self, item_id, payload, headers):
        return self._request(
            "POST", f"/distributor/catalog-items/{item_id}/stock-receipts",
            payload, headers)

    # --- JobAccount ---
    def create_job_account(self, payload, headers):
        return self._request("POST", "/distributor/job-accounts", payload, headers)

    def list_job_accounts(self, headers, params=None):
        return self._request("GET", "/distributor/job-accounts",
                             headers=headers, params=params)

    def get_job_account(self, job_account_id, headers):
        return self._request("GET", f"/distributor/job-accounts/{job_account_id}",
                             headers=headers)

    def close_job_account(self, job_account_id, headers):
        return self._request(
            "POST", f"/distributor/job-accounts/{job_account_id}/close",
            headers=headers)

    def file_lien_waiver(self, job_account_id, payload, headers):
        return self._request(
            "POST", f"/distributor/job-accounts/{job_account_id}/lien-waivers",
            payload, headers)

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/distributor/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/distributor/quotes",
                             headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/distributor/quotes/{quote_id}",
                             headers=headers)

    def submit_quote(self, quote_id, headers):
        return self._request("POST", f"/distributor/quotes/{quote_id}/submit",
                             headers=headers)

    def revise_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/distributor/quotes/{quote_id}/revise",
                             payload, headers)

    def award_quote(self, quote_id, headers):
        return self._request("POST", f"/distributor/quotes/{quote_id}/award",
                             headers=headers)

    # --- QuoteLine (BOM takeoff) ---
    def create_quote_line(self, payload, headers):
        return self._request("POST", "/distributor/quote-lines", payload, headers)

    def list_quote_lines(self, headers, params=None):
        return self._request("GET", "/distributor/quote-lines",
                             headers=headers, params=params)

    def get_quote_line(self, quote_line_id, headers):
        return self._request("GET", f"/distributor/quote-lines/{quote_line_id}",
                             headers=headers)

    # --- SubstitutionRequest ---
    def create_substitution_request(self, payload, headers):
        return self._request("POST", "/distributor/substitution-requests",
                             payload, headers)

    def list_substitution_requests(self, headers, params=None):
        return self._request("GET", "/distributor/substitution-requests",
                             headers=headers, params=params)

    def get_substitution_request(self, request_id, headers):
        return self._request(
            "GET", f"/distributor/substitution-requests/{request_id}",
            headers=headers)

    def decide_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/distributor/substitution-requests/{request_id}/decide",
            payload, headers)

    # --- Release ---
    def create_release(self, payload, headers):
        return self._request("POST", "/distributor/releases", payload, headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/distributor/releases",
                             headers=headers, params=params)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/distributor/releases/{release_id}",
                             headers=headers)

    def credit_approve_release(self, release_id, headers):
        return self._request(
            "POST", f"/distributor/releases/{release_id}/credit-approve",
            headers=headers)

    def allocate_release(self, release_id, headers):
        return self._request(
            "POST", f"/distributor/releases/{release_id}/allocate",
            headers=headers)

    def schedule_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"/distributor/releases/{release_id}/schedule",
            payload, headers)

    def deliver_release(self, release_id, headers):
        return self._request(
            "POST", f"/distributor/releases/{release_id}/deliver",
            headers=headers)

    def invoice_release(self, release_id, headers):
        return self._request(
            "POST", f"/distributor/releases/{release_id}/invoice",
            headers=headers)

    def cancel_release(self, release_id, headers):
        return self._request(
            "POST", f"/distributor/releases/{release_id}/cancel",
            headers=headers)

    # --- ReleaseLine / BackorderAllocation reads ---
    def list_release_lines(self, headers, params=None):
        return self._request("GET", "/distributor/release-lines",
                             headers=headers, params=params)

    def get_release_line(self, release_line_id, headers):
        return self._request("GET", f"/distributor/release-lines/{release_line_id}",
                             headers=headers)

    def list_backorder_allocations(self, headers, params=None):
        return self._request("GET", "/distributor/backorder-allocations",
                             headers=headers, params=params)

    def get_backorder_allocation(self, backorder_id, headers):
        return self._request(
            "GET", f"/distributor/backorder-allocations/{backorder_id}",
            headers=headers)

    # --- RebateProgram / RebateClaim ---
    def create_rebate_program(self, payload, headers):
        return self._request("POST", "/distributor/rebate-programs",
                             payload, headers)

    def list_rebate_programs(self, headers, params=None):
        return self._request("GET", "/distributor/rebate-programs",
                             headers=headers, params=params)

    def get_rebate_program(self, program_id, headers):
        return self._request("GET", f"/distributor/rebate-programs/{program_id}",
                             headers=headers)

    def create_rebate_claim(self, payload, headers):
        return self._request("POST", "/distributor/rebate-claims",
                             payload, headers)

    def list_rebate_claims(self, headers, params=None):
        return self._request("GET", "/distributor/rebate-claims",
                             headers=headers, params=params)

    def get_rebate_claim(self, claim_id, headers):
        return self._request("GET", f"/distributor/rebate-claims/{claim_id}",
                             headers=headers)

    def submit_rebate_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/distributor/rebate-claims/{claim_id}/submit",
            headers=headers)

    def decide_rebate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/distributor/rebate-claims/{claim_id}/decide",
            payload, headers)

    # --- Test-driving endpoints ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/distributor/_clock/set_current_utc",
                             payload, headers)

    def set_index_reading(self, payload, headers):
        return self._request("POST", "/distributor/_index-readings/set",
                             payload, headers)


api_client = ApiClient()
