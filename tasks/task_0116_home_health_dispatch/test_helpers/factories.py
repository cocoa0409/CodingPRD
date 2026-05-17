"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed and
system-managed fields are intentionally omitted so the implementation
cannot accidentally accept them as inputs.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Date helpers — PRD uses ISO 8601 calendar dates (YYYY-MM-DD).
# ---------------------------------------------------------------------------
def iso_date(d: date) -> str:
    """Render a Python date as a YYYY-MM-DD ISO 8601 calendar date."""
    return d.isoformat()


def parse_date(iso_str: str) -> date:
    """Parse a YYYY-MM-DD string into a Python date."""
    return date.fromisoformat(iso_str)


def date_offset(base: str, *, days: int) -> str:
    """Return base + days as YYYY-MM-DD."""
    return iso_date(parse_date(base) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_ALPHANUM_UPPER = string.ascii_uppercase + string.digits
_DIGITS = string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM_UPPER, k=n))


def random_medicare_id() -> str:
    """PRD §3.1: medicare_id is "unique across patients". No format is
    pinned beyond uniqueness."""
    return f"1{random.randint(10000000, 99999999)}A"


def random_zip() -> str:
    """A five-digit ZIP code. PRD §3.1 only requires "the five-digit ZIP
    code of the residence"."""
    return "".join(random.choices(_DIGITS, k=5))


# ---------------------------------------------------------------------------
# Patient — PRD §3.1 / §4
# ---------------------------------------------------------------------------
def create_patient_payload(
    *,
    full_name: Optional[str] = None,
    medicare_id: Optional[str] = None,
    home_zip: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients — IntakeCoordinator or PlatformAdmin.

    PRD §3.1: required input fields are full_name, medicare_id (unique),
    and home_zip (five-digit ZIP code of the residence).
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Patient {random_suffix(4)}"
        ),
        "medicare_id": (
            medicare_id if medicare_id is not None
            else random_medicare_id()
        ),
        "home_zip": (
            home_zip if home_zip is not None
            else TEST_DEFAULTS["DEFAULT_HOME_ZIP"]
        ),
    }
    payload.update(overrides)
    return payload


