"""Request payload builders.

Every monetary amount is emitted as a JSON integer of whole cents and every
decimal as a JSON number, exactly as PRD 3 describes the request bodies.  The
defaults below are the recurring worked examples used across the suite; any test
overrides just the fields its rule is about.
"""

from typing import Any, Dict, Optional

# --- Jurisdictions (PRD 3.1) -----------------------------------------------


def jurisdiction_payload(
    name: str = "City of Harbor",
    jurisdiction_code: str = "CITY-HARBOR",
    population: int = 180000,
    svi_score: float = 0.62,
    endorsement_weight: Optional[int] = 4,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "jurisdiction_code": jurisdiction_code,
        "population": population,
        "svi_score": svi_score,
    }
    if endorsement_weight is not None:
        payload["endorsement_weight"] = endorsement_weight
    if status is not None:
        payload["status"] = status
    payload.update(overrides)
    return payload


def harbor_payload(**overrides: Any) -> Dict[str, Any]:
    """The disadvantaged coastal city used as the primary member government."""
    return jurisdiction_payload(**overrides)


def ridge_payload(**overrides: Any) -> Dict[str, Any]:
    """A low-vulnerability neighbouring member government."""
    defaults = dict(
        name="Town of Ridge",
        jurisdiction_code="TOWN-RIDGE",
        population=40000,
        svi_score=0.18,
        endorsement_weight=3,
    )
    defaults.update(overrides)
    return jurisdiction_payload(**defaults)


# --- Hazard profiles (PRD 3.2) ---------------------------------------------


def hazard_profile_payload(
    jurisdiction_id: str,
    hazard_type: str = "FLOOD",
    scenario: str = "RCP85",
    horizon_year: int = 2060,
    exposure_index: float = 0.80,
    annual_event_probability: float = 0.02,
    projected_annual_loss_cents: int = 250000000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "hazard_type": hazard_type,
        "scenario": scenario,
        "horizon_year": horizon_year,
        "exposure_index": exposure_index,
        "annual_event_probability": annual_event_probability,
        "projected_annual_loss_cents": projected_annual_loss_cents,
    }
    payload.update(overrides)
    return payload


def hazard_revision_payload(
    exposure_index: float = 0.90,
    annual_event_probability: float = 0.03,
    projected_annual_loss_cents: int = 300000000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "exposure_index": exposure_index,
        "annual_event_probability": annual_event_probability,
        "projected_annual_loss_cents": projected_annual_loss_cents,
    }
    payload.update(overrides)
    return payload


# --- Lifeline assets (PRD 3.4) ---------------------------------------------


def asset_payload(
    jurisdiction_id: str,
    name: str = "Harbor Water Treatment Plant",
    asset_class: str = "WATER",
    replacement_value_cents: int = 1200000000,
    service_population: int = 150000,
    redundancy_factor: float = 0.25,
    is_shared: Optional[bool] = True,
    upstream_asset_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "name": name,
        "asset_class": asset_class,
        "replacement_value_cents": replacement_value_cents,
        "service_population": service_population,
        "redundancy_factor": redundancy_factor,
    }
    if is_shared is not None:
        payload["is_shared"] = is_shared
    if upstream_asset_id is not None:
        payload["upstream_asset_id"] = upstream_asset_id
    payload.update(overrides)
    return payload


# --- Vulnerability assessments (PRD 3.3) -----------------------------------


def assessment_payload(
    hazard_profile_id: str,
    asset_id: str,
    subject_type: str = "INFRASTRUCTURE",
    method: str = "ADDITIVE_WEIGHTED",
    sensitivity_score: float = 0.60,
    adaptive_capacity_score: float = 0.50,
    svi_overlay_applied: Optional[bool] = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hazard_profile_id": hazard_profile_id,
        "asset_id": asset_id,
        "subject_type": subject_type,
        "method": method,
        "sensitivity_score": sensitivity_score,
        "adaptive_capacity_score": adaptive_capacity_score,
    }
    if svi_overlay_applied is not None:
        payload["svi_overlay_applied"] = svi_overlay_applied
    payload.update(overrides)
    return payload


# --- Plan cycles (PRD 3.8) -------------------------------------------------


def plan_cycle_payload(
    cycle_label: str = "Regional Plan 2027-2032",
    endorsement_deadline: str = "2026-12-01T00:00:00Z",
    quorum_weight_bps: Optional[int] = 6600,
    max_revision_rounds: Optional[int] = 1,
    required_session_count: Optional[int] = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_label": cycle_label,
        "endorsement_deadline": endorsement_deadline,
    }
    if quorum_weight_bps is not None:
        payload["quorum_weight_bps"] = quorum_weight_bps
    if max_revision_rounds is not None:
        payload["max_revision_rounds"] = max_revision_rounds
    if required_session_count is not None:
        payload["required_session_count"] = required_session_count
    payload.update(overrides)
    return payload


# --- Adaptation projects (PRD 3.5) -----------------------------------------


