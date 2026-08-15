"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import COOP_DEFAULTS


def create_cooperative_payload(**overrides) -> dict:
    defaults = dict(COOP_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {"legal_name": "Test Member", "member_type": "RESIDENTIAL", "district_id": 1}
    defaults.update(overrides)
    return defaults


def create_service_location_payload(**overrides) -> dict:
    defaults = {"address": "1 Test Ln", "rate_class": "RESIDENTIAL"}
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = {
        "code": "RS-1",
        "rate_class": "RESIDENTIAL",
        "effective_from": "2025-01-01T00:00:00Z",
        "customer_charge_cents": 2000,
        "tiers": [{"up_to_kwh": None, "cents_per_kwh": 10}],
        "demand_charge_cents_per_kw": 0,
        "irrigation_offseason_discount_pct": 0,
        "load_management_credit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_meter_reading_payload(**overrides) -> dict:
    defaults = {
        "reading_at": "2026-08-01T00:00:00Z",
        "kwh_register": 0,
        "demand_kw": 0,
        "source": "AMR",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "billing_period_start": "2026-07-01T00:00:00Z",
        "billing_period_end": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(**overrides) -> dict:
    defaults = {"fiscal_year": 2025, "method": "FLAT_PER_MEMBER"}
    defaults.update(overrides)
    return defaults


def create_retirement_payload(**overrides) -> dict:
    defaults = {"method": "FIFO_OLDEST", "total_retire_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_outage_report_payload(**overrides) -> dict:
    defaults = {"cause": "WEATHER"}
    defaults.update(overrides)
    return defaults


def create_row_agreement_payload(**overrides) -> dict:
    defaults = {"easement_width_ft": 30}
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {"device_type": "WATER_HEATER"}
    defaults.update(overrides)
    return defaults


def create_service_order_payload(**overrides) -> dict:
    defaults = {
        "order_type": "NEW_SERVICE",
        "distance_ft": 100,
        "requires_road_bore": False,
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(**overrides) -> dict:
    defaults = {
        "year": 2026,
        "seats": [1],
        "voting_opens_at": "2026-08-01T00:00:00Z",
        "voting_closes_at": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ballot_payload(**overrides) -> dict:
    defaults = {"district": 1, "candidate_name": "Cand A", "is_proxy": False}
    defaults.update(overrides)
    return defaults
