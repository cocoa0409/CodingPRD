"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Deposit products ---
    def create_deposit_product(self, payload, headers):
        return self._request("POST", "/deposit-products", payload, headers)

    def list_deposit_products(self, headers, params=None):
        return self._request("GET", "/deposit-products", headers=headers, params=params)

    # --- Rate sheets ---
    def create_rate_sheet(self, payload, headers):
        return self._request("POST", "/rate-sheets", payload, headers)

    def list_rate_sheets(self, headers, params=None):
        return self._request("GET", "/rate-sheets", headers=headers, params=params)

    def get_rate_sheet(self, sheet_id, headers):
        return self._request("GET", f"/rate-sheets/{sheet_id}", headers=headers)

    def patch_rate_sheet(self, sheet_id, payload, headers):
        return self._request("PATCH", f"/rate-sheets/{sheet_id}", payload, headers)

    def submit_rate_sheet(self, sheet_id, headers):
        return self._request("POST", f"/rate-sheets/{sheet_id}/submit", {}, headers)

    def review_decision_rate_sheet(self, sheet_id, payload, headers):
        return self._request("POST", f"/rate-sheets/{sheet_id}/review-decision", payload, headers)

    def schedule_rate_sheet(self, sheet_id, headers):
        return self._request("POST", f"/rate-sheets/{sheet_id}/schedule", {}, headers)

    def activate_rate_sheet(self, sheet_id, headers):
        return self._request("POST", f"/rate-sheets/{sheet_id}/activate", {}, headers)

    def retire_rate_sheet(self, sheet_id, headers):
        return self._request("POST", f"/rate-sheets/{sheet_id}/retire", {}, headers)

    def get_margin_analysis(self, sheet_id, headers, params=None):
        return self._request("GET", f"/rate-sheets/{sheet_id}/margin-analysis", headers=headers, params=params)

    # --- Rate deployments ---
    def list_rate_deployments(self, headers, params=None):
        return self._request("GET", "/rate-deployments", headers=headers, params=params)

    def get_rate_deployment(self, deployment_id, headers):
        return self._request("GET", f"/rate-deployments/{deployment_id}", headers=headers)

    def execute_rate_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"/rate-deployments/{deployment_id}/execution", payload, headers)

    # --- Competitor rate scans ---
    def create_competitor_rate_scan(self, payload, headers):
        return self._request("POST", "/competitor-rate-scans", payload, headers)

    def list_competitor_rate_scans(self, headers, params=None):
        return self._request("GET", "/competitor-rate-scans", headers=headers, params=params)

    def get_competitor_rate_scan(self, scan_id, headers):
        return self._request("GET", f"/competitor-rate-scans/{scan_id}", headers=headers)

    def analyze_competitor_rate_scan(self, scan_id, headers):
        return self._request("POST", f"/competitor-rate-scans/{scan_id}/analyze", {}, headers)

    # --- Repricing cycles ---
    def create_repricing_cycle(self, payload, headers):
        return self._request("POST", "/repricing-cycles", payload, headers)

    def list_repricing_cycles(self, headers, params=None):
        return self._request("GET", "/repricing-cycles", headers=headers, params=params)

    def get_repricing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/repricing-cycles/{cycle_id}", headers=headers)

    # --- Promotional offers ---
    def create_promotional_offer(self, payload, headers):
        return self._request("POST", "/promotional-offers", payload, headers)

    def list_promotional_offers(self, headers, params=None):
        return self._request("GET", "/promotional-offers", headers=headers, params=params)

    def get_promotional_offer(self, offer_id, headers):
        return self._request("GET", f"/promotional-offers/{offer_id}", headers=headers)

    def publish_promotional_offer(self, offer_id, headers):
        return self._request("POST", f"/promotional-offers/{offer_id}/publish", {}, headers)

    def close_promotional_offer(self, offer_id, headers):
        return self._request("POST", f"/promotional-offers/{offer_id}/close", {}, headers)

    # --- Exception pricing requests ---
    def create_exception_pricing_request(self, payload, headers):
        return self._request("POST", "/exception-pricing-requests", payload, headers)

    def list_exception_pricing_requests(self, headers, params=None):
        return self._request("GET", "/exception-pricing-requests", headers=headers, params=params)

    def get_exception_pricing_request(self, request_id, headers):
        return self._request("GET", f"/exception-pricing-requests/{request_id}", headers=headers)

    def decide_exception_pricing_request(self, request_id, payload, headers):
        return self._request("POST", f"/exception-pricing-requests/{request_id}/decision", payload, headers)

    def resubmit_exception_pricing_request(self, request_id, payload, headers):
        return self._request("POST", f"/exception-pricing-requests/{request_id}/resubmit", payload, headers)

    def apply_exception_pricing_request(self, request_id, headers):
        return self._request("POST", f"/exception-pricing-requests/{request_id}/apply", {}, headers)

    # --- Deposit accounts ---
    def create_deposit_account(self, payload, headers):
        return self._request("POST", "/deposit-accounts", payload, headers)

    def list_deposit_accounts(self, headers, params=None):
        return self._request("GET", "/deposit-accounts", headers=headers, params=params)

    def get_deposit_account(self, account_id, headers):
        return self._request("GET", f"/deposit-accounts/{account_id}", headers=headers)

    def patch_deposit_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/deposit-accounts/{account_id}", payload, headers)

    def deposit_account_action(self, account_id, payload, headers):
        return self._request("POST", f"/deposit-accounts/{account_id}/actions", payload, headers)

    def post_interest(self, account_id, headers):
        return self._request("POST", f"/deposit-accounts/{account_id}/interest-postings", {}, headers)

    def get_rate_quote(self, account_id, headers):
        return self._request("GET", f"/deposit-accounts/{account_id}/rate-quote", headers=headers)

    # --- Funding curves ---
    def create_funding_curve(self, payload, headers):
        return self._request("POST", "/funding-curves", payload, headers)

    def list_funding_curves(self, headers, params=None):
        return self._request("GET", "/funding-curves", headers=headers, params=params)

    # --- Relationship bundles and enrollments ---
    def create_relationship_bundle(self, payload, headers):
        return self._request("POST", "/relationship-bundles", payload, headers)

    def list_relationship_bundles(self, headers, params=None):
        return self._request("GET", "/relationship-bundles", headers=headers, params=params)

    def create_bundle_enrollment(self, payload, headers):
        return self._request("POST", "/bundle-enrollments", payload, headers)

    def list_bundle_enrollments(self, headers, params=None):
        return self._request("GET", "/bundle-enrollments", headers=headers, params=params)

    def get_bundle_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/bundle-enrollments/{enrollment_id}", headers=headers)

    def transition_bundle_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/bundle-enrollments/{enrollment_id}/transition", payload, headers)

    # --- Disclosure notices ---
    def list_disclosure_notices(self, headers, params=None):
        return self._request("GET", "/disclosure-notices", headers=headers, params=params)

    def get_disclosure_notice(self, notice_id, headers):
        return self._request("GET", f"/disclosure-notices/{notice_id}", headers=headers)

    def resolve_disclosure_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/disclosure-notices/{notice_id}/resolution", payload, headers)

    # --- Migration batches ---
    def create_migration_batch(self, payload, headers):
        return self._request("POST", "/migration-batches", payload, headers)

    def list_migration_batches(self, headers, params=None):
        return self._request("GET", "/migration-batches", headers=headers, params=params)

    def get_migration_batch(self, batch_id, headers):
        return self._request("GET", f"/migration-batches/{batch_id}", headers=headers)

    def execute_migration_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/migration-batches/{batch_id}/execution", payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
