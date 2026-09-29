"""Payload factories — one per entity, input fields only."""

from typing import Optional


# ---------------------------------------------------------------------------
# PreservationProgram
# ---------------------------------------------------------------------------


def create_program_payload(**overrides) -> dict:
    """The eleven required program inputs plus the three optional ones."""
    defaults = {
        "name": "Statewide Farmland Preservation",
        "soil_weight": 0.35,
        "size_weight": 0.15,
        "contiguity_weight": 0.25,
        "pressure_weight": 0.25,
        "min_composite_score": 60.00,
        "max_negotiation_rounds": 3,
        "local_match_min_pct": 0.25,
        "federal_max_share_pct": 0.50,
        "impervious_allowance_pct": 0.02,
        "amendment_policy": "STRICT",
        "monitoring_interval_days": 365,
        "monitoring_grace_days": 30,
        "appraisal_engagement_buffer_days": 3,
    }
    defaults.update(overrides)
    return defaults


def create_program_required_only_payload(**overrides) -> dict:
    """Only the eleven required inputs — the three optional ones are omitted."""
    payload = create_program_payload(**overrides)
    for optional in (
        "monitoring_interval_days",
        "monitoring_grace_days",
        "appraisal_engagement_buffer_days",
    ):
        payload.pop(optional, None)
    return payload


# ---------------------------------------------------------------------------
# FundingRound
# ---------------------------------------------------------------------------


def create_funding_round_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "round_label": "2026 Cycle A",
        "opens_on": "2026-08-05T00:00:00Z",
        "closes_on": "2026-09-30T00:00:00Z",
        "pool_cents": 500_000_000,
    }
    defaults.update(overrides)
    return defaults


def rank_payload(score_basis: str = "RECEIPT_BASIS", **overrides) -> dict:
    defaults = {"score_basis": score_basis}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# FundingSource
# ---------------------------------------------------------------------------


def create_funding_source_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "source_name": "County Open Space Fund",
        "level": "LOCAL",
        "authorized_cents": 60_000_000,
        "obligation_window_start": "2026-01-01T00:00:00Z",
        "obligation_window_end": "2027-12-31T00:00:00Z",
        "max_share_pct": 0.35,
        "priority_order": 1,
        "requires_match": False,
        "fully_obligated_threshold_pct": 0.95,
    }
    defaults.update(overrides)
    return defaults


