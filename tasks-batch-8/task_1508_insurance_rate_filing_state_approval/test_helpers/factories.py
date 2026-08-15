"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import EXPERIENCE_DEFAULTS, FILING_DEFAULTS, PROFILE_DEFAULTS, WAVE_DEFAULTS


def create_product_payload(**overrides) -> dict:
    defaults = {"product_code": "PPA", "name": "Personal Auto"}
    defaults.update(overrides)
    return defaults


def create_profile_payload(product_id: str, state_code: str = "CA", **overrides) -> dict:
    defaults = {"product_id": product_id, "state_code": state_code}
    defaults.update(PROFILE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_indication_payload(
    product_id: str, expected_product_version: int, **overrides
) -> dict:
    defaults = {
        "product_id": product_id,
        "variant": "INCURRED_CREDIBILITY",
        "expected_product_version": expected_product_version,
    }
    defaults.update(EXPERIENCE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_filing_payload(
    product_id: str, state_code: str, indication_id: str, **overrides
) -> dict:
    defaults = {
        "product_id": product_id,
        "state_code": state_code,
        "indication_id": indication_id,
    }
    defaults.update(FILING_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_component_payload(
    component_type: str = "RATE",
    name: str = "Base Rates",
    content_ref: str = "s3://fil/rate.pdf",
    **overrides,
) -> dict:
    defaults = {
        "component_type": component_type,
        "name": name,
        "content_ref": content_ref,
    }
    defaults.update(overrides)
    return defaults


def create_deviation_payload(filing_id: str, **overrides) -> dict:
    defaults = {
        "filing_id": filing_id,
        "deviation_type": "RATE_FACTOR",
        "base_reference": "CW-TERR-REL",
        "deviation_factor": 1.05,
        "justification": "State-specific load justification",
    }
    defaults.update(overrides)
    return defaults


def create_objection_payload(filing_id: str, **overrides) -> dict:
    defaults = {"filing_id": filing_id, "question_text": "Justify the filing."}
    defaults.update(overrides)
    return defaults


def create_response_payload(response_text: str, expected_objection_version: int) -> dict:
    return {
        "response_text": response_text,
        "expected_objection_version": expected_objection_version,
    }


def create_wave_payload(filing_id: str, **overrides) -> dict:
    defaults = {"filing_id": filing_id}
    defaults.update(WAVE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_policy_payload(
    product_id: str,
    state_code: str = "CA",
    policy_number: str = "CA-1001",
    current_premium_cents: int = 100_000,
    class_rel_factor: float = 1.0,
    renewal_effective_date: str = "2026-11-20",
    **overrides,
) -> dict:
    defaults = {
        "product_id": product_id,
        "state_code": state_code,
        "policy_number": policy_number,
        "current_premium_cents": current_premium_cents,
        "class_rel_factor": class_rel_factor,
        "renewal_effective_date": renewal_effective_date,
    }
    defaults.update(overrides)
    return defaults
