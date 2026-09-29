"""HTTP client exposing one method per declared endpoint.

Paths are used exactly as the endpoint table states them: there is no common
prefix. Every method takes an explicit ``headers`` mapping because both
``X-User-ID`` and ``X-User-Role`` are required on every endpoint, including
reads and the two test-driving endpoints.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing.client import GenericApiClient


def _params(**kwargs: Any) -> Dict[str, Any]:
    """Drop unsupplied query parameters so defaults can be exercised."""
    return {k: v for k, v in kwargs.items() if v is not None}


def _body(**kwargs: Any) -> Dict[str, Any]:
    """Drop unsupplied body fields so declared defaults can be exercised."""
    return {k: v for k, v in kwargs.items() if v is not None}


class ShowSettlementApiClient(GenericApiClient):
    """Typed surface over the show settlement and risk service."""

    # ------------------------------------------------------------------
    # Test-driving endpoints
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self.post(
            "/_clock/set_current_utc", {"current_utc": current_utc}, headers=headers
        )

    def run_housekeeping(self, headers: Dict[str, str]):
        return self.post("/_ops/run", {}, headers=headers)

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------

    def create_market(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/markets", payload, headers=headers)

    def get_market(self, market_id: str, headers: Dict[str, str]):
        return self.get(f"/markets/{market_id}", headers=headers)

    def list_markets(
        self,
        headers: Dict[str, str],
        risk_posture: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/markets",
            headers=headers,
            params=_params(risk_posture=risk_posture, limit=limit, offset=offset),
        )

    def get_portfolio_risk(
        self,
        market_id: str,
        headers: Dict[str, str],
        valuation: Optional[str] = None,
    ):
        return self.get(
            f"/markets/{market_id}/portfolio-risk",
            headers=headers,
            params=_params(valuation=valuation),
        )

    # ------------------------------------------------------------------
    # Artists
    # ------------------------------------------------------------------

    def create_artist(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/artists", payload, headers=headers)

    def get_artist(self, artist_id: str, headers: Dict[str, str]):
        return self.get(f"/artists/{artist_id}", headers=headers)

    def list_artists(
        self,
        headers: Dict[str, str],
        tier: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/artists",
            headers=headers,
            params=_params(tier=tier, limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Venues
    # ------------------------------------------------------------------

    def create_venue(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/venues", payload, headers=headers)

    def get_venue(self, venue_id: str, headers: Dict[str, str]):
        return self.get(f"/venues/{venue_id}", headers=headers)

    def list_venues(
        self,
        headers: Dict[str, str],
        market_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/venues",
            headers=headers,
            params=_params(market_id=market_id, limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Shows
    # ------------------------------------------------------------------

    def create_show(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/shows", payload, headers=headers)

    def get_show(self, show_id: str, headers: Dict[str, str]):
        return self.get(f"/shows/{show_id}", headers=headers)

    def list_shows(
        self,
        headers: Dict[str, str],
        market_id: Optional[str] = None,
        artist_id: Optional[str] = None,
        venue_id: Optional[str] = None,
        rescheduled_from_show_id: Optional[str] = None,
        show_status: Optional[str] = None,
        sales_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/shows",
            headers=headers,
            params=_params(
                market_id=market_id,
                artist_id=artist_id,
                venue_id=venue_id,
                rescheduled_from_show_id=rescheduled_from_show_id,
                show_status=show_status,
                sales_status=sales_status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_settlement_projection(self, show_id: str, headers: Dict[str, str]):
        return self.get(f"/shows/{show_id}/settlement-projection", headers=headers)

    def put_show_on_sale(self, show_id: str, headers: Dict[str, str]):
        return self.post(f"/shows/{show_id}/on-sale", {}, headers=headers)

    def pause_sales(self, show_id: str, reason: str, headers: Dict[str, str]):
        return self.post(
            f"/shows/{show_id}/pause-sales", {"reason": reason}, headers=headers
        )

    def resume_sales(self, show_id: str, headers: Dict[str, str]):
        return self.post(f"/shows/{show_id}/resume-sales", {}, headers=headers)

    def perform_show(self, show_id: str, headers: Dict[str, str]):
        return self.post(f"/shows/{show_id}/perform", {}, headers=headers)

    def grant_exposure_override(
        self,
        show_id: str,
        headers: Dict[str, str],
        exposure_override_limit_cents: Optional[int] = None,
        exposure_override_justification: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                exposure_override_limit_cents=exposure_override_limit_cents,
                exposure_override_justification=exposure_override_justification,
            )
        return self.post(
            f"/shows/{show_id}/exposure-override", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Offers
    # ------------------------------------------------------------------

    def create_offer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/offers", payload, headers=headers)

    def get_offer(self, offer_id: str, headers: Dict[str, str]):
        return self.get(f"/offers/{offer_id}", headers=headers)

    def list_offers(
        self,
        headers: Dict[str, str],
        show_id: Optional[str] = None,
        status: Optional[str] = None,
        deal_structure: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/offers",
            headers=headers,
            params=_params(
                show_id=show_id,
                status=status,
                deal_structure=deal_structure,
                limit=limit,
                offset=offset,
            ),
        )

    def submit_offer(
        self,
        offer_id: str,
        headers: Dict[str, str],
        guarantee_cents: Optional[int] = None,
        versus_pct: Optional[float] = None,
        backend_split_artist_pct: Optional[float] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                guarantee_cents=guarantee_cents,
                versus_pct=versus_pct,
                backend_split_artist_pct=backend_split_artist_pct,
            )
        return self.post(f"/offers/{offer_id}/submit", payload, headers=headers)

    def counter_offer(
        self,
        offer_id: str,
        headers: Dict[str, str],
        counter_guarantee_cents: Optional[int] = None,
        counter_note: Optional[str] = None,
        counter_versus_pct: Optional[float] = None,
        counter_backend_split_artist_pct: Optional[float] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                counter_guarantee_cents=counter_guarantee_cents,
                counter_versus_pct=counter_versus_pct,
                counter_backend_split_artist_pct=counter_backend_split_artist_pct,
                counter_note=counter_note,
            )
        return self.post(f"/offers/{offer_id}/counter", payload, headers=headers)

    def accept_offer(self, offer_id: str, headers: Dict[str, str]):
        return self.post(f"/offers/{offer_id}/accept", {}, headers=headers)

    def withdraw_offer(self, offer_id: str, reason: str, headers: Dict[str, str]):
        return self.post(
            f"/offers/{offer_id}/withdraw", {"reason": reason}, headers=headers
        )

    # ------------------------------------------------------------------
    # Budget lines
    # ------------------------------------------------------------------

    def create_budget_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/budget-lines", payload, headers=headers)

    def get_budget_line(self, budget_line_id: str, headers: Dict[str, str]):
        return self.get(f"/budget-lines/{budget_line_id}", headers=headers)

    def list_budget_lines(
        self,
        headers: Dict[str, str],
        show_id: Optional[str] = None,
        category: Optional[str] = None,
        variance_status: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/budget-lines",
            headers=headers,
            params=_params(
                show_id=show_id,
                category=category,
                variance_status=variance_status,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def decide_variance(
        self,
        budget_line_id: str,
        headers: Dict[str, str],
        decision: Optional[str] = None,
        variance_justification: Optional[str] = None,
        approved_cap_cents: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                decision=decision,
                approved_cap_cents=approved_cap_cents,
                variance_justification=variance_justification,
            )
        return self.post(
            f"/budget-lines/{budget_line_id}/variance-decision", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Vendor invoices
    # ------------------------------------------------------------------

    def create_vendor_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/vendor-invoices", payload, headers=headers)

    def get_vendor_invoice(self, vendor_invoice_id: str, headers: Dict[str, str]):
        return self.get(f"/vendor-invoices/{vendor_invoice_id}", headers=headers)

    def list_vendor_invoices(
        self,
        headers: Dict[str, str],
        show_id: Optional[str] = None,
        budget_line_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/vendor-invoices",
            headers=headers,
            params=_params(
                show_id=show_id,
                budget_line_id=budget_line_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def verify_vendor_invoice(self, vendor_invoice_id: str, headers: Dict[str, str]):
        return self.post(
            f"/vendor-invoices/{vendor_invoice_id}/verify", {}, headers=headers
        )

    def approve_vendor_invoice(self, vendor_invoice_id: str, headers: Dict[str, str]):
        return self.post(
            f"/vendor-invoices/{vendor_invoice_id}/approve", {}, headers=headers
        )

    def dispute_vendor_invoice(
        self,
        vendor_invoice_id: str,
        headers: Dict[str, str],
        dispute_reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(dispute_reason=dispute_reason)
        return self.post(
            f"/vendor-invoices/{vendor_invoice_id}/dispute", payload, headers=headers
        )

    def resolve_vendor_invoice_dispute(
        self,
        vendor_invoice_id: str,
        headers: Dict[str, str],
        outcome: Optional[str] = None,
        amount_cents: Optional[int] = None,
        documentation_ref: Optional[str] = None,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                outcome=outcome,
                amount_cents=amount_cents,
                documentation_ref=documentation_ref,
                reason=reason,
            )
        return self.post(
            f"/vendor-invoices/{vendor_invoice_id}/dispute-resolution",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Ticket tiers
    # ------------------------------------------------------------------

    def create_ticket_tier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/ticket-tiers", payload, headers=headers)

    def get_ticket_tier(self, ticket_tier_id: str, headers: Dict[str, str]):
        return self.get(f"/ticket-tiers/{ticket_tier_id}", headers=headers)

    def list_ticket_tiers(
        self,
        headers: Dict[str, str],
        show_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/ticket-tiers",
            headers=headers,
            params=_params(
                show_id=show_id, status=status, limit=limit, offset=offset
            ),
        )

    def adjust_tier_price(
        self,
        ticket_tier_id: str,
        headers: Dict[str, str],
        new_price_cents: Optional[int] = None,
        expected_show_version: Optional[int] = None,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                new_price_cents=new_price_cents,
                expected_show_version=expected_show_version,
                reason=reason,
            )
        return self.post(
            f"/ticket-tiers/{ticket_tier_id}/price-adjustments", payload, headers=headers
        )

    def record_sales(
        self,
        ticket_tier_id: str,
        headers: Dict[str, str],
        qty: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(qty=qty)
        return self.post(
            f"/ticket-tiers/{ticket_tier_id}/sales", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Ticket holds
    # ------------------------------------------------------------------

    def create_ticket_hold(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/ticket-holds", payload, headers=headers)

    def get_ticket_hold(self, ticket_hold_id: str, headers: Dict[str, str]):
        return self.get(f"/ticket-holds/{ticket_hold_id}", headers=headers)

    def list_ticket_holds(
        self,
        headers: Dict[str, str],
        ticket_tier_id: Optional[str] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/ticket-holds",
            headers=headers,
            params=_params(
                ticket_tier_id=ticket_tier_id,
                kind=kind,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def release_ticket_hold(self, ticket_hold_id: str, headers: Dict[str, str]):
        return self.post(f"/ticket-holds/{ticket_hold_id}/release", {}, headers=headers)

    def convert_hold_to_comp(self, ticket_hold_id: str, headers: Dict[str, str]):
        return self.post(
            f"/ticket-holds/{ticket_hold_id}/convert-to-comp", {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------

    def create_settlement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/settlements", payload, headers=headers)

    def get_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self.get(f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(
        self,
        headers: Dict[str, str],
        show_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/settlements",
            headers=headers,
            params=_params(
                show_id=show_id, status=status, limit=limit, offset=offset
            ),
        )

    def calculate_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self.post(f"/settlements/{settlement_id}/calculate", {}, headers=headers)

    def respond_to_settlement(
        self,
        settlement_id: str,
        headers: Dict[str, str],
        response: Optional[str] = None,
        dispute_reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(response=response, dispute_reason=dispute_reason)
        return self.post(
            f"/settlements/{settlement_id}/artist-response", payload, headers=headers
        )

    def pay_settlement(
        self,
        settlement_id: str,
        headers: Dict[str, str],
        payment_method: Optional[str] = None,
        payment_reference: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                payment_method=payment_method, payment_reference=payment_reference
            )
        return self.post(f"/settlements/{settlement_id}/pay", payload, headers=headers)

    def reopen_settlement(
        self,
        settlement_id: str,
        headers: Dict[str, str],
        reopen_reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(reopen_reason=reopen_reason)
        return self.post(
            f"/settlements/{settlement_id}/reopen", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Cancellation events
    # ------------------------------------------------------------------

    def create_cancellation_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post("/cancellation-events", payload, headers=headers)

    def get_cancellation_event(
        self, cancellation_event_id: str, headers: Dict[str, str]
    ):
        return self.get(f"/cancellation-events/{cancellation_event_id}", headers=headers)

    def list_cancellation_events(
        self,
        headers: Dict[str, str],
        show_id: Optional[str] = None,
        replacement_show_id: Optional[str] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self.get(
            "/cancellation-events",
            headers=headers,
            params=_params(
                show_id=show_id,
                replacement_show_id=replacement_show_id,
                kind=kind,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def process_refunds(self, cancellation_event_id: str, headers: Dict[str, str]):
        return self.post(
            f"/cancellation-events/{cancellation_event_id}/process-refunds",
            {},
            headers=headers,
        )

    def file_claim(
        self,
        cancellation_event_id: str,
        headers: Dict[str, str],
        claim_amount_cents: Optional[int] = None,
        claim_documentation_ref: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                claim_amount_cents=claim_amount_cents,
                claim_documentation_ref=claim_documentation_ref,
            )
        return self.post(
            f"/cancellation-events/{cancellation_event_id}/file-claim",
            payload,
            headers=headers,
        )

    def settle_claim(
        self,
        cancellation_event_id: str,
        headers: Dict[str, str],
        outcome: Optional[str] = None,
        insurer_reference: Optional[str] = None,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(
                outcome=outcome, insurer_reference=insurer_reference, reason=reason
            )
        return self.post(
            f"/cancellation-events/{cancellation_event_id}/settle-claim",
            payload,
            headers=headers,
        )

    def reschedule_cancellation_event(
        self,
        cancellation_event_id: str,
        headers: Dict[str, str],
        replacement_show_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if payload is None:
            payload = _body(replacement_show_id=replacement_show_id)
        return self.post(
            f"/cancellation-events/{cancellation_event_id}/reschedule",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatches for verb-surface and malformed-request checks
    # ------------------------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(method, path, payload=payload, headers=headers, params=params)
