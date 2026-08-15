"""Payload factories — one per entity, input fields only."""
import itertools

# Counters keep human-supplied identifiers unique within a test run. The server
# database is empty at the start of every test, so cross-test reuse is safe.
_org_counter = itertools.count(1)
_facility_counter = itertools.count(1)
_schedule_counter = itertools.count(1)
_window_counter = itertools.count(1)


def create_organization_payload(**overrides) -> dict:
    n = next(_org_counter)
    defaults = {
        "name": f"Riverview SC {n}",
        "classification": "RESIDENT",
        "org_type": "YOUTH_LEAGUE",
        "prior_seasons_active": 3,
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    n = next(_facility_counter)
    defaults = {
        "name": f"Memorial Field {n}",
        "facility_class": "RECTANGLE",
        "has_lights": True,
        "capacity": 120,
        "weekly_prime_hour_cap": 12,
        "nightly_light_block_cap": 16,
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    n = next(_schedule_counter)
    defaults = {
        "name": f"2026 Standard {n}",
        "effective_from": "2026-07-01T00:00:00Z",
        "hourly_resident_cents": 2000,
        "hourly_nonresident_cents": 3250,
        "hourly_commercial_cents": 5000,
        "lights_block_cents": 700,
        "nonresident_surcharge_pct": 15,
        "commercial_surcharge_pct": 25,
        "tournament_day_cents": 24000,
        "tournament_day_min_minutes": 360,
        "deposit_pct": 25,
        "min_deposit_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(**overrides) -> dict:
    defaults = {
        "season_code": "2026-FALL",
        "opens_at": "2026-08-01T00:00:00Z",
        "closes_at": "2026-08-20T23:59:59Z",
        "prime_cap_hours_per_org": 10,
        "max_tournament_days_per_org": 2,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(window_id, facility_id, **overrides) -> dict:
    defaults = {
        "window_id": window_id,
        "facility_id": facility_id,
        "event_date": "2026-08-10",
        "start_minute": 1080,
        "end_minute": 1200,
        "event_type": "LEAGUE_GAME",
        "wants_lights": False,
        "headcount": 40,
    }
    defaults.update(overrides)
    return defaults


def create_closure_payload(facility_id, **overrides) -> dict:
    """Full-day closure by default (start_minute/end_minute omitted)."""
    defaults = {
        "facility_id": facility_id,
        "closure_date": "2026-08-10",
        "reason": "RAIN",
    }
    defaults.update(overrides)
    return defaults


def create_condition_payload(condition_status, reason, expected_facility_version,
                             **overrides) -> dict:
    defaults = {
        "condition_status": condition_status,
        "reason": reason,
        "expected_facility_version": expected_facility_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, method="CHECK", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "method": method}
    defaults.update(overrides)
    return defaults


def create_refund_payload(amount_cents, reason="Goodwill", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(delta_cents, note, expected_invoice_version,
                              **overrides) -> dict:
    defaults = {
        "delta_cents": delta_cents,
        "note": note,
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults


def create_reschedule_payload(new_date, new_start_minute, new_end_minute,
                              expected_permit_version, **overrides) -> dict:
    defaults = {
        "new_date": new_date,
        "new_start_minute": new_start_minute,
        "new_end_minute": new_end_minute,
        "expected_permit_version": expected_permit_version,
    }
    defaults.update(overrides)
    return defaults
