"""Request-payload factories, one per creatable resource.

Each factory returns a fully valid payload built from the documented required
fields, and accepts keyword overrides so a test can perturb exactly the one
field it is exercising. `None` is never injected implicitly: to omit an
optional field simply do not pass it; to send an explicit `null` pass it.
"""

from typing import Any, Optional

from .constants import TEST_DEFAULTS

_OMIT = object()


def _apply(payload: dict, overrides: dict) -> dict:
    """Merge overrides, dropping any key whose override is the omission token."""
    merged = dict(payload)
    for key, value in overrides.items():
        if value is _OMIT:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


OMIT = _OMIT


# ─── Seller onboarding ──────────────────────────────────────────────────────


def seller_payload(**overrides: Any) -> dict:
    return _apply(
        {
            "legal_name": TEST_DEFAULTS["SELLER_LEGAL_NAME"],
            "tin": TEST_DEFAULTS["SELLER_TIN"],
            "seller_type": TEST_DEFAULTS["SELLER_TYPE"],
        },
        overrides,
    )


def financial_statement_payload(**overrides: Any) -> dict:
    return _apply(
        {
            "fiscal_year_end": TEST_DEFAULTS["FISCAL_YEAR_END"],
            "tangible_net_worth_cents": TEST_DEFAULTS["TANGIBLE_NET_WORTH_CENTS"],
            "liquid_assets_cents": TEST_DEFAULTS["LIQUID_ASSETS_CENTS"],
            "audited": True,
        },
        overrides,
    )


def statement_review_payload(decision: str = "ACCEPT", **overrides: Any) -> dict:
    return _apply({"decision": decision}, overrides)


def qc_review_payload(review_type: str = "PRE_APPROVAL", **overrides: Any) -> dict:
    return _apply({"review_type": review_type}, overrides)


def qc_completion_payload(
    findings_count: int = 2, critical_findings_count: int = 0, **overrides: Any
) -> dict:
    return _apply(
        {
            "findings_count": findings_count,
            "critical_findings_count": critical_findings_count,
        },
        overrides,
    )


def approval_decision_payload(decision: str = "APPROVE", **overrides: Any) -> dict:
    return _apply({"decision": decision}, overrides)


def standing_action_payload(action: str, **overrides: Any) -> dict:
    return _apply({"action": action}, overrides)


# ─── Product eligibility ────────────────────────────────────────────────────


def product_payload(**overrides: Any) -> dict:
    return _apply(
        {
            "product_code": TEST_DEFAULTS["PRODUCT_CODE"],
            "base_price_pct": TEST_DEFAULTS["BASE_PRICE_PCT"],
            "min_fico": TEST_DEFAULTS["MIN_FICO"],
            "max_ltv_pct": TEST_DEFAULTS["MAX_LTV_PCT"],
            "max_loan_amount_cents": TEST_DEFAULTS["MAX_LOAN_AMOUNT_CENTS"],
            "allowed_commitment_types": ["MANDATORY", "BEST_EFFORTS"],
            "allowed_occupancies": ["PRIMARY", "SECOND_HOME"],
            "srp_pct": TEST_DEFAULTS["SRP_PCT"],
        },
        overrides,
    )


def pricing_adjustment_payload(**overrides: Any) -> dict:
    return _apply(
        {
            "adjustment_code": "LLPA-F700-L85",
            "fico_min": 700,
            "fico_max": 739,
            "ltv_min_pct": 80.0,
            "ltv_max_pct": 85.0,
            "price_adjustment_bps": -50,
        },
        overrides,
    )


# ─── Lock desk ──────────────────────────────────────────────────────────────


def commitment_payload(
    seller_id: str, product_id: str, **overrides: Any
) -> dict:
    return _apply(
        {
            "seller_id": seller_id,
            "product_id": product_id,
            "commitment_type": "MANDATORY",
            "notional_amount_cents": TEST_DEFAULTS["NOTIONAL_AMOUNT_CENTS"],
            "delivery_window_start": TEST_DEFAULTS["DELIVERY_WINDOW_START"],
            "delivery_expiry_date": TEST_DEFAULTS["DELIVERY_EXPIRY_DATE"],
            "reference_fico": TEST_DEFAULTS["REFERENCE_FICO"],
            "reference_ltv_pct": TEST_DEFAULTS["REFERENCE_LTV_PCT"],
        },
        overrides,
    )


def pair_off_payload(pair_off_market_price_pct: float, **overrides: Any) -> dict:
    return _apply(
        {"pair_off_market_price_pct": pair_off_market_price_pct}, overrides
    )


def expire_due_payload(seller_id: Optional[str] = None, **overrides: Any) -> dict:
    payload: dict = {}
    if seller_id is not None:
        payload["seller_id"] = seller_id
    return _apply(payload, overrides)


# ─── Loan delivery ──────────────────────────────────────────────────────────


def loan_payload(
    expected_commitment_version: int,
    seller_loan_number: str = "HP-0001",
    **overrides: Any,
) -> dict:
    return _apply(
        {
            "seller_loan_number": seller_loan_number,
            "note_amount_cents": TEST_DEFAULTS["NOTE_AMOUNT_CENTS"],
            "note_rate_pct": TEST_DEFAULTS["NOTE_RATE_PCT"],
            "fico": TEST_DEFAULTS["FICO"],
            "ltv_pct": TEST_DEFAULTS["LTV_PCT"],
            "occupancy": "PRIMARY",
            "servicing_election": "RETAINED",
            "closing_date": TEST_DEFAULTS["CLOSING_DATE"],
            "first_payment_due_date": TEST_DEFAULTS["FIRST_PAYMENT_DUE_DATE"],
            "expected_commitment_version": expected_commitment_version,
        },
        overrides,
    )


# ─── Purchase review ────────────────────────────────────────────────────────


def defect_payload(
    defect_code: str = "DEF-001",
    category: str = "CREDIT",
    severity: str = "MEDIUM",
    **overrides: Any,
) -> dict:
    return _apply(
        {
            "defect_code": defect_code,
            "category": category,
            "severity": severity,
        },
        overrides,
    )


def cure_payload(
    cure_document_reference: str = "CURE-DOC-001", **overrides: Any
) -> dict:
    return _apply({"cure_document_reference": cure_document_reference}, overrides)


def waive_payload(price_adjustment_bps: int = -25, **overrides: Any) -> dict:
    return _apply({"price_adjustment_bps": price_adjustment_bps}, overrides)


def suspense_condition_payload(
    condition_code: str = "COND-001", **overrides: Any
) -> dict:
    return _apply({"condition_code": condition_code}, overrides)


def condition_clear_payload(
    document_reference: str = "COND-DOC-001", **overrides: Any
) -> dict:
    return _apply({"document_reference": document_reference}, overrides)


# ─── Purchase advice and settlement ─────────────────────────────────────────


def advice_payload(expected_loan_version: int, **overrides: Any) -> dict:
    return _apply({"expected_loan_version": expected_loan_version}, overrides)


def settlement_payload(funding_reference: str = "WIRE-0001", **overrides: Any) -> dict:
    return _apply({"funding_reference": funding_reference}, overrides)


def payment_event_payload(event_type: str, **overrides: Any) -> dict:
    return _apply({"event_type": event_type}, overrides)


# ─── Repurchase and escrow ──────────────────────────────────────────────────


def repurchase_demand_payload(
    reason: str,
    demand_letter_reference: str = "DEMAND-0001",
    source_defect_id: Optional[str] = None,
    **overrides: Any,
) -> dict:
    payload: dict = {
        "reason": reason,
        "demand_letter_reference": demand_letter_reference,
    }
    if source_defect_id is not None:
        payload["source_defect_id"] = source_defect_id
    return _apply(payload, overrides)


def appeal_payload(
    appeal_reason: str = "Documentation supports the original underwrite.",
    **overrides: Any,
) -> dict:
    return _apply({"appeal_reason": appeal_reason}, overrides)


def demand_decision_payload(
    decision: str, note: Optional[str] = None, **overrides: Any
) -> dict:
    payload: dict = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return _apply(payload, overrides)


def demand_settlement_payload(
    remittance_reference: str = "REMIT-0001", **overrides: Any
) -> dict:
    return _apply({"remittance_reference": remittance_reference}, overrides)


def escrow_completion_payload(
    goodbye_letter_reference: str = "GOODBYE-0001", **overrides: Any
) -> dict:
    return _apply({"goodbye_letter_reference": goodbye_letter_reference}, overrides)


# ─── Scorecards ─────────────────────────────────────────────────────────────


def scorecard_payload(period_start: str, period_end: str, **overrides: Any) -> dict:
    return _apply(
        {"period_start": period_start, "period_end": period_end}, overrides
    )
