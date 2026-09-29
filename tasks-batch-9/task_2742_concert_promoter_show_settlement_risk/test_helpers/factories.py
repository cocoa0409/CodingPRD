"""Request payload builders.

Every money amount is emitted as a JSON number, never a string. Optional
fields are omitted entirely unless a caller supplies them, so that declared
defaults are genuinely exercised.
"""

import itertools
from typing import Any, Dict, Optional

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Market, artist, venue
# ---------------------------------------------------------------------------


def market_payload(
    name: Optional[str] = None,
    region_code: str = "PNW",
    guarantee_exposure_limit_cents: int = 10_000_000,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name or f"Market {_n()}",
        "region_code": region_code,
        "guarantee_exposure_limit_cents": guarantee_exposure_limit_cents,
    }
    payload.update(extra)
    return payload


def artist_payload(
    name: Optional[str] = None,
    agency: str = "Meridian Talent",
    tier: str = "ARENA",
    historical_sellthrough_pct: float = 82.00,
    withholding_pct: Optional[float] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "name": name or f"Act {_n()}",
            "agency": agency,
            "tier": tier,
            "historical_sellthrough_pct": historical_sellthrough_pct,
            "withholding_pct": withholding_pct,
        }
    )
    payload.update(extra)
    return payload


def venue_payload(
    market_id: str,
    name: Optional[str] = None,
    gross_capacity: int = 3000,
    facility_fee_cents_per_ticket: int = 350,
    ticket_tax_pct: float = 8.00,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "market_id": market_id,
        "name": name or f"Venue {_n()}",
        "gross_capacity": gross_capacity,
        "facility_fee_cents_per_ticket": facility_fee_cents_per_ticket,
        "ticket_tax_pct": ticket_tax_pct,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------


def show_payload(
    artist_id: str,
    venue_id: str,
    event_at: str = "2026-10-10T02:00:00.000Z",
    load_in_at: str = "2026-10-09T14:00:00.000Z",
    load_out_at: str = "2026-10-10T08:00:00.000Z",
    announce_at: str = "2026-08-15T15:00:00.000Z",
    venue_arrangement: str = "RENTAL",
    rental_fee_cents: Optional[int] = None,
    copromote_venue_share_pct: Optional[float] = None,
    venue_expense_pct_production: Optional[float] = None,
    venue_expense_pct_marketing: Optional[float] = None,
    venue_expense_pct_staffing: Optional[float] = None,
    venue_expense_pct_hospitality: Optional[float] = None,
    rescheduled_from_show_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    # A payload that contradicts its own venue_arrangement is malformed, so fill
    # the arrangement-specific terms coherently whenever a caller leaves them out.
    if venue_arrangement == "RENTAL":
        if rental_fee_cents is None:
            rental_fee_cents = 500_000
        if copromote_venue_share_pct is None:
            copromote_venue_share_pct = 0
    elif venue_arrangement == "CO_PROMOTE":
        if rental_fee_cents is None:
            rental_fee_cents = 0
        if copromote_venue_share_pct is None:
            copromote_venue_share_pct = 15.00
    if venue_arrangement in ("RENTAL", "CO_PROMOTE"):
        if venue_expense_pct_production is None:
            venue_expense_pct_production = 0
        if venue_expense_pct_marketing is None:
            venue_expense_pct_marketing = 0
        if venue_expense_pct_staffing is None:
            venue_expense_pct_staffing = 0
        if venue_expense_pct_hospitality is None:
            venue_expense_pct_hospitality = 0
    payload = _drop_none(
        {
            "artist_id": artist_id,
            "venue_id": venue_id,
            "event_at": event_at,
            "load_in_at": load_in_at,
            "load_out_at": load_out_at,
            "announce_at": announce_at,
            "venue_arrangement": venue_arrangement,
            "rental_fee_cents": rental_fee_cents,
            "copromote_venue_share_pct": copromote_venue_share_pct,
            "venue_expense_pct_production": venue_expense_pct_production,
            "venue_expense_pct_marketing": venue_expense_pct_marketing,
            "venue_expense_pct_staffing": venue_expense_pct_staffing,
            "venue_expense_pct_hospitality": venue_expense_pct_hospitality,
            "rescheduled_from_show_id": rescheduled_from_show_id,
        }
    )
    payload.update(extra)
    return payload


def rental_show_payload(artist_id: str, venue_id: str, rental_fee_cents: int = 500_000, **kwargs: Any) -> Dict[str, Any]:
    return show_payload(
        artist_id,
        venue_id,
        venue_arrangement="RENTAL",
        rental_fee_cents=rental_fee_cents,
        **kwargs,
    )


def copromote_show_payload(
    artist_id: str,
    venue_id: str,
    copromote_venue_share_pct: float = 15.00,
    venue_expense_pct_production: float = 50.00,
    venue_expense_pct_marketing: float = 25.00,
    venue_expense_pct_staffing: float = 100.00,
    venue_expense_pct_hospitality: float = 0,
    **kwargs: Any,
) -> Dict[str, Any]:
    return show_payload(
        artist_id,
        venue_id,
        venue_arrangement="CO_PROMOTE",
        copromote_venue_share_pct=copromote_venue_share_pct,
        venue_expense_pct_production=venue_expense_pct_production,
        venue_expense_pct_marketing=venue_expense_pct_marketing,
        venue_expense_pct_staffing=venue_expense_pct_staffing,
        venue_expense_pct_hospitality=venue_expense_pct_hospitality,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Offer
# ---------------------------------------------------------------------------


def offer_payload(
    show_id: str,
    expected_show_version: int,
    deal_structure: str = "FLAT_GUARANTEE",
    guarantee_cents: int = 2_000_000,
    deposit_cents: int = 0,
    expense_cap_cents: int = 4_000_000,
    versus_pct: Optional[float] = None,
    backend_split_artist_pct: Optional[float] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "show_id": show_id,
            "expected_show_version": expected_show_version,
            "deal_structure": deal_structure,
            "guarantee_cents": guarantee_cents,
            "deposit_cents": deposit_cents,
            "expense_cap_cents": expense_cap_cents,
            "versus_pct": versus_pct,
            "backend_split_artist_pct": backend_split_artist_pct,
        }
    )
    payload.update(extra)
    return payload


def counter_payload(
    counter_guarantee_cents: int = 2_500_000,
    counter_note: str = "the act needs a higher floor for this routing",
    counter_versus_pct: Optional[float] = None,
    counter_backend_split_artist_pct: Optional[float] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "counter_guarantee_cents": counter_guarantee_cents,
            "counter_versus_pct": counter_versus_pct,
            "counter_backend_split_artist_pct": counter_backend_split_artist_pct,
            "counter_note": counter_note,
        }
    )


# ---------------------------------------------------------------------------
# Budget line and vendor invoice
# ---------------------------------------------------------------------------


def budget_line_payload(
    show_id: str,
    category: str = "PRODUCTION",
    description: Optional[str] = None,
    budgeted_cents: int = 1_500_000,
    is_artist_deductible: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "show_id": show_id,
            "category": category,
            "description": description or f"line item {_n()}",
            "budgeted_cents": budgeted_cents,
            "is_artist_deductible": is_artist_deductible,
        }
    )
    payload.update(extra)
    return payload


