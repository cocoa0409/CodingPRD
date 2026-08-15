"""Payload factories — one per creatable entity, input fields only (PRD §3)."""

from .constants import DEFAULT_PLACEMENT_DATE


def farm_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Farm",
        "certification_program": "CONVENTIONAL",
        "daily_overhead_cents": 12000,
    }
    defaults.update(overrides)
    return defaults


def house_payload(farm_id, **overrides) -> dict:
    defaults = {
        "farm_id": farm_id,
        "house_code": "H1",
        "environment_type": "CAGED",
        "capacity_hens": 2000,
    }
    defaults.update(overrides)
    return defaults


def flock_payload(house_id, **overrides) -> dict:
    defaults = {
        "house_id": house_id,
        "breed_code": "HYLINE_BROWN",
        "breed_peak_rate_pct": 95.0,
        "placement_date": DEFAULT_PLACEMENT_DATE,
        "initial_hen_count": 1000,
        "pullet_cost_cents": 420000,
    }
    defaults.update(overrides)
    return defaults


def feed_delivery_payload(farm_id, **overrides) -> dict:
    defaults = {
        "farm_id": farm_id,
        "delivered_at": "2026-07-01",
        "quantity_kg": 5000,
        "cost_per_kg_cents": 50,
    }
    defaults.update(overrides)
    return defaults


def production_day_payload(flock_id, **overrides) -> dict:
    defaults = {
        "flock_id": flock_id,
        "lay_date": "2026-07-31",
        "eggs_collected": 240,
        "rejected_eggs": 0,
        "feed_issued_kg": 0,
        "mortality_count": 0,
    }
    defaults.update(overrides)
    return defaults


def grading_run_payload(flock_id, **overrides) -> dict:
    defaults = {
        "flock_id": flock_id,
        "grade": "A",
        "eggs_to_grade": 240,
    }
    defaults.update(overrides)
    return defaults


def grading_submit_payload(
    peewee_count=0,
    small_count=0,
    medium_count=0,
    large_count=0,
    xlarge_count=0,
    jumbo_count=0,
    cracked_count=0,
    dirty_count=0,
    blood_spot_count=0,
) -> dict:
    """The six size-class counts plus three undergrade counts (PRD §3.4)."""
    return {
        "peewee_count": peewee_count,
        "small_count": small_count,
        "medium_count": medium_count,
        "large_count": large_count,
        "xlarge_count": xlarge_count,
        "jumbo_count": jumbo_count,
        "cracked_count": cracked_count,
        "dirty_count": dirty_count,
        "blood_spot_count": blood_spot_count,
    }


def contract_payload(farm_id, **overrides) -> dict:
    defaults = {
        "farm_id": farm_id,
        "retailer_name": "RetailCo",
        "pricing_model": "MARKET_INDEX",
        "spread_cents": 5,
        "margin_pct": 0,
        "claim_premium_pct": 0,
        "claim_required": "NONE",
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
        "weekly_min_dozen": 10,
        "max_open_dozen": 1000,
    }
    defaults.update(overrides)
    return defaults


def settlement_payload(contract_id, expected_contract_version, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "period_start": "2026-07-20",
        "period_end": "2026-07-26",
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def salmonella_test_payload(flock_id, **overrides) -> dict:
    defaults = {
        "flock_id": flock_id,
        "test_type": "ENVIRONMENTAL",
        "scheduled_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def audit_payload(farm_id, **overrides) -> dict:
    defaults = {
        "farm_id": farm_id,
        "standard": "FDA_EGG_SAFETY",
        "audit_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def record_findings_payload(**overrides) -> dict:
    defaults = {
        "findings_count": 0,
        "corrective_actions_open": 0,
    }
    defaults.update(overrides)
    return defaults


def recall_payload(farm_id, **overrides) -> dict:
    defaults = {
        "farm_id": farm_id,
        "reason": "QUALITY",
        "pack_window_start": "2026-08-01",
        "pack_window_end": "2026-08-05",
    }
    defaults.update(overrides)
    return defaults


def disposition_payload(flock_id, **overrides) -> dict:
    defaults = {
        "flock_id": flock_id,
        "method": "RENDERING",
        "hen_count": 100,
        "revenue_cents": 0,
    }
    defaults.update(overrides)
    return defaults
