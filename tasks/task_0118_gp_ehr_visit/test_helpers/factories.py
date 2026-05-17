"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed and
system-managed fields are intentionally omitted so the implementation
cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC strings with three fractional
digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 ISO 8601 UTC, three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a timezone-aware datetime.

    Accepts both Z-suffixed and offset-tagged strings, with or without
    fractional seconds.
    """
    s = iso_ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def iso_date(d: date) -> str:
    """ISO 8601 calendar date (YYYY-MM-DD)."""
    return d.isoformat()


def parse_anchor() -> datetime:
    """Convenience: the clock anchor as a datetime."""
    return parse_iso(TEST_DEFAULTS["CLOCK_ANCHOR"])


def iso_anchor_offset(*, days: int = 0, hours: int = 0,
                      minutes: int = 0, seconds: int = 0) -> str:
    """ISO 8601 UTC, offset from the clock anchor by the supplied
    deltas."""
    return iso_utc(
        parse_anchor() + timedelta(
            days=days, hours=hours, minutes=minutes, seconds=seconds,
        ),
    )


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_DIGITS = string.digits


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + _DIGITS, k=n))


def random_mrn() -> str:
    """PRD §3.1: 'the pattern of the three letters MRN followed by
    exactly eight digits.' Regex: ^MRN[0-9]{8}$."""
    return "MRN" + "".join(random.choices(_DIGITS, k=8))


def random_npi() -> str:
    """PRD §3.2: 'the 10-digit npi (matching exactly ten digits).'"""
    return "".join(random.choices(_DIGITS, k=10))


def random_dea_number() -> str:
    """A DEA registration number. PRD §3.2 does not fix the format
    beyond 'non-null'; we use a clearly-formed string."""
    return "B" + "".join(random.choices(string.ascii_uppercase, k=1)) + \
        "".join(random.choices(_DIGITS, k=7))


def random_cpt_code() -> str:
    """PRD §3.3: 'a five-digit string matching the CPT-4 pattern'.
    Regex: ^[0-9]{5}$. We avoid the special TSC/CCS codes so generic
    random codes do not accidentally satisfy HEDIS numerators."""
    while True:
        code = "".join(random.choices(_DIGITS, k=5))
        if code not in {"99406", "99407", "88141", "88142"}:
            return code


def random_rxnorm_code() -> str:
    """An RxNorm identifier; PRD does not fix the format."""
    return "".join(random.choices(_DIGITS, k=6))


def random_otp() -> str:
    """PRD §3.4: 'a six-digit OTP string.'"""
    return "".join(random.choices(_DIGITS, k=6))