def patch_patient_payload(
    *,
    full_name: Optional[str] = None,
    home_zip: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /patients/{patientId} — IntakeCoordinator or PlatformAdmin.

    PRD §3.1: "If the patient's home_zip is later changed through a
    coordinator-driven update — which may also adjust the full_name —
    the server recomputes wage_index from the new ZIP."
    PRD §2.8: optional version field for optimistic concurrency control.
    """
    payload: Dict[str, Any] = {}
    if full_name is not None:
        payload["full_name"] = full_name
    if home_zip is not None:
        payload["home_zip"] = home_zip
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clinician — PRD §3.2 / §4
# ---------------------------------------------------------------------------
def create_clinician_payload(
    *,
    full_name: Optional[str] = None,
    discipline: str = "SN",
    license_expiration_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /clinicians — PlatformAdmin only.

    PRD §3.2: required input fields are full_name, discipline (one of
    SN, PT, OT, SLP, HHA), and license_expiration_date (YYYY-MM-DD).
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Clinician {random_suffix(4)}"
        ),
        "discipline": discipline,
        "license_expiration_date": (
            license_expiration_date if license_expiration_date is not None
            else TEST_DEFAULTS["FAR_FUTURE_LICENSE"]
        ),
    }
    payload.update(overrides)
    return payload


def patch_clinician_payload(
    *,
    status: Optional[str] = None,
    license_expiration_date: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /clinicians/{clinicianId} — PlatformAdmin.

    PRD §3.2: "Admins can amend the license_expiration_date or move a
    clinician between AVAILABLE and SUSPENDED after creation."
    PRD §2.8: optional version field for optimistic concurrency control.
    """
    payload: Dict[str, Any] = {}
    if status is not None:
        payload["status"] = status
    if license_expiration_date is not None:
        payload["license_expiration_date"] = license_expiration_date
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OASISAssessment — PRD §3.3 / §4
# ---------------------------------------------------------------------------
def create_oasis_payload(
    *,
    assessment_reason: str = "START_OF_CARE",
    assessment_date: Optional[str] = None,
    clinical_grouping: str = "MMTA_OTHER",
    functional_impairment_level: str = "MEDIUM",
    admission_source: str = "COMMUNITY",
    hha_companion_hours_ordered: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patientId}/oasis — IntakeCoordinator only.

    PRD §3.3: "The OASIS captures the clinical inputs PDGM needs:
    assessment_reason (one of START_OF_CARE, RECERTIFICATION, or
    RESUMPTION_OF_CARE), assessment_date as a YYYY-MM-DD ISO date,
    clinical_grouping (one of MMTA_OTHER, NEURO, WOUND, MS_REHAB,
    BEHAVIORAL, or COMPLEX), functional_impairment_level (LOW, MEDIUM,
    or HIGH), admission_source (COMMUNITY or INSTITUTIONAL), and
    hha_companion_hours_ordered."

    PRD §3.3: "If the coordinator does not supply
    hha_companion_hours_ordered, it defaults to 0".
    """
    payload: Dict[str, Any] = {
        "assessment_reason": assessment_reason,
        "assessment_date": (
            assessment_date if assessment_date is not None
            else TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
        ),
        "clinical_grouping": clinical_grouping,
        "functional_impairment_level": functional_impairment_level,
        "admission_source": admission_source,
    }
    if hha_companion_hours_ordered is not None:
        payload["hha_companion_hours_ordered"] = hha_companion_hours_ordered
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Episode — PRD §3.4 / §4
# ---------------------------------------------------------------------------
def create_episode_payload(
    *,
    source_oasis_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patientId}/episodes — IntakeCoordinator only.

    PRD §3.4: required input field is source_oasis_id, "referencing a
    source_oasis_id for an OASIS that is currently LOCKED."
    """
    payload: Dict[str, Any] = {"source_oasis_id": source_oasis_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Visit — PRD §3.5 / §4
# ---------------------------------------------------------------------------
def create_visit_payload(
    *,
    clinician_id: str,
    visit_type: str = "SN",
    visit_date: Optional[str] = None,
    start_minute: int = 480,
    end_minute: int = 540,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes/{episodeId}/visits — IntakeCoordinator only.

    PRD §3.5: required input fields are clinician_id, visit_type (one of
    SN, PT, OT, SLP, HHA), visit_date (YYYY-MM-DD ISO date), and the
    [start_minute, end_minute) half-open time window in which
    start_minute and end_minute are minute-of-day integers from 0
    through 1439 inclusive.
    """
    payload: Dict[str, Any] = {
        "clinician_id": clinician_id,
        "visit_type": visit_type,
        "visit_date": (
            visit_date if visit_date is not None
            else TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
        ),
        "start_minute": start_minute,
        "end_minute": end_minute,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Mileage — PRD §3.6 / §4
# ---------------------------------------------------------------------------
def create_mileage_payload(
    *,
    miles_driven: float = 10.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /visits/{visitId}/mileage — FieldClinician only.

    PRD §3.6: "The mileage payload carries a single field miles_driven
    representing the round-trip miles for that visit; it must be
    strictly greater than zero".
    """
    payload: Dict[str, Any] = {"miles_driven": miles_driven}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.7 / §4
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    target_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — PlatformAdmin only.

    PRD §2.7: "The current_date on the ClockState singleton is advanced
    monotonically through an admin-only test-driving capability that
    takes a target_date ISO date in the request body."
    """
    payload: Dict[str, Any] = {"target_date": target_date}
    payload.update(overrides)
    return payload


__all__ = [
    # date helpers
    "iso_date",
    "parse_date",
    "date_offset",
    # random
    "random_suffix",
    "random_medicare_id",
    "random_zip",
    # payloads
    "create_patient_payload",
    "patch_patient_payload",
    "create_clinician_payload",
    "patch_clinician_payload",
    "create_oasis_payload",
    "create_episode_payload",
    "create_visit_payload",
    "create_mileage_payload",
    "clock_advance_payload",
]
