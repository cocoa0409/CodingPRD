"""Typed HTTP client: one method per documented endpoint.

Every method returns the raw response object so that tests can assert on the
status code as well as on the envelope.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """One method per endpoint of the creator monetization surface."""

    # ------------------------------------------------------------ clock -----
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ---------------------------------------------------------- creators ----
    def create_creator(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/creators", payload, headers)

    def list_creators(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/creators", params, headers)

    def get_creator(self, creator_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/creators/{creator_id}", None, headers
        )

    def patch_creator_metrics(self, creator_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/creators/{creator_id}/metrics", payload, headers
        )

    def evaluate_creator(self, creator_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/creators/{creator_id}/evaluate", payload, headers
        )

    def create_policy_strike(self, creator_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/creators/{creator_id}/policy-strikes",
            payload,
            headers,
        )

    def set_payout_settings(self, creator_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/creators/{creator_id}/payout-settings",
            payload,
            headers,
        )

    def list_ledger_entries(self, creator_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/creators/{creator_id}/ledger-entries",
            params,
            headers,
        )

    def list_creator_fund_allocations(self, creator_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/creators/{creator_id}/fund-allocations",
            params,
            headers,
        )

    def get_earnings_summary(self, creator_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/creators/{creator_id}/earnings-summary",
            None,
            headers,
        )

    # ------------------------------------------------------ tax profiles ----
    def create_tax_profile(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/tax-profiles", payload, headers)

    def list_tax_profiles(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/tax-profiles", params, headers)

    def get_tax_profile(self, tax_profile_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/tax-profiles/{tax_profile_id}", None, headers
        )

    def submit_tax_profile(self, tax_profile_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/tax-profiles/{tax_profile_id}/submit",
            payload,
            headers,
        )

    def verify_tax_profile(self, tax_profile_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/tax-profiles/{tax_profile_id}/verify",
            payload,
            headers,
        )

    def revise_tax_profile(self, tax_profile_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/tax-profiles/{tax_profile_id}/revise",
            payload,
            headers,
        )

    # --------------------------------------------------- revenue products ---
    def create_product(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/revenue-products", payload, headers
        )

    def list_products(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/revenue-products", params, headers)

    def patch_product(self, product_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/revenue-products/{product_id}", payload, headers
        )

    def retire_product(self, product_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/revenue-products/{product_id}/retire",
            payload,
            headers,
        )

    # ------------------------------------------------------ content items ---
    def create_content_item(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/content-items", payload, headers)

    def list_content_items(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/content-items", params, headers)

    def get_content_item(self, content_item_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/content-items/{content_item_id}", None, headers
        )

    def rate_content_item(self, content_item_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/content-items/{content_item_id}/rate",
            payload,
            headers,
        )

    # ----------------------------------------------------- revenue events ---
    def create_revenue_event(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/revenue-events", payload, headers)

    def list_revenue_events(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/revenue-events", params, headers)

    # ------------------------------------------------------------ appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/appeals", params, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"{API_PREFIX}/appeals/{appeal_id}", None, headers)

    def start_appeal_review(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/appeals/{appeal_id}/start-review", payload, headers
        )

    def request_appeal_info(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/appeals/{appeal_id}/request-info", payload, headers
        )

    def respond_to_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/appeals/{appeal_id}/respond", payload, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/appeals/{appeal_id}/decide", payload, headers
        )

    # --------------------------------------------------- earnings periods ---
    def create_period(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/earnings-periods", payload, headers
        )

    def list_periods(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/earnings-periods", params, headers)

    def get_period(self, period_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/earnings-periods/{period_id}", None, headers
        )

    def close_period(self, period_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/earnings-periods/{period_id}/close",
            payload,
            headers,
        )

    # ------------------------------------------------ earnings statements ---
    def list_statements(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/earnings-statements", params, headers
        )

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/earnings-statements/{statement_id}", None, headers
        )

    def finalize_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/earnings-statements/{statement_id}/finalize",
            payload,
            headers,
        )

    def dispute_statement(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/earnings-statements/{statement_id}/dispute",
            payload,
            headers,
        )

    def resolve_dispute(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/earnings-statements/{statement_id}/resolve-dispute",
            payload,
            headers,
        )

    # ------------------------------------------------------------ payouts ---
    def create_payout(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/payouts", payload, headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/payouts", params, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"{API_PREFIX}/payouts/{payout_id}", None, headers)

    def submit_payout(self, payout_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/payouts/{payout_id}/submit", payload, headers
        )

    def record_settlement(self, payout_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/payouts/{payout_id}/record-settlement",
            payload,
            headers,
        )

    def retry_payout(self, payout_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/payouts/{payout_id}/retry", payload, headers
        )

    # ---------------------------------------------------- investigations ----
    def create_investigation(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/investigations", payload, headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/investigations", params, headers)

    def get_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/investigations/{investigation_id}", None, headers
        )

    def substantiate_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/investigations/{investigation_id}/substantiate",
            payload,
            headers,
        )

    def clear_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/investigations/{investigation_id}/clear",
            payload,
            headers,
        )

    # ----------------------------------------------------- creator funds ----
    def create_fund(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/creator-funds", payload, headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/creator-funds", params, headers)

    def get_fund(self, fund_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/creator-funds/{fund_id}", None, headers
        )

    def allocate_fund(self, fund_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/creator-funds/{fund_id}/allocate", payload, headers
        )

    def void_fund_allocations(self, fund_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/creator-funds/{fund_id}/void-allocations",
            payload,
            headers,
        )

    def disburse_fund(self, fund_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/creator-funds/{fund_id}/disburse", payload, headers
        )

    def list_fund_allocations(self, fund_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/creator-funds/{fund_id}/fund-allocations",
            params,
            headers,
        )
