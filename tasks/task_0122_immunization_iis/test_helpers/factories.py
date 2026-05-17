"""Payload factories - one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed
and system-managed fields are intentionally omitted so the
implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits;
date_of_birth is an ISO 8601 calendar date YYYY-MM-DD.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp / date helpers.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits.

    PRD §2.4: "Both timestamps follow ISO 8601 UTC notation with three
    fractional-second digits."
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso(iso_ts: str) -> datetime:
    """Parse ISO 8601 UTC into a timezone-aware datetime."""
    s = iso_ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def iso_date(d: date) -> str:
    return d.isoformat()


def parse_anchor() -> datetime:
    return parse_iso(TEST_DEFAULTS["CLOCK_ANCHOR"])


def iso_anchor_offset(*, days: int = 0, hours: int = 0,
                      minutes: int = 0, seconds: int = 0,
                      milliseconds: int = 0) -> str:
    return iso_utc(
        parse_anchor() + timedelta(
            days=days, hours=hours, minutes=minutes,
            seconds=seconds, milliseconds=milliseconds,
        ),
    )


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_DIGITS = string.digits


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + _DIGITS, k=n))


def random_cvx() -> str:
    """PRD §3.2: 'a CDC cvx_code (1 to 6 characters, globally unique
    among ACTIVE products)'."""
    return random_suffix(6)


def random_lot_number() -> str:
    return "LOT-" + random_suffix(6)


def random_npi() -> str:
    """PRD §3.2: 'a 10-digit npi'."""
    return "".join(random.choices(_DIGITS, k=10))


def random_uuid_like() -> str:
    return "-".join([
        random_suffix(8),
        random_suffix(4),
        random_suffix(4),
        random_suffix(4),
        random_suffix(12),
    ]).lower()


