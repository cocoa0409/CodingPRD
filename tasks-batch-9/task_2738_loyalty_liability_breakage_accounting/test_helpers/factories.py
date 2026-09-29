"""
Request-body builders, one per creatable resource.

Each builder returns a valid payload with every required field filled from the
reference configuration, and accepts keyword overrides so a test can move exactly
the one value it is probing. Passing ``None`` for a field removes it, which is how
a test omits an optional input or drops a required one on purpose.
"""

import itertools
from typing import Any, Dict, Optional

from test_helpers.constants import (
    BREAKAGE_METHOD_COHORT_WEIGHTED,
    CHANGE_EXPIRY_DAYS,
    COHORT_C1_CODE,
    COHORT_C1_ENROLLMENT_END,
    COHORT_C1_ENROLLMENT_START,
    COHORT_C1_OBSERVED_RATE_BP,
    COHORT_C1_SAMPLE_SIZE,
    CURRENCY_USD,
    DEFAULT_ESCHEAT_DISCLOSURE_THRESHOLD_CENTS,
    DEFAULT_HISTORICAL_REDEMPTION_RATE_BP,
    DEFAULT_ISSUANCE_RATE_MILLICENTS,
    DEFAULT_MIN_DORMANCY_DAYS,
    DEFAULT_MIN_INVOICE_CENTS,
    DEFAULT_PER_ISSUANCE_POINT_CAP,
    DEFAULT_POINT_EXPIRY_DAYS,
    DEFAULT_PROMO_MULTIPLIER_CAP_BP,
    DEFAULT_REDEMPTION_RATE_MILLICENTS,
    DEFAULT_SETTLEMENT_LAG_DAYS,
    DEFAULT_SSP_MILLICENTS_PER_POINT,
    PARTNER_PG_CODE,
    PARTNER_WINDOW_END,
    PARTNER_WINDOW_START,
    PERIOD_AUG_CODE,
    PERIOD_AUG_END,
    PERIOD_AUG_START,
    REDEMPTION_RATE_CEILING_BP,
    REDEMPTION_RATE_FLOOR_BP,
    REDEMPTION_TYPE_CATALOG,
    RELATIONSHIP_THIRD_PARTY,
    STATE_TX,
    TIER_BASE,
    TIER_MULTIPLIER_BP,
)

# Monotonic counters so repeated builder calls never collide on a unique code.
_counters: Dict[str, "itertools.count[int]"] = {}


