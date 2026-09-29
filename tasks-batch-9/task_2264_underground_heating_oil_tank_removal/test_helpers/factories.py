"""Payload factories: one per write operation, carrying only input fields.

Each factory produces a valid, minimal-but-complete body and accepts keyword
overrides so a test can vary exactly the field under examination.  Server-minted
and derived fields never appear here — they are outputs, not inputs.

Passing ``None`` for an optional key drops it from the payload entirely, which is
how a test omits a field rather than sending a null.
"""
from typing import Optional

from .constants import (
    DEFAULT_ACCREDITED,
    DEFAULT_BASELINE_SCOPE_CUBIC_YARDS,
    DEFAULT_COMMITTED_TURNAROUND_HOURS,
    DEFAULT_EXCAVATION_LIMIT_CUBIC_YARDS,
    DEFAULT_HOLDING_TIME_HOURS,
    DEFAULT_MAX_CONCURRENT_ANALYSES,
    DEFAULT_MOBILIZATION_BUFFER_MINUTES,
)

_SENTINEL = object()


def _prune(payload: dict) -> dict:
    """Drop keys explicitly set to the omission sentinel."""
    return {k: v for k, v in payload.items() if v is not _SENTINEL}


# --------------------------------------------------------------------------- #
# Property
# --------------------------------------------------------------------------- #
def property_payload(**overrides) -> dict:
    """A registrable residential tank site.

    The two coverage figures are omitted by default so the server's declared
    defaults apply; pass them explicitly to exercise the waterfall capacities.
    """
    payload = {
        "street_address": "14 Larchmont Lane",
        "state_code": "NJ",
        "county_code": "MONMOUTH",
        "homeowner_name": "Dana Whitfield",
        "homeowner_email": "dana.whitfield@example.com",
        "insurance_carrier_code": "GARDEN-MUTUAL",
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# TankProject
# --------------------------------------------------------------------------- #
def tank_project_payload(property_id: str, **overrides) -> dict:
    """A decommissioning project with both scope figures pinned explicitly."""
    payload = {
        "property_id": property_id,
        "baseline_scope_cubic_yards": DEFAULT_BASELINE_SCOPE_CUBIC_YARDS,
        "excavation_limit_cubic_yards": DEFAULT_EXCAVATION_LIMIT_CUBIC_YARDS,
    }
    payload.update(overrides)
    return _prune(payload)


def minimal_tank_project_payload(property_id: str, **overrides) -> dict:
    """Only the parent reference, so both scope figures take their defaults."""
    payload = {"property_id": property_id}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# The tank-locating sweep survey
# --------------------------------------------------------------------------- #
def sweep_survey_payload(**overrides) -> dict:
    """One located tank with all five descriptors.

    The descriptor set below scores well under the abandonment threshold, so the
    recommendation is REMOVAL and a REMOVAL work order needs no override reason:
    depth 60 inches contributes 18.0, clearance 90 inches contributes 0.0, the
    tank is not under a structure, its 550-gallon capacity contributes 8.0 and
    its steel shell contributes 10.0.
    """
    payload = {
        "survey_method": "GPR",
        "tanks_detected_count": 1,
        "tank_capacity_gallons": 550,
        "tank_depth_to_top_inches": 60,
        "tank_distance_to_foundation_inches": 90,
        "tank_under_structure": False,
        "tank_material": "STEEL",
    }
    payload.update(overrides)
    return _prune(payload)


def abandonment_sweep_survey_payload(**overrides) -> dict:
    """Every factor at or beyond its clamp, so the raw sum overshoots the cap."""
    payload = {
        "survey_method": "MAGNETOMETER",
        "tanks_detected_count": 1,
        "tank_capacity_gallons": 1000,
        "tank_depth_to_top_inches": 200,
        "tank_distance_to_foundation_inches": 0,
        "tank_under_structure": True,
        "tank_material": "STEEL",
    }
    payload.update(overrides)
    return _prune(payload)


def no_tank_sweep_survey_payload(**overrides) -> dict:
    """A sweep that located nothing, so the five descriptors are not required."""
    payload = {
        "survey_method": "MAGNETOMETER",
        "tanks_detected_count": 0,
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# HomeownerDisclosure
# --------------------------------------------------------------------------- #
def disclosure_payload(tank_project_id: str, **overrides) -> dict:
    payload = {
        "tank_project_id": tank_project_id,
        "disclosure_kind": "SWEEP_FINDINGS",
    }
    payload.update(overrides)
    return _prune(payload)


def disclosure_response_payload(**overrides) -> dict:
    payload = {
        "response": "ACKNOWLEDGED",
        "response_channel": "PORTAL",
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Permit
# --------------------------------------------------------------------------- #
def permit_payload(tank_project_id: str, **overrides) -> dict:
    payload = {
        "tank_project_id": tank_project_id,
        "permit_type": "MUNICIPAL_DECOMMISSION",
    }
    payload.update(overrides)
    return _prune(payload)


def permit_decision_payload(decision: str = "ISSUED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Crew
# --------------------------------------------------------------------------- #
def crew_payload(**overrides) -> dict:
    payload = {
        "crew_name": "Redbank Excavation Crew",
        "cert_level": "TANK_TECH_II",
        "mobilization_buffer_minutes": DEFAULT_MOBILIZATION_BUFFER_MINUTES,
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# DecommissionWorkOrder
# --------------------------------------------------------------------------- #
def work_order_payload(
    tank_project_id: str,
    crew_id: str,
    scheduled_start_at: str = "2026-08-06T13:00:00Z",
    scheduled_end_at: str = "2026-08-06T21:00:00Z",
    **overrides,
) -> dict:
    """An eight-hour booking executing the recommended REMOVAL method."""
    payload = {
        "tank_project_id": tank_project_id,
        "crew_id": crew_id,
        "method": "REMOVAL",
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return _prune(payload)


def field_event_payload(event: str, **overrides) -> dict:
    payload = {"event": event}
    payload.update(overrides)
    return _prune(payload)


def field_complete_payload(
    actual_excavated_cubic_yards: float = 9.5,
    hauled_tons: float = 12.4,
    **overrides,
) -> dict:
    """The COMPLETE event with both mandatory crew-reported figures."""
    payload = {
        "event": "COMPLETE",
        "actual_excavated_cubic_yards": actual_excavated_cubic_yards,
        "hauled_tons": hauled_tons,
    }
    payload.update(overrides)
    return _prune(payload)


def billing_event_payload(event: str, **overrides) -> dict:
    payload = {"event": event}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Laboratory
# --------------------------------------------------------------------------- #
def laboratory_payload(**overrides) -> dict:
    """A laboratory with all four operating parameters pinned explicitly."""
    payload = {
        "lab_name": "Shore Analytical Services",
        "accredited": DEFAULT_ACCREDITED,
        "committed_turnaround_hours": DEFAULT_COMMITTED_TURNAROUND_HOURS,
        "holding_time_hours": DEFAULT_HOLDING_TIME_HOURS,
        "max_concurrent_analyses": DEFAULT_MAX_CONCURRENT_ANALYSES,
    }
    payload.update(overrides)
    return _prune(payload)


def minimal_laboratory_payload(**overrides) -> dict:
    """Only the name, so all four operating parameters take their defaults."""
    payload = {"lab_name": "Shore Analytical Services"}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# SoilSample
# --------------------------------------------------------------------------- #
def soil_sample_payload(
    tank_project_id: str,
    work_order_id: str,
    laboratory_id: str,
    sample_point: str = "TANK_BOTTOM",
    depth_inches: int = 96,
    retest_of_sample_id: Optional[str] = _SENTINEL,
    **overrides,
) -> dict:
    payload = {
        "tank_project_id": tank_project_id,
        "work_order_id": work_order_id,
        "laboratory_id": laboratory_id,
        "sample_point": sample_point,
        "depth_inches": depth_inches,
        "retest_of_sample_id": retest_of_sample_id,
    }
    payload.update(overrides)
    return _prune(payload)


def custody_event_payload(event: str, **overrides) -> dict:
    payload = {"event": event}
    payload.update(overrides)
    return _prune(payload)


def result_payload(
    tph_mg_kg: float = 120.0, benzene_mg_kg: float = 0.05, **overrides
) -> dict:
    """A clean analytical result: both figures well below their action levels."""
    payload = {"tph_mg_kg": tph_mg_kg, "benzene_mg_kg": benzene_mg_kg}
    payload.update(overrides)
    return _prune(payload)


def retract_result_payload(**overrides) -> dict:
    payload = {"reason": "chromatogram baseline drift invalidates the quantitation"}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# RemediationChangeOrder
# --------------------------------------------------------------------------- #
def change_order_payload(
    tank_project_id: str,
    expected_project_version: int,
    additional_cubic_yards: float = 3.5,
    unit_rate_cents: int = 1001,
    disposal_class: str = "NON_HAZARDOUS",
    supersedes_change_order_id: Optional[str] = _SENTINEL,
    **overrides,
) -> dict:
    payload = {
        "tank_project_id": tank_project_id,
        "additional_cubic_yards": additional_cubic_yards,
        "unit_rate_cents": unit_rate_cents,
        "disposal_class": disposal_class,
        "expected_project_version": expected_project_version,
        "supersedes_change_order_id": supersedes_change_order_id,
    }
    payload.update(overrides)
    return _prune(payload)


def change_order_decision_payload(decision: str = "APPROVED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# TrustFundClaim
# --------------------------------------------------------------------------- #
def trust_fund_claim_payload(
    tank_project_id: str,
    expected_project_version: int,
    variant: str = "PRELIMINARY_ESTIMATE",
    claimed_costs_cents: int = 900000,
    **overrides,
) -> dict:
    payload = {
        "tank_project_id": tank_project_id,
        "variant": variant,
        "claimed_costs_cents": claimed_costs_cents,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return _prune(payload)


def claim_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# NFALetter
# --------------------------------------------------------------------------- #
def nfa_letter_payload(
    tank_project_id: str, closing_date: str = "2026-09-15T00:00:00Z", **overrides
) -> dict:
    payload = {"tank_project_id": tank_project_id, "closing_date": closing_date}
    payload.update(overrides)
    return _prune(payload)


def rescind_payload(**overrides) -> dict:
    payload = {
        "rescission_reason": "a neighbouring monitoring well returned dirty",
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# InsuranceNotification
# --------------------------------------------------------------------------- #
def insurance_notification_payload(
    tank_project_id: str, notification_kind: str = "FIRST_PARTY", **overrides
) -> dict:
    payload = {
        "tank_project_id": tank_project_id,
        "notification_kind": notification_kind,
    }
    payload.update(overrides)
    return _prune(payload)


#: Re-exported so a test can spell an omission explicitly.
OMIT = _SENTINEL
