"""Payload factories — one per entity, input fields only.

Factory defaults are deterministic per test process via counters so that
uniqueness-constrained fields (school_code) never collide within a test, and
aliases stay distinguishable in debugging output.
"""
import itertools

from .constants import SCREENING_FACTOR_KEYS

_school_counter = itertools.count(1)
_alias_counter = itertools.count(1)


def next_school_code() -> str:
    return f"SCH{next(_school_counter):05d}"


def next_subject_alias() -> str:
    return f"STU-{next(_alias_counter):05d}"


def create_school_payload(**overrides) -> dict:
    defaults = {
        "name": "Test School",
        "school_code": next_school_code(),
        "enrollment_count": 500,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(school_id: str, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "subject_alias": next_subject_alias(),
        "reporter_channel": "TIP_LINE",
        "summary": "reported concern under assessment",
    }
    defaults.update(overrides)
    return defaults


def triage_payload(**overrides) -> dict:
    defaults = {"triage_priority": "ROUTINE", "triage_notes": "triage notes"}
    defaults.update(overrides)
    return defaults


def screening_payload(true_count: int = 3, **overrides) -> dict:
    """Six-factor screening body with exactly `true_count` factors true.

    The first `true_count` keys of the screening instrument are set true and
    the rest false; overrides can flip individual factors afterwards.
    """
    payload = {name: (i < true_count) for i, name in enumerate(SCREENING_FACTOR_KEYS)}
    payload.update(overrides)
    return payload


def moderate_score_factors() -> list:
    """Factor set scoring 30 (MODERATE) under the standard variant."""
    return [
        {"factor_code": "GRIEVANCE_HISTORY", "severity": 2},
        {"factor_code": "PEER_REPORTS", "severity": 2},
    ]


def create_assessment_payload(case_id: str, variant: str = "STANDARD",
                              factors=None, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "variant": variant,
        "factors": factors if factors is not None else moderate_score_factors(),
    }
    defaults.update(overrides)
    return defaults


def update_assessment_payload(**overrides) -> dict:
    return dict(overrides)


def create_interview_payload(case_id: str, interviewee_type: str = "WITNESS",
                             starts_at: str = "2026-08-05T10:00:00Z",
                             ends_at: str = "2026-08-05T11:00:00Z",
                             **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "interviewee_type": interviewee_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def complete_interview_payload(findings_score: int = 5,
                               summary: str = "interview findings", **overrides) -> dict:
    defaults = {"findings_score": findings_score, "summary": summary}
    defaults.update(overrides)
    return defaults


def create_plan_payload(case_id: str, cadence_mode: str = "FROM_COMPLETION",
                        cadence_days=None, conditions=None, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "cadence_mode": cadence_mode,
        "conditions": conditions if conditions is not None else ["counselor check-in"],
    }
    if cadence_days is not None:
        defaults["cadence_days"] = cadence_days
    defaults.update(overrides)
    return defaults


def create_referral_payload(case_id: str, referral_type: str = "MENTAL_HEALTH",
                            agency_name: str = "County MH",
                            urgency: str = "ROUTINE", **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "referral_type": referral_type,
        "agency_name": agency_name,
        "urgency": urgency,
    }
    defaults.update(overrides)
    return defaults


def create_checkin_payload(case_id: str, due_date: str, **overrides) -> dict:
    defaults = {"case_id": case_id, "due_date": due_date}
    defaults.update(overrides)
    return defaults


def complete_checkin_payload(outcome: str = "ON_TRACK",
                             notes: str = "check-in notes", **overrides) -> dict:
    defaults = {"outcome": outcome, "notes": notes}
    defaults.update(overrides)
    return defaults


def create_reentry_plan_payload(case_id: str, conditions=None, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "conditions": conditions if conditions is not None else ["counseling intake completed"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(doc_type: str = "INTAKE_NOTE",
                            body: str = "case note body", **overrides) -> dict:
    defaults = {"doc_type": doc_type, "body": body}
    defaults.update(overrides)
    return defaults
