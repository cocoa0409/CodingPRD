"""Payload factories — one per entity, input fields only (PRD section 4)."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_code": f"PLAN-{_n()}",
        "included_acres_per_year": 500,
        "base_fee_cents": 0,
        "overage_rate_cents_per_acre": 300,
        "spray_allowed": False,
        "ndvi_turnaround_hours": 24,
        "storage_retention_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_grower_payload(subscription_plan_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "legal_name": f"Grower {n}",
        "contact_email": f"grower{n}@example.com",
        "subscription_plan_id": subscription_plan_id,
        "subscription_started_on": "2026-01-01",
        "liability_coverage_cents": 50_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_field_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "field_name": f"Field {n}",
        "legal_acres": 100,
        "airspace_class": "G",
        "insurance_policy_no": f"POL-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_pilot_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "pilot_name": f"Pilot {n}",
        "part107_certificate_no": f"P107-{_n()}-{_n()}",
        "part107_expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(field_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "field_id": field_id,
        "authorization_ref": f"LAANC-{n}",
        "max_altitude_ft": 400,
        "effective_from": "2026-06-02T00:00:00Z",
        "effective_until": "2026-06-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_mission_payload(pilot_id, **overrides) -> dict:
    defaults = {
        "mission_type": "SCOUT",
        "pilot_id": pilot_id,
        "scheduled_start": "2026-06-02T08:00:00Z",
        "scheduled_end": "2026-06-02T10:00:00Z",
        "acres_planned": 10,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(mission_id, **overrides) -> dict:
    defaults = {
        "mission_id": mission_id,
        "claim_amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
