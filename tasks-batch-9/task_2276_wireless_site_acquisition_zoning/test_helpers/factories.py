"""Payload builders.

Each builder returns the canonical create payload for one resource and accepts
keyword overrides. Passing ``None`` for a key removes it, which is how a test
exercises a missing required field.
"""

from typing import Any, Dict

from . import constants as C
from .test_users import AGENT_OWNER, ANALYST, DESIGNER, PLANNER


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------------------
def jurisdiction_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": C.JURISDICTION_NAME,
            "market_code": C.MARKET_CODE,
            "by_right_review_days": C.BY_RIGHT_REVIEW_DAYS,
            "conditional_use_review_days": C.CONDITIONAL_USE_REVIEW_DAYS,
            "variance_review_days": C.VARIANCE_REVIEW_DAYS,
            "hearing_cadence_days": C.HEARING_CADENCE_DAYS,
            "requires_visual_simulation": True,
            "min_visual_simulations": C.MIN_VISUAL_SIMULATIONS,
            "max_continuances": C.MAX_CONTINUANCES,
            "historic_district_flag": False,
            "tribal_consultation_required": False,
            "historical_delay_factor": C.HISTORICAL_DELAY_FACTOR,
            "appeal_window_days": C.APPEAL_WINDOW_DAYS,
        },
        overrides,
    )


def search_ring_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": C.RING_NAME,
            "market_code": C.MARKET_CODE,
            "center_lat": C.RING_CENTER_LAT,
            "center_lon": C.RING_CENTER_LON,
            "radius_m": C.RING_RADIUS_M,
            "required_agl_m": C.RING_REQUIRED_AGL_M,
            "objective_type": C.RING_OBJECTIVE_TYPE,
            "target_rsrp_dbm": C.RING_TARGET_RSRP_DBM,
            "target_capacity_gbps": C.RING_TARGET_CAPACITY_GBPS,
            "market_benchmark_monthly_rent_usd": C.MARKET_BENCHMARK_MONTHLY_RENT_USD,
            "capex_budget_usd": C.CAPEX_BUDGET_USD,
            "priority_rank": 1,
        },
        overrides,
    )


def landlord_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": C.LANDLORD_NAME,
            "entity_type": C.LANDLORD_ENTITY_TYPE,
            "contact_email": C.LANDLORD_EMAIL,
            "market_code": C.MARKET_CODE,
            "outreach_optout": False,
        },
        overrides,
    )


def tribal_landlord_payload(**overrides: Any) -> Dict[str, Any]:
    return landlord_payload(
        legal_name=C.TRIBAL_LANDLORD_NAME,
        entity_type=C.TRIBAL_LANDLORD_ENTITY_TYPE,
        contact_email=C.TRIBAL_LANDLORD_EMAIL,
        **overrides,
    )


def candidate_payload(
    search_ring_id: str, landlord_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "search_ring_id": search_ring_id,
            "landlord_id": landlord_id,
            "jurisdiction_id": jurisdiction_id,
            "owning_agent_user_id": AGENT_OWNER,
            "site_type": "TOWER",
            "lat": C.CANDIDATE_LAT,
            "lon": C.CANDIDATE_LON,
            "distance_from_center_m": C.CANDIDATE_DISTANCE_M,
            "agl_m": C.CANDIDATE_AGL_M,
            "months_to_availability": C.CANDIDATE_MONTHS_TO_AVAILABILITY,
            "measured_rsrp_dbm": C.CANDIDATE_RSRP_DBM,
            "offered_capacity_gbps": C.CANDIDATE_CAPACITY_GBPS,
        },
        overrides,
    )


def lease_payload(candidate_id: str, landlord_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "candidate_id": candidate_id,
            "landlord_id": landlord_id,
            "negotiating_agent_user_id": AGENT_OWNER,
            "base_monthly_rent_usd": C.LEASE_BASE_RENT_USD,
            "escalation_type": C.LEASE_ESCALATION_TYPE,
            "escalation_pct": C.LEASE_ESCALATION_PCT,
            "initial_term_years": C.LEASE_INITIAL_TERM_YEARS,
            "renewal_option_count": C.LEASE_RENEWAL_OPTION_COUNT,
            "renewal_term_years": C.LEASE_RENEWAL_TERM_YEARS,
            "equipment_expansion_sqft": C.LEASE_EXPANSION_SQFT,
            "revenue_share_pct": C.LEASE_REVENUE_SHARE_PCT,
        },
        overrides,
    )


def zoning_application_payload(candidate_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "candidate_id": candidate_id,
            "application_type": "CONDITIONAL_USE",
            "filed_by_user_id": PLANNER,
        },
        overrides,
    )


def visual_simulation_payload(view_angle_deg: int, photo_reference: str) -> Dict[str, Any]:
    return {"view_angle_deg": view_angle_deg, "photo_reference": photo_reference}


def structural_analysis_payload(
    candidate_id: str, expected_candidate_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "candidate_id": candidate_id,
            "analysis_type": C.TIA_222_H,
            "existing_load_pct": C.BASE_EXISTING_LOAD_PCT,
            "appurtenance_count": C.BASE_APPURTENANCE_COUNT,
            "wind_speed_mph": C.BASE_WIND_SPEED_MPH,
            "ice_thickness_in": C.BASE_ICE_THICKNESS_IN,
            "performed_by_user_id": ANALYST,
            "expected_candidate_version": expected_candidate_version,
        },
        overrides,
    )


def modification_design_payload(
    structural_analysis_id: str, estimated_cost_usd: float, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "structural_analysis_id": structural_analysis_id,
            "scope": "REINFORCEMENT",
            "estimated_cost_usd": estimated_cost_usd,
            "designed_by_user_id": DESIGNER,
        },
        overrides,
    )


def environmental_review_payload(candidate_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "candidate_id": candidate_id,
            "nepa_category": "CATEGORICAL_EXCLUSION",
            "section106_required": False,
        },
        overrides,
    )


def permit_payload(candidate_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "candidate_id": candidate_id,
            "permit_type": C.PERMIT_TYPE_BUILDING,
            "valid_days": C.PERMIT_VALID_DAYS_DEFAULT,
        },
        overrides,
    )


def utility_provider_payload(
    name: str = C.PROVIDER_NAME,
    concurrent_crew_capacity: int = 2,
    quoted_interval_days: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "market_code": C.MARKET_CODE,
            "concurrent_crew_capacity": concurrent_crew_capacity,
            "quoted_interval_days": quoted_interval_days,
        },
        overrides,
    )


def backhaul_order_payload(
    candidate_id: str,
    provider_id: str,
    order_type: str,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "candidate_id": candidate_id,
            "provider_id": provider_id,
            "order_type": order_type,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def on_air_plan_payload(
    search_ring_id: str, target_on_air_date: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "search_ring_id": search_ring_id,
            "target_on_air_date": target_on_air_date,
        },
        overrides,
    )


__all__ = [
    "OMIT",
    "jurisdiction_payload",
    "search_ring_payload",
    "landlord_payload",
    "tribal_landlord_payload",
    "candidate_payload",
    "lease_payload",
    "zoning_application_payload",
    "visual_simulation_payload",
    "structural_analysis_payload",
    "modification_design_payload",
    "environmental_review_payload",
    "permit_payload",
    "utility_provider_payload",
    "backhaul_order_payload",
    "on_air_plan_payload",
]
