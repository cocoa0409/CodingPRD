"""Payload factories — one per resource, input fields only."""

import itertools
from typing import List, Optional

from .constants import TEST_DEFAULTS

_permit_seq = itertools.count(1)


def next_permit_number() -> str:
    """A unique Corps permit identifier of the shape LLL-DDDD-DDDDD."""
    n = next(_permit_seq)
    return f"SAJ-2026-{n:05d}"


# ─── Parties ──────────────────────────────────────────

def create_sponsor_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Cypress Bend Restoration Partners LLC",
        "legal_entity_type": "PRIVATE_ENTREPRENEURIAL",
        "performance_bond_cents": TEST_DEFAULTS["SPONSOR_BOND_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_permittee_payload(**overrides) -> dict:
    payload = {
        "organization_name": "Gulf Coast Terminals Inc",
        "permit_number": next_permit_number(),
        "impact_huc8_code": TEST_DEFAULTS["SITE_HUC8"],
        "required_credits": 12.00,
    }
    payload.update(overrides)
    return payload


def create_deposit_payload(amount_cents: int = 40_000_000, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_irt_member_payload(**overrides) -> dict:
    payload = {
        "member_name": "Reviewer One",
        "agency": "USACE",
    }
    payload.update(overrides)
    return payload


# ─── Bank site ────────────────────────────────────────

def create_bank_payload(sponsor_id: str, **overrides) -> dict:
    payload = {
        "sponsor_id": sponsor_id,
        "site_name": "Cypress Bend",
        "site_huc8_code": TEST_DEFAULTS["SITE_HUC8"],
        "service_area_huc8_codes": list(TEST_DEFAULTS["SERVICE_AREA"]),
        "hgm_class": TEST_DEFAULTS["HGM_CLASS"],
        "annual_stewardship_cost_cents": TEST_DEFAULTS["ANNUAL_STEWARDSHIP_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_easement_payload(deed_reference: str = "BK 4821 PG 116", **overrides) -> dict:
    payload = {"deed_reference": deed_reference}
    payload.update(overrides)
    return payload


def create_stewardship_contribution_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ─── Prospectus ───────────────────────────────────────

def create_prospectus_payload(bank_id: str, **overrides) -> dict:
    payload = {
        "bank_id": bank_id,
        "objective_summary": (
            "Restore depressional wetland hydrology on 205 acres of prior-converted "
            "cropland, replant native forested and emergent communities, and suppress "
            "invasive species to serve documented watershed need."
        ),
        "proposed_credits": 100.00,
    }
    payload.update(overrides)
    return payload


def create_vote_payload(position: str = "CONCUR", **overrides) -> dict:
    payload = {"position": position}
    payload.update(overrides)
    return payload


# ─── Work plan ────────────────────────────────────────

CANONICAL_CREDIT_STRATA: List[dict] = [
    {"stratum_code": "UPLAND_BUFFER", "acres": 101.50, "lift_factor": 0.375},
    {"stratum_code": "EMERGENT_MARSH", "acres": 70.50, "lift_factor": 0.625},
    {"stratum_code": "FORESTED_WETLAND", "acres": 33.30, "lift_factor": 0.500},
]

CANONICAL_PERFORMANCE_STANDARDS: List[dict] = [
    {
        "standard_code": "HYDROPERIOD_DAYS",
        "comparator": "GTE",
        "threshold_value": 120,
        "weight": 0.300,
        "effective_from_year": 1,
    },
    {
        "standard_code": "INVASIVE_COVER_PCT",
        "comparator": "LTE",
        "threshold_value": 10.0,
        "weight": 0.250,
        "effective_from_year": 1,
    },
    {
        "standard_code": "NATIVE_COVER_PCT",
        "comparator": "GTE",
        "threshold_value": 80.0,
        "weight": 0.300,
        "effective_from_year": 3,
    },
    {
        "standard_code": "STEM_DENSITY_PER_ACRE",
        "comparator": "GTE",
        "threshold_value": 400,
        "weight": 0.150,
        "effective_from_year": 3,
    },
]


def create_work_plan_payload(bank_id: str, **overrides) -> dict:
    payload = {
        "bank_id": bank_id,
        "hydrology_restoration_acres": 205.30,
        "planting_acres": 104.00,
        "invasive_control_acres": 33.30,
        "invasive_control_protocol": "INTEGRATED",
        "credit_strata": [dict(s) for s in CANONICAL_CREDIT_STRATA],
        "performance_standards": [dict(s) for s in CANONICAL_PERFORMANCE_STANDARDS],
    }
    payload.update(overrides)
    return payload


def decide_work_plan_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Release milestones ───────────────────────────────

def create_milestone_payload(
    bank_id: str,
    milestone_code: str = "INSTRUMENT_EXECUTION",
    release_pct: float = 0.150,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-09-01T00:00:00Z",
    predecessor_milestone_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "bank_id": bank_id,
        "milestone_code": milestone_code,
        "release_pct": release_pct,
        "window_start": window_start,
        "window_end": window_end,
    }
    if predecessor_milestone_id is not None:
        payload["predecessor_milestone_id"] = predecessor_milestone_id
    payload.update(overrides)
    return payload


def approve_release_payload(expected_bank_version: int, **overrides) -> dict:
    payload = {"expected_bank_version": expected_bank_version}
    payload.update(overrides)
    return payload


# ─── Monitoring ───────────────────────────────────────

def measurements(**by_code) -> List[dict]:
    """Build a measurements array from standard_code=value keyword pairs."""
    return [
        {"standard_code": code, "measured_value": value}
        for code, value in by_code.items()
    ]


YEAR1_PASSING_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 130},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 6.0},
]

YEAR3_PASSING_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 128},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 7.0},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 86.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 430},
]


def create_monitoring_report_payload(
    bank_id: str,
    monitoring_year: int = 1,
    window_start: str = "2027-03-01T00:00:00Z",
    window_end: str = "2027-06-01T00:00:00Z",
    measurements_array: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    payload = {
        "bank_id": bank_id,
        "monitoring_year": monitoring_year,
        "window_start": window_start,
        "window_end": window_end,
        "measurements": (
            [dict(m) for m in measurements_array]
            if measurements_array is not None
            else [dict(m) for m in YEAR1_PASSING_MEASUREMENTS]
        ),
    }
    payload.update(overrides)
    return payload


def review_report_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def inspect_payload(outcome: str = "CLEARED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ─── Credit sales ─────────────────────────────────────

def create_credit_sale_payload(
    bank_id: str,
    permittee_id: str,
    credits_requested: float,
    expected_bank_version: int,
    impact_huc8_code: str = TEST_DEFAULTS["SITE_HUC8"],
    **overrides,
) -> dict:
    payload = {
        "bank_id": bank_id,
        "permittee_id": permittee_id,
        "credits_requested": credits_requested,
        "impact_huc8_code": impact_huc8_code,
        "expected_bank_version": expected_bank_version,
    }
    payload.update(overrides)
    return payload


def cancel_sale_payload(cancelled_reason: str = "BUYER_WITHDREW", **overrides) -> dict:
    payload = {"cancelled_reason": cancelled_reason}
    payload.update(overrides)
    return payload
