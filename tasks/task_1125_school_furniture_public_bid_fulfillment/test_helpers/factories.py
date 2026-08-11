"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import (
    BID_DUE_DATE, ORDER_BY_DATE, STANDARD_TIER_TABLE, TEST_DEFAULTS,
    WINDOW_END, WINDOW_START,
)

D = TEST_DEFAULTS


def create_district_payload(**overrides) -> dict:
    defaults = {
        "name": "District D1",
        "annual_cap_cents": D["ANNUAL_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_school_site_payload(**overrides) -> dict:
    defaults = {
        "district_id": None,
        "name": "West ES",
        "daily_crew_capacity": D["SITE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_spec_payload(**overrides) -> dict:
    defaults = {
        "district_id": None,
        "title": "Spec A",
        "bid_due_date": BID_DUE_DATE,
        "delivery_window_start": WINDOW_START,
        "delivery_window_end": WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_spec_line_payload(**overrides) -> dict:
    defaults = {
        "bid_spec_id": None,
        "manufacturer": D["MANUFACTURER"],
        "model": D["MODEL"],
        "qty": D["SPEC_LINE_QTY"],
        "max_unit_price_cents": D["MAX_UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_coop_agreement_payload(**overrides) -> dict:
    defaults = {
        "name": "Coop C1",
        "contract_year": D["FISCAL_YEAR"],
        "tier_table": [dict(row) for row in STANDARD_TIER_TABLE],
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(**overrides) -> dict:
    defaults = {
        "bid_spec_id": None,
        "district_id": None,
        "pricing_mode": "AWARD_FLAT",
        "flat_unit_price_cents": D["FLAT_UNIT_PRICE_CENTS"],
        "install_rate_cents": D["INSTALL_RATE_CENTS"],
        "order_by_date": ORDER_BY_DATE,
        "warranty_years": D["WARRANTY_YEARS"],
        "extended_years": 0,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(**overrides) -> dict:
    defaults = {
        "award_id": None,
        "po_number": "PO-1",
        "fiscal_year": D["FISCAL_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_po_line_payload(**overrides) -> dict:
    defaults = {
        "purchase_order_id": None,
        "spec_line_id": None,
        "ordered_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "purchase_order_id": None,
        "school_site_id": None,
        "scheduled_date": "2026-07-01",
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {"name": "Crew Alpha"}
    defaults.update(overrides)
    return defaults


def create_install_task_payload(**overrides) -> dict:
    defaults = {
        "shipment_id": None,
        "crew_id": None,
        "school_site_id": None,
        "room_label": "W-12",
        "start_date": "2026-07-06",
        "end_date": "2026-07-08",
        "crew_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_damage_report_payload(**overrides) -> dict:
    defaults = {
        "po_line_id": None,
        "damaged_qty": 1,
        "discovered_during": "DELIVERY",
        "fault_type": "TRANSIT",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "po_line_id": None,
        "parts_cost_cents": 5000,
        "description": "glide failure",
    }
    defaults.update(overrides)
    return defaults
