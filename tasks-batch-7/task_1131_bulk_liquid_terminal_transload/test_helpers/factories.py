"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid

from .constants import DEFAULTS


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": "Test Customer", "contact_email": "ops@example.com"}
    defaults.update(overrides)
    return defaults


def create_tank_payload(**overrides) -> dict:
    defaults = {
        "tank_code": _unique("T"),
        "product_grade": "DIESEL",
        "capacity_bbl": DEFAULTS["TANK_CAPACITY_BBL"],
        "heel_bbl": 0,
    }
    defaults.update(overrides)
    return defaults


def create_terminal_resource_payload(**overrides) -> dict:
    defaults = {
        "resource_code": _unique("DOCK"),
        "resource_type": "DOCK",
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_grade": "DIESEL",
        "committed_capacity_bbl": DEFAULTS["COMMITTED_CAPACITY_BBL"],
        "min_monthly_throughput_bbl": DEFAULTS["MIN_MONTHLY_THROUGHPUT_BBL"],
        "throughput_fee_per_bbl": DEFAULTS["THROUGHPUT_FEE_PER_BBL"],
        "shortfall_fee_per_bbl": DEFAULTS["SHORTFALL_FEE_PER_BBL"],
        "loss_allowance_pct": DEFAULTS["LOSS_ALLOWANCE_PCT"],
        "excess_loss_rate_per_bbl": DEFAULTS["EXCESS_LOSS_RATE_PER_BBL"],
        "start_date": DEFAULTS["LEASE_START"],
        "end_date": DEFAULTS["LEASE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(expected_lease_version, **proposed) -> dict:
    payload = {"expected_lease_version": expected_lease_version}
    payload.update(proposed)
    return payload


def create_allocation_payload(tank_id, **overrides) -> dict:
    defaults = {
        "tank_id": tank_id,
        "allocated_bbl": DEFAULTS["ALLOCATED_BBL"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(tank_id, **overrides) -> dict:
    defaults = {
        "permit_type": "VAPOR_CONTROL",
        "tank_id": tank_id,
        "valid_from": "2026-05-10T00:00:00Z",
        "valid_until": "2026-05-10T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_movement_payload(lease_id, tank_id, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "tank_id": tank_id,
        "direction": "RECEIPT",
        "mode": "VESSEL",
        "product_grade": "DIESEL",
        "declared_volume_bbl": DEFAULTS["DECLARED_VOLUME_BBL"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_gauge_ticket_payload(**overrides) -> dict:
    defaults = {
        "ticket_type": "OPENING",
        "observed_volume_bbl": 0,
        "observed_temp_f": 60,
        "observed_at": "2026-05-10T08:05:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(**overrides) -> dict:
    defaults = {"sample_type": "INLINE"}
    defaults.update(overrides)
    return defaults


def create_record_result_payload(**overrides) -> dict:
    defaults = {"lab_result": "PASSED", "specific_gravity": 0.85}
    defaults.update(overrides)
    return defaults


def create_statement_payload(period=DEFAULTS["STATEMENT_PERIOD"], **overrides) -> dict:
    payload = {"period": period}
    payload.update(overrides)
    return payload
