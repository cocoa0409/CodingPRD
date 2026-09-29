"""One method per declared endpoint (PRD section 4).

All resource paths are mounted at the server root, with no version or
service prefix.  Write methods take an explicit payload dict and an explicit
headers dict; list methods take headers plus keyword filters, which the
server combines conjunctively.  Every method returns the raw
`requests.Response` so a test can assert on status as well as body.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed surface over the Move Concierge API."""

    # -- the logical clock (PRD 2.4) ------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc — move the logical clock to `to_iso8601`."""
        return self._request("POST", "/_clock/set_current_utc", payload=payload, headers=headers)

    # -- feed sources ---------------------------------------------------
    def create_feed_source(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /feed-sources — register a property-manager or mover feed."""
        return self._request("POST", "/feed-sources", payload=payload, headers=headers)

    def get_feed_source(self, feed_source_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /feed-sources/{id} — read one feed source and its accrued balance."""
        return self.get(f"/feed-sources/{feed_source_id}", headers=headers)

    def patch_feed_source_status(
        self, feed_source_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /feed-sources/{id}/status — suspend or reactivate a feed."""
        return self._request(
            "PATCH", f"/feed-sources/{feed_source_id}/status", payload=payload, headers=headers
        )

    # -- residents ------------------------------------------------------
    def create_resident(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /residents — create the resident who is moving."""
        return self._request("POST", "/residents", payload=payload, headers=headers)

    def get_resident(self, resident_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /residents/{id} — read one resident, including its current version."""
        return self.get(f"/residents/{resident_id}", headers=headers)

    def patch_marketing_preferences(
        self, resident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /residents/{id}/marketing-preferences — record an opt-out or opt-in."""
        return self._request(
            "PATCH", f"/residents/{resident_id}/marketing-preferences", payload=payload, headers=headers
        )

    # -- service addresses ----------------------------------------------
    def create_service_address(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /service-addresses — create an origin or destination address."""
        return self._request("POST", "/service-addresses", payload=payload, headers=headers)

    def get_service_address(self, address_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /service-addresses/{id} — read one address with its derived fields."""
        return self.get(f"/service-addresses/{address_id}", headers=headers)

    # -- utility providers ----------------------------------------------
    def create_utility_provider(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /utility-providers — register a provider with its operational terms."""
        return self._request("POST", "/utility-providers", payload=payload, headers=headers)

    def get_utility_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /utility-providers/{id} — read one utility provider."""
        return self.get(f"/utility-providers/{provider_id}", headers=headers)

    def patch_provider_status(
        self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /utility-providers/{id}/status — deactivate or reactivate a provider."""
        return self._request(
            "PATCH", f"/utility-providers/{provider_id}/status", payload=payload, headers=headers
        )

    # -- provider service territories -----------------------------------
    def create_territory(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /provider-service-territories — declare coverage over a date interval."""
        return self._request("POST", "/provider-service-territories", payload=payload, headers=headers)

    def get_territory(self, territory_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /provider-service-territories/{id} — read one territory row."""
        return self.get(f"/provider-service-territories/{territory_id}", headers=headers)

    def list_territories(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /provider-service-territories — list territory rows with filters."""
        return self.get("/provider-service-territories", headers=headers, params=params or None)

    # -- referral partners ----------------------------------------------
    def create_referral_partner(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /referral-partners — register a partner with payout and attribution terms."""
        return self._request("POST", "/referral-partners", payload=payload, headers=headers)

    def get_referral_partner(self, partner_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /referral-partners/{id} — read one referral partner."""
        return self.get(f"/referral-partners/{partner_id}", headers=headers)

    def patch_partner_status(
        self, partner_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /referral-partners/{id}/status — pause or resume a partner."""
        return self._request(
            "PATCH", f"/referral-partners/{partner_id}/status", payload=payload, headers=headers
        )

    # -- move records ---------------------------------------------------
    def create_move(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /moves — ingest a move record and run both duplicate passes."""
        return self._request("POST", "/moves", payload=payload, headers=headers)

    def get_move(self, move_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /moves/{id} — read one move with its derived fields."""
        return self.get(f"/moves/{move_id}", headers=headers)

    def list_moves(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /moves — list move records with conjunctive filters and pagination."""
        return self.get("/moves", headers=headers, params=params or None)

    def get_move_readiness(self, move_id: str, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /moves/{id}/readiness — computed read of the score and its four components."""
        return self.get(f"/moves/{move_id}/readiness", headers=headers, params=params or None)

    def create_identity_verification(
        self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /moves/{id}/identity-verifications — open a KBA attempt or record an override."""
        return self._request(
            "POST", f"/moves/{move_id}/identity-verifications", payload=payload, headers=headers
        )

    def run_provider_mapping(
        self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /moves/{id}/provider-mapping — resolve providers and create service orders."""
        return self._request("POST", f"/moves/{move_id}/provider-mapping", payload=payload, headers=headers)

    def resolve_duplicate(
        self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /moves/{id}/duplicate-resolution — dismiss, rescore or merge into a survivor."""
        return self._request(
            "POST", f"/moves/{move_id}/duplicate-resolution", payload=payload, headers=headers
        )

    def cancel_move(self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /moves/{id}/cancellation — cancel a move and unwind everything it opened."""
        return self._request("POST", f"/moves/{move_id}/cancellation", payload=payload, headers=headers)

    def clear_attention(
        self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /moves/{id}/attention-clearances — return a parked move to SCHEDULING."""
        return self._request(
            "POST", f"/moves/{move_id}/attention-clearances", payload=payload, headers=headers
        )

    def complete_move(
        self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /moves/{id}/completion — close out a settled move."""
        return self._request("POST", f"/moves/{move_id}/completion", payload=payload, headers=headers)

    def evaluate_consents(
        self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /moves/{id}/consent-evaluations — expire lapsed consents and verifications."""
        return self._request(
            "POST", f"/moves/{move_id}/consent-evaluations", payload=payload, headers=headers
        )

    # -- identity verifications -----------------------------------------
    def get_identity_verification(self, verification_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /identity-verifications/{id} — read one verification attempt."""
        return self.get(f"/identity-verifications/{verification_id}", headers=headers)

    def list_identity_verifications(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /identity-verifications — list attempts with filters."""
        return self.get("/identity-verifications", headers=headers, params=params or None)

    def post_kba_result(
        self, verification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /identity-verifications/{id}/kba-result — vendor posts outcome and score."""
        return self._request(
            "POST", f"/identity-verifications/{verification_id}/kba-result", payload=payload, headers=headers
        )

    # -- utility orders -------------------------------------------------
    def get_utility_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /utility-orders/{id} — read one order with both state dimensions."""
        return self.get(f"/utility-orders/{order_id}", headers=headers)

    def list_utility_orders(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /utility-orders — list service orders with filters and pagination."""
        return self.get("/utility-orders", headers=headers, params=params or None)

    def schedule_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /utility-orders/{id}/schedule — commit the service window and account data."""
        return self._request("POST", f"/utility-orders/{order_id}/schedule", payload=payload, headers=headers)

    def create_credit_check(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /utility-orders/{id}/credit-checks — dispatch a handoff and freeze the snapshot."""
        return self._request(
            "POST", f"/utility-orders/{order_id}/credit-checks", payload=payload, headers=headers
        )

    def pay_deposit(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /utility-orders/{id}/deposit-payments — record an exact-match deposit payment."""
        return self._request(
            "POST", f"/utility-orders/{order_id}/deposit-payments", payload=payload, headers=headers
        )

    def activate_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /utility-orders/{id}/activation — provider confirms the service is live."""
        return self._request(
            "POST", f"/utility-orders/{order_id}/activation", payload=payload, headers=headers
        )

    def report_provision_failure(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /utility-orders/{id}/provision-failure — provider reports it cannot provision."""
        return self._request(
            "POST", f"/utility-orders/{order_id}/provision-failure", payload=payload, headers=headers
        )

    def close_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /utility-orders/{id}/closure — close a live service after the final read."""
        return self._request("POST", f"/utility-orders/{order_id}/closure", payload=payload, headers=headers)

    def waive_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /utility-orders/{id}/waiver — mark a DRAFT order not applicable."""
        return self._request("POST", f"/utility-orders/{order_id}/waiver", payload=payload, headers=headers)

    # -- credit-check handoffs ------------------------------------------
    def get_credit_check_handoff(self, handoff_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /credit-check-handoffs/{id} — read one handoff."""
        return self.get(f"/credit-check-handoffs/{handoff_id}", headers=headers)

    def list_credit_check_handoffs(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /credit-check-handoffs — list handoffs with filters."""
        return self.get("/credit-check-handoffs", headers=headers, params=params or None)

    def post_bureau_response(
        self, handoff_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /credit-check-handoffs/{id}/bureau-response — bureau returns a score."""
        return self._request(
            "POST", f"/credit-check-handoffs/{handoff_id}/bureau-response", payload=payload, headers=headers
        )

    # -- address-change filings -----------------------------------------
    def create_filing(
        self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /moves/{id}/address-change-filings — draft a USPS change-of-address filing."""
        return self._request(
            "POST", f"/moves/{move_id}/address-change-filings", payload=payload, headers=headers
        )

    def get_filing(self, filing_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /address-change-filings/{id} — read one filing."""
        return self.get(f"/address-change-filings/{filing_id}", headers=headers)

    def list_filings(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /address-change-filings — list filings with filters."""
        return self.get("/address-change-filings", headers=headers, params=params or None)

    def submit_filing(
        self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /address-change-filings/{id}/submission — submit or resubmit to USPS."""
        return self._request(
            "POST", f"/address-change-filings/{filing_id}/submission", payload=payload, headers=headers
        )

    def post_usps_response(
        self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /address-change-filings/{id}/usps-response — USPS confirms or rejects."""
        return self._request(
            "POST", f"/address-change-filings/{filing_id}/usps-response", payload=payload, headers=headers
        )

    def cancel_filing(
        self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /address-change-filings/{id}/cancellation — withdraw a filing."""
        return self._request(
            "POST", f"/address-change-filings/{filing_id}/cancellation", payload=payload, headers=headers
        )

    # -- consent records ------------------------------------------------
    def create_consent_record(
        self, resident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /residents/{id}/consent-records — record a data-sharing consent under OCC."""
        return self._request(
            "POST", f"/residents/{resident_id}/consent-records", payload=payload, headers=headers
        )

    def get_consent_record(self, consent_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /consent-records/{id} — read one consent record."""
        return self.get(f"/consent-records/{consent_id}", headers=headers)

    def list_consent_records(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /consent-records — list consent records with filters."""
        return self.get("/consent-records", headers=headers, params=params or None)

    def revoke_consent(
        self, consent_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /consent-records/{id}/revocation — revoke a granted consent."""
        return self._request(
            "POST", f"/consent-records/{consent_id}/revocation", payload=payload, headers=headers
        )

    # -- referral placements --------------------------------------------
    def create_placement(
        self, move_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /moves/{id}/referral-placements — place a partner referral under OCC."""
        return self._request(
            "POST", f"/moves/{move_id}/referral-placements", payload=payload, headers=headers
        )

    def get_placement(self, placement_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /referral-placements/{id} — read one placement with its share figures."""
        return self.get(f"/referral-placements/{placement_id}", headers=headers)

    def list_placements(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /referral-placements — list placements with filters."""
        return self.get("/referral-placements", headers=headers, params=params or None)

    def accept_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /referral-placements/{id}/acceptance — partner accepts the referral."""
        return self._request(
            "POST", f"/referral-placements/{placement_id}/acceptance", payload=payload, headers=headers
        )

    def decline_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /referral-placements/{id}/decline — partner declines; posts no ledger entry."""
        return self._request(
            "POST", f"/referral-placements/{placement_id}/decline", payload=payload, headers=headers
        )

    def convert_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /referral-placements/{id}/conversions — report gross revenue in the window."""
        return self._request(
            "POST", f"/referral-placements/{placement_id}/conversions", payload=payload, headers=headers
        )

    def settle_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /referral-placements/{id}/settlement — settle on the final gross, posting deltas."""
        return self._request(
            "POST", f"/referral-placements/{placement_id}/settlement", payload=payload, headers=headers
        )

    def reverse_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /referral-placements/{id}/reversal — chargeback; returns ledger net to zero."""
        return self._request(
            "POST", f"/referral-placements/{placement_id}/reversal", payload=payload, headers=headers
        )

    # -- revenue-share ledger -------------------------------------------
    def get_ledger_entry(self, entry_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /revenue-share-ledger-entries/{id} — read one immutable ledger entry."""
        return self.get(f"/revenue-share-ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        """GET /revenue-share-ledger-entries — list entries in created_at ascending order."""
        return self.get("/revenue-share-ledger-entries", headers=headers, params=params or None)

    # -- raw escape hatch -----------------------------------------------
    def raw_request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Send an arbitrary request, including one with no headers at all."""
        return self._request(method, path, payload=payload, headers=headers, params=params)


api_client = ApiClient()
