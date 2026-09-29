"""Payload factories: valid-by-default request bodies with keyword overrides.

Every factory returns a dict that satisfies the contract's declared field
requirements, so a test that wants to probe one rule overrides only the field
that rule is about. Unique values (bar numbers, recognition numbers, cycle
labels, facility names, grant codes) come from a per-process counter so repeated
calls inside one test never collide on a uniqueness constraint.
"""

import itertools
from typing import Any, Dict, List, Optional

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def unique_suffix() -> str:
    """A short unique token usable inside any unique string field."""
    return "{0:04d}".format(_seq())


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def client_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Rosa Mena",
        "preferred_language_code": "es",
        "country_of_birth_code": "GT",
        "date_of_birth": "1990-04-11",
        "household_size": 3,
        "annual_household_income_cents": 2000000,
    }
    payload.update(overrides)
    return payload


def a_number(seed: Optional[int] = None) -> str:
    """A well-formed alien registration number (``^A[0-9]{9}$``)."""
    value = _seq() if seed is None else seed
    return "A{0:09d}".format(value)


# ---------------------------------------------------------------------------
# ProgramCapacityCycle
# ---------------------------------------------------------------------------


def cycle_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_label": "FY26-H2-{0}".format(unique_suffix()),
        "period_start_date": "2026-07-01",
        "period_end_date": "2026-12-31",
        "total_case_slots": 10,
        "reserved_detained_slots": 2,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DetentionFacility
# ---------------------------------------------------------------------------


def facility_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "EL-PASO-SPC-{0}".format(unique_suffix()),
        "jurisdiction_code": "TX-ELP",
        "visit_lead_time_hours": 48,
        "max_daily_visit_slots": 4,
        "expedited_filing_days": 21,
        "access_credential_required": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OrganizationRecognition
# ---------------------------------------------------------------------------


def recognition_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recognition_number": "REC-2026-{0}".format(unique_suffix()),
        "effective_date": "2026-01-01",
        "expiry_date": "2029-01-01",
        "authorized_forums": [
            "USCIS",
            "EOIR_IMMIGRATION_COURT",
            "BIA",
            "ASYLUM_OFFICE",
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Representative
# ---------------------------------------------------------------------------


def staff_attorney_payload(**overrides: Any) -> Dict[str, Any]:
    """STAFF_ATTORNEY: bar_number is required for this type and only this type."""
    payload: Dict[str, Any] = {
        "full_name": "Ada Ortiz",
        "rep_type": "STAFF_ATTORNEY",
        "languages": ["en", "es"],
        "max_case_load": 25,
        "max_supervisees": 10,
        "weekly_capacity_hours": 40,
        "bar_number": "BAR-{0}".format(unique_suffix()),
    }
    payload.update(overrides)
    return payload


def accredited_rep_payload(**overrides: Any) -> Dict[str, Any]:
    """ACCREDITED_REP: bar_number must be null for every non-attorney type."""
    payload: Dict[str, Any] = {
        "full_name": "Nadia Rey",
        "rep_type": "ACCREDITED_REP",
        "languages": ["en", "es"],
        "max_case_load": 25,
        "max_supervisees": 10,
        "weekly_capacity_hours": 40,
    }
    payload.update(overrides)
    return payload


def volunteer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Omar Vale",
        "rep_type": "PRO_BONO_VOLUNTEER",
        "languages": ["en"],
        "max_case_load": 5,
        "max_supervisees": 0,
        "weekly_capacity_hours": 8,
    }
    payload.update(overrides)
    return payload


def law_graduate_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Lee Park",
        "rep_type": "LAW_GRADUATE",
        "languages": ["en"],
        "max_case_load": 10,
        "max_supervisees": 0,
        "weekly_capacity_hours": 20,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Accreditation
# ---------------------------------------------------------------------------


def accreditation_payload(
    representative_id: str,
    recognition_id: str,
    accreditation_type: str = "FULL",
    requested_forums: Optional[List[str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "representative_id": representative_id,
        "recognition_id": recognition_id,
        "accreditation_type": accreditation_type,
        "requested_forums": (
            list(requested_forums)
            if requested_forums is not None
            else ["USCIS", "EOIR_IMMIGRATION_COURT", "BIA", "ASYLUM_OFFICE"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IntakeScreening
# ---------------------------------------------------------------------------


def intake_payload(
    client_id: str, cycle_id: str, case_type: str = "U_VISA", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "cycle_id": cycle_id,
        "case_type": case_type,
        "detained": False,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CaseAssignment
# ---------------------------------------------------------------------------


def assignment_payload(
    matter_id: str,
    representative_id: str,
    expected_matter_version: int,
    role_on_case: str = "LEAD",
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "matter_id": matter_id,
        "representative_id": representative_id,
        "role_on_case": role_on_case,
        "expected_matter_version": expected_matter_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------


def evidence_payload(
    matter_id: str,
    tier: str = "REQUIRED",
    weight_points: int = 5,
    item_type: str = "IDENTITY_DOCUMENT",
    **overrides: Any
) -> Dict[str, Any]:
    """weight_points must sit between 1 and 10 inclusive."""
    payload: Dict[str, Any] = {
        "matter_id": matter_id,
        "item_type": item_type,
        "tier": tier,
        "weight_points": weight_points,
        "source_language_code": "en",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------


def declaration_payload(
    matter_id: str,
    preparer_assignment_id: str,
    language_code: str = "es",
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "matter_id": matter_id,
        "preparer_assignment_id": preparer_assignment_id,
        "language_code": language_code,
        "word_count": 950,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InterpretationSession
# ---------------------------------------------------------------------------


def session_payload(
    matter_id: str,
    language_code: str = "es",
    purpose: str = "DECLARATION_READBACK",
    interpreter_source: str = "CONTRACT",
    scheduled_start_utc: str = "2026-08-03T09:00:00.000Z",
    scheduled_end_utc: str = "2026-08-03T10:00:00.000Z",
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "matter_id": matter_id,
        "language_code": language_code,
        "interpreter_source": interpreter_source,
        "purpose": purpose,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CalendarEvent
# ---------------------------------------------------------------------------


def event_payload(
    matter_id: str,
    event_type: str = "BIOMETRICS",
    starts_at_utc: str = "2026-08-08T14:00:00.000Z",
    ends_at_utc: str = "2026-08-08T15:00:00.000Z",
    location_code: str = "ELPASC",
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "matter_id": matter_id,
        "event_type": event_type,
        "starts_at_utc": starts_at_utc,
        "ends_at_utc": ends_at_utc,
        "location_code": location_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InformedDecision
# ---------------------------------------------------------------------------


def informed_decision_payload(
    matter_id: str,
    counseled_by_assignment_id: str,
    expected_matter_version: int,
    decision_type: str = "FILE_AFFIRMATIVE",
    counseling_language_code: str = "es",
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "matter_id": matter_id,
        "counseled_by_assignment_id": counseled_by_assignment_id,
        "decision_type": decision_type,
        "risks_disclosed": ["REMOVAL_RISK"],
        "alternatives_disclosed": ["DO_NOTHING"],
        "counseling_language_code": counseling_language_code,
        "expected_matter_version": expected_matter_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# GrantReport
# ---------------------------------------------------------------------------


def grant_report_payload(
    cycle_id: str,
    disclosure_level: str = "DEIDENTIFIED_CASE_LEVEL",
    period_start_date: str = "2026-09-01",
    period_end_date: str = "2026-09-30",
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "grant_code": "EOIRLSP{0}".format(unique_suffix()),
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "disclosure_level": disclosure_level,
    }
    payload.update(overrides)
    return payload