def _next(kind: str) -> int:
    """The next number in an independent sequence, per kind of code."""
    if kind not in _counters:
        _counters[kind] = itertools.count(1)
    return next(_counters[kind])


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge overrides into a payload, treating an explicit None as "remove this
    field" so a test can omit an input entirely.
    """
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── LoyaltyProgram ──────────────────────────────────────────────────────────
def program_payload(**overrides: Any) -> Dict[str, Any]:
    """A complete, valid programme configuration."""
    payload: Dict[str, Any] = {
        "name": f"Skyline Rewards {_next('program')}",
        "currency_code": CURRENCY_USD,
        "ssp_millicents_per_point": DEFAULT_SSP_MILLICENTS_PER_POINT,
        "point_expiry_days": DEFAULT_POINT_EXPIRY_DAYS,
        "per_issuance_point_cap": DEFAULT_PER_ISSUANCE_POINT_CAP,
        "tier_multiplier_bp": dict(TIER_MULTIPLIER_BP),
        "promo_multiplier_cap_bp": DEFAULT_PROMO_MULTIPLIER_CAP_BP,
        "breakage_method": BREAKAGE_METHOD_COHORT_WEIGHTED,
        "historical_redemption_rate_bp": DEFAULT_HISTORICAL_REDEMPTION_RATE_BP,
        "escheat_disclosure_threshold_cents": DEFAULT_ESCHEAT_DISCLOSURE_THRESHOLD_CENTS,
    }
    return _apply(payload, overrides)


def minimal_program_payload(**overrides: Any) -> Dict[str, Any]:
    """Only the inputs the contract requires, so the defaults can be observed."""
    payload: Dict[str, Any] = {
        "name": f"Bare Rewards {_next('program')}",
        "ssp_millicents_per_point": DEFAULT_SSP_MILLICENTS_PER_POINT,
        "point_expiry_days": DEFAULT_POINT_EXPIRY_DAYS,
        "per_issuance_point_cap": DEFAULT_PER_ISSUANCE_POINT_CAP,
        "tier_multiplier_bp": dict(TIER_MULTIPLIER_BP),
        "historical_redemption_rate_bp": DEFAULT_HISTORICAL_REDEMPTION_RATE_BP,
    }
    return _apply(payload, overrides)


# ─── StateExpiryRule ─────────────────────────────────────────────────────────
def state_expiry_rule_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A state rule that permits expiry and requires escheatment."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "state_code": STATE_TX,
        "expiry_permitted": True,
        "min_dormancy_days": DEFAULT_MIN_DORMANCY_DAYS,
        "escheatment_required": True,
        "escheat_rate_bp": 6000,
    }
    return _apply(payload, overrides)


# ─── Cohort ──────────────────────────────────────────────────────────────────
def cohort_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """An enrolment vintage with an observed redemption rate."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "cohort_code": f"{COHORT_C1_CODE}-{_next('cohort')}",
        "enrollment_start_date": COHORT_C1_ENROLLMENT_START,
        "enrollment_end_date": COHORT_C1_ENROLLMENT_END,
        "observed_redemption_rate_bp": COHORT_C1_OBSERVED_RATE_BP,
        "sample_size": COHORT_C1_SAMPLE_SIZE,
    }
    return _apply(payload, overrides)


# ─── Member ──────────────────────────────────────────────────────────────────
def member_payload(program_id: str, cohort_id: str, **overrides: Any) -> Dict[str, Any]:
    """A member of one programme and one enrolment vintage."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "cohort_id": cohort_id,
        "external_member_ref": f"EXT-{_next('member'):05d}",
        "state_code": STATE_TX,
        "tier": TIER_BASE,
    }
    return _apply(payload, overrides)


# ─── AccountingPeriod ────────────────────────────────────────────────────────
def period_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A half-open monthly window, inclusive of start_at and exclusive of end_at."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "period_code": PERIOD_AUG_CODE,
        "start_at": PERIOD_AUG_START,
        "end_at": PERIOD_AUG_END,
    }
    return _apply(payload, overrides)


# ─── PartnerAgreement ────────────────────────────────────────────────────────
def agreement_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A third-party agreement over a closed effective window."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "partner_code": f"{PARTNER_PG_CODE}{_next('partner')}",
        "relationship_type": RELATIONSHIP_THIRD_PARTY,
        "issuance_rate_millicents_per_point": DEFAULT_ISSUANCE_RATE_MILLICENTS,
        "redemption_rate_millicents_per_point": DEFAULT_REDEMPTION_RATE_MILLICENTS,
        "settlement_lag_days": DEFAULT_SETTLEMENT_LAG_DAYS,
        "net_settlement_enabled": False,
        "min_invoice_cents": DEFAULT_MIN_INVOICE_CENTS,
        "effective_start_date": PARTNER_WINDOW_START,
        "effective_end_date": PARTNER_WINDOW_END,
    }
    return _apply(payload, overrides)


def minimal_agreement_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Only the required inputs, so the agreement's own defaults can be observed."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "partner_code": f"{PARTNER_PG_CODE}{_next('partner')}",
        "relationship_type": RELATIONSHIP_THIRD_PARTY,
        "issuance_rate_millicents_per_point": DEFAULT_ISSUANCE_RATE_MILLICENTS,
        "redemption_rate_millicents_per_point": DEFAULT_REDEMPTION_RATE_MILLICENTS,
        "effective_start_date": PARTNER_WINDOW_START,
        "effective_end_date": PARTNER_WINDOW_END,
    }
    return _apply(payload, overrides)


# ─── PointLot ────────────────────────────────────────────────────────────────
def point_lot_payload(
    member_id: str, period_id: str, base_points: int = 1000, **overrides: Any
) -> Dict[str, Any]:
    """An issuance of base points to one member inside one period."""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "period_id": period_id,
        "base_points": base_points,
    }
    return _apply(payload, overrides)


# ─── RedemptionEvent ─────────────────────────────────────────────────────────
def redemption_payload(
    member_id: str, period_id: str, points_requested: int = 500, **overrides: Any
) -> Dict[str, Any]:
    """A catalogue redemption request against one member's balance."""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "period_id": period_id,
        "points_requested": points_requested,
        "redemption_type": REDEMPTION_TYPE_CATALOG,
    }
    return _apply(payload, overrides)


