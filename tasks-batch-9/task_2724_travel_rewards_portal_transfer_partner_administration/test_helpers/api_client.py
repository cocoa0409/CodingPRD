"""
One method per declared endpoint of §4, plus ISO-8601 canonicalisation.

Every method returns the raw `requests.Response` so a test can assert on the
status code as well as the envelope. Listing methods take an explicit `params`
dict so the pagination and filter contract of §2.3 can be exercised.

§2.4 fixes the wire format of every timestamp at "ISO 8601 UTC with three
fractional digits". Rather than have individual tests assert on raw string
width, this client canonicalises every timestamp-shaped string in a decoded
response body to exactly three fractional digits and a trailing `Z`, so that a
test may compare `scheduled_post_at` against the literal instant the PRD's
arithmetic produces without caring whether the server emitted `...T00:00:00Z`,
`...T00:00:00.0Z` or `...T00:00:00.000000Z`. Expected literals written in a test
are put through the same `canonical_timestamp` helper.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

#: A timestamp-shaped string: a date, a time, optional fractional seconds, and a
#: UTC designator of either `Z` or a numeric zero offset.
_TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})$"
)


def canonical_timestamp(value: Any) -> Any:
    """
    Normalise one timestamp-shaped string to three fractional digits and `Z`.

    Values that are not timestamp-shaped are returned untouched, so this is safe
    to apply to every string in a response body.
    """
    if not isinstance(value, str):
        return value
    match = _TIMESTAMP_RE.match(value)
    if not match:
        return value
    seconds, fraction, offset = match.groups()
    if offset not in ("Z", "+00:00", "+0000", "-00:00", "-0000"):
        # A non-zero offset is not a UTC instant; leave it visible to the test.
        return value
    milliseconds = (fraction or "")[:3].ljust(3, "0")
    return f"{seconds}.{milliseconds}Z"


def canonicalise(payload: Any) -> Any:
    """Recursively canonicalise every timestamp-shaped string in a structure."""
    if isinstance(payload, dict):
        return {key: canonicalise(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [canonicalise(item) for item in payload]
    return canonical_timestamp(payload)


class RewardsApiClient(GenericApiClient):
    """HTTP surface of the Travel Rewards Portal API, mounted under `/rewards`."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        response = super()._request(method, path, payload, headers, params)
        _install_canonical_json(response)
        return response

    # ─── The logical clock (§2.4) ──────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        """POST /rewards/_clock/set_current_utc — `ProgramAdmin` only."""
        return self._request(
            "POST", "/rewards/_clock/set_current_utc", payload, headers
        )

    def get_clock(self, headers: Optional[Dict] = None):
        """GET /rewards/_clock — open to all five roles."""
        return self._request("GET", "/rewards/_clock", None, headers)

    # ─── The deterministic sweep (§2.10) ───────────────────────────────

    def run_ops(self, headers: Optional[Dict] = None, payload: Optional[Dict] = None):
        """POST /rewards/ops-runs — `ProgramAdmin` only."""
        return self._request("POST", "/rewards/ops-runs", payload or {}, headers)

    # ─── Accounts (§3.1) ───────────────────────────────────────────────

    def create_account(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/rewards/accounts/{account_id}", None, headers)

    def list_accounts(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/rewards/accounts", params, headers)

    def close_account(
        self,
        account_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/rewards/accounts/{account_id}/close", payload or {}, headers
        )

    # ─── Merchant categories (§3.2) ────────────────────────────────────

    def create_merchant_category(
        self, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", "/rewards/merchant-categories", payload, headers)

    def get_merchant_category(self, category_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/merchant-categories/{category_id}", None, headers
        )

    def list_merchant_categories(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/merchant-categories", params, headers)

    # ─── Bonus category rotations (§3.2) ───────────────────────────────

    def create_rotation(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/rotations", payload, headers)

    def get_rotation(self, rotation_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/rewards/rotations/{rotation_id}", None, headers)

    def list_rotations(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/rotations", params, headers)

    def publish_rotation(
        self,
        rotation_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/rewards/rotations/{rotation_id}/publish", payload or {}, headers
        )

    # ─── Purchases (§3.3, §3.4) ────────────────────────────────────────

    def create_transaction(
        self, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", "/rewards/transactions", payload, headers)

    def get_transaction(self, transaction_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/transactions/{transaction_id}", None, headers
        )

    def list_transactions(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/transactions", params, headers)

    def reverse_transaction(
        self,
        transaction_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/rewards/transactions/{transaction_id}/reverse", payload, headers
        )

    # ─── The points ledger (§2.7) ──────────────────────────────────────

    def get_ledger_entry(self, entry_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/points-ledger-entries/{entry_id}", None, headers
        )

    def list_ledger_entries(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/points-ledger-entries", params, headers)

    # ─── Travel agency partners (§3.5) ─────────────────────────────────

    def create_agency_partner(
        self, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", "/rewards/agency-partners", payload, headers)

    def get_agency_partner(self, agency_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/agency-partners/{agency_id}", None, headers
        )

    def list_agency_partners(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/agency-partners", params, headers)

    def suspend_agency_partner(
        self, agency_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/agency-partners/{agency_id}/suspend", payload, headers
        )

    # ─── Portal inventory offers (§3.5) ────────────────────────────────

    def create_offer(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/inventory-offers", payload, headers)

    def get_offer(self, offer_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/inventory-offers/{offer_id}", None, headers
        )

    def list_offers(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/rewards/inventory-offers", params, headers)

    def resync_offer(
        self, offer_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/inventory-offers/{offer_id}/resync", payload, headers
        )

    def suspend_offer(
        self, offer_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/inventory-offers/{offer_id}/suspend", payload, headers
        )

    def reinstate_offer(
        self,
        offer_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/inventory-offers/{offer_id}/reinstate",
            payload or {},
            headers,
        )

    def withdraw_offer(
        self,
        offer_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/inventory-offers/{offer_id}/withdraw",
            payload or {},
            headers,
        )

    def book_offer(
        self, offer_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        """POST /rewards/inventory-offers/{id}/book — the only PORTAL_BOOKING route."""
        return self._request(
            "POST", f"/rewards/inventory-offers/{offer_id}/book", payload, headers
        )

    # ─── Redemption orders (§3.6) ──────────────────────────────────────

    def create_order(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        """POST /rewards/redemption-orders — the flat STATEMENT_CREDIT route."""
        return self._request("POST", "/rewards/redemption-orders", payload, headers)

    def get_order(self, order_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/redemption-orders/{order_id}", None, headers
        )

    def list_orders(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/rewards/redemption-orders", params, headers)

    def confirm_order(
        self,
        order_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/redemption-orders/{order_id}/confirm",
            payload or {},
            headers,
        )

    def cancel_order(
        self, order_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/redemption-orders/{order_id}/cancel", payload, headers
        )

    def ticket_order(
        self, order_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/redemption-orders/{order_id}/ticket", payload, headers
        )

    def refund_order(
        self, order_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/redemption-orders/{order_id}/refund", payload, headers
        )

    def settle_order(
        self, order_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/redemption-orders/{order_id}/settle", payload, headers
        )

    # ─── Transfer partner agreements (§3.7) ────────────────────────────

    def create_agreement(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/partner-agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/partner-agreements/{agreement_id}", None, headers
        )

    def list_agreements(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/partner-agreements", params, headers)

    def submit_agreement(
        self,
        agreement_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/partner-agreements/{agreement_id}/submit",
            payload or {},
            headers,
        )

    def revise_agreement(
        self,
        agreement_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/partner-agreements/{agreement_id}/revise",
            payload or {},
            headers,
        )

    def approve_agreement(
        self,
        agreement_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/partner-agreements/{agreement_id}/approve",
            payload or {},
            headers,
        )

    def suspend_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/rewards/partner-agreements/{agreement_id}/suspend",
            payload,
            headers,
        )

    def reinstate_agreement(
        self,
        agreement_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/partner-agreements/{agreement_id}/reinstate",
            payload or {},
            headers,
        )

    def terminate_agreement(
        self,
        agreement_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/partner-agreements/{agreement_id}/terminate",
            payload or {},
            headers,
        )

    # ─── Promotional bonus events (§3.7) ───────────────────────────────

    def create_bonus_event(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/bonus-events", payload, headers)

    def get_bonus_event(self, event_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/rewards/bonus-events/{event_id}", None, headers)

    def list_bonus_events(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/bonus-events", params, headers)

    def cancel_bonus_event(
        self, event_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/bonus-events/{event_id}/cancel", payload, headers
        )

    # ─── Transfer requests (§3.8) ──────────────────────────────────────

    def create_transfer(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/transfer-requests", payload, headers)

    def get_transfer(self, transfer_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/transfer-requests/{transfer_id}", None, headers
        )

    def list_transfers(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/transfer-requests", params, headers)

    def hold_transfer(
        self, transfer_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/transfer-requests/{transfer_id}/hold", payload, headers
        )

    def release_transfer(
        self,
        transfer_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/transfer-requests/{transfer_id}/release",
            payload or {},
            headers,
        )

    def clear_screening(
        self,
        transfer_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/transfer-requests/{transfer_id}/clear-screening",
            payload or {},
            headers,
        )

    def reject_transfer(
        self, transfer_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/transfer-requests/{transfer_id}/reject", payload, headers
        )

    def reverse_transfer(
        self, transfer_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/transfer-requests/{transfer_id}/reverse", payload, headers
        )

    # ─── Fraud cases (§3.9) ────────────────────────────────────────────

    def create_fraud_case(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/fraud-cases", payload, headers)

    def get_fraud_case(self, case_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/rewards/fraud-cases/{case_id}", None, headers)

    def list_fraud_cases(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/fraud-cases", params, headers)

    def review_fraud_case(
        self,
        case_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/rewards/fraud-cases/{case_id}/review", payload or {}, headers
        )

    def confirm_fraud_case(
        self, case_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/fraud-cases/{case_id}/confirm", payload, headers
        )

    def clear_fraud_case(
        self, case_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/fraud-cases/{case_id}/clear", payload, headers
        )

    # ─── Benefit entitlements (§3.9) ───────────────────────────────────

    def create_entitlement(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/benefit-entitlements", payload, headers)

    def get_entitlement(self, entitlement_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/benefit-entitlements/{entitlement_id}", None, headers
        )

    def list_entitlements(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/benefit-entitlements", params, headers)

    def consume_entitlement(
        self,
        entitlement_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/benefit-entitlements/{entitlement_id}/consume",
            payload or {},
            headers,
        )

    # ─── Programme change notices (§3.10) ──────────────────────────────

    def create_notice(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/change-notices", payload, headers)

    def get_notice(self, notice_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/rewards/change-notices/{notice_id}", None, headers)

    def list_notices(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/rewards/change-notices", params, headers)

    def submit_notice(
        self,
        notice_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/rewards/change-notices/{notice_id}/submit", payload or {}, headers
        )

    def revise_notice(
        self,
        notice_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/rewards/change-notices/{notice_id}/revise", payload or {}, headers
        )

    def announce_notice(
        self,
        notice_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/rewards/change-notices/{notice_id}/announce",
            payload or {},
            headers,
        )

    def withdraw_notice(
        self, notice_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/rewards/change-notices/{notice_id}/withdraw", payload, headers
        )

    # ─── Liability snapshots (§3.11) ───────────────────────────────────

    def create_snapshot(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/rewards/liability-snapshots", payload, headers)

    def get_snapshot(self, snapshot_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/rewards/liability-snapshots/{snapshot_id}", None, headers
        )

    def list_snapshots(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/rewards/liability-snapshots", params, headers)

    # ─── Generic escape hatches ────────────────────────────────────────

    def get_path(
        self, path: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        """Read an arbitrary path, for the identifier-resolution checks of §2.4."""
        return self._request("GET", path, params, headers)

    def post_path(
        self, path: str, payload: Optional[Dict] = None, headers: Optional[Dict] = None
    ):
        """Write to an arbitrary path, for the identifier-resolution checks of §2.4."""
        return self._request("POST", path, payload, headers)


def _install_canonical_json(response) -> None:
    """
    Replace `response.json` with a canonicalising, memoised equivalent.

    The raw text is left untouched, so a test that genuinely needs the wire bytes
    can still read `response.text`.
    """
    original = response.json
    cache = {}

    def canonical_json(**kwargs):
        if "value" not in cache:
            cache["value"] = canonicalise(original(**kwargs))
        return cache["value"]

    response.json = canonical_json
