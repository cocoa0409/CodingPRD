"""HTTP client with one method per endpoint declared by the PRD.

"Every path is absolute at the root" — no prefix is added anywhere.  Every
method returns the raw ``requests.Response`` so tests can assert status codes
themselves.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class GiftCardApiClient(GenericApiClient):
    """One method per row of the PRD endpoint table."""

    # ------------------------------------------------------------------
    # Risk policy singleton and the deterministic clock
    # ------------------------------------------------------------------
    def get_risk_policy(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/risk-policy", headers=headers)

    def update_risk_policy(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("PUT", "/risk-policy", payload, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Retail stores
    # ------------------------------------------------------------------
    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/stores", params, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # ------------------------------------------------------------------
    # Card racks
    # ------------------------------------------------------------------
    def create_card_rack(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/card-racks", payload, headers)

    def list_card_racks(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/card-racks", params, headers)

    def get_card_rack(self, rack_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/card-racks/{rack_id}", headers=headers)

    def audit_card_rack(
        self, rack_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/card-racks/{rack_id}/audits", payload, headers)

    def clear_card_rack_tamper(
        self, rack_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/card-racks/{rack_id}/clear-tamper", payload, headers)

    # ------------------------------------------------------------------
    # Gift cards
    # ------------------------------------------------------------------
    def create_gift_card(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/gift-cards", payload, headers)

    def list_gift_cards(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/gift-cards", params, headers)

    def get_gift_card(self, card_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/gift-cards/{card_id}", headers=headers)

    def create_balance_inquiry(
        self, card_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/gift-cards/{card_id}/balance-inquiries", payload, headers)

    def list_balance_inquiries(
        self, card_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/gift-cards/{card_id}/balance-inquiries", params, headers)

    def create_redemption(
        self, card_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/gift-cards/{card_id}/redemptions", payload, headers)

    def create_redemption_hold(
        self, card_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/gift-cards/{card_id}/redemption-holds", payload, headers)

    def list_card_redemption_holds(
        self, card_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/gift-cards/{card_id}/redemption-holds", params, headers)

    def list_card_reseller_listings(
        self, card_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/gift-cards/{card_id}/reseller-listings", params, headers)

    def override_card_posture(
        self, card_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/gift-cards/{card_id}/posture", payload, headers)

    # ------------------------------------------------------------------
    # Redemption holds
    # ------------------------------------------------------------------
    def get_redemption_hold(self, hold_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/redemption-holds/{hold_id}", headers=headers)

    def settle_redemption_hold(
        self, hold_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/redemption-holds/{hold_id}/settle", payload, headers)

    # ------------------------------------------------------------------
    # Issuance requests
    # ------------------------------------------------------------------
    def create_issuance_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/issuance-requests", payload, headers)

    def list_issuance_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/issuance-requests", params, headers)

    def get_issuance_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/issuance-requests/{request_id}", headers=headers)

    def screen_issuance_request(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/issuance-requests/{request_id}/screen", payload if payload is not None else {}, headers
        )

    def decide_issuance_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/issuance-requests/{request_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Ledger events
    # ------------------------------------------------------------------
    def list_ledger_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ledger-events", params, headers)

    def get_ledger_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ledger-events/{event_id}", headers=headers)

    def reverse_ledger_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ledger-events/{event_id}/reverse", payload, headers)

    # ------------------------------------------------------------------
    # Bulk purchase orders
    # ------------------------------------------------------------------
    def create_bulk_purchase_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/bulk-purchase-orders", payload, headers)

    def list_bulk_purchase_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/bulk-purchase-orders", params, headers)

    def get_bulk_purchase_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/bulk-purchase-orders/{order_id}", headers=headers)

    def verify_bulk_order_identity(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/bulk-purchase-orders/{order_id}/identity-verification", payload, headers
        )

    def decide_bulk_purchase_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/bulk-purchase-orders/{order_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Draining alerts
    # ------------------------------------------------------------------
    def create_draining_alert(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/draining-alerts", payload, headers)

    def list_draining_alerts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/draining-alerts", params, headers)

    def get_draining_alert(self, alert_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/draining-alerts/{alert_id}", headers=headers)

    def triage_draining_alert(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/draining-alerts/{alert_id}/triage", payload, headers)

    def resolve_draining_alert(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/draining-alerts/{alert_id}/resolve", payload, headers)

    def reopen_draining_alert(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/draining-alerts/{alert_id}/reopen", payload, headers)

    def list_alert_referrals(
        self, alert_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/draining-alerts/{alert_id}/referrals", params, headers)

    # ------------------------------------------------------------------
    # Law-enforcement referrals
    # ------------------------------------------------------------------
    def create_law_enforcement_referral(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/law-enforcement-referrals", payload, headers)

    def get_law_enforcement_referral(self, referral_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/law-enforcement-referrals/{referral_id}", headers=headers)

    # ------------------------------------------------------------------
    # Victim claims
    # ------------------------------------------------------------------
    def create_victim_claim(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/victim-claims", payload, headers)

    def list_victim_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/victim-claims", params, headers)

    def get_victim_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/victim-claims/{claim_id}", headers=headers)

    def request_claim_evidence(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/victim-claims/{claim_id}/request-evidence", payload, headers)

    def resubmit_claim_evidence(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/victim-claims/{claim_id}/resubmit-evidence", payload, headers)

    def decide_victim_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/victim-claims/{claim_id}/decide", payload, headers)

    def rescind_victim_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/victim-claims/{claim_id}/rescind", payload, headers)

    # ------------------------------------------------------------------
    # Reseller listings
    # ------------------------------------------------------------------
    def create_reseller_listing(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reseller-listings", payload, headers)

    def list_reseller_listings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/reseller-listings", params, headers)

    def get_reseller_listing(self, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reseller-listings/{listing_id}", headers=headers)

    def validate_reseller_listing(
        self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/reseller-listings/{listing_id}/validate", payload, headers)

    # ------------------------------------------------------------------
    # Liability periods
    # ------------------------------------------------------------------
    def create_liability_period(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/liability-periods", payload, headers)

    def list_liability_periods(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/liability-periods", params, headers)

    def get_liability_period(self, period_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/liability-periods/{period_id}", headers=headers)

    def close_liability_period(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/liability-periods/{period_id}/close", payload, headers)

    def restate_liability_period(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/liability-periods/{period_id}/restate", payload, headers)

    def get_exposure_summary(self, period_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/liability-periods/{period_id}/exposure-summary", headers=headers
        )
