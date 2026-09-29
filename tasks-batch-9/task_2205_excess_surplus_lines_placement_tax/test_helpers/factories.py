"""Payload factories for the Surplus Lines Placement Tax API.

Each factory returns a valid request body with sensible defaults and accepts
``**overrides`` so a test can vary exactly the field it is interested in.
Passing the :data:`OMIT` sentinel for a field removes it from the payload,
which is how tests exercise defaulting behaviour; passing ``None`` sends an
explicit JSON null.
"""

import itertools
from typing import Any, Dict, List, Optional


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "OMIT"


#: Sentinel meaning "leave this field out of the request body entirely".
OMIT = _Omit()

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, _Omit):
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Brokers and licences
# ---------------------------------------------------------------------------
def broker_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {"firm_name": "Lone Star Surplus Partners", "home_state": "TX"},
        overrides,
    )


def broker_license_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {
            "state_code": "TX",
            "license_number": f"SL-TX-{1000 + _next()}",
            "license_type": "SURPLUS_LINES",
            "expires_on": "2027-12-31T00:00:00Z",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# State programs
# ---------------------------------------------------------------------------
def state_program_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {
            "state_code": "TX",
            "premium_tax_rate": 0.0485,
            "stamping_fee_rate": 0.0015,
            "stamping_fee_cap_cents": None,
            "stamping_office_required": True,
            "allocation_method": "ALLOCATED_MULTI",
            "diligent_search_min_declinations": 3,
            "export_list_exempts_search": True,
            "filing_frequency": "MONTHLY",
            "filing_deadline_days": 30,
            "return_premium_tax_refundable": True,
            "return_premium_stamping_refundable": False,
            "min_carrier_capital_surplus_cents": 1_500_000_000,
            "required_notice_codes": ["TX-SL-1", "TX-SL-2"],
        },
        overrides,
    )


def tx_program_payload(**overrides) -> Dict[str, Any]:
    """Texas: ALLOCATED_MULTI, stamping office, uncapped, monthly, 30 days."""
    return state_program_payload(**overrides)


def nv_program_payload(**overrides) -> Dict[str, Any]:
    """Nevada: no stamping office, two declinations, monthly, 45 days."""
    base = {
        "state_code": "NV",
        "premium_tax_rate": 0.035,
        "stamping_fee_rate": 0.004,
        "stamping_fee_cap_cents": None,
        "stamping_office_required": False,
        "allocation_method": "ALLOCATED_MULTI",
        "diligent_search_min_declinations": 2,
        "export_list_exempts_search": False,
        "filing_frequency": "MONTHLY",
        "filing_deadline_days": 45,
        "return_premium_tax_refundable": False,
        "return_premium_stamping_refundable": False,
        "min_carrier_capital_surplus_cents": 500_000_000,
        "required_notice_codes": ["NV-SL"],
    }
    return _apply(base, overrides)


def ca_program_payload(**overrides) -> Dict[str, Any]:
    """California: HOME_STATE_SINGLE, capped stamping fee, quarterly."""
    base = {
        "state_code": "CA",
        "premium_tax_rate": 0.03,
        "stamping_fee_rate": 0.0018,
        "stamping_fee_cap_cents": 50000,
        "stamping_office_required": True,
        "allocation_method": "HOME_STATE_SINGLE",
        "diligent_search_min_declinations": 3,
        "export_list_exempts_search": False,
        "filing_frequency": "QUARTERLY",
        "filing_deadline_days": 45,
        "return_premium_tax_refundable": True,
        "return_premium_stamping_refundable": True,
        "min_carrier_capital_surplus_cents": 1_500_000_000,
        "required_notice_codes": ["CA-D1", "CA-D2"],
    }
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
def carrier_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {
            "naic_number": f"{10000 + _next()}",
            "legal_name": "Atlas Specialty Insurance Company",
            "domicile_type": "US_STATE",
            "capital_surplus_cents": 6_000_000_000,
            "am_best_rating": "A_PLUS",
            "trust_fund_cents": 0,
            "naic_quarterly_listing": True,
        },
        overrides,
    )


def carrier_eligibility_payload(
    carrier_id: str, state_program_id: str, **overrides
) -> Dict[str, Any]:
    return _apply(
        {
            "carrier_id": carrier_id,
            "state_program_id": state_program_id,
            "listed_on": "2026-01-01T00:00:00Z",
        },
        overrides,
    )


def review_decision_payload(decision: str, expected_carrier_version: int, **overrides):
    return _apply(
        {"decision": decision, "expected_carrier_version": expected_carrier_version},
        overrides,
    )


# ---------------------------------------------------------------------------
# Placements and declinations
# ---------------------------------------------------------------------------
def exposure(state_code: str, insured_value_cents: int) -> Dict[str, Any]:
    return {"state_code": state_code, "insured_value_cents": insured_value_cents}


def placement_payload(
    state_exposures: Optional[List[Dict[str, Any]]] = None, **overrides
) -> Dict[str, Any]:
    if state_exposures is None:
        state_exposures = [
            exposure("TX", 300_000_000),
            exposure("NV", 300_000_000),
            exposure("CA", 300_000_000),
        ]
    return _apply(
        {
            "insured_name": "Gulf Fabricators LLC",
            "principal_place_of_business_state": "TX",
            "coverage_class": "PROPERTY",
            "is_export_list_risk": False,
            "state_exposures": state_exposures,
        },
        overrides,
    )


def declination_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {
            "admitted_carrier_name": "Republic Admitted Mutual",
            "state_code": "TX",
            "reason_code": "NO_APPETITE",
            "declined_on": "2026-07-10T00:00:00Z",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------
def policy_payload(
    placement_id: str, carrier_id: str, expected_placement_version: int, **overrides
) -> Dict[str, Any]:
    return _apply(
        {
            "placement_id": placement_id,
            "carrier_id": carrier_id,
            "policy_number": f"SL-2026-{_next():04d}",
            "effective_date": "2026-08-01T00:00:00Z",
            "expiration_date": "2027-08-01T00:00:00Z",
            "original_gross_premium_cents": 1_000_000,
            "policy_fee_cents": 25000,
            "broker_fee_cents": 50000,
            "min_earned_premium_pct": 0.25,
            "expected_placement_version": expected_placement_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Endorsements and cancellations
# ---------------------------------------------------------------------------
def endorsement_payload(expected_policy_version: int, **overrides) -> Dict[str, Any]:
    return _apply(
        {
            "endorsement_type": "PREMIUM_INCREASE",
            "premium_delta_cents": 200_000,
            "effective_date": "2026-09-01T00:00:00Z",
            "supersedes_endorsement_id": None,
            "expected_policy_version": expected_policy_version,
        },
        overrides,
    )


def cancellation_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {"cancellation_type": "FLAT", "cancellation_date": "2026-08-01T00:00:00Z"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Filing batches and affidavits
# ---------------------------------------------------------------------------
def filing_batch_payload(
    state_program_id: str, broker_id: str, period_key: str = "2026-08", **overrides
) -> Dict[str, Any]:
    return _apply(
        {
            "state_program_id": state_program_id,
            "broker_id": broker_id,
            "period_key": period_key,
        },
        overrides,
    )


def affidavit_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {"affidavit_type": "DILIGENT_SEARCH", "declination_count_attested": 3},
        overrides,
    )
