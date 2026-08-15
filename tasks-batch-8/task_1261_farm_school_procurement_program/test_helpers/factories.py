"""Payload factories — one per entity, input fields only (PRD sections 3.1-3.8)."""
import itertools

from .constants import (
    DEFAULT_GRANT_AWARD_CENTS,
    DEFAULT_LOCAL_SPEND_TARGET_PCT,
    DEFAULT_RADIUS_MILES,
    DEFAULT_YEAR_END,
    DEFAULT_YEAR_START,
)

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_program_year_payload(**overrides) -> dict:
    defaults = {
        "school_year_label": "Y1",
        "start_date": DEFAULT_YEAR_START,
        "end_date": DEFAULT_YEAR_END,
        "local_radius_miles": DEFAULT_RADIUS_MILES,
        "preference_model": "TIERED",
        "grant_award_cents": DEFAULT_GRANT_AWARD_CENTS,
        "local_spend_target_pct": DEFAULT_LOCAL_SPEND_TARGET_PCT,
    }
    defaults.update(overrides)
    return defaults


def create_farm_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "legal_name": f"Green Acres {i}",
        "contact_email": f"farm{i}@example.com",
        "distance_miles_to_hub": 30,
        "acres": 100,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "SAFETY_CERT",
        "issuer": "StateAg",
        "effective_on": "2026-01-01",
        "expires_on": "2027-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Tomato {i}",
        "category": "PRODUCE",
        "unit": "LB",
        "season_start_week": 1,
        "season_end_week": 20,
    }
    defaults.update(overrides)
    return defaults


def create_offering_payload(**overrides) -> dict:
    defaults = {
        "price_cents_per_unit": 250,
        "max_weekly_quantity": 500,
        "harvest_start_week": 4,
        "harvest_end_week": 12,
    }
    defaults.update(overrides)
    return defaults


def create_forecast_line_payload(**overrides) -> dict:
    defaults = {
        "week_number": 6,
        "planned_quantity": 400,
    }
    defaults.update(overrides)
    return defaults


def create_kitchen_payload(**overrides) -> dict:
    i = _n()
    defaults = {"name": f"Lincoln ES {i}"}
    defaults.update(overrides)
    return defaults


def create_receiving_window_payload(**overrides) -> dict:
    defaults = {
        "weekday": "MON",
        "start_minute": 480,
        "end_minute": 720,
        "capacity_deliveries": 3,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "committed_quantity": 200,
        "harvest_start_week": 5,
        "harvest_end_week": 10,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(**overrides) -> dict:
    return dict(overrides)


def create_delivery_payload(**overrides) -> dict:
    defaults = {
        "delivery_date": "2026-08-10",
        "quantity": 40,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    i = _n()
    defaults = {"invoice_number": f"INV-{i}"}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {"period_month": "2026-08"}
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(**overrides) -> dict:
    return dict(overrides)


def create_substitution_request_payload(**overrides) -> dict:
    defaults = {"quantity": 10, "reason": "SEASONALITY_GAP"}
    defaults.update(overrides)
    return defaults
