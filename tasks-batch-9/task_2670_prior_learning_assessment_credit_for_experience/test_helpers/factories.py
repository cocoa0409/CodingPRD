"""Request-payload builders.

Each builder returns a plain dict carrying only the fields the PRD names for
that request, with valid defaults, and merges ``**overrides`` last so a test can
bend exactly one field. Money is always an ``int`` count of cents and every
basis-point figure is an ``int``; nothing here emits a numeric string.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import ALL_SOURCE_TYPES
from .types import (
    Alignment,
    ArtifactType,
    CourseLevel,
    PaymentMethod,
    SourceType,
)

Json = Dict[str, Any]

_counter = itertools.count(1)


def unique_suffix() -> int:
    """Monotonic per-process counter for codes that must be unique."""
    return next(_counter)


# --------------------------------------------------------------------------
# Programmes (PRD S3.1)
# --------------------------------------------------------------------------
def program_payload(
    program_code: Optional[str] = None,
    total_credits_required: int = 120,
    residency_min_credits: int = 30,
    pla_max_credits: int = 45,
    pla_max_pct_bp: int = 2500,
    pla_upper_division_max_credits: int = 12,
    allowed_source_types: Optional[List[str]] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "program_code": program_code or "PROG%04d" % unique_suffix(),
        "title": "Bachelor of Science",
        "total_credits_required": total_credits_required,
        "residency_min_credits": residency_min_credits,
        "pla_max_credits": pla_max_credits,
        "pla_max_pct_bp": pla_max_pct_bp,
        "pla_upper_division_max_credits": pla_upper_division_max_credits,
        "allowed_source_types": list(allowed_source_types or ALL_SOURCE_TYPES),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Courses and learning outcomes (PRD S3.1)
# --------------------------------------------------------------------------
def outcome_payload(outcome_code: str, weight_bp: int, **overrides: Any) -> Json:
    payload: Json = {
        "outcome_code": outcome_code,
        "description": "Outcome %s" % outcome_code,
        "weight_bp": weight_bp,
    }
    payload.update(overrides)
    return payload


def even_outcomes(count: int) -> List[Json]:
    """``count`` outcomes whose ``weight_bp`` values total exactly 10000."""
    base = 10000 // count
    weights = [base] * count
    weights[-1] += 10000 - sum(weights)
    return [outcome_payload("OC%d" % (i + 1), weights[i]) for i in range(count)]


def course_payload(
    course_code: Optional[str] = None,
    department_code: str = "CS",
    credits: int = 3,
    level: str = CourseLevel.LOWER,
    learning_outcomes: Optional[List[Json]] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "course_code": course_code or "CRS%04d" % unique_suffix(),
        "title": "Introductory Course",
        "department_code": department_code,
        "credits": credits,
        "level": level,
        "learning_outcomes": learning_outcomes if learning_outcomes is not None else even_outcomes(2),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Credential recommendations and articulation rules (PRD S3.2)
# --------------------------------------------------------------------------
def recommendation_payload(
    credential_code: Optional[str] = None,
    source_type: str = SourceType.CREDIT_BY_EXAM,
    recommended_credits: int = 3,
    recommended_level: str = CourseLevel.LOWER,
    effective_from: str = "2020-01-01T00:00:00Z",
    **overrides: Any,
) -> Json:
    payload: Json = {
        "source_type": source_type,
        "credential_code": credential_code or "CRED%04d" % unique_suffix(),
        "title": "National Credential",
        "issuing_body": "National Council",
        "recommended_credits": recommended_credits,
        "recommended_level": recommended_level,
        "effective_from": effective_from,
    }
    payload.update(overrides)
    return payload


def rule_payload(
    recommendation_id: str,
    course_id: str,
    awarded_credits: int = 3,
    effective_from: str = "2020-01-01T00:00:00Z",
    **overrides: Any,
) -> Json:
    payload: Json = {
        "recommendation_id": recommendation_id,
        "course_id": course_id,
        "awarded_credits": awarded_credits,
        "effective_from": effective_from,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Students and assessors (PRD S3.3, S3.6)
# --------------------------------------------------------------------------
def student_payload(program_id: str, student_number: Optional[str] = None, **overrides: Any) -> Json:
    payload: Json = {
        "student_number": student_number or "S%06d" % unique_suffix(),
        "full_name": "Test Student",
        "program_id": program_id,
    }
    payload.update(overrides)
    return payload


def assessor_payload(
    department_code: str = "CS",
    credential_rank: int = 3,
    employee_number: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "employee_number": employee_number or "E%06d" % unique_suffix(),
        "full_name": "Test Assessor",
        "department_code": department_code,
        "credential_rank": credential_rank,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Claims (PRD S3.3)
# --------------------------------------------------------------------------
def claim_payload(
    student_id: str,
    course_id: str,
    source_type: str = SourceType.PORTFOLIO,
    credits_requested: int = 3,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "student_id": student_id,
        "course_id": course_id,
        "source_type": source_type,
        "credits_requested": credits_requested,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Portfolios and artifacts (PRD S3.4)
# --------------------------------------------------------------------------
def portfolio_payload(claim_id: str, **overrides: Any) -> Json:
    payload: Json = {"claim_id": claim_id, "narrative": "Ten years of practice."}
    payload.update(overrides)
    return payload


def mapping(learning_outcome_id: str, alignment: str = Alignment.PRIMARY) -> Json:
    return {"learning_outcome_id": learning_outcome_id, "alignment": alignment}


def artifact_payload(
    outcome_mappings: List[Json],
    artifact_type: str = ArtifactType.WORK_PRODUCT,
    title: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "artifact_type": artifact_type,
        "title": title or "Artifact %d" % unique_suffix(),
        "evidence_uri": "https://evidence.example.edu/a%d" % unique_suffix(),
        "outcome_mappings": list(outcome_mappings),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Scoring (PRD S3.7)
# --------------------------------------------------------------------------
def rubric_score_payload(learning_outcome_id: str, points_awarded: int, **overrides: Any) -> Json:
    payload: Json = {
        "learning_outcome_id": learning_outcome_id,
        "points_awarded": points_awarded,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Money (PRD S3.10)
# --------------------------------------------------------------------------
def payment_payload(amount_cents: int, method: str = PaymentMethod.CARD, **overrides: Any) -> Json:
    payload: Json = {"amount_cents": int(amount_cents), "method": method}
    payload.update(overrides)
    return payload