# ─── BreakageEstimate ────────────────────────────────────────────────────────
def estimate_payload(
    period_id: str,
    memo_narrative: str = "Cohort-weighted measurement supporting the period close.",
    **overrides: Any,
) -> Dict[str, Any]:
    """
    An estimate request with a sensitivity band wide enough to straddle any
    measurable rate, so a test that is not probing the band never trips it.
    """
    payload: Dict[str, Any] = {
        "period_id": period_id,
        "memo_narrative": memo_narrative,
        "sensitivity_low_bp": REDEMPTION_RATE_FLOOR_BP,
        "sensitivity_high_bp": REDEMPTION_RATE_CEILING_BP,
    }
    return _apply(payload, overrides)


# ─── SettlementStatement ─────────────────────────────────────────────────────
def statement_payload(
    partner_agreement_id: str,
    period_id: str,
    expected_partner_agreement_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A statement request carrying the agreement version the caller last read."""
    payload: Dict[str, Any] = {
        "partner_agreement_id": partner_agreement_id,
        "period_id": period_id,
        "expected_partner_agreement_version": expected_partner_agreement_version,
    }
    return _apply(payload, overrides)


# ─── ProgramChangeOrder ──────────────────────────────────────────────────────
def change_order_payload(
    program_id: str,
    effective_at: str,
    change_type: str = CHANGE_EXPIRY_DAYS,
    behavior_elasticity_bp: int = 500,
    new_point_expiry_days: Optional[int] = 365,
    **overrides: Any,
) -> Dict[str, Any]:
    """A modelled programme change, by default a shortening of the expiry horizon."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "change_type": change_type,
        "behavior_elasticity_bp": behavior_elasticity_bp,
        "effective_at": effective_at,
    }
    if new_point_expiry_days is not None:
        payload["new_point_expiry_days"] = new_point_expiry_days
    return _apply(payload, overrides)


# ─── Action bodies ───────────────────────────────────────────────────────────
def approval_payload(expected_program_version: int, **overrides: Any) -> Dict[str, Any]:
    """The body an estimate approval carries."""
    return _apply({"expected_program_version": expected_program_version}, overrides)


def rejection_payload(reason: str = "Sample size unsupported by the memorandum.") -> Dict[str, Any]:
    return {"rejection_reason": reason}


def reversal_payload(reason: str = "Fulfilment cancelled at the member's request.") -> Dict[str, Any]:
    return {"reversal_reason": reason}


def dispute_payload(reason: str = "Partner-issued point count disagrees with our own.") -> Dict[str, Any]:
    return {"dispute_reason": reason}


def resolution_payload(note: str = "Reconciled against the partner's own journal.") -> Dict[str, Any]:
    return {"resolution_note": note}


def write_off_payload(reason: str = "Partner insolvent; balance uncollectable.") -> Dict[str, Any]:
    return {"write_off_reason": reason}
