"""Request-payload builders.

Each builder returns a valid minimal-plus-defaults payload for one endpoint and
accepts keyword overrides, so a test can vary exactly the one field under test.
Passing ``None`` for a key that the builder supplies by default removes it from
the payload, which is how an omitted-optional case is expressed.
"""
from __future__ import annotations

import itertools
from typing import Any, Dict, Optional

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


def _alpha(n: int) -> str:
    """Encode a positive counter as uppercase letters only.

    PRD 3.1 constrains ``market_code`` to "3 to 12 characters of uppercase
    letters and hyphens", so a generated code may not carry digits.
    """
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out or "A"


def market_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    return _merge(
        {
            "market_code": f"EU-M{_alpha(n)}",
            "name": f"Market {n}",
            "paid_slot_capacity": 3,
            "price_display_mode": "TOTAL_UPFRONT",
            "ranking_disclosure_required": True,
        },
        overrides,
    )


def supplier_payload(home_market_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    return _merge(
        {
            "legal_name": f"Supplier {n} SARL",
            "supplier_type": "HOTEL",
            "home_market_id": home_market_id,
            "contact_email": f"ops{n}@supplier.example",
            "conversion_index": 50,
        },
        overrides,
    )


def certification_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    return _merge(
        {
            "content_score_claimed": 90,
            "connectivity_protocol": "JSON_V2",
            "sample_payload_ref": f"s3://cert-samples/pkg-{n}.json",
        },
        overrides,
    )


def certification_decision_payload(
    decision: str = "CERTIFY",
    content_score: int = 88,
    connectivity_score: int = 91,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "decision": decision,
            "content_score": content_score,
            "connectivity_score": connectivity_score,
        },
        overrides,
    )


def agency_agreement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "model": "AGENCY",
            "effective_from": "2026-08-01",
            "effective_to": "2026-09-30",
            "base_commission_pct": 0.15,
            "chargeback_liability_pct_marketplace": 0.60,
            "fraud_liability_cap_cents": 50000,
            "settlement_terms_days": 30,
        },
        overrides,
    )


def merchant_agreement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "model": "MERCHANT",
            "effective_from": "2026-08-01",
            "effective_to": "2026-12-31",
            "base_markup_pct": 0.12,
            "chargeback_liability_pct_marketplace": 0.25,
            "fraud_liability_cap_cents": 50000,
            "settlement_terms_days": 30,
        },
        overrides,
    )


def override_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "supplier_id": supplier_id,
            "rate_plan_id": None,
            "override_type": "COMMISSION_PCT",
            "value": 0.20,
            "effective_from": "2026-08-01",
            "effective_to": "2026-12-31",
            "justification": "Negotiated volume deal.",
        },
        overrides,
    )


def rate_plan_payload(market_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    return _merge(
        {
            "market_id": market_id,
            "name": f"Plan {n}",
            "currency": "EUR",
            "cancellation_policy_code": "FLEX",
            "free_cancel_cutoff_hours": 48,
            "tax_fee_pct": 0.01,
            "parity_monitored": True,
        },
        overrides,
    )


def offer_payload(
    travel_date: str,
    net_rate_cents: int,
    expected_rate_plan_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "travel_date": travel_date,
            "net_rate_cents": net_rate_cents,
            "allotment_total": 3,
            "expected_rate_plan_version": expected_rate_plan_version,
        },
        overrides,
    )


def observation_payload(
    travel_date: str, direct_total_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "travel_date": travel_date,
            "channel": "SUPPLIER_WEB",
            "observed_at": "2026-08-05T09:00:00Z",
            "direct_total_cents": direct_total_cents,
        },
        overrides,
    )


def placement_payload(
    supplier_id: str, market_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "supplier_id": supplier_id,
            "market_id": market_id,
            "slots": 2,
            "boost_points": 8,
            "fee_cents": 250000,
            "disclosure_label": "SPONSORED",
            "window_start": "2026-09-01",
            "window_end": "2026-10-01",
        },
        overrides,
    )


def ranking_run_payload(
    market_id: str, travel_date: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "market_id": market_id,
            "travel_date": travel_date,
            "sort_profile": "BEST_VALUE",
            "disclosure_version": "criteria-2026-08",
        },
        overrides,
    )


def package_payload(market_id: str, travel_date: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    return _merge(
        {
            "market_id": market_id,
            "travel_date": travel_date,
            "name": f"City Break {n}",
            "opaque": True,
        },
        overrides,
    )


def component_payload(offer_id: str, component_type: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"offer_id": offer_id, "component_type": component_type}, overrides)


def booking_payload(
    quoted_total_cents: int,
    offer_id: Optional[str] = None,
    package_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    n = _seq()
    base: Dict[str, Any] = {
        "traveler_reference": f"LOCATOR{n:05d}",
        "quoted_total_cents": quoted_total_cents,
        "payment_token": f"tok_{n:05d}",
    }
    if offer_id is not None:
        base["offer_id"] = offer_id
    if package_id is not None:
        base["package_id"] = package_id
    return _merge(base, overrides)


def dispute_payload(
    dispute_type: str, claim_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "dispute_type": dispute_type,
            "claim_cents": claim_cents,
            "narrative": "Traveller asserts the stay was not delivered as sold.",
        },
        overrides,
    )


def scorecard_payload(
    period_start: str, period_end: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"period_start": period_start, "period_end": period_end}, overrides)