def project_payload(
    plan_cycle_id: str,
    jurisdiction_id: str,
    name: str = "Harbor Levee Raise",
    hazard_type: str = "FLOOD",
    strategy_type: str = "PROTECT",
    base_cost_cents: int = 42000000,
    service_life_years: int = 30,
    cobenefit_points: int = 12,
    feasibility_score: float = 0.70,
    prerequisite_project_id: Optional[str] = None,
    indicator_code: Optional[str] = None,
    indicator_target_value: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_cycle_id": plan_cycle_id,
        "jurisdiction_id": jurisdiction_id,
        "name": name,
        "hazard_type": hazard_type,
        "strategy_type": strategy_type,
        "base_cost_cents": base_cost_cents,
        "service_life_years": service_life_years,
        "cobenefit_points": cobenefit_points,
        "feasibility_score": feasibility_score,
    }
    if prerequisite_project_id is not None:
        payload["prerequisite_project_id"] = prerequisite_project_id
    if indicator_code is not None:
        payload["indicator_code"] = indicator_code
    if indicator_target_value is not None:
        payload["indicator_target_value"] = indicator_target_value
    payload.update(overrides)
    return payload


def retrofit_project_payload(
    plan_cycle_id: str,
    jurisdiction_id: str,
    name: str = "Harbor Pump Retrofit",
    **overrides: Any,
) -> Dict[str, Any]:
    """The accommodate-family project whose worked figures recur in the suite."""
    defaults = dict(
        name=name,
        strategy_type="ACCOMMODATE",
        base_cost_cents=30000000,
        service_life_years=25,
        cobenefit_points=10,
        feasibility_score=0.65,
    )
    defaults.update(overrides)
    return project_payload(plan_cycle_id, jurisdiction_id, **defaults)


def asset_link_payload(
    asset_id: str,
    avoided_loss_annual_cents: int,
    benefit_reaches_disadvantaged: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "asset_id": asset_id,
        "avoided_loss_annual_cents": avoided_loss_annual_cents,
    }
    if benefit_reaches_disadvantaged is not None:
        payload["benefit_reaches_disadvantaged"] = benefit_reaches_disadvantaged
    payload.update(overrides)
    return payload


def analysis_payload(
    method: str = "ANNUALIZED_EQUIVALENT",
    discount_rate_bps: Optional[int] = 700,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"method": method}
    if discount_rate_bps is not None:
        payload["discount_rate_bps"] = discount_rate_bps
    payload.update(overrides)
    return payload


# --- Capital programs (PRD 3.7) --------------------------------------------


def capital_program_payload(
    fiscal_year: int = 2027,
    authorized_cents: int = 60000000,
    equity_target_bps: Optional[int] = 4000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fiscal_year": fiscal_year,
        "authorized_cents": authorized_cents,
    }
    if equity_target_bps is not None:
        payload["equity_target_bps"] = equity_target_bps
    payload.update(overrides)
    return payload


def allocation_payload(
    project_id: str,
    allocated_cents: int,
    expected_capital_program_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "allocated_cents": allocated_cents,
        "expected_capital_program_version": expected_capital_program_version,
    }
    payload.update(overrides)
    return payload


def grant_submission_payload(grant_funder: str = "BRIC", **overrides: Any) -> Dict[str, Any]:
    payload = {"grant_funder": grant_funder}
    payload.update(overrides)
    return payload


def equity_waiver_payload(
    waiver_rationale: str = "Sole evacuation route for the Harbor mobile-home park.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"waiver_rationale": waiver_rationale}
    payload.update(overrides)
    return payload


def indicator_report_payload(
    reported_value: float, period_label: str = "2027-Q1", **overrides: Any
) -> Dict[str, Any]:
    payload = {"reported_value": reported_value, "period_label": period_label}
    payload.update(overrides)
    return payload


# --- Engagement and endorsement (PRD 3.8) ----------------------------------


def engagement_session_payload(
    host_jurisdiction_id: str,
    window_start: str = "2026-09-10T17:00:00Z",
    window_end: str = "2026-09-10T20:00:00Z",
    modality: str = "IN_PERSON",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "host_jurisdiction_id": host_jurisdiction_id,
        "modality": modality,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def session_completion_payload(
    attendee_count: int = 120,
    disadvantaged_attendee_count: int = 70,
    preferred_strategy_type: str = "PROTECT",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "attendee_count": attendee_count,
        "disadvantaged_attendee_count": disadvantaged_attendee_count,
        "preferred_strategy_type": preferred_strategy_type,
    }
    payload.update(overrides)
    return payload


def endorsement_payload(
    jurisdiction_id: str,
    decision: str = "ENDORSED",
    condition_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"jurisdiction_id": jurisdiction_id, "decision": decision}
    if condition_note is not None:
        payload["condition_note"] = condition_note
    payload.update(overrides)
    return payload


# --- Mutual aid (PRD 3.9) --------------------------------------------------


def pact_payload(
    host_jurisdiction_id: str,
    resource_class: str = "PUMPS",
    pledged_units: int = 10,
    window_start: str = "2026-09-01T00:00:00Z",
    window_end: str = "2026-10-01T00:00:00Z",
    max_concurrent_commitments: Optional[int] = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "host_jurisdiction_id": host_jurisdiction_id,
        "resource_class": resource_class,
        "pledged_units": pledged_units,
        "window_start": window_start,
        "window_end": window_end,
    }
    if max_concurrent_commitments is not None:
        payload["max_concurrent_commitments"] = max_concurrent_commitments
    payload.update(overrides)
    return payload


def commitment_payload(
    requesting_jurisdiction_id: str,
    asset_id: str,
    committed_units: int,
    window_start: str,
    window_end: str,
    expected_mutual_aid_pact_version: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "requesting_jurisdiction_id": requesting_jurisdiction_id,
        "asset_id": asset_id,
        "committed_units": committed_units,
        "window_start": window_start,
        "window_end": window_end,
        "expected_mutual_aid_pact_version": expected_mutual_aid_pact_version,
    }
    payload.update(overrides)
    return payload
