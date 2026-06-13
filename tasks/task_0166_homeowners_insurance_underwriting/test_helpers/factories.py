"""Payload factories — one per entity, input fields only.

Defaults are chosen so the common "FRAME 2000sqft 1story roof5" property yields
a COMPONENT replacement_cost of 274200.00 (the value used across the design
indices), and a low-zone risk assessment that keeps the property insurable.
"""

DEFAULTS = {
    "PROPERTY_STREET": "1 Pine St",
    "STATE_CODE": "CA",
    "YEAR_BUILT": 2009,
    "SQUARE_FOOTAGE": 2000,
    "CONSTRUCTION_TYPE": "FRAME",
    "ROOF_AGE_YEARS": 5,
    "STORIES": 1,
    "REQUESTED_COVERAGE_A": 300000,
    "WIND_HAIL_DEDUCTIBLE_PCT": 2,
    "AUTHORITY_LIMIT": 1000000,
    "BUFFER_MINUTES": 60,
}


def create_property_payload(**overrides) -> dict:
    """source: input — street_address, state_code, year_built, square_footage,
    construction_type, roof_age_years, stories(optional default 1)."""
    payload = {
        "street_address": DEFAULTS["PROPERTY_STREET"],
        "state_code": DEFAULTS["STATE_CODE"],
        "year_built": DEFAULTS["YEAR_BUILT"],
        "square_footage": DEFAULTS["SQUARE_FOOTAGE"],
        "construction_type": DEFAULTS["CONSTRUCTION_TYPE"],
        "roof_age_years": DEFAULTS["ROOF_AGE_YEARS"],
        "stories": DEFAULTS["STORIES"],
    }
    payload.update(overrides)
    return payload


def estimate_payload(method="COMPONENT", **overrides) -> dict:
    payload = {"method": method}
    payload.update(overrides)
    return payload


def create_risk_assessment_payload(property_id, **overrides) -> dict:
    """source: input — property_id, wildfire_fuel_density, slope_grade_pct,
    defensible_space_ft, flood_zone, distance_to_coast_mi.
    Defaults: low-risk (PROVISIONAL ~ 60, FINAL low), flood X, coast 60mi -> TIER_1."""
    payload = {
        "property_id": property_id,
        "wildfire_fuel_density": 60,
        "slope_grade_pct": 40,
        "defensible_space_ft": 100,
        "flood_zone": "X",
        "distance_to_coast_mi": 60,
    }
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    """source: input — full_name, license_state, buffer_minutes(optional default 60)."""
    payload = {
        "full_name": "Ivy Insp",
        "license_state": "CA",
        "buffer_minutes": DEFAULTS["BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(property_id, inspector_id, window_start, window_end, **overrides) -> dict:
    """source: input — property_id, inspector_id, window_start, window_end."""
    payload = {
        "property_id": property_id,
        "inspector_id": inspector_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def complete_inspection_payload(roof_ok=True, electrical_ok=True, plumbing_ok=True, hvac_ok=True, **overrides) -> dict:
    """source: input — roof_ok, electrical_ok, plumbing_ok, hvac_ok."""
    payload = {
        "roof_ok": roof_ok,
        "electrical_ok": electrical_ok,
        "plumbing_ok": plumbing_ok,
        "hvac_ok": hvac_ok,
    }
    payload.update(overrides)
    return payload


def reschedule_inspection_payload(window_start, window_end, **overrides) -> dict:
    payload = {"window_start": window_start, "window_end": window_end}
    payload.update(overrides)
    return payload


def create_application_payload(property_id, requested_coverage_a=None, **overrides) -> dict:
    """source: input — property_id, requested_coverage_a, wind_hail_deductible_pct(optional default 2)."""
    payload = {
        "property_id": property_id,
        "requested_coverage_a": (
            DEFAULTS["REQUESTED_COVERAGE_A"] if requested_coverage_a is None else requested_coverage_a
        ),
    }
    payload.update(overrides)
    return payload


def bind_application_payload(effective_date, expiration_date, expected_application_version, **overrides) -> dict:
    """source: input — effective_date, expiration_date, expected_application_version."""
    payload = {
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def decline_application_payload(reason="INSPECTION_FAILED", **overrides) -> dict:
    """source: input — reason (WILDFIRE_UNINSURABLE | INSPECTION_FAILED)."""
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def create_endorsement_payload(application_id, kind, peril_code, coverage_limit=None, **overrides) -> dict:
    """source: input — application_id, kind, peril_code, coverage_limit(optional default 0)."""
    payload = {
        "application_id": application_id,
        "kind": kind,
        "peril_code": peril_code,
    }
    if coverage_limit is not None:
        payload["coverage_limit"] = coverage_limit
    payload.update(overrides)
    return payload


def create_underwriter_payload(**overrides) -> dict:
    """source: input — full_name, authority_limit."""
    payload = {
        "full_name": "Uma UW",
        "authority_limit": DEFAULTS["AUTHORITY_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_payment_payload(policy_id, purpose, amount, **overrides) -> dict:
    """source: input — policy_id, purpose (BINDING | REINSTATEMENT), amount."""
    payload = {"policy_id": policy_id, "purpose": purpose, "amount": amount}
    payload.update(overrides)
    return payload