def variance_decision_payload(
    decision: str = "APPROVE",
    approved_cap_cents: Optional[int] = None,
    variance_justification: str = "overage reviewed against the signed change order",
) -> Dict[str, Any]:
    return _drop_none(
        {
            "decision": decision,
            "approved_cap_cents": approved_cap_cents,
            "variance_justification": variance_justification,
        }
    )


def vendor_invoice_payload(
    show_id: str,
    budget_line_id: str,
    amount_cents: int = 1_500_000,
    vendor_name: str = "Cascade Staging",
    invoice_date: str = "2026-10-09",
    documentation_ref: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "show_id": show_id,
        "budget_line_id": budget_line_id,
        "vendor_name": vendor_name,
        "amount_cents": amount_cents,
        "invoice_date": invoice_date,
        "documentation_ref": documentation_ref or f"INV-{_n():05d}",
    }
    payload.update(extra)
    return payload


def dispute_resolution_payload(
    outcome: str = "RESUBMIT",
    amount_cents: Optional[int] = None,
    documentation_ref: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "outcome": outcome,
            "amount_cents": amount_cents,
            "documentation_ref": documentation_ref,
            "reason": reason,
        }
    )


# ---------------------------------------------------------------------------
# Ticket tier and hold
# ---------------------------------------------------------------------------


def ticket_tier_payload(
    show_id: str,
    tier_name: Optional[str] = None,
    price_cents: int = 5_000,
    allocation_qty: int = 1_000,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "show_id": show_id,
        "tier_name": tier_name or f"TIER-{_n()}",
        "price_cents": price_cents,
        "allocation_qty": allocation_qty,
    }
    payload.update(extra)
    return payload


def price_adjustment_payload(
    new_price_cents: int,
    expected_show_version: int,
    reason: str = "sustained demand after the first sales week",
) -> Dict[str, Any]:
    return {
        "new_price_cents": new_price_cents,
        "expected_show_version": expected_show_version,
        "reason": reason,
    }


def ticket_hold_payload(
    ticket_tier_id: str,
    kind: str = "PROMOTER_HOLD",
    qty: int = 10,
    holder: str = "front of house mix position",
    expires_at: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "ticket_tier_id": ticket_tier_id,
            "kind": kind,
            "qty": qty,
            "holder": holder,
            "expires_at": expires_at,
        }
    )
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def settlement_payload(show_id: str, **extra: Any) -> Dict[str, Any]:
    payload = {"show_id": show_id}
    payload.update(extra)
    return payload


def artist_response_payload(
    response: str = "SIGN", dispute_reason: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none({"response": response, "dispute_reason": dispute_reason})


def payment_payload(
    payment_method: str = "WIRE", payment_reference: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "payment_method": payment_method,
        "payment_reference": payment_reference or f"WIRE-{_n():06d}",
    }


# ---------------------------------------------------------------------------
# Cancellation event
# ---------------------------------------------------------------------------


def cancellation_event_payload(
    show_id: str,
    kind: str = "CANCELLED",
    reason: str = "the act cancelled the routing on medical advice",
    **extra: Any,
) -> Dict[str, Any]:
    payload = {"show_id": show_id, "kind": kind, "reason": reason}
    payload.update(extra)
    return payload


def claim_payload(
    claim_amount_cents: int = 1_000_000,
    claim_documentation_ref: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "claim_amount_cents": claim_amount_cents,
        "claim_documentation_ref": claim_documentation_ref or f"CLAIM-{_n():05d}",
    }


def claim_settlement_payload(
    outcome: str = "SETTLE",
    insurer_reference: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "outcome": outcome,
            "insurer_reference": insurer_reference,
            "reason": reason,
        }
    )


def exposure_override_payload(
    exposure_override_limit_cents: int,
    exposure_override_justification: str = "strategic routing worth the ceiling breach",
) -> Dict[str, Any]:
    return {
        "exposure_override_limit_cents": exposure_override_limit_cents,
        "exposure_override_justification": exposure_override_justification,
    }
