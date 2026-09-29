"""Payload factories, one per creatable resource.

Every factory returns a valid minimal payload with all required fields present
and allows any field to be overridden by keyword.  Monetary fields are emitted
as JSON numbers (never strings), per PRD 2.8.
"""

from typing import Any, Dict, List, Optional

from .constants import ORG_CURRICULUM_VERSION


_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def affiliate_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /affiliates — PRD 3.1."""
    n = _next()
    payload: Dict[str, Any] = {
        "name": f"Test Affiliate {n}",
        "level": "DOUBLE_A",
        "market_city": "Testville",
        "meal_stipend_cents_per_day": 3000,
    }
    payload.update(overrides)
    return payload


def agreement_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /affiliates/{id}/agreements — PRD 3.2."""
    payload: Dict[str, Any] = {
        "term_start_date": "2026-01-01",
        "term_end_date": "2026-12-31",
        "facility_standard_tier": "TIER_1",
        "club_reimbursement_cap_cents": 900000,
        "minimum_active_players": 0,
    }
    payload.update(overrides)
    return payload


def facility_review_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /affiliates/{id}/facility-reviews — PRD 3.1."""
    payload: Dict[str, Any] = {
        "category": "CLUBHOUSE",
        "review_date": "2026-04-01",
        "score": 90,
    }
    payload.update(overrides)
    return payload


def staff_member_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /staff-members — PRD 3.4."""
    n = _next()
    payload: Dict[str, Any] = {
        "full_name": f"Coach Number {n}",
        "discipline": "PITCHING",
        "curriculum_version_certified": ORG_CURRICULUM_VERSION,
        "certification_expires_on": "2027-01-31",
    }
    payload.update(overrides)
    return payload


def staff_allocation_payload(
    staff_member_id: str,
    affiliate_id: str,
    expected_affiliate_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /staff-allocations — PRD 3.4 and PRD 2.7."""
    payload: Dict[str, Any] = {
        "staff_member_id": staff_member_id,
        "affiliate_id": affiliate_id,
        "staff_role": "PITCHING_COACH",
        "fte_pct": 50,
        "effective_start": "2026-04-01",
        "effective_end": "2026-09-01",
        "curriculum_version": ORG_CURRICULUM_VERSION,
        "expected_affiliate_version": expected_affiliate_version,
    }
    payload.update(overrides)
    return payload


def player_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /players — PRD 3.5."""
    n = _next()
    payload: Dict[str, Any] = {
        "full_name": f"Player Number {n}",
        "origin": "DOMESTIC_DRAFT",
        "signed_date": "2025-06-10",
    }
    payload.update(overrides)
    return payload


def medical_clearance_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /players/{id}/medical-clearances — PRD 3.5."""
    payload: Dict[str, Any] = {"clearance_type": "LEVEL_ASSIGNMENT"}
    payload.update(overrides)
    return payload


def clearance_issue_payload(**overrides: Any) -> Dict[str, Any]:
    """ISSUE action on a clearance — PRD 3.5."""
    payload: Dict[str, Any] = {
        "action": "ISSUE",
        "cleared_workload_ceiling_index": 25.00,
        "expires_on": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def assignment_payload(
    player_id: str,
    affiliate_id: str,
    expected_player_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /assignments — PRD 3.6 and PRD 2.7."""
    payload: Dict[str, Any] = {
        "player_id": player_id,
        "affiliate_id": affiliate_id,
        "assignment_type": "LEVEL",
        "movement_reason": "INITIAL",
        "effective_date": "2026-08-05",
        "end_date": "2026-09-30",
        "expected_player_version": expected_player_version,
    }
    payload.update(overrides)
    return payload


def development_plan_payload(
    curriculum_modules: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """POST /assignments/{id}/development-plans — PRD 3.7."""
    payload: Dict[str, Any] = {
        "target_level": "TRIPLE_A",
        "curriculum_version": ORG_CURRICULUM_VERSION,
        "curriculum_modules": list(curriculum_modules or ["MOD_MECHANICS", "MOD_GAMEPLAN"]),
    }
    payload.update(overrides)
    return payload


def workload_log_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /assignments/{id}/workload-logs — PRD 3.7."""
    payload: Dict[str, Any] = {"log_date": "2026-08-01"}
    payload.update(overrides)
    return payload


def signing_pool_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /signing-pools — PRD 3.9."""
    payload: Dict[str, Any] = {"season_year": 2026, "base_pool_cents": 5000000}
    payload.update(overrides)
    return payload


def international_signing_payload(
    pool_id: str,
    player_id: str,
    academy_affiliate_id: str,
    expected_pool_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /international-signings — PRD 3.9 and PRD 2.7."""
    payload: Dict[str, Any] = {
        "pool_id": pool_id,
        "player_id": player_id,
        "academy_affiliate_id": academy_affiliate_id,
        "bonus_cents": 500000,
        "expected_pool_version": expected_pool_version,
    }
    payload.update(overrides)
    return payload


def disposition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    """Generic disposition body: `action` plus any action-specific fields."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload
