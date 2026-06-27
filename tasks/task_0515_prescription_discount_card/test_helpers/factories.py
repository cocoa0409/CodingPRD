"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import ATORVA_NDC

# Default validity window covering the standard test clock (2026-05-15).
DEFAULT_EFFECTIVE_AT = "2026-05-01T00:00:00Z"
DEFAULT_EXPIRES_AT = "2027-01-01T00:00:00Z"


def create_drug_payload(**overrides) -> dict:
    """POST /drugs input: name, ndc, dosage_mg, form, awp_cents, is_controlled?."""
    defaults = {
        "name": "Atorvastatin",
        "ndc": ATORVA_NDC,
        "dosage_mg": 20,
        "form": "TABLET",
        "awp_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_pharmacy_payload(**overrides) -> dict:
    """POST /pharmacies input: name, chain_code, state_code, dispense_fee_cents, is_mail_order?."""
    defaults = {
        "name": "PH One",
        "chain_code": "CVS",
        "state_code": "CA",
        "dispense_fee_cents": 200,
    }
    defaults.update(overrides)
    return defaults


def create_price_quote_payload(drug_id: str, pharmacy_id: str, **overrides) -> dict:
    """POST /price-quotes input: drug_id, pharmacy_id, three price tiers, window."""
    defaults = {
        "drug_id": drug_id,
        "pharmacy_id": pharmacy_id,
        "cash_price_cents": 7000,
        "discount_price_cents": 5500,
        "gold_price_cents": 5200,
        "effective_at": DEFAULT_EFFECTIVE_AT,
        "expires_at": DEFAULT_EXPIRES_AT,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    """POST /members input: email, full_name, state_code, has_insurance?."""
    defaults = {
        "email": "member@example.com",
        "full_name": "Test Member",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_comparison_payload(member_id: str, drug_id: str, **overrides) -> dict:
    """POST /comparisons input: member_id, drug_id, state_code."""
    defaults = {
        "member_id": member_id,
        "drug_id": drug_id,
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_insurance_estimate_payload(member_id: str, **overrides) -> dict:
    """POST /comparisons/{id}/insurance-estimate input: member_id, copay_cents, deductible."""
    defaults = {
        "member_id": member_id,
        "copay_cents": 1000,
        "deductible_remaining_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_discount_card_payload(member_id: str, comparison_id: str, **overrides) -> dict:
    """POST /discount-cards input: member_id, comparison_id."""
    defaults = {
        "member_id": member_id,
        "comparison_id": comparison_id,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(discount_card_id: str, pharmacy_id: str, **overrides) -> dict:
    """POST /claims input: discount_card_id, pharmacy_id, quantity."""
    defaults = {
        "discount_card_id": discount_card_id,
        "pharmacy_id": pharmacy_id,
        "quantity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_copay_card_payload(drug_id: str, **overrides) -> dict:
    """POST /copay-cards input: sponsor_name, drug_id, max_benefit_cents, per_fill_cap_cents."""
    defaults = {
        "sponsor_name": "Pfizer",
        "drug_id": drug_id,
        "max_benefit_cents": 50000,
        "per_fill_cap_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_copay_link_payload(copay_card_id: str, member_id: str, claim_id: str,
                              **overrides) -> dict:
    """POST /copay-links input: copay_card_id, member_id, claim_id."""
    defaults = {
        "copay_card_id": copay_card_id,
        "member_id": member_id,
        "claim_id": claim_id,
    }
    defaults.update(overrides)
    return defaults


def create_gold_membership_payload(member_id: str, **overrides) -> dict:
    """POST /gold-memberships input: member_id, tier, coverage_start, coverage_end, covered?."""
    defaults = {
        "member_id": member_id,
        "tier": "GOLD_INDIVIDUAL",
        "coverage_start": "2026-05-01T00:00:00Z",
        "coverage_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_mail_order_payload(discount_card_id: str, pharmacy_id: str, member_id: str,
                              **overrides) -> dict:
    """POST /mail-orders input: discount_card_id, pharmacy_id, member_id, quantity, ship_to_state."""
    defaults = {
        "discount_card_id": discount_card_id,
        "pharmacy_id": pharmacy_id,
        "member_id": member_id,
        "quantity": 2,
        "ship_to_state": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_telehealth_referral_payload(member_id: str, comparison_id: str, **overrides) -> dict:
    """POST /telehealth-referrals input: member_id, comparison_id, reason."""
    defaults = {
        "member_id": member_id,
        "comparison_id": comparison_id,
        "reason": "PRICE_TOO_HIGH",
    }
    defaults.update(overrides)
    return defaults
