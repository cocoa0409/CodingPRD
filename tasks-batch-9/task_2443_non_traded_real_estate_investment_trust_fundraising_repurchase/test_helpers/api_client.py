"""HTTP client with one method per endpoint of PRD §4."""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """One method per row of the PRD §4 endpoint table."""

    # ─── Offerings ────────────────────────────────────────────────────

    def create_offering(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/offerings", payload, headers)

    def list_offerings(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/offerings", params, headers)

    def get_offering(self, offering_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/offerings/{offering_id}", None, headers)

    def drive_registration(
        self, offering_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/offerings/{offering_id}/registration", payload, headers
        )

    def drive_escrow(
        self, offering_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/offerings/{offering_id}/escrow", payload, headers)

    def drive_repurchase_plan(
        self, offering_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/offerings/{offering_id}/repurchase-plan", payload, headers
        )

    # ─── Share classes ────────────────────────────────────────────────

    def create_share_class(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/share-classes", payload, headers)

    def list_share_classes(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/share-classes", params, headers)

    def get_share_class(
        self, share_class_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/share-classes/{share_class_id}", None, headers)

    def set_share_class_status(
        self, share_class_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/share-classes/{share_class_id}/status", payload, headers
        )

    # ─── Investors ────────────────────────────────────────────────────

    def create_investor(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/investors", payload, headers)

    def list_investors(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/investors", params, headers)

    def get_investor(self, investor_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/investors/{investor_id}", None, headers)

    def record_suitability_documentation(
        self, investor_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/investors/{investor_id}/suitability-documentation", payload, headers
        )

    def get_investor_statement(
        self, investor_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/investors/{investor_id}/statement", None, headers)

    # ─── Broker-dealers ───────────────────────────────────────────────

    def create_broker_dealer(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/broker-dealers", payload, headers)

    def list_broker_dealers(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/broker-dealers", params, headers)

    def get_broker_dealer(
        self, broker_dealer_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/broker-dealers/{broker_dealer_id}", None, headers)

    def set_supervision_status(
        self, broker_dealer_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/broker-dealers/{broker_dealer_id}/supervision-status",
            payload,
            headers,
        )

    # ─── Selling agreements ───────────────────────────────────────────

    def create_selling_agreement(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/selling-agreements", payload, headers)

    def list_selling_agreements(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/selling-agreements", params, headers)

    def get_selling_agreement(
        self, selling_agreement_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/selling-agreements/{selling_agreement_id}", None, headers
        )

    def set_selling_agreement_status(
        self, selling_agreement_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/selling-agreements/{selling_agreement_id}/status", payload, headers
        )

    def record_supervision_finding(
        self, selling_agreement_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/selling-agreements/{selling_agreement_id}/supervision-findings",
            payload,
            headers,
        )

    # ─── Subscriptions ────────────────────────────────────────────────

    def create_subscription(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/subscriptions", params, headers)

    def get_subscription(
        self, subscription_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/subscriptions/{subscription_id}", None, headers)

    def set_subscription_status(
        self, subscription_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/status", payload, headers
        )

    # ─── Share lots ───────────────────────────────────────────────────

    def list_share_lots(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/share-lots", params, headers)

    def get_share_lot(self, share_lot_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/share-lots/{share_lot_id}", None, headers)

    # ─── Valuation records ────────────────────────────────────────────

    def create_nav_record(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/nav-records", payload, headers)

    def list_nav_records(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/nav-records", params, headers)

    def get_nav_record(self, nav_record_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/nav-records/{nav_record_id}", None, headers)

    def set_nav_record_status(
        self, nav_record_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/nav-records/{nav_record_id}/status", payload, headers
        )

    # ─── Distribution declarations ────────────────────────────────────

    def create_distribution_declaration(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/distribution-declarations", payload, headers)

    def list_distribution_declarations(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/distribution-declarations", params, headers)

    def get_distribution_declaration(
        self, distribution_declaration_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/distribution-declarations/{distribution_declaration_id}", None, headers
        )

    def drive_declaration_payment(
        self,
        distribution_declaration_id: str,
        payload: Payload = None,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution-declarations/{distribution_declaration_id}/payment",
            payload,
            headers,
        )

    # ─── Repurchase periods ───────────────────────────────────────────

    def create_repurchase_period(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/repurchase-periods", payload, headers)

    def list_repurchase_periods(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/repurchase-periods", params, headers)

    def get_repurchase_period(
        self, repurchase_period_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/repurchase-periods/{repurchase_period_id}", None, headers
        )

    def process_repurchase_period(
        self, repurchase_period_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/repurchase-periods/{repurchase_period_id}/processing", payload, headers
        )

    # ─── Repurchase requests ──────────────────────────────────────────

    def create_repurchase_request(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/repurchase-requests", payload, headers)

    def list_repurchase_requests(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/repurchase-requests", params, headers)

    def get_repurchase_request(
        self, repurchase_request_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/repurchase-requests/{repurchase_request_id}", None, headers
        )

    def set_repurchase_request_status(
        self, repurchase_request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/repurchase-requests/{repurchase_request_id}/status", payload, headers
        )

    # ─── Liquidity events ─────────────────────────────────────────────

    def create_liquidity_event(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/liquidity-events", payload, headers)

    def list_liquidity_events(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/liquidity-events", params, headers)

    def get_liquidity_event(
        self, liquidity_event_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/liquidity-events/{liquidity_event_id}", None, headers)

    def drive_liquidity_event(
        self, liquidity_event_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/liquidity-events/{liquidity_event_id}/status", payload, headers
        )

    # ─── Ballots ──────────────────────────────────────────────────────

    def cast_stockholder_vote(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/stockholder-votes", payload, headers)

    def list_stockholder_votes(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/stockholder-votes", params, headers)

    def get_stockholder_vote(
        self, stockholder_vote_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/stockholder-votes/{stockholder_vote_id}", None, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )
