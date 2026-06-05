"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the fields a client supplies on create; computed,
system, and server-managed fields are never included. Tests pass overrides for
the values they control and rely on PRD defaults for the rest.
"""
import itertools

# Monotonic counter so factory-minted unique fields (qr_code, email) never
# collide within a single test's setup sequence.
_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def create_plan_payload(**overrides) -> dict:
    """Plan inputs (PRD §3.1). slow_zone_discount_pct and active are optional."""
    defaults = {
        "code": "STANDARD",
        "unlock_fee_cents": 100,
        "per_minute_cents": 30,
        "daily_cap_cents": 0,
        "slow_zone_discount_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(**overrides) -> dict:
    """Zone inputs (PRD §2.5, §3.1). max_speed_kph optional (slow zones only)."""
    defaults = {
        "name": f"Zone-{_next()}",
        "zone_type": "RIDE_OK",
        "priority": 5,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    """Vehicle inputs (PRD §3.1). battery_pct optional (defaults to 100)."""
    defaults = {
        "vehicle_type": "SCOOTER",
        "qr_code": f"QR-{_next()}",
        "battery_pct": 100,
        "current_zone_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_rider_payload(**overrides) -> dict:
    """Rider inputs (PRD §3.2)."""
    defaults = {
        "email": f"rider-{_next()}@example.com",
        "full_name": "Test Rider",
        "plan_id": None,
    }
    defaults.update(overrides)
    return defaults


def topup_payload(**overrides) -> dict:
    """Top-up input (PRD §3.2)."""
    defaults = {"amount_cents": 5000}
    defaults.update(overrides)
    return defaults


def change_plan_payload(**overrides) -> dict:
    """Change-plan inputs (PRD §3.2, §2.7)."""
    defaults = {"plan_id": None, "expected_rider_version": None}
    defaults.update(overrides)
    return defaults


def create_trip_payload(**overrides) -> dict:
    """Trip unlock inputs (PRD §3.3)."""
    defaults = {"rider_id": None, "vehicle_id": None}
    defaults.update(overrides)
    return defaults


def end_trip_payload(**overrides) -> dict:
    """End-trip input (PRD §3.5)."""
    defaults = {"end_zone_id": None}
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    """Technician inputs (PRD §3.7). on_shift optional (defaults to true)."""
    defaults = {
        "name": f"Technician-{_next()}",
        "depot_zone_id": None,
        "on_shift": True,
    }
    defaults.update(overrides)
    return defaults


def create_rebalancing_task_payload(**overrides) -> dict:
    """RebalancingTask inputs (PRD §3.7, §2.7). target_zone_id optional for SWAP."""
    defaults = {
        "vehicle_id": None,
        "task_type": "MOVE",
        "target_zone_id": None,
        "window_start": "2026-06-01T10:00:00Z",
        "window_end": "2026-06-01T11:00:00Z",
        "expected_vehicle_version": None,
    }
    defaults.update(overrides)
    return defaults


def assign_task_payload(**overrides) -> dict:
    """Assign-task input (PRD §3.7)."""
    defaults = {"technician_id": None}
    defaults.update(overrides)
    return defaults


def create_low_income_application_payload(**overrides) -> dict:
    """LowIncomeApplication inputs (PRD §3.2)."""
    defaults = {
        "rider_id": None,
        "household_size": 2,
        "annual_income_cents": 4000000,
    }
    defaults.update(overrides)
    return defaults


def create_mds_report_payload(**overrides) -> dict:
    """MDSReport inputs (PRD §3.8)."""
    defaults = {
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2026-06-01T01:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    """Test-driving clock input (PRD §3.9)."""
    return {"to_iso8601": to_iso8601}


def set_battery_payload(battery_pct: int) -> dict:
    """Test-driving battery setter input (PRD §3.9)."""
    return {"battery_pct": battery_pct}
