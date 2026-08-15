"""Payload factories — one per creatable resource, input fields only."""
from uuid import uuid4

from .constants import DEFAULT_ITEM, DEFAULT_RATE_CARD


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def create_renter_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("Renter"),
        "renter_type": "THEATRE",
        "credit_limit_cents": 10000000,
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "insurer_name": "InsCo",
        "policy_number": _unique("POL"),
        "coverage_cents": 600000,
        "effective_date": "2026-01-01",
        "expiry_date": "2027-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_RATE_CARD)
    defaults["name"] = _unique("RC")
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_ITEM)
    defaults["name"] = _unique("Item")
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "barcode": _unique("BC"),
        "condition_grade": "B",
        "acquisition_date": "2025-01-15",
        "acquisition_cost_cents": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_production_payload(**overrides) -> dict:
    defaults = {
        "title": _unique("Prod"),
        "rehearsal_start_date": "2026-08-10",
        "performance_start_date": "2026-09-01",
        "closing_date": "2026-10-26",
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    defaults = {
        "quantity": 1,
        "window_start_date": "2026-09-01",
        "window_end_date": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults


def create_pull_list_payload(**overrides) -> dict:
    return dict(overrides)


def create_fitting_payload(**overrides) -> dict:
    defaults = {"alteration_type": "HEM"}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {"claim_type": "DAMAGE"}
    defaults.update(overrides)
    return defaults


def create_check_in_payload(**overrides) -> dict:
    defaults = {
        "condition_grade_after": "B",
        "damage_severity": "NONE",
        "restoration_complete": True,
    }
    defaults.update(overrides)
    return defaults
