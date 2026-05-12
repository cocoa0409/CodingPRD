"""Payload factories — one per entity creation/transition.

Each factory emits the exact field schema declared by the PRD endpoint
input list (source: input fields only) and supplies sensible defaults.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, Optional


def unique_suffix() -> str:
    """Short unique suffix for fields that must be globally unique."""
    return uuid.uuid4().hex[:10]


def unique_doc_hash() -> str:
    """Generate a unique 64-char lowercase hex id_document_hash."""
    src = uuid.uuid4().hex + uuid.uuid4().hex
    return hashlib.sha256(src.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Community
# ---------------------------------------------------------------------------
def create_community_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()[:6]
    digits = "".join(c for c in suffix if c.isdigit())
    if len(digits) < 3:
        digits = (digits + "123456")[:6]
    digits = digits[:6]
    if len(digits) < 3:
        digits = digits + "000"
    payload: Dict[str, Any] = {
        "name": f"Community {suffix}",
        "code": f"CMTY-{digits}",
        "timezone": "UTC",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Household
# ---------------------------------------------------------------------------
def create_household_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()[:6]
    payload: Dict[str, Any] = {
        "address": f"Bldg A Unit {suffix}",
        "building_code": f"BLDG-A",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Resident
# ---------------------------------------------------------------------------
def create_resident_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": f"Resident {unique_suffix()[:6]}",
        "id_document_hash": unique_doc_hash(),
        "relation": "HEAD",
    }
    payload.update(overrides)
    return payload


def verify_resident_payload(decision: str = "APPROVE") -> Dict[str, Any]:
    return {"decision": decision}


def restrict_resident_payload(
    until: str, reason: str = "Restricted for testing",
) -> Dict[str, Any]:
    return {"until": until, "reason": reason}


# ---------------------------------------------------------------------------
# PointRule
# ---------------------------------------------------------------------------
def create_point_rule_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 input list: category, base_rate_per_kg, plus optional
    threshold/multiplier/peak/cap fields. Defaults from PRD §3.2."""
    payload: Dict[str, Any] = {
        "category": "RECYCLABLE",
        "base_rate_per_kg": 10.00,
        "bonus_consecutive_threshold_days": 7,
        "bonus_consecutive_multiplier": 1.20,
        "peak_period_start_hour": 7,
        "peak_period_end_hour": 9,
        "peak_period_bonus_flat": 5,
        "category_bonus_flat": 0,
        "daily_cap_points": 200,
    }
    payload.update(overrides)
    return payload


def activate_point_rule_payload(activated_at: str) -> Dict[str, Any]:
    return {"activated_at": activated_at}


# ---------------------------------------------------------------------------
# Disposal
# ---------------------------------------------------------------------------
def create_disposal_payload(
    resident_id: str, disposal_time: str, **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3 input list. Provide exactly one of weight_kg / volume_liters."""
    payload: Dict[str, Any] = {
        "resident_id": resident_id,
        "disposal_time": disposal_time,
        "location_code": "BIN-01",
        "declared_category": "RECYCLABLE",
        "actual_category": "RECYCLABLE",
        "scoring_method": "MANUAL",
        "accuracy_score": 1.000,
        "evidence_uri": f"https://evidence.example/{unique_suffix()}",
        "weight_kg": 2.000,
    }
    payload.update(overrides)
    return payload


def correct_disposal_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: optional actual_category and/or accuracy_score; required reason."""
    payload: Dict[str, Any] = {"reason": "Correction during audit"}
    payload.update(overrides)
    return payload


def void_disposal_payload(reason: str = "Voided during audit") -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# MallItem
# ---------------------------------------------------------------------------
def create_mall_item_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Item {unique_suffix()[:6]}",
        "cost_points": 50,
        "stock": 10,
        "channel": "STATION",
    }
    payload.update(overrides)
    return payload


def patch_mall_item_payload(**fields: Any) -> Dict[str, Any]:
    return dict(fields)


# ---------------------------------------------------------------------------
# RedemptionOrder
# ---------------------------------------------------------------------------
def submit_redemption_order_payload(
    mall_item_id: str, household_id: str, resident_id: str,
    quantity: int = 1,
) -> Dict[str, Any]:
    return {
        "mall_item_id": mall_item_id,
        "quantity": quantity,
        "household_id": household_id,
        "resident_id": resident_id,
    }


def reject_redemption_order_payload(
    reason: str = "Insufficient justification",
) -> Dict[str, Any]:
    return {"reason": reason}


def return_redemption_order_payload(
    reason: str = "Item arrived damaged",
) -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Violation
# ---------------------------------------------------------------------------
def create_violation_payload(
    resident_id: str, occurred_at: str, **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "resident_id": resident_id,
        "violation_type": "MIS_SORTING",
        "occurred_at": occurred_at,
        "evidence_uri": f"https://evidence.example/{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


def appeal_violation_payload(
    reason: str = "I dispute this finding",
) -> Dict[str, Any]:
    return {"reason": reason}


def decide_violation_payload(
    decision: str, reason: str = "Reviewer decision",
) -> Dict[str, Any]:
    return {"decision": decision, "reason": reason}


# ---------------------------------------------------------------------------
# RankingPeriod
# ---------------------------------------------------------------------------
def create_ranking_period_payload(
    granularity: str,
    dimension: str,
    window_start: str,
    window_end: str,
) -> Dict[str, Any]:
    return {
        "granularity": granularity,
        "dimension": dimension,
        "window_start": window_start,
        "window_end": window_end,
    }


# ---------------------------------------------------------------------------
# Clock advance
# ---------------------------------------------------------------------------
def advance_clock_payload(to_iso: str) -> Dict[str, Any]:
    return {"to": to_iso}


__all__ = [
    "unique_suffix",
    "unique_doc_hash",
    "create_community_payload",
    "create_household_payload",
    "create_resident_payload",
    "verify_resident_payload",
    "restrict_resident_payload",
    "create_point_rule_payload",
    "activate_point_rule_payload",
    "create_disposal_payload",
    "correct_disposal_payload",
    "void_disposal_payload",
    "create_mall_item_payload",
    "patch_mall_item_payload",
    "submit_redemption_order_payload",
    "reject_redemption_order_payload",
    "return_redemption_order_payload",
    "create_violation_payload",
    "appeal_violation_payload",
    "decide_violation_payload",
    "create_ranking_period_payload",
    "advance_clock_payload",
]
