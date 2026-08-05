"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_INCENTIVE_RATE_CENTS_PER_KWH,
    DEFAULT_PENALTY_RATE_CENTS_PER_KWH,
    DEFAULT_CAPACITY_INCENTIVE_CENTS_PER_KW,
    DEFAULT_SEASON_START,
    DEFAULT_SEASON_END,
)


def create_program_payload(**overrides) -> dict:
    """Required program inputs. Optional config fields (baseline_method,
    settlement_method, performance_floor_pct, notification_lead_minutes,
    max_events_per_season) are only sent when supplied via overrides."""
    payload = {
        "name": "Summer DR Program",
        "utility_name": "Metro Utility",
        "incentive_rate_cents_per_kwh": DEFAULT_INCENTIVE_RATE_CENTS_PER_KWH,
        "penalty_rate_cents_per_kwh": DEFAULT_PENALTY_RATE_CENTS_PER_KWH,
        "capacity_incentive_cents_per_kw": DEFAULT_CAPACITY_INCENTIVE_CENTS_PER_KW,
        "season_start_date": DEFAULT_SEASON_START,
        "season_end_date": DEFAULT_SEASON_END,
    }
    payload.update(overrides)
    return payload


def create_aggregator_payload(**overrides) -> dict:
    payload = {"name": "VPP Aggregator", "contact_email": "agg@example.com"}
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": "Premise Owner",
        "email": "cust@example.com",
        "service_address": "1 Main St",
        "utility_account_id": "UA-1001",
    }
    payload.update(overrides)
    return payload


def create_device_payload(customer_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "device_type": "BATTERY",
        "nameplate_kw": 10,
        "capacity_kwh": 20,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(device_id, program_id, committed_kw=5, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "program_id": program_id,
        "committed_kw": committed_kw,
    }
    payload.update(overrides)
    return payload


def create_dispatch_event_payload(program_id, window_start, window_end,
                                  target_reduction_kw=5, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "window_start": window_start,
        "window_end": window_end,
        "target_reduction_kw": target_reduction_kw,
    }
    payload.update(overrides)
    return payload


def create_meter_reading_payload(interval_start, interval_end, kw_load,
                                 reading_type, dispatch_event_id=None, **overrides) -> dict:
    payload = {
        "interval_start": interval_start,
        "interval_end": interval_end,
        "kw_load": kw_load,
        "reading_type": reading_type,
    }
    if dispatch_event_id is not None:
        payload["dispatch_event_id"] = dispatch_event_id
    payload.update(overrides)
    return payload


def create_settlement_payload(dispatch_event_id, **overrides) -> dict:
    payload = {"dispatch_event_id": dispatch_event_id}
    payload.update(overrides)
    return payload
