"""Payload factories — one per entity, input fields only (PRD §3)."""
import copy

from .constants import (
    DEFAULT_POSSESSION_START,
    DEFAULT_OWNERSHIP_ACQUIRED,
    DEFAULT_WEIGHED_AT,
    DEFAULT_PREMIUM_SCHEDULE,
    DEFAULT_STATE_QUALIFY_RANK,
    DEFAULT_SALE_RANK_THRESHOLD,
    DEFAULT_SPECIES_SALE_ORDER,
    OWNERSHIP_DEADLINE,
    POSSESSION_DEADLINE,
    TEST_DEFAULTS,
)


def create_fair_payload(**overrides) -> dict:
    defaults = {
        "name": "County Fair",
        "ownership_deadline_at": OWNERSHIP_DEADLINE,
        "possession_deadline_at": POSSESSION_DEADLINE,
        "premium_budget_cents": TEST_DEFAULTS["PREMIUM_BUDGET_CENTS"],
        "commission_rate": TEST_DEFAULTS["COMMISSION_RATE"],
        "buyer_premium_rate": TEST_DEFAULTS["BUYER_PREMIUM_RATE"],
        "yardage_fee_cents": TEST_DEFAULTS["YARDAGE_FEE_CENTS"],
        "premium_cap_cents": TEST_DEFAULTS["PREMIUM_CAP_CENTS"],
        "premium_schedule": copy.deepcopy(DEFAULT_PREMIUM_SCHEDULE),
        "state_qualify_rank": copy.deepcopy(DEFAULT_STATE_QUALIFY_RANK),
        "sale_rank_threshold": copy.deepcopy(DEFAULT_SALE_RANK_THRESHOLD),
        "species_sale_order": list(DEFAULT_SPECIES_SALE_ORDER),
    }
    defaults.update(overrides)
    return defaults


def create_exhibitor_payload(fair_id, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "full_name": "Ann A",
        "organization": "FFA",
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(fair_id, exhibitor_id, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "exhibitor_id": exhibitor_id,
        "species": "MARKET_STEER",
        "tag_number": "S-001",
        "ownership_acquired_at": DEFAULT_OWNERSHIP_ACQUIRED,
        "possession_start_at": DEFAULT_POSSESSION_START,
    }
    defaults.update(overrides)
    return defaults


def create_weigh_ticket_payload(entry_id, expected_entry_version, **overrides) -> dict:
    defaults = {
        "entry_id": entry_id,
        "weight_lbs": 1200,
        "weighed_at": DEFAULT_WEIGHED_AT,
        "expected_entry_version": expected_entry_version,
    }
    defaults.update(overrides)
    return defaults


def create_class_payload(fair_id, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "species": "MARKET_STEER",
        "class_code": "STEER-A",
        "weight_min_lbs": 1000,
        "weight_max_lbs": 1500,
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_judge_payload(fair_id, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "full_name": "Judge Jo",
        "qualified_species": ["MARKET_STEER"],
    }
    defaults.update(overrides)
    return defaults


def create_ring_slot_payload(fair_id, class_id, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "class_id": class_id,
        "ring_name": "MAIN",
        "starts_at": "2026-07-10T09:00:00Z",
        "ends_at": "2026-07-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_buyer_payload(fair_id, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "business_name": "Packers Inc",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(lot_id, buyer_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "buyer_id": buyer_id,
        "amount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_payload(entry_id, **overrides) -> dict:
    defaults = {
        "entry_id": entry_id,
        "disposition_type": "RETURN",
        "destination": "Home Farm",
    }
    defaults.update(overrides)
    return defaults


def create_health_inspection_payload(entry_id, **overrides) -> dict:
    defaults = {
        "entry_id": entry_id,
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_affidavit_payload(entry_id, **overrides) -> dict:
    defaults = {"entry_id": entry_id}
    defaults.update(overrides)
    return defaults
