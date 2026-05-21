"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.6: every monetary quantity is stored and exchanged as integer
cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 ISO 8601 UTC with three fractional digits
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_instant_utc(
    year: int, month: int, day: int,
    hour: int = 0, minute: int = 0, second: int = 0, millis: int = 0,
) -> str:
    micros = millis * 1000
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            micros, tzinfo=timezone.utc))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_years(iso_ts: str, years: int) -> str:
    """Leap-year-aware ISO date math — advance whole years."""
    dt = parse_iso(iso_ts)
    try:
        return iso_utc(dt.replace(year=dt.year + years))
    except ValueError:
        return iso_utc(dt.replace(year=dt.year + years, day=28))


def date_only_utc(year: int, month: int, day: int) -> str:
    """A midnight-UTC ISO 8601 timestamp for date-only fields like DOB."""
    return iso_instant_utc(year, month, day)


# ---------------------------------------------------------------------------
# Random suffix — for uniqueness across parallel tests
# ---------------------------------------------------------------------------
_SUFFIX_CHARS = string.ascii_lowercase + string.digits
_NAME_COUNTER = [0]


def random_suffix(length: int = 8) -> str:
    return "".join(random.choices(_SUFFIX_CHARS, k=length))


def unique_legal_name(prefix: Optional[str] = None) -> str:
    """A legal_name unique within the test process.

    PRD §3.1: "The legal_name must be unique, on a case-insensitive
    comparison, among all entities whose formation_status is not
    DISSOLVED and not ADMINISTRATIVELY_DISSOLVED."
    """
    _NAME_COUNTER[0] += 1
    p = prefix or TEST_DEFAULTS["ENTITY_NAME_PREFIX"]
    return f"{p} {_NAME_COUNTER[0]:06d}-{random_suffix(4)}"


# ===========================================================================
# BusinessEntity — PRD §3.1
# ===========================================================================
def create_entity_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: A Filer submits legal_name, entity_type, home_state,
    registered_agent_id, and — only when the entity type is CORP —
    authorized_shares plus the optional bookkeeping fields
    total_gross_assets_cents and total_issued_shares.

    The defaults shape an LLC entity. Tests override entity_type to
    CORP/LP and supply authorized_shares as needed.
    """
    entity_type = overrides.get("entity_type", "LLC")
    payload: Dict[str, Any] = {
        "legal_name": overrides.get("legal_name", unique_legal_name()),
        "entity_type": entity_type,
        "home_state": overrides.get(
            "home_state", TEST_DEFAULTS["HOME_STATE"],
        ),
        "registered_agent_id": overrides.get("registered_agent_id"),
    }
    if entity_type == "CORP":
        payload["authorized_shares"] = overrides.get(
            "authorized_shares",
            TEST_DEFAULTS["AUTHORIZED_SHARES_DEFAULT"],
        )
        # Bookkeeping fields default to 0 per PRD §3.1.
        if "total_gross_assets_cents" in overrides:
            payload["total_gross_assets_cents"] = (
                overrides["total_gross_assets_cents"]
            )
        if "total_issued_shares" in overrides:
            payload["total_issued_shares"] = overrides["total_issued_shares"]
    # Allow callers to set these explicitly even on LLC/LP (the server
    # is expected to reject CORP-only fields on non-CORP rows if it
    # chooses; tests focus on the entity_type-driven base case).
    for k in ("authorized_shares",
              "total_gross_assets_cents", "total_issued_shares"):
        if k in overrides and k not in payload:
            payload[k] = overrides[k]
    return payload


def credit_deposit_payload(amount_cents: int) -> Dict[str, Any]:
    """PRD §3.6: "the credit-deposit endpoint, accepting amount_cents,
    lets a TaxOfficer top up an entity's credit_balance_cents by the
    supplied amount."""
    return {"amount_cents": amount_cents}


# ===========================================================================
# RegisteredAgent — PRD §3.2
# ===========================================================================
def create_registered_agent_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: "Creating an agent — done either by a
    RegisteredAgentService or by a StateRegistrar — requires agent_name,
    physical_address, and service_state."
    """
    return {
        "agent_name": overrides.get(
            "agent_name", f"Agent {random_suffix(4)}",
        ),
        "physical_address": overrides.get(
            "physical_address", TEST_DEFAULTS["AGENT_ADDRESS"],
        ),
        "service_state": overrides.get(
            "service_state", TEST_DEFAULTS["HOME_STATE"],
        ),
    }


