"""Payload factories — one per entity, input fields only."""
import itertools

# Monotonic counters keep emails / VINs unique within a single test run.
_email_counter = itertools.count(1)
_vin_counter = itertools.count(1)


def _unique_email() -> str:
    return f"buyer{next(_email_counter)}@x.test"


# Valid 17-char VINs exclude I, O, Q. Build a deterministic-but-unique VIN by
# embedding a zero-padded counter into a valid template.
def _unique_vin() -> str:
    n = next(_vin_counter)
    suffix = f"{n:06d}"  # 6 digits
    return "1HGCM82633A" + suffix  # 11 + 6 = 17 valid chars


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_type": "INDIVIDUAL",
        "legal_name": "Test Buyer",
        "email": _unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "vin": _unique_vin(),
        "year": 2019,
        "make": "Honda",
        "model": "Accord",
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "tier_code": "STANDARD",
        "base_fee_cents": 15000,
        "vin_history_fee_cents": 3000,
        "per_mile_dispatch_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Inspector",
        "base_lat": 34.0,
        "base_lng": -118.0,
        "certified_tiers": ["STANDARD"],
        "max_daily_jobs": 3,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(account_id: str, vehicle_id: str, fee_schedule_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "vehicle_id": vehicle_id,
        "fee_schedule_id": fee_schedule_id,
        "location_lat": 34.0,
        "location_lng": -118.0,
        "rush_tier": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(order_id: str, inspector_id: str, expected_order_version: int,
                              window_start: str = "2026-06-02T09:00:00Z",
                              window_end: str = "2026-06-02T11:00:00Z",
                              dispatch_miles: float = 10, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "inspector_id": inspector_id,
        "window_start": window_start,
        "window_end": window_end,
        "dispatch_miles": dispatch_miles,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(order_id: str, assignment_id: str,
                          odometer_reading: int = 30000,
                          points_total: int = 100,
                          points_failed: int = 5,
                          road_test_done: bool = True, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "assignment_id": assignment_id,
        "odometer_reading": odometer_reading,
        "points_total": points_total,
        "points_failed": points_failed,
        "road_test_done": road_test_done,
    }
    defaults.update(overrides)
    return defaults


def create_photo_payload(caption: str = "defect", is_critical: bool = False,
                         url: str = "http://x/p.jpg", **overrides) -> dict:
    defaults = {
        "caption": caption,
        "is_critical": is_critical,
        "url": url,
    }
    defaults.update(overrides)
    return defaults


def create_history_record_payload(record_type: str, event_date: str, **overrides) -> dict:
    defaults = {
        "record_type": record_type,
        "event_date": event_date,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(year: int, make: str, model: str,
                          campaign_id: str = "RC-1", severity: str = "HIGH", **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "year": year,
        "make": make,
        "model": model,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(order_id: str, report_id: str, reason: str, claimed_cents: int, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "report_id": report_id,
        "reason": reason,
        "claimed_cents": claimed_cents,
    }
    defaults.update(overrides)
    return defaults
