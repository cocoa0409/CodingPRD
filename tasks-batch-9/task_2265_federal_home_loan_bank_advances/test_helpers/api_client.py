"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the FHLB Advances Collateral Pledging API."""

    # ------------------------------------------------------------------
    # Member banks
    # ------------------------------------------------------------------
    def create_member_bank(self, payload, headers):
        return self._request("POST", "/fhlb/member-banks", payload, headers)

    def get_member_bank(self, member_bank_id, headers):
        return self._request(
            "GET", f"/fhlb/member-banks/{member_bank_id}", headers=headers
        )

    def get_borrowing_capacity(self, member_bank_id, headers, params=None):
        return self._request(
            "GET",
            f"/fhlb/member-banks/{member_bank_id}/borrowing-capacity",
            headers=headers,
            params=params,
        )

    def activate_member_bank(self, member_bank_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/member-banks/{member_bank_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def patch_member_bank_condition(self, member_bank_id, payload, headers):
        return self._request(
            "PATCH",
            f"/fhlb/member-banks/{member_bank_id}/condition",
            payload,
            headers,
        )

    def execute_pledge_agreement(self, member_bank_id, payload, headers):
        return self._request(
            "POST",
            f"/fhlb/member-banks/{member_bank_id}/pledge-agreement",
            payload,
            headers,
        )

    def escalate_shortfall(self, member_bank_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/member-banks/{member_bank_id}/escalate-shortfall",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Stock subscriptions
    # ------------------------------------------------------------------
    def create_stock_subscription(self, payload, headers):
        return self._request("POST", "/fhlb/stock-subscriptions", payload, headers)

    def list_stock_subscriptions(self, headers, params=None):
        return self._request(
            "GET", "/fhlb/stock-subscriptions", headers=headers, params=params
        )

    def get_stock_subscription(self, stock_subscription_id, headers):
        return self._request(
            "GET", f"/fhlb/stock-subscriptions/{stock_subscription_id}", headers=headers
        )

    def issue_stock_subscription(self, stock_subscription_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/stock-subscriptions/{stock_subscription_id}/issue",
            payload if payload is not None else {},
            headers,
        )

    def request_stock_redemption(self, stock_subscription_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/stock-subscriptions/{stock_subscription_id}/request-redemption",
            payload if payload is not None else {},
            headers,
        )

    def repurchase_stock_subscription(
        self, stock_subscription_id, headers, payload=None
    ):
        return self._request(
            "POST",
            f"/fhlb/stock-subscriptions/{stock_subscription_id}/repurchase",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Collateral assets
    # ------------------------------------------------------------------
    def create_collateral_asset(self, payload, headers):
        return self._request("POST", "/fhlb/collateral-assets", payload, headers)

    def list_collateral_assets(self, headers, params=None):
        return self._request(
            "GET", "/fhlb/collateral-assets", headers=headers, params=params
        )

    def get_collateral_asset(self, collateral_asset_id, headers):
        return self._request(
            "GET", f"/fhlb/collateral-assets/{collateral_asset_id}", headers=headers
        )

    def review_asset_eligibility(self, collateral_asset_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/collateral-assets/{collateral_asset_id}/review-eligibility",
            payload if payload is not None else {},
            headers,
        )

    def patch_asset_documentation(self, collateral_asset_id, payload, headers):
        return self._request(
            "PATCH",
            f"/fhlb/collateral-assets/{collateral_asset_id}/documentation",
            payload,
            headers,
        )

    def substitute_collateral_asset(self, collateral_asset_id, payload, headers):
        return self._request(
            "POST",
            f"/fhlb/collateral-assets/{collateral_asset_id}/substitute",
            payload,
            headers,
        )

    def create_safekeeping_receipt(self, collateral_asset_id, payload, headers):
        return self._request(
            "POST",
            f"/fhlb/collateral-assets/{collateral_asset_id}/safekeeping-receipts",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Safekeeping receipts
    # ------------------------------------------------------------------
    def list_safekeeping_receipts(self, headers, params=None):
        return self._request(
            "GET", "/fhlb/safekeeping-receipts", headers=headers, params=params
        )

    def get_safekeeping_receipt(self, safekeeping_receipt_id, headers):
        return self._request(
            "GET",
            f"/fhlb/safekeeping-receipts/{safekeeping_receipt_id}",
            headers=headers,
        )

    def confirm_safekeeping_receipt(self, safekeeping_receipt_id, payload, headers):
        return self._request(
            "POST",
            f"/fhlb/safekeeping-receipts/{safekeeping_receipt_id}/confirm",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Collateral verification reviews
    # ------------------------------------------------------------------
    def create_verification_review(self, payload, headers):
        return self._request(
            "POST", "/fhlb/collateral-verification-reviews", payload, headers
        )

    def list_verification_reviews(self, headers, params=None):
        return self._request(
            "GET",
            "/fhlb/collateral-verification-reviews",
            headers=headers,
            params=params,
        )

    def get_verification_review(self, collateral_verification_review_id, headers):
        return self._request(
            "GET",
            f"/fhlb/collateral-verification-reviews/{collateral_verification_review_id}",
            headers=headers,
        )

    def begin_field_work(self, collateral_verification_review_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/begin-field-work",
            payload if payload is not None else {},
            headers,
        )

    def create_review_finding(
        self, collateral_verification_review_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/findings",
            payload,
            headers,
        )

    def issue_findings(self, collateral_verification_review_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/issue-findings",
            payload if payload is not None else {},
            headers,
        )

    def retest_review(self, collateral_verification_review_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/retest",
            payload if payload is not None else {},
            headers,
        )

    def close_review(self, collateral_verification_review_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Review findings
    # ------------------------------------------------------------------
    def list_review_findings(self, headers, params=None):
        return self._request(
            "GET", "/fhlb/review-findings", headers=headers, params=params
        )

    def get_review_finding(self, review_finding_id, headers):
        return self._request(
            "GET", f"/fhlb/review-findings/{review_finding_id}", headers=headers
        )

    def remediate_review_finding(self, review_finding_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/review-findings/{review_finding_id}/remediate",
            payload if payload is not None else {},
            headers,
        )

    def waive_review_finding(self, review_finding_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/review-findings/{review_finding_id}/waive",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Advance products
    # ------------------------------------------------------------------
    def create_advance_product(self, payload, headers):
        return self._request("POST", "/fhlb/advance-products", payload, headers)

    def get_advance_product(self, advance_product_id, headers):
        return self._request(
            "GET", f"/fhlb/advance-products/{advance_product_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Advances
    # ------------------------------------------------------------------
    def create_advance(self, payload, headers):
        return self._request("POST", "/fhlb/advances", payload, headers)

    def list_advances(self, headers, params=None):
        return self._request("GET", "/fhlb/advances", headers=headers, params=params)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/fhlb/advances/{advance_id}", headers=headers)

    def approve_advance(self, advance_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/advances/{advance_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def fund_advance(self, advance_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/advances/{advance_id}/fund",
            payload if payload is not None else {},
            headers,
        )

    def repay_advance(self, advance_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/advances/{advance_id}/repay",
            payload if payload is not None else {},
            headers,
        )

    def create_prepayment_quote(self, advance_id, payload, headers):
        return self._request(
            "POST", f"/fhlb/advances/{advance_id}/prepayment-quotes", payload, headers
        )

    # ------------------------------------------------------------------
    # Prepayment events
    # ------------------------------------------------------------------
    def list_prepayment_events(self, headers, params=None):
        return self._request(
            "GET", "/fhlb/prepayment-events", headers=headers, params=params
        )

    def get_prepayment_event(self, prepayment_event_id, headers):
        return self._request(
            "GET", f"/fhlb/prepayment-events/{prepayment_event_id}", headers=headers
        )

    def settle_prepayment_event(self, prepayment_event_id, headers, payload=None):
        return self._request(
            "POST",
            f"/fhlb/prepayment-events/{prepayment_event_id}/settle",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Community program allocations
    # ------------------------------------------------------------------
    def create_community_program_allocation(self, payload, headers):
        return self._request(
            "POST", "/fhlb/community-program-allocations", payload, headers
        )

    def get_community_program_allocation(
        self, community_program_allocation_id, headers
    ):
        return self._request(
            "GET",
            f"/fhlb/community-program-allocations/{community_program_allocation_id}",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Administrative test-driving capabilities
    # ------------------------------------------------------------------
    def set_logical_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_market_rate(self, payload, headers):
        return self._request("POST", "/_ops/set-market-rate", payload, headers)


api_client = ApiClient()