def patch_registered_agent_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §2.5: PATCH endpoints accept an optional version field."""
    payload: Dict[str, Any] = {}
    for k in ("agent_name", "physical_address", "version"):
        if k in overrides:
            payload[k] = overrides[k]
    return payload


# ===========================================================================
# OperatingAgreement — PRD §3.3
# ===========================================================================
def create_operating_agreement_payload(business_entity_id: str,
                                       **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: "Attaching an OperatingAgreement to a BusinessEntity is
    a Filer operation that supplies business_entity_id, template_code,
    and template_version."
    """
    return {
        "business_entity_id": business_entity_id,
        "template_code": overrides.get("template_code", "LLC_MM"),
        "template_version": overrides.get(
            "template_version", TEST_DEFAULTS["TEMPLATE_VERSION"],
        ),
    }


# ===========================================================================
# EINApplication — PRD §3.4
# ===========================================================================
def create_ein_application_payload(business_entity_id: str,
                                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: "its Filer creates an EINApplication carrying
    business_entity_id, responsible_party_name, and
    responsible_party_ssn_last4."
    """
    return {
        "business_entity_id": business_entity_id,
        "responsible_party_name": overrides.get(
            "responsible_party_name",
            TEST_DEFAULTS["RESPONSIBLE_PARTY_NAME"],
        ),
        "responsible_party_ssn_last4": overrides.get(
            "responsible_party_ssn_last4", TEST_DEFAULTS["SSN_LAST4"],
        ),
    }


# ===========================================================================
# AnnualReport — PRD §3.5
# ===========================================================================
def create_annual_report_payload(business_entity_id: str,
                                 report_year: int,
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: "An AnnualReport is created by the Filer carrying
    business_entity_id, report_year, principal_office_address, and
    officer_director_count."
    """
    return {
        "business_entity_id": business_entity_id,
        "report_year": report_year,
        "principal_office_address": overrides.get(
            "principal_office_address",
            TEST_DEFAULTS["PRINCIPAL_OFFICE_ADDRESS"],
        ),
        "officer_director_count": overrides.get(
            "officer_director_count",
            TEST_DEFAULTS["OFFICER_DIRECTOR_COUNT"],
        ),
    }


def patch_annual_report_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: "The revision endpoint also accepts changes to
    principal_office_address, officer_director_count, and an optional
    version for OCC."
    """
    payload: Dict[str, Any] = {}
    for k in ("principal_office_address",
              "officer_director_count", "version"):
        if k in overrides:
            payload[k] = overrides[k]
    return payload


def reject_annual_report_payload(rejection_reason: str) -> Dict[str, Any]:
    """PRD §3.5: "The rejection_reason field must be supplied as a
    non-empty string."""
    return {"rejection_reason": rejection_reason}


# ===========================================================================
# FranchiseTaxAssessment — PRD §3.6
# ===========================================================================
def create_tax_assessment_payload(business_entity_id: str,
                                  tax_year: int,
                                  calculation_method: str,
                                  ) -> Dict[str, Any]:
    """PRD §3.6: "Franchise tax assessments are created by a TaxOfficer
    carrying business_entity_id, tax_year, and calculation_method."
    """
    return {
        "business_entity_id": business_entity_id,
        "tax_year": tax_year,
        "calculation_method": calculation_method,
    }


# ===========================================================================
# ForeignQualification — PRD §3.7
# ===========================================================================
def create_foreign_qualification_payload(business_entity_id: str,
                                         foreign_state: str,
                                         foreign_registered_agent_id: str,
                                         certificate_of_good_standing_date: str,
                                         ) -> Dict[str, Any]:
    """PRD §3.7: "the Filer files a ForeignQualification carrying
    business_entity_id, foreign_state, foreign_registered_agent_id, and
    certificate_of_good_standing_date."
    """
    return {
        "business_entity_id": business_entity_id,
        "foreign_state": foreign_state,
        "foreign_registered_agent_id": foreign_registered_agent_id,
        "certificate_of_good_standing_date":
            certificate_of_good_standing_date,
    }


def patch_foreign_qualification_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: "the patch endpoint, which can carry a fresh
    certificate_of_good_standing_date, a revised
    foreign_registered_agent_id, and an optional version for OCC."
    """
    payload: Dict[str, Any] = {}
    for k in ("certificate_of_good_standing_date",
              "foreign_registered_agent_id", "version"):
        if k in overrides:
            payload[k] = overrides[k]
    return payload


# ===========================================================================
# BeneficialOwner — PRD §3.8
# ===========================================================================
def create_beneficial_owner_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: "supplied by the Filer with full_legal_name,
    date_of_birth, residential_address, identifying_document_type, and
    identifying_document_number."
    """
    return {
        "full_legal_name": overrides.get(
            "full_legal_name",
            f"{TEST_DEFAULTS['OWNER_NAME_PREFIX']} {random_suffix(4)}",
        ),
        "date_of_birth": overrides.get(
            "date_of_birth", date_only_utc(1980, 1, 1),
        ),
        "residential_address": overrides.get(
            "residential_address", TEST_DEFAULTS["OWNER_ADDRESS"],
        ),
        "identifying_document_type": overrides.get(
            "identifying_document_type", "US_PASSPORT",
        ),
        "identifying_document_number": overrides.get(
            "identifying_document_number",
            f"{TEST_DEFAULTS['OWNER_DOC_NUMBER_PREFIX']}-{random_suffix(8)}",
        ),
    }


# ===========================================================================
# BOIOwnership — PRD §3.8
# ===========================================================================
def add_boi_ownership_payload(beneficial_owner_id: str,
                              ownership_percent_basis_points: int,
                              ) -> Dict[str, Any]:
    """PRD §3.8: "Adding an ownership row stamps effective_at to the
    current clock instant"; the input fields are beneficial_owner_id
    and ownership_percent_basis_points."""
    return {
        "beneficial_owner_id": beneficial_owner_id,
        "ownership_percent_basis_points": ownership_percent_basis_points,
    }


# ===========================================================================
# BOIReport — PRD §3.8
# ===========================================================================
def create_boi_report_payload(business_entity_id: str,
                              filing_type: str = "INITIAL",
                              ) -> Dict[str, Any]:
    """PRD §3.8: "A BOIReport is created by the Filer carrying
    business_entity_id and filing_type — one of INITIAL, UPDATE, or
    CORRECTION."""
    return {
        "business_entity_id": business_entity_id,
        "filing_type": filing_type,
    }


# ===========================================================================
# Clock advance — PRD §3.12
# ===========================================================================
def clock_advance_payload(duration_iso8601: str) -> Dict[str, Any]:
    """PRD §3.12: "The clock-advance capability accepts a
    duration_iso8601 (an ISO 8601 duration like 'P30D' or 'PT1H')."""
    return {"duration_iso8601": duration_iso8601}


__all__ = [
    "iso_utc", "utcnow", "iso_now", "iso_instant_utc",
    "parse_iso", "add_days", "add_seconds", "add_years",
    "date_only_utc",
    "random_suffix", "unique_legal_name",
    "create_entity_payload", "credit_deposit_payload",
    "create_registered_agent_payload", "patch_registered_agent_payload",
    "create_operating_agreement_payload",
    "create_ein_application_payload",
    "create_annual_report_payload", "patch_annual_report_payload",
    "reject_annual_report_payload",
    "create_tax_assessment_payload",
    "create_foreign_qualification_payload",
    "patch_foreign_qualification_payload",
    "create_beneficial_owner_payload",
    "add_boi_ownership_payload",
    "create_boi_report_payload",
    "clock_advance_payload",
]
