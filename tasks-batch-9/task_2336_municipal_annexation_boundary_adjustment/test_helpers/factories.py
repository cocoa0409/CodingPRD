"""Request-payload factories.

Every factory returns a complete, valid payload for its endpoint and accepts
keyword overrides so a test can perturb exactly one field. Values that the PRD
declares optional are simply omitted unless overridden, so that tests which
care about declared defaults get them from the server rather than from here.
"""
import itertools
from typing import Any, Dict, Optional

from . import constants as C

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_state_codes = itertools.cycle(
    f"{a}{b}" for a in _LETTERS for b in _LETTERS
)
_counter = itertools.count(1)


def unique_state_code() -> str:
    """A fresh two-uppercase-letter state code (they must be unique)."""
    return next(_state_codes)


def unique_suffix() -> int:
    return next(_counter)


def unique_apn(prefix: str = "APN") -> str:
    return f"{prefix}-{next(_counter):06d}"


# ==========================================================================
# StatuteProfile
# ==========================================================================
def statute_profile_payload(**overrides: Any) -> Dict[str, Any]:
    """A statute authorizing all four methods, otherwise every declared
    default left to the server."""
    payload: Dict[str, Any] = {
        "state_code": unique_state_code(),
        "authorized_methods": [
            "PETITION_100",
            "PETITION_MAJORITY",
            "REFERENDUM",
            "INVOLUNTARY_ORDINANCE",
        ],
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# Municipality
# ==========================================================================
def municipality_payload(statute_profile_id: str, **overrides: Any) -> Dict[str, Any]:
    """A city whose perimeter and citywide figures make the canonical
    territory in `fixtures` comfortably certifiable.

    The city's `state_code` must equal the referenced statute profile's, so
    callers that build a payload directly must pass the profile's code as an
    override; `fixtures.create_municipality` does this automatically.
    """
    payload: Dict[str, Any] = {
        "statute_profile_id": statute_profile_id,
        "name": f"City of Testville {unique_suffix()}",
        "state_code": "NC",
        "population": 40000,
        "citywide_annual_service_cost_cents": 800000000,
        "citywide_population": 40000,
        "general_fund_millage_rate": 10.0,
        "corporate_boundary_perimeter_feet": 80000,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# ServiceProvider
# ==========================================================================
def service_provider_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "provider_name": f"Public Works {unique_suffix()}",
        "service_types": ["POLICE", "FIRE", "WATER", "SEWER"],
        "concurrent_project_capacity": 10,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# PropertyOwner
# ==========================================================================
def property_owner_payload(**overrides: Any) -> Dict[str, Any]:
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "owner_name": f"Owner {n}",
        "contact_email": f"owner{n}@example.test",
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# AnnexationCase
# ==========================================================================
def annexation_case_payload(municipality_id: str, **overrides: Any) -> Dict[str, Any]:
    """Territory measurements that pass all three statutory tests under the
    default statute: contiguity 20000/80000 = 0.2500 (twice the 0.1250
    minimum, so the ramp saturates) and a fully developed lot set."""
    payload: Dict[str, Any] = {
        "municipality_id": municipality_id,
        "method": "INVOLUNTARY_ORDINANCE",
        "shared_boundary_feet": 20000,
        "total_lot_count": 4,
        "developed_lot_count": 4,
        "dwelling_units": 8,
    }
    payload.update(overrides)
    return payload


def de_annexation_case_payload(
    municipality_id: str, predecessor_case_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = annexation_case_payload(
        municipality_id,
        case_type="DE_ANNEXATION",
        predecessor_case_id=predecessor_case_id,
    )
    payload.update(overrides)
    return payload


# ==========================================================================
# Parcel
# ==========================================================================
def parcel_payload(primary_owner_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "primary_owner_id": primary_owner_id,
        "parcel_apn": unique_apn(),
        "assessed_value_cents": 25000000,
        "acreage": 5.00,
        "is_developed": True,
        "dwelling_units": 2,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# UtilityAccount
# ==========================================================================
def utility_account_payload(
    parcel_id: str, service_provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "parcel_id": parcel_id,
        "service_provider_id": service_provider_id,
        "service_type": "WATER",
        "monthly_base_cents": 10000,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# Petition
# ==========================================================================
def petition_payload(annexation_case_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "annexation_case_id": annexation_case_id,
        "petition_type": "OWNER_MAJORITY",
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# ParcelOwnerConsent
# ==========================================================================
def consent_payload(
    petition_id: str,
    parcel_id: str,
    property_owner_id: str,
    ownership_share_pct: float = 100.00,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "petition_id": petition_id,
        "parcel_id": parcel_id,
        "property_owner_id": property_owner_id,
        "ownership_share_pct": ownership_share_pct,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# FiscalImpactAnalysis
# ==========================================================================
def fiscal_analysis_payload(
    annexation_case_id: str,
    expected_case_version: int,
    analysis_method: str = "AVERAGE_COST",
    projected_population: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """A projected population of 0 makes the AVERAGE_COST base cost 0, so the
    analysis is comfortably surplus and its `deficit_ratio_pct` is 0.00."""
    payload: Dict[str, Any] = {
        "annexation_case_id": annexation_case_id,
        "analysis_method": analysis_method,
        "projected_population": projected_population,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# PlanOfServices
# ==========================================================================
def plan_of_services_payload(annexation_case_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"annexation_case_id": annexation_case_id}
    payload.update(overrides)
    return payload


# ==========================================================================
# ServiceCommitment
# ==========================================================================
def service_commitment_payload(
    plan_of_services_id: str,
    service_provider_id: str,
    service_type: str,
    expected_plan_of_services_version: int,
    window_start_date: str = C.COMMITMENT_WINDOW_START,
    window_end_date: str = C.COMMITMENT_WINDOW_END,
    cost_cents: int = 100000,
    committed_account_count: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_of_services_id": plan_of_services_id,
        "service_provider_id": service_provider_id,
        "service_type": service_type,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "cost_cents": cost_cents,
        "expected_plan_of_services_version": expected_plan_of_services_version,
    }
    if committed_account_count is not None:
        payload["committed_account_count"] = committed_account_count
    payload.update(overrides)
    return payload


# ==========================================================================
# PublicHearing
# ==========================================================================
def public_hearing_payload(
    annexation_case_id: str,
    municipality_id: str,
    scheduled_start_at: str = C.HEARING_START_AT,
    scheduled_end_at: str = C.HEARING_END_AT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "annexation_case_id": annexation_case_id,
        "municipality_id": municipality_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# ProtestFiling
# ==========================================================================
def protest_filing_payload(
    public_hearing_id: str,
    parcel_id: str,
    property_owner_id: str,
    ownership_share_pct: float = 100.00,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "public_hearing_id": public_hearing_id,
        "parcel_id": parcel_id,
        "property_owner_id": property_owner_id,
        "ownership_share_pct": ownership_share_pct,
    }
    payload.update(overrides)
    return payload
