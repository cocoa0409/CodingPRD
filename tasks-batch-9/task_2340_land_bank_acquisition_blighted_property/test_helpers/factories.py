"""
Request-payload factories.

Each factory returns only the fields the endpoint accepts as input, with
overrides applied last so a test can pin any single value. Nothing here invents
system, computed or read-only fields.

``parcel_id`` values must be unique across the registry and must match the
county assessor pattern APN- followed by four to eight digits, so the property
factory mints a fresh sequential number on every call.
"""

from itertools import count
from typing import Any, Dict, List, Optional

_parcel_seq = count(100001)


def next_parcel_id() -> str:
    """Mint a fresh assessor parcel number in the APN-<digits> form."""
    return f"APN-{next(_parcel_seq)}"


def property_payload(**overrides: Any) -> Dict[str, Any]:
    """A registrable parcel: vacant lot, grade C structure, ward 3."""
    payload: Dict[str, Any] = {
        "parcel_id": next_parcel_id(),
        "address": "100 Alder St",
        "situs_ward": 3,
        "lot_area_sqft": 10000,
        "assessed_value_cents": 200000,
        "structure_present": False,
        "structure_condition_grade": "C",
        "vacancy_months": 5,
    }
    payload.update(overrides)
    return payload


def funding_source_payload(**overrides: Any) -> Dict[str, Any]:
    """An unrestricted general-fund line authorized for 1,000,000 cents."""
    payload: Dict[str, Any] = {
        "name": "Maintenance Line",
        "source_type": "GENERAL_FUND",
        "authorized_cents": 1000000,
        "restriction": "ANY",
        "expires_on": "2029-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def acquisition_packet_payload(
    property_id: str, funding_source_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A donation packet with no purchase price; donor_name is the paired field."""
    payload: Dict[str, Any] = {
        "property_id": property_id,
        "funding_source_id": funding_source_id,
        "channel": "DONATION",
        "offer_price_cents": 0,
        "title_search_fee_cents": 0,
        "donor_name": "Alder Street Trust",
    }
    payload.update(overrides)
    return payload


def contractor_payload(**overrides: Any) -> Dict[str, Any]:
    """A mowing contractor with four crews and a licence into 2027."""
    payload: Dict[str, Any] = {
        "name": "Meadow Mowing Co",
        "license_expires_on": "2027-12-31T00:00:00Z",
        "max_concurrent_crews": 4,
        "specialties": ["MOW"],
        "debarred": False,
    }
    payload.update(overrides)
    return payload


def maintenance_order_payload(
    contractor_id: Optional[str],
    funding_source_id: str,
    expected_property_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A MOW order over a two-day half-open window."""
    payload: Dict[str, Any] = {
        "work_type": "MOW",
        "contractor_id": contractor_id,
        "funding_source_id": funding_source_id,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-03T00:00:00Z",
        "expected_property_version": expected_property_version,
    }
    payload.update(overrides)
    return payload


def demolition_run_payload(
    funding_source_id: str, budget_cents: int, expected_funding_source_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "funding_source_id": funding_source_id,
        "budget_cents": budget_cents,
        "expected_funding_source_version": expected_funding_source_version,
    }
    payload.update(overrides)
    return payload


def applicant_payload(**overrides: Any) -> Dict[str, Any]:
    """An individual buyer with no nonprofit registration."""
    payload: Dict[str, Any] = {
        "legal_name": "Ada Bellweather",
        "applicant_type": "INDIVIDUAL",
        "contact_email": "ada@example.test",
    }
    payload.update(overrides)
    return payload


def disposition_application_payload(
    property_id: str, applicant_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A developer RFP application offering 900,000 cents."""
    payload: Dict[str, Any] = {
        "property_id": property_id,
        "applicant_id": applicant_id,
        "program": "DEVELOPER_RFP",
        "proposed_use": "Eight-unit townhouse row",
        "offer_price_cents": 900000,
    }
    payload.update(overrides)
    return payload


def development_agreement_payload(application_id: str, **overrides: Any) -> Dict[str, Any]:
    """A two-milestone statutory agreement with the reverter armed."""
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "performance_deadline": "2027-06-01T00:00:00Z",
        "milestone_count": 2,
        "reverter_clause_active": True,
        "abatement_years": 3,
        "discharge_mode": "STATUTORY",
        "projected_improved_value_cents": 10000000,
    }
    payload.update(overrides)
    return payload


def reuse_hearing_payload(**overrides: Any) -> Dict[str, Any]:
    """A quorate, well-supported hearing: 8 comments, 6 in support."""
    payload: Dict[str, Any] = {
        "hearing_at": "2026-07-15T00:00:00Z",
        "comment_count": 8,
        "support_count": 6,
        "summary": "Neighbourhood association backs a pocket park.",
    }
    payload.update(overrides)
    return payload


def parcel_adjacency_payload(
    property_id: str, adjacent_property_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "property_id": property_id,
        "adjacent_property_id": adjacent_property_id,
        "shared_boundary_feet": 40,
    }
    payload.update(overrides)
    return payload


def title_action_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action_type": "QUIET_TITLE_SUIT"}
    payload.update(overrides)
    return payload


def code_violation_report_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "open_code_violation_count": 0,
        "nuisance_complaint_count": 0,
    }
    payload.update(overrides)
    return payload


def tax_roll_posting_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delinquent_tax_balance_cents": 0,
        "tax_year": 2026,
    }
    payload.update(overrides)
    return payload


def without(payload: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """Return a copy of ``payload`` with the named keys removed."""
    return {k: v for k, v in payload.items() if k not in keys}


def specialties(*work_types: str) -> List[str]:
    """Helper for readable contractor specialty lists."""
    return list(work_types)