# ---------------------------------------------------------------------------
# Patient — PRD §3.1.
# ---------------------------------------------------------------------------
def create_patient_payload(
    *,
    mrn: Optional[str] = None,
    first_name: str = "Test",
    last_name: str = "Patient",
    date_of_birth: str = "1986-01-15",
    sex_at_birth: str = "MALE",
    portal_enabled: Optional[bool] = None,
    smoking_status: Optional[str] = None,
    chronic_conditions: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients — Receptionist or ClinicAdmin.

    PRD §3.1: required input fields are mrn, first_name, last_name,
    date_of_birth, sex_at_birth. portal_enabled, smoking_status, and
    chronic_conditions are optional with documented defaults.
    """
    payload: Dict[str, Any] = {
        "mrn": mrn if mrn is not None else random_mrn(),
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": date_of_birth,
        "sex_at_birth": sex_at_birth,
    }
    if portal_enabled is not None:
        payload["portal_enabled"] = portal_enabled
    if smoking_status is not None:
        payload["smoking_status"] = smoking_status
    if chronic_conditions is not None:
        payload["chronic_conditions"] = list(chronic_conditions)
    payload.update(overrides)
    return payload


def patch_patient_payload(
    *,
    smoking_status: Optional[str] = None,
    chronic_conditions: Optional[List[str]] = None,
    portal_enabled: Optional[bool] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /patients/{id}. PRD §3.1: 'smoking_status,
    chronic_conditions, and portal_enabled may be revised through the
    patient PATCH operation (which also accepts an optional version
    for OCC).'"""
    payload: Dict[str, Any] = {}
    if smoking_status is not None:
        payload["smoking_status"] = smoking_status
    if chronic_conditions is not None:
        payload["chronic_conditions"] = list(chronic_conditions)
    if portal_enabled is not None:
        payload["portal_enabled"] = portal_enabled
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def bind_pcp_payload(*, provider_id: str,
                     version: Optional[int] = None,
                     **overrides: Any) -> Dict[str, Any]:
    """POST /patients/{id}/bind-pcp. PRD §3.1: 'Binding by a
    Receptionist or ClinicAdmin supplies a provider_id'."""
    payload: Dict[str, Any] = {"provider_id": provider_id}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Provider — PRD §3.2.
# ---------------------------------------------------------------------------
def create_provider_payload(
    *,
    npi: Optional[str] = None,
    full_name: str = "Dr. Test Provider",
    role_type: str = "PCP_ONLY",
    specialty: Optional[str] = None,
    dea_number: Optional[str] = None,
    epcs_enrolled: Optional[bool] = None,
    panel_cap: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /providers — ClinicAdmin only.

    PRD §3.2: payload includes the 10-digit npi, full_name, role_type
    (PCP_ONLY | SPECIALIST_ONLY | BOTH), and optional specialty. The
    specialty is required when role_type is SPECIALIST_ONLY or BOTH.
    dea_number, epcs_enrolled, and panel_cap are optional with
    documented defaults.
    """
    payload: Dict[str, Any] = {
        "npi": npi if npi is not None else random_npi(),
        "full_name": full_name,
        "role_type": role_type,
    }
    if role_type in {"SPECIALIST_ONLY", "BOTH"}:
        payload["specialty"] = specialty if specialty is not None \
            else "Family Medicine"
    elif specialty is not None:
        payload["specialty"] = specialty
    if dea_number is not None:
        payload["dea_number"] = dea_number
    if epcs_enrolled is not None:
        payload["epcs_enrolled"] = epcs_enrolled
    if panel_cap is not None:
        payload["panel_cap"] = panel_cap
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Encounter — PRD §3.3.
# ---------------------------------------------------------------------------
def create_encounter_payload(
    *,
    provider_id: str,
    encounter_type: str = "CONSULTATION",
    scheduled_start: Optional[str] = None,
    scheduled_end: Optional[str] = None,
    chief_complaint: Optional[str] = "Routine visit",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/encounters — Receptionist or
    ClinicAdmin.

    PRD §3.3: payload supplies provider_id, encounter_type
    (CONSULTATION | PHYSICAL | VACCINATION), scheduled_start,
    scheduled_end, and optionally chief_complaint.
    """
    if scheduled_start is None:
        scheduled_start = iso_anchor_offset(hours=2)
    if scheduled_end is None:
        scheduled_end = iso_anchor_offset(hours=2, minutes=30)
    payload: Dict[str, Any] = {
        "provider_id": provider_id,
        "encounter_type": encounter_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if chief_complaint is not None:
        payload["chief_complaint"] = chief_complaint
    payload.update(overrides)
    return payload


def patch_encounter_payload(
    *,
    vital_signs: Optional[Dict[str, Any]] = None,
    chief_complaint: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /encounters/{id}. PRD §3.3: 'a Nurse or Provider may PATCH
    the encounter to populate or revise vital_signs and chief_complaint
    (and may supply an optional version for OCC).'"""
    payload: Dict[str, Any] = {}
    if vital_signs is not None:
        payload["vital_signs"] = dict(vital_signs)
    if chief_complaint is not None:
        payload["chief_complaint"] = chief_complaint
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def default_vital_signs(*,
                        bp_systolic: int = 120,
                        bp_diastolic: int = 80,
                        pulse: int = 72,
                        temp_c: float = 36.7,
                        weight_kg: float = 70.0,
                        height_cm: float = 175.0) -> Dict[str, Any]:
    """PRD §3.3: 'The vital_signs object holds six fields: bp_systolic,
    bp_diastolic, pulse, temp_c, weight_kg, and height_cm.'"""
    return {
        "bp_systolic": bp_systolic,
        "bp_diastolic": bp_diastolic,
        "pulse": pulse,
        "temp_c": temp_c,
        "weight_kg": weight_kg,
        "height_cm": height_cm,
    }


# ---------------------------------------------------------------------------
# CPT line item — PRD §3.3.
# ---------------------------------------------------------------------------
def create_cpt_line_item_payload(
    *,
    cpt_code: str,
    units: int = 1,
    modifier: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /encounters/{id}/cpt-line-items.

    PRD §3.3: 'supplies a cpt_code (a five-digit string), a units count
    between 1 and 50 inclusive, and optionally a modifier such as 25,
    59, TC, or 26.'
    """
    payload: Dict[str, Any] = {"cpt_code": cpt_code, "units": units}
    if modifier is not None:
        payload["modifier"] = modifier
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CPT fee catalog — PRD §3.7.
# ---------------------------------------------------------------------------
def create_cpt_code_payload(
    *,
    cpt_code: Optional[str] = None,
    description: str = "Test CPT code",
    list_price_cents: int = TEST_DEFAULTS["CPT_LIST_PRICE_CENTS"],
    allowed_price_cents: int = TEST_DEFAULTS["CPT_ALLOWED_PRICE_CENTS"],
    is_preventive: Optional[bool] = None,
    is_telehealth_eligible: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cpt-codes — ClinicAdmin only.

    PRD §3.7: 'A ClinicAdmin creates an entry by supplying the cpt_code,
    a human description, the non-negative list_price_cents, the
    non-negative allowed_price_cents (which must be less than or equal
    to list_price_cents — a violation yields ERR_INVALID_BILLING_UNITS),
    an optional is_preventive flag (defaulting to false), and an
    optional is_telehealth_eligible flag (defaulting to false).'
    """
    payload: Dict[str, Any] = {
        "cpt_code": cpt_code if cpt_code is not None else random_cpt_code(),
        "description": description,
        "list_price_cents": list_price_cents,
        "allowed_price_cents": allowed_price_cents,
    }
    if is_preventive is not None:
        payload["is_preventive"] = is_preventive
    if is_telehealth_eligible is not None:
        payload["is_telehealth_eligible"] = is_telehealth_eligible
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Prescription — PRD §3.4.
# ---------------------------------------------------------------------------
def create_prescription_payload(
    *,
    provider_id: str,
    encounter_id: str,
    drug_name: str = "Amoxicillin",
    rxnorm_code: Optional[str] = None,
    is_controlled: bool = False,
    dea_schedule: Optional[str] = None,
    dose_mg: float = 500.0,
    quantity: int = 20,
    refills_authorized: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/prescriptions — Provider only.

    PRD §3.4: 'supplying the authoring provider_id, the originating
    encounter_id ... drug_name, an rxnorm_code identifier, an
    is_controlled boolean, the dose_mg strength, a quantity between 1
    and 360 tablets, and a refills_authorized integer between 0 and 5.'

    PRD §3.4: 'If is_controlled is true, the dea_schedule must be one
    of II, III, IV, or V; if is_controlled is false, dea_schedule must
    be null.' The factory follows this exactly.
    """
    payload: Dict[str, Any] = {
        "provider_id": provider_id,
        "encounter_id": encounter_id,
        "drug_name": drug_name,
        "rxnorm_code": rxnorm_code if rxnorm_code is not None
        else random_rxnorm_code(),
        "is_controlled": is_controlled,
        "dose_mg": dose_mg,
        "quantity": quantity,
        "refills_authorized": refills_authorized,
    }
    if is_controlled:
        payload["dea_schedule"] = dea_schedule if dea_schedule is not None \
            else "IV"
    else:
        # PRD §3.4: must be null when not controlled.
        payload["dea_schedule"] = None
    payload.update(overrides)
    return payload


def sign_prescription_payload(
    *,
    epcs_two_factor_token: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /prescriptions/{id}/sign.

    PRD §3.4: 'the request body must include epcs_two_factor_token as a
    six-digit OTP string' for controlled signing. For non-controlled
    prescriptions the OTP is not required.
    """
    payload: Dict[str, Any] = {}
    if epcs_two_factor_token is not None:
        payload["epcs_two_factor_token"] = epcs_two_factor_token
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Referral — PRD §3.5.
# ---------------------------------------------------------------------------
def create_referral_payload(
    *,
    referring_provider_id: str,
    referred_to_provider_id: str,
    encounter_id: str,
    reason: str = "Routine specialist consult",
    priority: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/referrals — Provider only.

    PRD §3.5: 'The request supplies the referring_provider_id, the
    referred_to_provider_id, the originating encounter_id (which must
    be COMPLETED), a free-text clinical reason, and an optional
    priority chosen from ROUTINE (the default) or URGENT.'
    """
    payload: Dict[str, Any] = {
        "referring_provider_id": referring_provider_id,
        "referred_to_provider_id": referred_to_provider_id,
        "encounter_id": encounter_id,
        "reason": reason,
    }
    if priority is not None:
        payload["priority"] = priority
    payload.update(overrides)
    return payload


def referral_action_payload(
    *,
    response_note: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /referrals/{id}/accept | reject | return-to-pcp | complete.

    PRD §3.5: 'an optional response_note may be supplied' and 'Both
    transitions accept an optional response_note and an optional
    version.'
    """
    payload: Dict[str, Any] = {}
    if response_note is not None:
        payload["response_note"] = response_note
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Portal message — PRD §3.6.
# ---------------------------------------------------------------------------
def create_portal_message_payload(
    *,
    patient_id: str,
    provider_id: str,
    body: str = "Hello provider, I have a quick question.",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /portal/messages.

    PRD §3.6: 'creates a new PortalMessage by supplying the patient_id,
    the provider_id (which must equal the patient's current
    pcp_provider_id), and a body string between 1 and 2000 characters
    inclusive.'
    """
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "body": body,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# HEDIS recompute — PRD §3.8.
# ---------------------------------------------------------------------------
def hedis_recompute_payload(
    *,
    year: int,
    patient_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /hedis/recompute — ClinicAdmin only.

    PRD §3.8: 'the HEDIS recompute action, which accepts a four-digit
    year and an optional patient_ids filter.'
    """
    payload: Dict[str, Any] = {"year": year}
    if patient_ids is not None:
        payload["patient_ids"] = list(patient_ids)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-only / OCC — PRD §2.9 / §2.5.
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    seconds: Optional[int] = None,
    to: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — test-only.

    PRD §2.9: 'Clock-advance accepts either a relative seconds integer
    or an absolute target to instant.'
    """
    payload: Dict[str, Any] = {}
    if seconds is not None:
        payload["seconds"] = seconds
    if to is not None:
        payload["to"] = to
    payload.update(overrides)
    return payload


def occ_payload(version: Optional[int] = None,
                **overrides: Any) -> Dict[str, Any]:
    """Minimal action-payload that carries only an optional version for
    PRD §2.5 OCC checks. Action endpoints that take no other inputs use
    this shape."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


__all__ = [
    # time helpers
    "iso_utc",
    "parse_iso",
    "iso_date",
    "parse_anchor",
    "iso_anchor_offset",
    # random helpers
    "random_suffix",
    "random_mrn",
    "random_npi",
    "random_dea_number",
    "random_cpt_code",
    "random_rxnorm_code",
    "random_otp",
    # payload factories
    "create_patient_payload",
    "patch_patient_payload",
    "bind_pcp_payload",
    "create_provider_payload",
    "create_encounter_payload",
    "patch_encounter_payload",
    "default_vital_signs",
    "create_cpt_line_item_payload",
    "create_cpt_code_payload",
    "create_prescription_payload",
    "sign_prescription_payload",
    "create_referral_payload",
    "referral_action_payload",
    "create_portal_message_payload",
    "hedis_recompute_payload",
    "clock_advance_payload",
    "occ_payload",
]
