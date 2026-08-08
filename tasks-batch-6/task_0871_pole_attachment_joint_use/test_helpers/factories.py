"""Payload factories — one per entity, input (client-supplied) fields only.

Field names are PRD-exact. Only fields the client actually sends are included;
system/computed fields are never part of a create payload.
"""
from .constants import (
    CANONICAL_ANNUAL_RENTAL_RATE_CENTS,
    CANONICAL_LABOR_RATE_CENTS_PER_HOUR,
)


def create_pole_owner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Owner",
        "owner_category": "ELECTRIC_UTILITY",
        "annual_rental_rate_cents": CANONICAL_ANNUAL_RENTAL_RATE_CENTS,
        "make_ready_labor_rate_cents_per_hour": CANONICAL_LABOR_RATE_CENTS_PER_HOUR,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(pole_owner_id: str, **overrides) -> dict:
    defaults = {
        "pole_owner_id": pole_owner_id,
        "crew_name": "C1",
        "region": "R1",
    }
    defaults.update(overrides)
    return defaults


def create_pole_payload(pole_owner_id: str, **overrides) -> dict:
    defaults = {
        "pole_owner_id": pole_owner_id,
        "tag": "P1",
        "height_ft": 35,
        "usable_communication_space_inches": 60,
    }
    defaults.update(overrides)
    return defaults


def create_attacher_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Acme",
        "cin": "CIN1",
        "contact_email": "a@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(pole_id: str, attacher_id: str, **overrides) -> dict:
    defaults = {
        "pole_id": pole_id,
        "attacher_id": attacher_id,
        "requested_space_inches": 6,
        "requested_position_inches": 240,
        "purpose": "FIBER",
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(crew_id: str, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "window_start": "2026-05-10T08:00:00Z",
        "window_end": "2026-05-10T12:00:00Z",
        "estimated_labor_hours": 4,
        "make_ready_required": True,
        "existing_attacher_count": 0,
        "complexity_class": "SIMPLE",
        "findings": "ok",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(pole_id: str, attacher_id: str, **overrides) -> dict:
    defaults = {
        "pole_id": pole_id,
        "attacher_id": attacher_id,
        "discovered_space_inches": 8,
        "discovered_position_inches": 150,
        "good_faith": True,
        "estimated_install_years_ago": 1,
    }
    defaults.update(overrides)
    return defaults


def create_annual_rental_invoice_payload(attacher_id: str, pole_owner_id: str, **overrides) -> dict:
    defaults = {
        "attacher_id": attacher_id,
        "pole_owner_id": pole_owner_id,
        "invoice_type": "ANNUAL_RENTAL",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(attacher_id: str, **overrides) -> dict:
    defaults = {
        "attacher_id": attacher_id,
        "reason": "disputed",
    }
    defaults.update(overrides)
    return defaults
