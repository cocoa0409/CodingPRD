"""Request-payload builders with valid defaults and keyword overrides.

Each builder returns a plain dict that satisfies every required field of the
corresponding endpoint, so a test only has to name the one or two values it
actually cares about. Identifier-bearing fields that the contract requires to
be unique (``payer_tax_id``, ``npi``, ``external_member_id``) are sequenced by
a module-level counter so repeated calls inside one test never collide.
"""

import itertools
from typing import Any, Dict

_seq = itertools.count(1)


def next_sequence() -> int:
    """Monotonic counter used to keep uniqueness-constrained fields distinct."""
    return next(_seq)


def unique_tax_id() -> str:
    return "94-{:07d}".format(next_sequence())


def unique_npi() -> str:
    return "{:010d}".format(1000000000 + next_sequence())


def unique_member_id() -> str:
    return "M-{:06d}".format(next_sequence())


def unique_file_reference() -> str:
    return "PFR-{:06d}".format(next_sequence())


# ---------------------------------------------------------------------------
# DelegationAgreement
# ---------------------------------------------------------------------------
def agreement_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "payer_name": "Cascadia Benefit Plan",
        "payer_tax_id": unique_tax_id(),
        "delegation_scope": "FULL_RISK",
        "base_pmpm_cents": 20000,
        "reconciliation_method": "ROSTER_SNAPSHOT",
        "ibnr_method": "COMPLETION_FACTOR",
        "ibnr_completion_factor_bps": 8000,
        "target_claims_pmpm_cents": 15000,
        "professional_pool_share_bps": 6000,
        "institutional_pool_share_bps": 4000,
        "quality_withhold_bps": 700,
        "stop_loss_attachment_cents": 5000000,
        "reinsurance_recovery_bps": 9000,
        "max_panel_size": 5,
        "continuity_of_care_days": 90,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PhysicianMember
# ---------------------------------------------------------------------------
def physician_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "npi": unique_npi(),
        "full_name": "Rowan Adeyemi",
        "specialty": "PRIMARY_CARE",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Enrollee
# ---------------------------------------------------------------------------
def enrollee_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "external_member_id": unique_member_id(),
        "age_band": "ADULT",
        "benefit_tier": "HMO",
        "risk_score_bps": 10000,
        "coverage_start_date": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MemberAssignment
# ---------------------------------------------------------------------------
def assignment_payload(
    enrollee_id: str,
    physician_id: str,
    expected_enrollee_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enrollee_id": enrollee_id,
        "physician_id": physician_id,
        "effective_date": "2026-01-01T00:00:00Z",
        "assignment_source": "MANUAL",
        "expected_enrollee_version": expected_enrollee_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EnrollmentFile and its rows
# ---------------------------------------------------------------------------
def enrollment_file_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "coverage_month": "2026-07",
        "payer_file_reference": unique_file_reference(),
    }
    payload.update(overrides)
    return payload


def enrollment_row_payload(
    external_member_id: str, physician_npi: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "external_member_id": external_member_id,
        "physician_npi": physician_npi,
        "row_action": "ADD",
        "claimed_capitation_cents": 20000,
        "effective_date": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RiskPool
# ---------------------------------------------------------------------------
def risk_pool_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pool_type": "PROFESSIONAL",
        "pool_year_start": "2026-01-01T00:00:00Z",
        "pool_year_end": "2026-12-31T23:59:59Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DownstreamClaim
# ---------------------------------------------------------------------------
def claim_payload(
    agreement_id: str,
    enrollee_id: str,
    attributed_physician_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agreement_id": agreement_id,
        "enrollee_id": enrollee_id,
        "attributed_physician_id": attributed_physician_id,
        "pool_type": "PROFESSIONAL",
        "downstream_provider_name": "Willamette Surgical Partners",
        "billed_cents": 20000,
        "service_date": "2026-06-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# StopLossRecovery
# ---------------------------------------------------------------------------
def recovery_payload(pool_id: str, enrollee_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"pool_id": pool_id, "enrollee_id": enrollee_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# QualityScorecard
# ---------------------------------------------------------------------------
def scorecard_payload(
    physician_id: str, expected_physician_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "physician_id": physician_id,
        "measurement_period": "2026",
        "hedis_composite_bps": 9000,
        "access_score_bps": 8000,
        "patient_experience_bps": 7000,
        "attributed_member_months": 12,
        "expected_physician_version": expected_physician_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------
def state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload
