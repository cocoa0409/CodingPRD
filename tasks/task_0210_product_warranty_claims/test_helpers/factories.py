"""Payload factories — one per input-bearing endpoint (PRD §3).

Every factory accepts **overrides so a test can dial a specific value (e.g.,
purchase_price_cents=60000 for the msrp-clamp test). Input fields only — system
and computed fields (status, version, warranty_end_date, remaining_coverage_cents,
proof_status, active_tier_id, rma_number, assessed_value_cents, ...) are never
supplied by the client.
"""
from typing import Optional


# ─── Product (PRD §3.1) ──────────────────────────────────────────────────────
def create_product_payload(
    model_number: str = "MDL-0001",
    category: str = "ELECTRONICS",
    msrp_cents: int = 60000,
    base_warranty_months: int = 12,
    serviceable_lifespan_months: int = 48,
    **overrides,
) -> dict:
    payload = {
        "model_number": model_number,
        "category": category,
        "msrp_cents": msrp_cents,
        "base_warranty_months": base_warranty_months,
        "serviceable_lifespan_months": serviceable_lifespan_months,
    }
    payload.update(overrides)
    return payload


# ─── CoverageTier (PRD §3.1) ─────────────────────────────────────────────────
def create_coverage_tier_payload(
    product_id: str,
    tier_name: str = "BASE",
    extension_months: int = 0,
    price_cents: int = 0,
    coverage_cap_cents: int = 20000,
    depreciation_method: str = "STRAIGHT_LINE",
    refund_eligible: Optional[bool] = None,
    premium_refund_method: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "product_id": product_id,
        "tier_name": tier_name,
        "extension_months": extension_months,
        "price_cents": price_cents,
        "coverage_cap_cents": coverage_cap_cents,
        "depreciation_method": depreciation_method,
    }
    if refund_eligible is not None:
        payload["refund_eligible"] = refund_eligible
    if premium_refund_method is not None:
        payload["premium_refund_method"] = premium_refund_method
    payload.update(overrides)
    return payload


# ─── Owner (PRD §3.2) ────────────────────────────────────────────────────────
def create_owner_payload(
    full_name: str = "Test Owner",
    email: str = "owner@example.com",
    **overrides,
) -> dict:
    payload = {"full_name": full_name, "email": email}
    payload.update(overrides)
    return payload


# ─── Registration (PRD §3.2) ─────────────────────────────────────────────────
def create_registration_payload(
    product_id: str,
    owner_user_id: str,
    serial_number: str = "SN-0001",
    purchase_date: str = "2024-01-15T00:00:00Z",
    purchase_price_cents: int = 50000,
    **overrides,
) -> dict:
    payload = {
        "product_id": product_id,
        "serial_number": serial_number,
        "owner_user_id": owner_user_id,
        "purchase_date": purchase_date,
        "purchase_price_cents": purchase_price_cents,
    }
    payload.update(overrides)
    return payload


# ─── ExtendedWarranty (PRD §3.4) ─────────────────────────────────────────────
def create_extended_warranty_payload(
    registration_id: str,
    coverage_tier_id: str,
    amount_paid_cents: int,
    **overrides,
) -> dict:
    payload = {
        "registration_id": registration_id,
        "coverage_tier_id": coverage_tier_id,
        "amount_paid_cents": amount_paid_cents,
    }
    payload.update(overrides)
    return payload


# ─── ProofOfPurchase (PRD §3.3) ──────────────────────────────────────────────
def create_proof_payload(
    registration_id: str,
    document_type: str = "RECEIPT",
    stated_purchase_date: str = "2024-01-15T00:00:00Z",
    stated_amount_cents: int = 50000,
    **overrides,
) -> dict:
    payload = {
        "registration_id": registration_id,
        "document_type": document_type,
        "stated_purchase_date": stated_purchase_date,
        "stated_amount_cents": stated_amount_cents,
    }
    payload.update(overrides)
    return payload


# ─── Claim (PRD §3.5) ────────────────────────────────────────────────────────
def create_claim_payload(
    registration_id: str,
    defect_category: str = "MANUFACTURING",
    reported_date: str = "2024-02-15T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "registration_id": registration_id,
        "defect_category": defect_category,
        "reported_date": reported_date,
    }
    payload.update(overrides)
    return payload


# ─── Warranty transfer initiation (PRD §3.11) ────────────────────────────────
def transfer_payload(
    to_owner_user_id: str,
    expected_registration_version: int,
    **overrides,
) -> dict:
    payload = {
        "to_owner_user_id": to_owner_user_id,
        "expected_registration_version": expected_registration_version,
    }
    payload.update(overrides)
    return payload


# ─── Adjudication decision (PRD §3.7) ────────────────────────────────────────
def adjudicate_approve_payload(
    resolution_type: str,
    repair_cost_cents: Optional[int] = None,
    replace_cost_cents: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {"decision": "approve", "resolution_type": resolution_type}
    if repair_cost_cents is not None:
        payload["repair_cost_cents"] = repair_cost_cents
    if replace_cost_cents is not None:
        payload["replace_cost_cents"] = replace_cost_cents
    payload.update(overrides)
    return payload


def adjudicate_deny_payload(**overrides) -> dict:
    payload = {"decision": "deny"}
    payload.update(overrides)
    return payload


# ─── Clock (PRD §3.13) ───────────────────────────────────────────────────────
def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