def suspend_source_payload(reason: str = "appropriation rescinded", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Landowner
# ---------------------------------------------------------------------------


def create_landowner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Harlan Family Trust",
        "mailing_state": "PA",
        "tax_id_last4": "4417",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Parcel
# ---------------------------------------------------------------------------


def create_parcel_payload(landowner_id: str, **overrides) -> dict:
    """The canonical 160-acre Lancaster parcel: soil 84.00, pressure 78.00."""
    defaults = {
        "landowner_id": landowner_id,
        "county": "Lancaster",
        "acres": 160.00,
        "prime_soil_acres": 120.00,
        "statewide_important_soil_acres": 24.00,
        "contiguous_preserved_acres": 80.00,
        "road_frontage_feet": 640,
        "sewer_available": True,
        "zoning_min_lot_acres": 2.0,
        "baseline_dwelling_rights": 4,
        "unrestricted_value_cents": 288_000_000,
        "restricted_value_cents": 112_450_000,
        "mortgage_lienholder_name": "Midstate Farm Credit",
    }
    defaults.update(overrides)
    return defaults


def create_small_parcel_payload(landowner_id: str, **overrides) -> dict:
    """A 40-acre all-prime Chester parcel with no lienholder."""
    defaults = {
        "landowner_id": landowner_id,
        "county": "Chester",
        "acres": 40.00,
        "prime_soil_acres": 40.00,
        "statewide_important_soil_acres": 0.00,
        "contiguous_preserved_acres": 40.00,
        "road_frontage_feet": 100,
        "sewer_available": False,
        "zoning_min_lot_acres": 10.0,
        "baseline_dwelling_rights": 2,
        "unrestricted_value_cents": 60_000_000,
        "restricted_value_cents": 35_000_000,
    }
    defaults.update(overrides)
    return defaults


def patch_parcel_payload(expected_parcel_version: int, **overrides) -> dict:
    defaults = {"expected_parcel_version": expected_parcel_version}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def create_application_payload(
    funding_round_id: str, parcel_id: str, landowner_id: str, **overrides
) -> dict:
    defaults = {
        "funding_round_id": funding_round_id,
        "parcel_id": parcel_id,
        "landowner_id": landowner_id,
        "requested_price_cents": 170_000_000,
    }
    defaults.update(overrides)
    return defaults


def withdrawal_payload(withdrawal_reason: str = "family decided to keep the rights", **overrides) -> dict:
    defaults = {"withdrawal_reason": withdrawal_reason}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Appraisal
# ---------------------------------------------------------------------------


def engage_appraisal_payload(
    appraiser_user_id: str = "appraiser-1", **overrides
) -> dict:
    defaults = {
        "appraiser_user_id": appraiser_user_id,
        "appraiser_firm": "Brandywine Rural Appraisal",
        "engagement_start": "2026-08-12T00:00:00Z",
        "engagement_end": "2026-08-26T00:00:00Z",
        "method": "PAIRED_SALES",
    }
    defaults.update(overrides)
    return defaults


def submit_appraisal_payload(
    unrestricted_value_cents: int = 288_000_000,
    restricted_value_cents: int = 112_450_000,
    **overrides,
) -> dict:
    defaults = {
        "unrestricted_value_cents": unrestricted_value_cents,
        "restricted_value_cents": restricted_value_cents,
    }
    defaults.update(overrides)
    return defaults


def review_appraisal_payload(decision: str = "CERTIFY", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Offers, counters and the funding plan
# ---------------------------------------------------------------------------


def issue_offer_payload(
    expected_application_version: int,
    offer_cents: int,
    structure: str = "FULL_PURCHASE",
    offer_expires_on: str = "2026-11-19T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "expected_application_version": expected_application_version,
        "offer_cents": offer_cents,
        "structure": structure,
        "offer_expires_on": offer_expires_on,
    }
    defaults.update(overrides)
    return defaults


def counter_payload(counter_cents: int, **overrides) -> dict:
    defaults = {"counter_cents": counter_cents}
    defaults.update(overrides)
    return defaults


def funding_plan_payload(
    expected_application_version: int,
    target_closing_date: str = "2027-01-15T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "expected_application_version": expected_application_version,
        "target_closing_date": target_closing_date,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ClosingRequirement
# ---------------------------------------------------------------------------


def submit_title_payload(exception_count: int = 0, **overrides) -> dict:
    defaults = {"exception_count": exception_count}
    defaults.update(overrides)
    return defaults


def submit_subordination_payload(
    lienholder_name: str = "Midstate Farm Credit", **overrides
) -> dict:
    defaults = {"lienholder_name": lienholder_name}
    defaults.update(overrides)
    return defaults


def submit_survey_payload(surveyed_acres: float = 160.00, **overrides) -> dict:
    defaults = {"surveyed_acres": surveyed_acres}
    defaults.update(overrides)
    return defaults


def review_requirement_payload(decision: str = "ACCEPT", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def waiver_payload(waiver_reason: str = "recent survey of record accepted", **overrides) -> dict:
    defaults = {"waiver_reason": waiver_reason}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Easement (recorded at closing)
# ---------------------------------------------------------------------------


def record_closing_payload(
    recorded_on: str = "2026-12-15T00:00:00Z",
    protected_acres: float = 160.00,
    residential_rights_retained: int = 2,
    **overrides,
) -> dict:
    defaults = {
        "recorded_on": recorded_on,
        "protected_acres": protected_acres,
        "residential_rights_retained": residential_rights_retained,
        "subdivision_permitted": False,
        "permitted_uses": ["CROP_PRODUCTION", "LIVESTOCK", "FARM_STAND"],
    }
    defaults.update(overrides)
    return defaults


def cancel_closing_payload(reason: str = "title defect could not be cleared", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Stewardship
# ---------------------------------------------------------------------------


def impervious_request_payload(
    added_impervious_sqft: int, description: str = "new equipment shed pad", **overrides
) -> dict:
    defaults = {
        "added_impervious_sqft": added_impervious_sqft,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def schedule_visit_payload(
    easement_id: str,
    window_start: str = "2027-12-20T00:00:00Z",
    window_end: str = "2027-12-27T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "easement_id": easement_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def complete_visit_payload(observed_impervious_sqft: int, **overrides) -> dict:
    defaults = {"observed_impervious_sqft": observed_impervious_sqft}
    defaults.update(overrides)
    return defaults


def cancel_visit_payload(reason: str = "weather closed the access lane", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def open_violation_payload(
    easement_id: str, violation_type: str = "UNAUTHORIZED_SUBDIVISION", **overrides
) -> dict:
    defaults = {"easement_id": easement_id, "violation_type": violation_type}
    defaults.update(overrides)
    return defaults


def cure_plan_payload(cure_plan_note: str = "lot line consolidation filed", **overrides) -> dict:
    defaults = {"cure_plan_note": cure_plan_note}
    defaults.update(overrides)
    return defaults


def cure_verification_payload(verification_note: Optional[str] = None, **overrides) -> dict:
    defaults = {}
    if verification_note is not None:
        defaults["verification_note"] = verification_note
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Amendment
# ---------------------------------------------------------------------------


def draft_amendment_payload(
    expected_easement_version: int,
    amendment_type: str = "BOUNDARY_ADJUSTMENT",
    net_conservation_benefit_cents: int = 500_000,
    **overrides,
) -> dict:
    defaults = {
        "expected_easement_version": expected_easement_version,
        "amendment_type": amendment_type,
        "net_conservation_benefit_cents": net_conservation_benefit_cents,
    }
    defaults.update(overrides)
    return defaults


def decide_amendment_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def rescind_amendment_payload(reason: str = "landowner reversed the request", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults
