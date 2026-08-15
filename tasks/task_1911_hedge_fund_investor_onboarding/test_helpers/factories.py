"""Payload factories — one per entity, input fields only."""
from typing import Optional

# Default server-side logical clock before any set call: 2026-08-01T00:00:00Z.
# Factories pick timestamps that are reasonable relative to that clock.

FUND_DEFAULTS = {
    "fund_name": "Test Fund LP",
    "domicile": "Cayman",
    "gate_threshold_pct": 0.25,
    "lockup_months_default": 12,
    "notice_days_default": 30,
    "fiscal_year_end_month": 12,
}

SHARE_CLASS_DEFAULTS = {
    "class_code": "A1",
    "min_initial_investment_cents": 100000,
    "min_additional_investment_cents": 50000,
    "management_fee_bps": 200,
    "performance_fee_bps": 2000,
    "hurdle_rate_bps": 0,
    "high_water_mark_required": False,
    "lockup_months": 0,
    "notice_days": 0,
    "redemption_frequency": "MONTHLY",
}

INVESTOR_DEFAULTS = {
    "legal_name": "Test Investor",
    "investor_type": "INDIVIDUAL",
    "tax_id": "T-000",
    "email": "investor@example.com",
    "residence_country": "US",
    "is_us_person": True,
}

KYC_CASE_DEFAULTS = {
    "risk_rating": "LOW",
    "pep_hit": False,
    "sanctions_hit": False,
    "adverse_media_hit": False,
}

ACCREDITATION_DEFAULTS = {
    "attestation_tier": "ACCREDITED",
    "evidence_type": "CPA_LETTER",
    "evidence_document_id": "doc-1",
    "attested_at_utc": "2026-08-01T00:00:00Z",
}

MFN_CLAUSE_DEFAULTS = {
    "clause_tag": "FEE_REBATE",
    "clause_text": "Standard MFN clause",
    "capacity_threshold_cents": 0,
    "fee_rebate_bps": 100,
    "notice_days_reduction": 0,
}


def create_fund_payload(**overrides) -> dict:
    payload = dict(FUND_DEFAULTS)
    payload.update(overrides)
    return payload


def create_share_class_payload(**overrides) -> dict:
    payload = dict(SHARE_CLASS_DEFAULTS)
    payload.update(overrides)
    return payload


def create_investor_payload(**overrides) -> dict:
    payload = dict(INVESTOR_DEFAULTS)
    payload.update(overrides)
    return payload


def create_kyc_case_payload(**overrides) -> dict:
    payload = dict(KYC_CASE_DEFAULTS)
    payload.update(overrides)
    return payload


def create_accreditation_payload(**overrides) -> dict:
    payload = dict(ACCREDITATION_DEFAULTS)
    payload.update(overrides)
    return payload


def create_subscription_payload(**overrides) -> dict:
    payload = {
        "investor_id": overrides.pop("investor_id", ""),
        "share_class_id": overrides.pop("share_class_id", ""),
        "commitment_amount_cents": overrides.pop("commitment_amount_cents", 100000),
        "funding_deadline_utc": overrides.pop("funding_deadline_utc", "2026-09-30T00:00:00Z"),
    }
    payload.update(overrides)
    return payload


def create_nav_period_payload(**overrides) -> dict:
    payload = {"period_end_utc": overrides.pop("period_end_utc", "2026-08-31T23:59:59Z")}
    payload.update(overrides)
    return payload


def create_funding_payload(**overrides) -> dict:
    payload = {
        "amount_cents": overrides.pop("amount_cents", 100000),
        "received_at_utc": overrides.pop("received_at_utc", "2026-08-05T00:00:00Z"),
    }
    payload.update(overrides)
    return payload


def create_side_letter_payload(**overrides) -> dict:
    payload = {
        "subscription_id": overrides.pop("subscription_id", ""),
        "terms_document_id": overrides.pop("terms_document_id", "doc-terms"),
    }
    if "supersedes_side_letter_id" in overrides:
        payload["supersedes_side_letter_id"] = overrides.pop("supersedes_side_letter_id")
    payload.update(overrides)
    return payload


def create_mfn_clause_payload(**overrides) -> dict:
    payload = dict(MFN_CLAUSE_DEFAULTS)
    payload.update(overrides)
    return payload


def create_redemption_payload(**overrides) -> dict:
    payload = {
        "capital_account_id": overrides.pop("capital_account_id", ""),
        "requested_amount_cents": overrides.pop("requested_amount_cents", 1000),
        "requested_effective_period_id": overrides.pop("requested_effective_period_id", ""),
    }
    if "requested_shares" in overrides:
        payload["requested_shares"] = overrides.pop("requested_shares")
    payload.update(overrides)
    return payload
