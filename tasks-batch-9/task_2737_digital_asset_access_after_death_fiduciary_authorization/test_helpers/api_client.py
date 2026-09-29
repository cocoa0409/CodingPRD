"""
One method per endpoint of the Digital Estate Fiduciary Access API.

Every method returns the raw ``requests.Response`` so that a test can assert on
the HTTP status as well as on the body. Query filters and pagination arguments
are passed through as a dict so that a test can send a deliberately invalid
value (for example ``limit=0``) without the client silently correcting it.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is None so an omitted filter is really omitted."""
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None}


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the service under test."""

    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Platform ────────────────────────────────────────────────────────────
    def create_platform(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/platforms", payload, headers)

    def get_platform(self, platform_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/platforms/{platform_id}", None, headers)

    def list_platforms(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/platforms", _clean(filters), headers)

    def update_platform(
        self, platform_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/platforms/{platform_id}", payload, headers)

    # ─── Estate ──────────────────────────────────────────────────────────────
    def create_estate(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/estates", payload, headers)

    def get_estate(self, estate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/estates/{estate_id}", None, headers)

    def list_estates(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/estates", _clean(filters), headers)

    def close_estate(
        self, estate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/estates/{estate_id}/close", payload, headers)

    def get_authority_resolution(
        self,
        estate_id: str,
        headers: Dict[str, str],
        platform_id: Optional[str] = None,
        asset_category: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/estates/{estate_id}/authority-resolution",
            _clean({"platform_id": platform_id, "asset_category": asset_category}),
            headers,
        )

    def run_grant_expiry_sweep(self, estate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/estates/{estate_id}/grant-expiry-sweeps", {}, headers)

    # ─── Fiduciary ───────────────────────────────────────────────────────────
    def create_fiduciary(
        self, estate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/estates/{estate_id}/fiduciaries", payload, headers)

    def get_fiduciary(self, fiduciary_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/fiduciaries/{fiduciary_id}", None, headers)

    def list_fiduciaries(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/fiduciaries", _clean(filters), headers)

    # ─── Document ────────────────────────────────────────────────────────────
    def create_document(
        self, estate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/estates/{estate_id}/documents", payload, headers)

    def get_document(self, document_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/documents/{document_id}", None, headers)

    def list_documents(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/documents", _clean(filters), headers)

    def transition_document(
        self, document_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/documents/{document_id}/transitions", payload, headers)

    # ─── AuthorityDirective ──────────────────────────────────────────────────
    def create_authority_directive(
        self, estate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/estates/{estate_id}/authority-directives", payload, headers
        )

    def get_authority_directive(self, directive_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/authority-directives/{directive_id}", None, headers)

    def list_authority_directives(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/authority-directives", _clean(filters), headers)

    # ─── DigitalAsset ────────────────────────────────────────────────────────
    def create_digital_asset(
        self, estate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/estates/{estate_id}/digital-assets", payload, headers)

    def get_digital_asset(self, asset_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/digital-assets/{asset_id}", None, headers)

    def list_digital_assets(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/digital-assets", _clean(filters), headers)

    def create_transferability_review(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/digital-assets/{asset_id}/transferability-reviews", payload, headers
        )

    # ─── SubscriptionTerm ────────────────────────────────────────────────────
    def create_subscription_term(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/digital-assets/{asset_id}/subscription-terms", payload, headers
        )

    def get_subscription_term(self, term_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/subscription-terms/{term_id}", None, headers)

    def list_subscription_terms(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/subscription-terms", _clean(filters), headers)

    # ─── PlatformRequest ─────────────────────────────────────────────────────
    def create_platform_request(
        self, estate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/estates/{estate_id}/platform-requests", payload, headers)

    def get_platform_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/platform-requests/{request_id}", None, headers)

    def list_platform_requests(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/platform-requests", _clean(filters), headers)

    def transition_platform_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/platform-requests/{request_id}/transitions", payload, headers
        )

    # ─── AuthorityGrant ──────────────────────────────────────────────────────
    def get_authority_grant(self, grant_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/authority-grants/{grant_id}", None, headers)

    def list_authority_grants(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/authority-grants", _clean(filters), headers)

    def transition_authority_grant(
        self, grant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/authority-grants/{grant_id}/transitions", payload, headers
        )

    # ─── BeneficiaryDesignation ──────────────────────────────────────────────
    def create_beneficiary_designation(
        self, estate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/estates/{estate_id}/beneficiary-designations", payload, headers
        )

    def get_beneficiary_designation(
        self, designation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/beneficiary-designations/{designation_id}", None, headers
        )

    def list_beneficiary_designations(
        self, headers: Dict[str, str], **filters: Any
    ) -> requests.Response:
        return self._request("GET", "/beneficiary-designations", _clean(filters), headers)

    # ─── DispositionElection ─────────────────────────────────────────────────
    def create_disposition_election(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/digital-assets/{asset_id}/disposition-elections", payload, headers
        )

    def get_disposition_election(self, election_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/disposition-elections/{election_id}", None, headers)

    def list_disposition_elections(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/disposition-elections", _clean(filters), headers)

    def transition_disposition_election(
        self, election_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/disposition-elections/{election_id}/transitions", payload, headers
        )

    # ─── CancellationOrder ───────────────────────────────────────────────────
    def get_cancellation_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/cancellation-orders/{order_id}", None, headers)

    def list_cancellation_orders(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/cancellation-orders", _clean(filters), headers)

    def transition_cancellation_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/cancellation-orders/{order_id}/transitions", payload, headers
        )

    # ─── RefundClaim ─────────────────────────────────────────────────────────
    def create_refund_claim(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/cancellation-orders/{order_id}/refund-claims", payload, headers
        )

    def get_refund_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/refund-claims/{claim_id}", None, headers)

    def list_refund_claims(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/refund-claims", _clean(filters), headers)

    def transition_refund_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/refund-claims/{claim_id}/transitions", payload, headers)

    # ─── ValuationRun ────────────────────────────────────────────────────────
    def create_valuation_run(
        self, estate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/estates/{estate_id}/valuation-runs", payload, headers)

    def get_valuation_run(self, run_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/valuation-runs/{run_id}", None, headers)

    def list_valuation_runs(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", "/valuation-runs", _clean(filters), headers)

    def transition_valuation_run(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/valuation-runs/{run_id}/transitions", payload, headers)

    # ─── Raw escape hatch ────────────────────────────────────────────────────
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send an arbitrary request — for path-parameter and shape probes."""
        return self._request(method, path, payload, headers)


# ─── Module-level singleton ──────────────────────────────────────────────────
# The server lifecycle is owned by the harness; this client just points at it.
api_client = ApiClient()
