"""Request-payload factories.

Each factory returns a valid, complete payload for one write endpoint and accepts
keyword overrides so a test can perturb exactly one field.  Passing
``field=None`` removes the key entirely, which is how a test exercises an
omitted optional (or a missing required) field.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CATEGORY_MOS_TRAINING,
    CREDENTIAL_ACTIVE,
    DB_NPDB,
    DECISION_APPROVE,
    EVALUATOR_ACTIVE,
    EXAM_NATIONAL,
    MILITARY_NONE,
    PATHWAY_ENDORSEMENT,
    SEVERITY_ADVISORY,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``None`` drops the key from the payload."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Professions ──────────────────────────────────────

def profession_payload(**overrides: Any) -> Dict[str, Any]:
    """A fully specified profession registration."""
    return _merge(
        {
            "profession_code": "RN",
            "title": "Registered Nurse",
            "required_scope_elements": ["ASSESS", "TREAT", "PRESCRIBE", "SUPERVISE"],
            "critical_scope_elements": ["PRESCRIBE"],
            "required_practice_hours": 2000,
            "requirement_hours_total": 240.0,
            "exam_waiver_min_score": 70.00,
            "jurisprudence_exam_required": True,
            "universal_recognition_min_residency_months": 12,
            "standard_processing_days": 90,
            "base_fee_cents": 25000,
            "endorsement_fee_cents": 10000,
            "exam_fee_cents": 8000,
            "jurisprudence_fee_cents": 5000,
            "permit_fee_cents": 6000,
            "expedite_surcharge_pct": 0.15,
        },
        overrides,
    )


def registered_nurse_payload(**overrides: Any) -> Dict[str, Any]:
    """The Registered Nurse profession used as the default regulatory frame."""
    return profession_payload(**overrides)


def reciprocal_agreement_payload(**overrides: Any) -> Dict[str, Any]:
    """A compact between the profession in the path and a partner state."""
    return _merge(
        {
            "partner_state": "TX",
            "fee_waiver_pct": 0.50,
            "exam_waiver_allowed": False,
            "jurisprudence_waiver_allowed": False,
            "expires_on": "2027-12-31T00:00:00Z",
        },
        overrides,
    )


# ─── Applicants and their filings ─────────────────────

def applicant_payload(**overrides: Any) -> Dict[str, Any]:
    """Agency intake of one applicant."""
    return _merge(
        {
            "full_name": "Aurel Vasquez",
            "state_code": "TX",
            "residency_months": 24,
            "military_status": MILITARY_NONE,
        },
        overrides,
    )


def credential_payload(**overrides: Any) -> Dict[str, Any]:
    """An out-of-state credential filing, active and verified by default."""
    return _merge(
        {
            "issuing_state": "OK",
            "license_number": "OK-19001",
            "scope_elements": ["ASSESS", "TREAT", "SUPERVISE"],
            "practice_hours": 1200,
            "status": CREDENTIAL_ACTIVE,
            "verified_good_standing": True,
            "issued_at": "2020-05-01T00:00:00Z",
        },
        overrides,
    )


def training_record_payload(**overrides: Any) -> Dict[str, Any]:
    """A military training or field-experience record filing."""
    return _merge(
        {
            "category": CATEGORY_MOS_TRAINING,
            "documented_hours": 133,
            "source_document": "JST-8891",
            "verified": True,
        },
        overrides,
    )


def disciplinary_record_payload(applicant_id: str, **overrides: Any) -> Dict[str, Any]:
    """A national-database disciplinary finding posted against an applicant."""
    return _merge(
        {
            "applicant_id": applicant_id,
            "source_state": "OK",
            "source_database": DB_NPDB,
            "severity": SEVERITY_ADVISORY,
            "action_effective_at": "2025-06-01T00:00:00Z",
            "reported_at": "2026-06-01T00:00:00Z",
        },
        overrides,
    )


# ─── Applications ─────────────────────────────────────

def application_payload(
    applicant_id: str,
    profession_id: str,
    primary_credential_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Opening a DRAFT application on one of the three portability pathways."""
    return _merge(
        {
            "applicant_id": applicant_id,
            "profession_id": profession_id,
            "primary_credential_id": primary_credential_id,
            "pathway": PATHWAY_ENDORSEMENT,
            "expedited": False,
        },
        overrides,
    )


def payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """A payment recorded against an application's outstanding balance."""
    return _merge({"amount_cents": amount_cents}, overrides)


def exam_result_payload(
    passed: bool = True, exam_kind: str = EXAM_NATIONAL, **overrides: Any
) -> Dict[str, Any]:
    """A recorded national or jurisprudence examination result."""
    return _merge({"exam_kind": exam_kind, "passed": passed, "score": 88.00}, overrides)


def deficiency_payload(**overrides: Any) -> Dict[str, Any]:
    """A recorded deficiency with its reason code."""
    return _merge({"reason_code": "MISSING_TRANSCRIPT"}, overrides)


def decision_payload(decision: str = DECISION_APPROVE, **overrides: Any) -> Dict[str, Any]:
    """The board deputy's terminal decision."""
    return _merge({"decision": decision, "memo": "board reviewed"}, overrides)


# ─── Evaluations ──────────────────────────────────────

def evaluation_payload(application_id: str, credential_id: str, **overrides: Any) -> Dict[str, Any]:
    """Opening the substantial-equivalency evaluation for an application."""
    return _merge(
        {"application_id": application_id, "credential_id": credential_id}, overrides
    )


def scope_review_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """The analyst's scope-of-practice opinion (first parallel dimension)."""
    return _merge({"decision": decision, "note": "scope compared"}, overrides)


def discipline_finding_payload(
    finding: str, databases_checked: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """The assigned evaluator's national-database finding (second dimension)."""
    return _merge(
        {
            "finding": finding,
            "databases_checked": list(databases_checked) if databases_checked else [DB_NPDB],
        },
        overrides,
    )


# ─── Credit awards ────────────────────────────────────

def credit_award_payload(application_id: str, training_record_id: str, **overrides: Any) -> Dict[str, Any]:
    """Converting one verified training record into credit against an application."""
    return _merge(
        {"application_id": application_id, "training_record_id": training_record_id}, overrides
    )


# ─── Permits ──────────────────────────────────────────

def temporary_permit_payload(
    application_id: str, effective_at: str, expected_application_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Issuing a temporary practice permit, with the mandatory stale-view guard."""
    return _merge(
        {
            "application_id": application_id,
            "effective_at": effective_at,
            "expected_application_version": expected_application_version,
        },
        overrides,
    )


def permit_revocation_payload(reason_code: str = "APPLICANT_WITHDREW", **overrides: Any) -> Dict[str, Any]:
    """A board deputy's direct revocation of an ACTIVE permit."""
    return _merge({"reason_code": reason_code}, overrides)


# ─── Evaluators and assignments ───────────────────────

def evaluator_payload(profession_code: str = "RN", **overrides: Any) -> Dict[str, Any]:
    """Registering a contract evaluator for national-database review."""
    return _merge(
        {
            "full_name": "Dana Whitfield",
            "profession_code": profession_code,
            "status": EVALUATOR_ACTIVE,
            "max_concurrent_reviews": 2,
        },
        overrides,
    )


def review_assignment_payload(
    evaluator_id: str,
    application_id: str,
    window_start_at: str,
    window_end_at: str,
    expected_evaluator_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Booking an evaluator's closed review window, with the stale-view guard."""
    return _merge(
        {
            "evaluator_id": evaluator_id,
            "application_id": application_id,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "expected_evaluator_version": expected_evaluator_version,
        },
        overrides,
    )
