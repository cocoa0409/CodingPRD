"""Payload factories — one per create/action endpoint, input fields only (PRD §4)."""
from .constants import (
    DEFAULT_BASE_PRICE_CENTS_PER_TON,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    SLOT_AM_END,
    SLOT_AM_START,
)


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "C-1",
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
        "base_price_cents_per_ton": DEFAULT_BASE_PRICE_CENTS_PER_TON,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "name": "M1",
        "member_code": "M-1001",
        "haul_distance_miles": 22.5,
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    defaults = {
        "name": "ST",
        "booking_capacity_tons": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_pile_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "capacity_tons": 200,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(campaign_id: str, station_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "station_id": station_id,
        "slot_start": SLOT_AM_START,
        "slot_end": SLOT_AM_END,
        "estimated_tons": 20,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(booking_id: str, **overrides) -> dict:
    defaults = {"booking_id": booking_id}
    defaults.update(overrides)
    return defaults


def weigh_payload(gross_weight_lbs: float, tare_weight_lbs: float, **overrides) -> dict:
    defaults = {
        "gross_weight_lbs": gross_weight_lbs,
        "tare_weight_lbs": tare_weight_lbs,
    }
    defaults.update(overrides)
    return defaults


def accept_payload(pile_id: str, **overrides) -> dict:
    defaults = {"pile_id": pile_id}
    defaults.update(overrides)
    return defaults


def create_sample_payload(ticket_id: str, sample_type: str, **overrides) -> dict:
    defaults = {"ticket_id": ticket_id, "sample_type": sample_type}
    defaults.update(overrides)
    return defaults


def record_result_payload(sugar_pct: float, trash_pct: float, **overrides) -> dict:
    defaults = {"sugar_pct": sugar_pct, "trash_pct": trash_pct}
    defaults.update(overrides)
    return defaults


def create_loss_event_payload(pile_id: str, method: str, survey_at: str,
                              window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "pile_id": pile_id,
        "method": method,
        "survey_at": survey_at,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def open_accrual_payload(estimated_pool_value_cents: int, **overrides) -> dict:
    defaults = {"estimated_pool_value_cents": estimated_pool_value_cents}
    defaults.update(overrides)
    return defaults


def close_pool_payload(gross_pool_value_cents: int, **overrides) -> dict:
    defaults = {"gross_pool_value_cents": gross_pool_value_cents}
    defaults.update(overrides)
    return defaults


def create_installment_payload(pct_of_estimated: float, expected_pool_version: int,
                               **overrides) -> dict:
    defaults = {
        "pct_of_estimated": pct_of_estimated,
        "expected_pool_version": expected_pool_version,
    }
    defaults.update(overrides)
    return defaults


def complete_reclaim_payload(shipped_lbs: float, **overrides) -> dict:
    defaults = {"shipped_lbs": shipped_lbs}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def revise_settlement_payload(expected_settlement_version: int, **overrides) -> dict:
    defaults = {"expected_settlement_version": expected_settlement_version}
    defaults.update(overrides)
    return defaults


def generate_settlements_payload(campaign_id: str, **overrides) -> dict:
    defaults = {"campaign_id": campaign_id}
    defaults.update(overrides)
    return defaults
