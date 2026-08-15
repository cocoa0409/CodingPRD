"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_servicer_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {"name": f"Servicer {n}", "code": f"SVC-{n}"}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {"name": f"Crew {n}", "crew_code": f"CR-{n}"}
    defaults.update(overrides)
    return defaults


def create_investor_allowable_payload(**overrides) -> dict:
    defaults = {
        "investor_type": "FHA",
        "item_code": "GRASS_CUT",
        "max_per_occurrence_cents": 3000,
        "max_occurrences_per_calendar_year": 20,
        "aggregate_cap_cents_per_property_year": 60000,
        "requires_bid_over_cents": 999999,
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(servicer_id, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "servicer_id": servicer_id,
        "address_line1": f"{n} Test St",
        "municipality_code": TEST_DEFAULTS["MUNICIPALITY"],
        "state_code": TEST_DEFAULTS["STATE"],
        "zip": TEST_DEFAULTS["ZIP"],
        "investor_type": "FHA",
        "lot_size_sqft": 5000,
        "heating_system": "FORCED_AIR",
        "fixture_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "order_type": "GRASS_CUT",
        "due_date": TEST_DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(property_id, **overrides) -> dict:
    defaults = {"property_id": property_id, "due_date": TEST_DEFAULTS["DUE_DATE"]}
    defaults.update(overrides)
    return defaults


def record_inspection_payload(**overrides) -> dict:
    defaults = {
        "occupancy_determination": "VACANT",
        "interior_access": False,
        "personal_property_present": False,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_payload(property_id, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "property_id": property_id,
        "description": f"household items {n}",
        "valuation_cents": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_recurring_plan_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "service_type": "GRASS_CUT",
        "season_start_md": "04-01",
        "season_end_md": "10-31",
        "interval_days": 14,
        "max_per_season": 6,
    }
    defaults.update(overrides)
    return defaults


def create_code_violation_payload(property_id, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "property_id": property_id,
        "citation_number": f"CV-{n}",
        "violation_class": "MINOR",
        "daily_fine_cents": 500,
        "fine_cap_cents": 20000,
        "cure_deadline": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(property_id, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "property_id": property_id,
        "municipality_code": TEST_DEFAULTS["MUNICIPALITY"],
        "registration_number": f"REG-{n}",
        "fee_cents": 25000,
        "valid_from": "2026-08-01",
        "valid_to": "2027-02-01",
    }
    defaults.update(overrides)
    return defaults


def create_damage_report_payload(property_id, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "property_id": property_id,
        "damage_type": "VANDALISM",
        "severity": "MINOR",
        "is_interior": False,
        "description": f"damage {n}",
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(amount_cents, expected_damage_report_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_damage_report_version": expected_damage_report_version,
    }
    defaults.update(overrides)
    return defaults


def create_photo_evidence_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "category": "BEFORE",
        "taken_at": "2026-08-02T09:00:00Z",
        "content_hash": f"hash-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_expense_line_payload(**overrides) -> dict:
    defaults = {
        "item_code": "GRASS_CUT",
        "quantity": 1,
        "unit_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
