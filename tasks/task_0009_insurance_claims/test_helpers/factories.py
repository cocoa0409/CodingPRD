"""Payload factories — one per resource, input fields only (PRD §3 / §4)."""
from typing import List, Optional


# ─── Policy (PRD §2.6, §3.9) ────────────────────────────────────────
def create_policy_payload(
    policy_number: str = "POLICY00000001",
    insured_party_id: str = "test-customer-1",
    coverage_type: str = "AUTO",
    coverage_limit_cents: int = 1_000_000,
    deductible_cents: int = 100_000,
    coinsurance_ratio: float = 0.8000,
    effective_from: str = "2024-01-01T00:00:00.000Z",
    effective_to: str = "2030-01-01T00:00:00.000Z",
    reporting_window_days: Optional[int] = 30,
    **overrides,
) -> dict:
    payload = {
        "policy_number": policy_number,
        "insured_party_id": insured_party_id,
        "coverage_type": coverage_type,
        "coverage_limit_cents": coverage_limit_cents,
        "deductible_cents": deductible_cents,
        "coinsurance_ratio": coinsurance_ratio,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    if reporting_window_days is not None:
        payload["reporting_window_days"] = reporting_window_days
    payload.update(overrides)
    return payload


# ─── Adjuster ───────────────────────────────────────────────────────
def create_adjuster_payload(
    full_name: str = "Test Adjuster",
    license_number: str = "LIC-TEST-0001",
    specialty: str = "AUTO",
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "license_number": license_number,
        "specialty": specialty,
    }
    payload.update(overrides)
    return payload


# ─── RepairShop ─────────────────────────────────────────────────────
def create_repair_shop_payload(
    name: str = "Test Repair Shop",
    tax_id: str = "TAX-TEST-0001",
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "tax_id": tax_id,
    }
    payload.update(overrides)
    return payload


# ─── Claim intake (PRD §3.1) ────────────────────────────────────────
def create_claim_payload(
    policy_id: Optional[str] = None,
    report_channel: str = "WEB",
    idempotency_key: str = "idem-key-test-1",
    loss_date: str = "2024-06-01T00:00:00.000Z",
    incident_description: str = "Test loss event description",
    claimed_amount_cents: int = 600_000,
    salvage_value_cents: Optional[int] = 0,
    **overrides,
) -> dict:
    payload = {
        "policy_id": policy_id,
        "report_channel": report_channel,
        "idempotency_key": idempotency_key,
        "loss_date": loss_date,
        "incident_description": incident_description,
        "claimed_amount_cents": claimed_amount_cents,
    }
    if salvage_value_cents is not None:
        payload["salvage_value_cents"] = salvage_value_cents
    payload.update(overrides)
    return payload


# ─── Investigation open (PRD §3.2) ─────────────────────────────────
def create_investigation_payload(
    adjuster_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {"adjuster_id": adjuster_id}
    payload.update(overrides)
    return payload


# ─── Investigation patch (photos / doc-auth / assessed loss) ───────
def patch_investigation_payload(
    photo_urls: Optional[List[str]] = None,
    document_authenticity_passed: Optional[bool] = None,
    assessed_loss_cents: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {}
    if photo_urls is not None:
        payload["photo_urls"] = photo_urls
    if document_authenticity_passed is not None:
        payload["document_authenticity_passed"] = document_authenticity_passed
    if assessed_loss_cents is not None:
        payload["assessed_loss_cents"] = assessed_loss_cents
    payload.update(overrides)
    return payload


# ─── EstimateLineItem ──────────────────────────────────────────────
def create_estimate_line_item_payload(
    repair_shop_id: Optional[str] = None,
    description: str = "Replace damaged part",
    amount_cents: int = 500_000,
    **overrides,
) -> dict:
    payload = {
        "repair_shop_id": repair_shop_id,
        "description": description,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


# ─── ReviewDecision (primary) ──────────────────────────────────────
def create_decision_payload(
    outcome: str = "APPROVE",
    rationale: str = "Reviewed and approved.",
    **overrides,
) -> dict:
    payload = {"outcome": outcome, "rationale": rationale}
    payload.update(overrides)
    return payload


# ─── ReviewDecision on appeal (secondary) ──────────────────────────
def create_appeal_decision_payload(
    outcome: str = "OVERTURN",
    rationale: str = "Appeal sustained.",
    **overrides,
) -> dict:
    payload = {"outcome": outcome, "rationale": rationale}
    payload.update(overrides)
    return payload


# ─── Appeal ────────────────────────────────────────────────────────
def create_appeal_payload(
    grounds: str = "Customer provides additional evidence.",
    **overrides,
) -> dict:
    payload = {"grounds": grounds}
    payload.update(overrides)
    return payload


# ─── Subrogation ───────────────────────────────────────────────────
def create_subrogation_payload(
    amount_cents: int = 30_000,
    **overrides,
) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ─── FraudFlag ─────────────────────────────────────────────────────
def create_fraud_flag_payload(
    signal: str = "DUPLICATE_PATTERN",
    severity: float = 0.5,
    repair_shop_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {"signal": signal, "severity": severity}
    if repair_shop_id is not None:
        payload["repair_shop_id"] = repair_shop_id
    payload.update(overrides)
    return payload


# ─── Test-driving payloads ─────────────────────────────────────────
def advance_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def bank_event_payload(payout_id: str, **overrides) -> dict:
    payload = {"payout_id": payout_id}
    payload.update(overrides)
    return payload