# ---------------------------------------------------------------------------
# Patient - PRD §3.1.
# ---------------------------------------------------------------------------
def create_patient_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 input shape: first_name (1..80), last_name (1..80),
    date_of_birth (ISO 8601 date strictly in the past), sex_at_birth
    (FEMALE|MALE|UNKNOWN), state_resident (boolean, default true),
    guardian_contact_email, medical_exemption_on_file (default false)."""
    defaults: Dict[str, Any] = {
        "first_name": "Test",
        "last_name": "Patient-" + random_suffix(4),
        "date_of_birth": "2020-01-01",
        "sex_at_birth": "FEMALE",
        "state_resident": True,
        "guardian_contact_email": "guardian-" + random_suffix(4).lower()
                                  + "@example.test",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# VaccineProduct - PRD §3.2.
# ---------------------------------------------------------------------------
def create_vaccine_product_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 input: cvx_code (1..6, unique among ACTIVE), trade_name,
    antigens (array, min length 1), min_age_days (>= 0), max_age_days
    (nullable), route (IM|SC|ORAL|INTRANASAL), contraindication_flags
    (array, optional)."""
    defaults: Dict[str, Any] = {
        "cvx_code": random_cvx(),
        "trade_name": "TestVax-" + random_suffix(4),
        "antigens": ["MMR_MEASLES"],
        "min_age_days": 365,
        "max_age_days": 2555,
        "route": "IM",
        "contraindication_flags": [],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# VaccineLot - PRD §3.2.
# ---------------------------------------------------------------------------
def create_vaccine_lot_payload(vaccine_product_id: str,
                               provider_organization_id: str,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 input: vaccine_product_id, provider_organization_id,
    lot_number (unique within vaccine_product_id), expiration_date,
    doses_on_hand."""
    defaults: Dict[str, Any] = {
        "vaccine_product_id": vaccine_product_id,
        "provider_organization_id": provider_organization_id,
        "lot_number": random_lot_number(),
        "expiration_date": "2030-12-31",
        "doses_on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


def recall_payload(reason: str = "MANUFACTURER_DEFECT") -> Dict[str, Any]:
    """PRD §3.5: 'a reason of MANUFACTURER_DEFECT, CONTAMINATION, or
    EXPIRED.'"""
    return {"reason": reason}


# ---------------------------------------------------------------------------
# ProviderOrganization - PRD §3.2.
# ---------------------------------------------------------------------------
def create_provider_organization_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 input: name, npi (exactly 10 digits, unique),
    reporting_jurisdiction (IN_STATE|OUT_OF_STATE)."""
    defaults: Dict[str, Any] = {
        "name": "Test Clinic " + random_suffix(4),
        "npi": random_npi(),
        "reporting_jurisdiction": "IN_STATE",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AdministeredDose (schedule / administer / cancel / invalidate)
# - PRD §3.3.
# ---------------------------------------------------------------------------
def schedule_dose_payload(vaccine_product_id: str, lot_id: str,
                          provider_organization_id: str,
                          administering_clinician_id: str,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: scheduling a future dose by posting under the patient
    with a payload containing vaccine_product_id, lot_id,
    provider_organization_id, and administering_clinician_id."""
    defaults: Dict[str, Any] = {
        "vaccine_product_id": vaccine_product_id,
        "lot_id": lot_id,
        "provider_organization_id": provider_organization_id,
        "administering_clinician_id": administering_clinician_id,
    }
    defaults.update(overrides)
    return defaults


def administer_dose_payload(administered_at: str,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'The administer request carries only the
    administered_at instant.'"""
    defaults: Dict[str, Any] = {"administered_at": administered_at}
    defaults.update(overrides)
    return defaults


def invalidate_dose_payload(reason: str = "DATA_ERROR",
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3 invalidate: '... supplying the reason DATA_ERROR.'"""
    defaults: Dict[str, Any] = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AllergyRecord - PRD §3.4.
# ---------------------------------------------------------------------------
def create_allergy_payload(allergen_code: str = "EGG",
                           severity: str = "ANAPHYLAXIS",
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4 input: allergen_code (EGG|LATEX|NEOMYCIN|GELATIN|YEAST
    |OTHER) and severity (MILD|MODERATE|SEVERE|ANAPHYLAXIS)."""
    defaults: Dict[str, Any] = {
        "allergen_code": allergen_code,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AdverseEvent - PRD §3.9.
# ---------------------------------------------------------------------------
def create_adverse_event_payload(patient_id: str, dose_id: str,
                                 onset_at: str,
                                 symptom_codes: Optional[List[str]] = None,
                                 seriousness: str = "NON_SERIOUS",
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9 input: patient_id, dose_id, onset_at, symptom_codes
    (array of at least one MedDRA-like code), seriousness."""
    defaults: Dict[str, Any] = {
        "patient_id": patient_id,
        "dose_id": dose_id,
        "onset_at": onset_at,
        "symptom_codes": (symptom_codes if symptom_codes is not None
                          else ["PAIN_AT_INJECTION_SITE"]),
        "seriousness": seriousness,
    }
    defaults.update(overrides)
    return defaults


def conclude_review_payload(conclusion: str = "NOT_RELATED",
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9 conclude-review: 'a conclusion of either
    CAUSALLY_RELATED or NOT_RELATED.'"""
    defaults: Dict[str, Any] = {"conclusion": conclusion}
    defaults.update(overrides)
    return defaults


def submit_vaers_payload(elective: Optional[bool] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9 submit-vaers: optional 'elective' flag."""
    body: Dict[str, Any] = {}
    if elective is not None:
        body["elective"] = elective
    body.update(overrides)
    return body


def vaers_ack_payload(adverse_event_id: str, outcome: str = "ACK",
                      **overrides: Any) -> Dict[str, Any]:
    """PRD §2.10 / §4: 'accepting an adverse_event_id and an outcome.'"""
    defaults: Dict[str, Any] = {
        "adverse_event_id": adverse_event_id,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AntigenScheduleRule - PRD §3.7.
# ---------------------------------------------------------------------------
def create_antigen_schedule_rule_payload(
    antigen: str,
    dose_sequence_number: int,
    routine_min_age_days: int,
    routine_recommended_age_days: int,
    routine_max_age_days: int,
    catchup_min_interval_days: int,
    prerequisite_rule_id: Optional[str] = None,
    school_enrollment_required: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7 input: antigen, dose_sequence_number (>=1, unique with
    antigen), routine_min_age_days, routine_recommended_age_days,
    routine_max_age_days, catchup_min_interval_days,
    prerequisite_rule_id (null for first dose), school_enrollment_required."""
    defaults: Dict[str, Any] = {
        "antigen": antigen,
        "dose_sequence_number": dose_sequence_number,
        "routine_min_age_days": routine_min_age_days,
        "routine_recommended_age_days": routine_recommended_age_days,
        "routine_max_age_days": routine_max_age_days,
        "catchup_min_interval_days": catchup_min_interval_days,
        "prerequisite_rule_id": prerequisite_rule_id,
        "school_enrollment_required": school_enrollment_required,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# SchoolEnrollmentCertificate - PRD §3.8.
# ---------------------------------------------------------------------------
def create_certificate_payload(school_year: str = "2026-2027",
                               grade_level: str = "K",
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8 input: school_year (YYYY-YYYY with second year one
    greater than first) and grade_level (K|G1..G12)."""
    defaults: Dict[str, Any] = {
        "school_year": school_year,
        "grade_level": grade_level,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Clock - PRD §2.10 / §4.
# ---------------------------------------------------------------------------
def clock_advance_payload(to_timestamp: str) -> Dict[str, Any]:
    """PRD §4 / §2.10: 'advance the server's logical clock to a
    supplied to_timestamp.'"""
    return {"to_timestamp": to_timestamp}


# ---------------------------------------------------------------------------
# OCC payload helper - PRD §2.7.
# ---------------------------------------------------------------------------
def occ_payload(version: int) -> Dict[str, Any]:
    """PRD §2.7: 'Action endpoints (the various state-transition
    operations) and any update endpoint accept an optional version
    field in the request body.'"""
    return {"version": version}


__all__ = [
    "iso_utc",
    "parse_iso",
    "iso_date",
    "parse_anchor",
    "iso_anchor_offset",
    "random_suffix",
    "random_cvx",
    "random_lot_number",
    "random_npi",
    "random_uuid_like",
    "create_patient_payload",
    "create_vaccine_product_payload",
    "create_vaccine_lot_payload",
    "recall_payload",
    "create_provider_organization_payload",
    "schedule_dose_payload",
    "administer_dose_payload",
    "invalidate_dose_payload",
    "create_allergy_payload",
    "create_adverse_event_payload",
    "conclude_review_payload",
    "submit_vaers_payload",
    "vaers_ack_payload",
    "create_antigen_schedule_rule_payload",
    "create_certificate_payload",
    "clock_advance_payload",
    "occ_payload",
]
