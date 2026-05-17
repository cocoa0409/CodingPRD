"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared ``input`` fields are produced;
computed and system-managed fields are intentionally omitted so the
implementation cannot accidentally accept them as inputs.

PRD §2.4: every monetary value is integer cents; rate fields are
real-valued multipliers.
"""
from __future__ import annotations

import random
import string
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_MAIL_ORDER_DISCOUNT_RATE,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
_DIGITS = string.digits


def random_suffix(n: int = 8) -> str:
    """Random uppercase alphanumeric suffix, useful for unique names."""
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=n),
    )


def random_ndc() -> str:
    """PRD §3.1: "Each Drug is created with an eleven-digit National
    Drug Code ndc … which must consist of exactly eleven digit
    characters." Returns a unique-looking 11-digit numeric string."""
    return "".join(random.choices(_DIGITS, k=11))


def random_npi() -> str:
    """PRD §3.3: "a ten-digit prescriber_npi matching the National
    Provider Identifier format (exactly ten digit characters)." """
    return "".join(random.choices(_DIGITS, k=10))


# ---------------------------------------------------------------------------
# Plan — PRD §3.1
# ---------------------------------------------------------------------------
def create_plan_payload(
    *,
    name: Optional[str] = None,
    deductible_cents: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    coinsurance_rate: Optional[float] = None,
    mail_order_discount_rate: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/plans — PBMAdmin only.

    PRD §3.1 required: name, deductible_cents, oop_max_cents,
    coinsurance_rate. Optional: mail_order_discount_rate (defaults to
    0.90 server-side per PRD §3.1).
    """
    payload: Dict[str, Any] = {
        "name": name if name is not None else f"Plan {random_suffix(4)}",
        "deductible_cents": (
            deductible_cents if deductible_cents is not None
            else TEST_DEFAULTS["PLAN_DEDUCTIBLE_CENTS"]
        ),
        "oop_max_cents": (
            oop_max_cents if oop_max_cents is not None
            else TEST_DEFAULTS["PLAN_OOP_MAX_CENTS"]
        ),
        "coinsurance_rate": (
            coinsurance_rate if coinsurance_rate is not None
            else TEST_DEFAULTS["PLAN_COINSURANCE_RATE"]
        ),
    }
    if mail_order_discount_rate is not None:
        payload["mail_order_discount_rate"] = mail_order_discount_rate
    payload.update(overrides)
    return payload


def patch_plan_payload(
    *,
    deductible_cents: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    coinsurance_rate: Optional[float] = None,
    mail_order_discount_rate: Optional[float] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /pbm/plans/{id} — PBMAdmin only. PRD §4: input fields are
    deductible_cents?, oop_max_cents?, coinsurance_rate?,
    mail_order_discount_rate?, and version."""
    payload: Dict[str, Any] = {}
    if deductible_cents is not None:
        payload["deductible_cents"] = deductible_cents
    if oop_max_cents is not None:
        payload["oop_max_cents"] = oop_max_cents
    if coinsurance_rate is not None:
        payload["coinsurance_rate"] = coinsurance_rate
    if mail_order_discount_rate is not None:
        payload["mail_order_discount_rate"] = mail_order_discount_rate
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Drug — PRD §3.1
# ---------------------------------------------------------------------------
def create_drug_payload(
    *,
    ndc: Optional[str] = None,
    generic_name: Optional[str] = None,
    brand_name: Optional[str] = None,
    unit_allowed_cents: Optional[int] = None,
    is_specialty: Optional[bool] = None,
    requires_prior_auth: Optional[bool] = None,
    step_therapy_predecessor_ndc: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/drugs — PBMAdmin only.

    PRD §3.1 required input: ndc (exactly 11 digits), generic_name,
    brand_name, unit_allowed_cents. Optional with PRD defaults:
    is_specialty (false), requires_prior_auth (false),
    step_therapy_predecessor_ndc (null).
    """
    payload: Dict[str, Any] = {
        "ndc": ndc if ndc is not None else random_ndc(),
        "generic_name": (
            generic_name if generic_name is not None
            else f"Drug-G-{random_suffix(4)}"
        ),
        "brand_name": (
            brand_name if brand_name is not None
            else f"Drug-B-{random_suffix(4)}"
        ),
        "unit_allowed_cents": (
            unit_allowed_cents if unit_allowed_cents is not None
            else TEST_DEFAULTS["DRUG_UNIT_ALLOWED_CENTS"]
        ),
    }
    if is_specialty is not None:
        payload["is_specialty"] = is_specialty
    if requires_prior_auth is not None:
        payload["requires_prior_auth"] = requires_prior_auth
    if step_therapy_predecessor_ndc is not None:
        payload["step_therapy_predecessor_ndc"] = (
            step_therapy_predecessor_ndc
        )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Member — PRD §3.2
# ---------------------------------------------------------------------------
def create_member_payload(
    *,
    plan_id: str,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/members — PBMAdmin only.

    PRD §3.2 required: plan_id, full_name, date_of_birth (ISO 8601
    calendar date).
    """
    payload: Dict[str, Any] = {
        "plan_id": plan_id,
        "full_name": (
            full_name if full_name is not None
            else f"Member {random_suffix(4)}"
        ),
        "date_of_birth": (
            date_of_birth if date_of_birth is not None
            else TEST_DEFAULTS["DEFAULT_DATE_OF_BIRTH"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FormularyEntry — PRD §3.1
# ---------------------------------------------------------------------------
def create_formulary_entry_payload(
    *,
    plan_id: str,
    drug_id: str,
    tier: Optional[int] = None,
    copay_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/formulary-entries — PBMAdmin only.

    PRD §3.1 required: plan_id, drug_id, tier (1-5), copay_cents (>=0).
    """
    payload: Dict[str, Any] = {
        "plan_id": plan_id,
        "drug_id": drug_id,
        "tier": (
            tier if tier is not None
            else TEST_DEFAULTS["FORMULARY_TIER"]
        ),
        "copay_cents": (
            copay_cents if copay_cents is not None
            else TEST_DEFAULTS["FORMULARY_COPAY_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


def patch_formulary_entry_payload(
    *,
    tier: Optional[int] = None,
    copay_cents: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /pbm/formulary-entries/{id} — PBMAdmin only. PRD §4:
    input is tier?, copay_cents?, version."""
    payload: Dict[str, Any] = {}
    if tier is not None:
        payload["tier"] = tier
    if copay_cents is not None:
        payload["copay_cents"] = copay_cents
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PriorAuthorization — PRD §3.3
# ---------------------------------------------------------------------------
def create_prior_authorization_payload(
    *,
    member_id: str,
    drug_id: str,
    prescriber_npi: Optional[str] = None,
    clinical_rationale: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations — Prescriber only.

    PRD §3.3 required: member_id, drug_id, prescriber_npi (exactly 10
    digits), clinical_rationale (non-empty).
    """
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "drug_id": drug_id,
        "prescriber_npi": (
            prescriber_npi if prescriber_npi is not None
            else random_npi()
        ),
        "clinical_rationale": (
            clinical_rationale if clinical_rationale is not None
            else (
                "Patient meets clinical criteria per published "
                "guidelines and prior therapy has been documented."
            )
        ),
    }
    payload.update(overrides)
    return payload


def resubmit_prior_authorization_payload(
    *,
    clinical_rationale: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations/{id}/resubmit — Prescriber only.

    PRD §3.3: resubmit accepts refreshed clinical_rationale and version.
    """
    payload: Dict[str, Any] = {
        "clinical_rationale": (
            clinical_rationale if clinical_rationale is not None
            else (
                "Updated clinical rationale with the additional "
                "information the reviewer requested."
            )
        ),
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def deny_prior_authorization_payload(
    *,
    denial_reason: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations/{id}/deny — ClinicalReviewer
    only. PRD §3.3: takes denial_reason and version."""
    payload: Dict[str, Any] = {
        "denial_reason": (
            denial_reason if denial_reason is not None
            else "Clinical criteria not satisfied per policy."
        ),
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def occ_payload(version: Optional[int] = None,
                **overrides: Any) -> Dict[str, Any]:
    """Body containing only ``version`` (PRD §2.6). Used by simple
    state-transition endpoints that take no other body field."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Claim — PRD §3.4
# ---------------------------------------------------------------------------
def create_claim_payload(
    *,
    member_id: str,
    drug_id: str,
    channel: str = "RETAIL_30",
    days_supply: Optional[int] = None,
    quantity: Optional[int] = None,
    prior_auth_id: Optional[str] = None,
    copay_card_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/claims — Prescriber or ClaimsAdjudicator.

    PRD §3.4 required: member_id, drug_id, channel, days_supply,
    quantity. Optional: prior_auth_id, copay_card_id.
    """
    if days_supply is None:
        if channel == "MAIL_ORDER_90":
            days_supply = TEST_DEFAULTS["CLAIM_DAYS_SUPPLY_MAIL"]
        elif channel == "SPECIALTY":
            days_supply = TEST_DEFAULTS["CLAIM_DAYS_SUPPLY_SPECIALTY"]
        else:
            days_supply = TEST_DEFAULTS["CLAIM_DAYS_SUPPLY_RETAIL"]

    payload: Dict[str, Any] = {
        "member_id": member_id,
        "drug_id": drug_id,
        "channel": channel,
        "days_supply": days_supply,
        "quantity": (
            quantity if quantity is not None
            else TEST_DEFAULTS["CLAIM_QUANTITY"]
        ),
    }
    if prior_auth_id is not None:
        payload["prior_auth_id"] = prior_auth_id
    if copay_card_id is not None:
        payload["copay_card_id"] = copay_card_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CopayCard — PRD §3.8
# ---------------------------------------------------------------------------
def create_copay_card_payload(
    *,
    member_id: str,
    drug_id: str,
    max_benefit_cents: Optional[int] = None,
    per_claim_cap_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/copay-cards — PBMAdmin only.

    PRD §3.8 required: member_id, drug_id, max_benefit_cents,
    per_claim_cap_cents (>= 0 and <= max_benefit_cents).
    """
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "drug_id": drug_id,
        "max_benefit_cents": (
            max_benefit_cents if max_benefit_cents is not None
            else TEST_DEFAULTS["COPAY_CARD_MAX_BENEFIT_CENTS"]
        ),
        "per_claim_cap_cents": (
            per_claim_cap_cents if per_claim_cap_cents is not None
            else TEST_DEFAULTS["COPAY_CARD_PER_CLAIM_CAP_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RebateAgreement — PRD §3.6
# ---------------------------------------------------------------------------
def create_rebate_agreement_payload(
    *,
    drug_id: str,
    manufacturer_name: Optional[str] = None,
    rebate_rate: Optional[float] = None,
    clawback_window_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /pbm/rebate-agreements — PBMAdmin only.

    PRD §3.6 required: drug_id, manufacturer_name, rebate_rate (0..1).
    Optional: clawback_window_days (defaults to 90 server-side).
    """
    payload: Dict[str, Any] = {
        "drug_id": drug_id,
        "manufacturer_name": (
            manufacturer_name if manufacturer_name is not None
            else f"Manufacturer {random_suffix(4)}"
        ),
        "rebate_rate": (
            rebate_rate if rebate_rate is not None
            else TEST_DEFAULTS["REBATE_RATE"]
        ),
    }
    if clawback_window_days is not None:
        payload["clawback_window_days"] = clawback_window_days
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# /_clock/advance — PRD §2.11 / §4
# ---------------------------------------------------------------------------
def clock_advance_payload(*, seconds: int,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance — PBMAdmin only. PRD §2.11: "advances that
    clock by an integer number of seconds." """
    payload: Dict[str, Any] = {"seconds": seconds}
    payload.update(overrides)
    return payload


__all__ = [
    "random_suffix",
    "random_ndc",
    "random_npi",
    "create_plan_payload",
    "patch_plan_payload",
    "create_drug_payload",
    "create_member_payload",
    "create_formulary_entry_payload",
    "patch_formulary_entry_payload",
    "create_prior_authorization_payload",
    "resubmit_prior_authorization_payload",
    "deny_prior_authorization_payload",
    "occ_payload",
    "create_claim_payload",
    "create_copay_card_payload",
    "create_rebate_agreement_payload",
    "clock_advance_payload",
]
