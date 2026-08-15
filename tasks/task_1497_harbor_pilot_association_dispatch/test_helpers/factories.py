"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import (
    MAIN_TARIFF_TIERS, MAIN_TARIFF_EFFECTIVE_FROM,
    DRAFT_SURCHARGE_THRESHOLD_DM, DRAFT_SURCHARGE_PCT,
    DETENTION_FREE_MINUTES, DETENTION_RATE_CENTS_PER_MINUTE,
    DELAY_RATE_CENTS_PER_MINUTE, ENDORSEMENT_EXPIRY_FUTURE, ETA_DEFAULT,
)


def make_pilot_payload(**overrides) -> dict:
    defaults = {"full_name": "Pilot One", "license_number": "LIC-1", "share_units": 1}
    defaults.update(overrides)
    return defaults


def make_endorsement_payload(**overrides) -> dict:
    defaults = {
        "endorsement_class": "UNLIMITED",
        "tonnage_cap_gt": 100000,
        "expires_at": ENDORSEMENT_EXPIRY_FUTURE,
    }
    defaults.update(overrides)
    return defaults


def make_order_payload(**overrides) -> dict:
    defaults = {
        "vessel_name": "MV One",
        "gt": 8000,
        "draft_dm": 90,
        "order_type": "ARRIVAL",
        "eta": ETA_DEFAULT,
    }
    defaults.update(overrides)
    return defaults


def make_boat_payload(**overrides) -> dict:
    defaults = {"name": "Boat A", "capacity_persons": 6}
    defaults.update(overrides)
    return defaults


def make_tariff_schedule_payload(**overrides) -> dict:
    defaults = {
        "effective_from": MAIN_TARIFF_EFFECTIVE_FROM,
        "tiers": [dict(t) for t in MAIN_TARIFF_TIERS],
        "draft_surcharge_threshold_dm": DRAFT_SURCHARGE_THRESHOLD_DM,
        "draft_surcharge_pct": DRAFT_SURCHARGE_PCT,
        "detention_free_minutes": DETENTION_FREE_MINUTES,
        "detention_rate_cents_per_minute": DETENTION_RATE_CENTS_PER_MINUTE,
        "delay_rate_cents_per_minute": DELAY_RATE_CENTS_PER_MINUTE,
    }
    defaults.update(overrides)
    return defaults


def make_dispatch_payload(scheduled_start="2026-08-10T10:00:00Z",
                          scheduled_end="2026-08-10T11:00:00Z", **overrides) -> dict:
    defaults = {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}
    defaults.update(overrides)
    return defaults


def make_completion_payload(detention_minutes=0, delay_minutes=0, **overrides) -> dict:
    defaults = {"detention_minutes": detention_minutes, "delay_minutes": delay_minutes}
    defaults.update(overrides)
    return defaults


def make_incident_payload(assignment_id, incident_type="NEAR_MISS",
                          description="near miss at buoy 4", **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "incident_type": incident_type,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def make_apprentice_payload(**overrides) -> dict:
    defaults = {"full_name": "App X", "track": "STANDARD"}
    defaults.update(overrides)
    return defaults


def make_record_progress_payload(trips_delta=10, evaluation_score=80, **overrides) -> dict:
    defaults = {"trips_delta": trips_delta, "evaluation_score": evaluation_score}
    defaults.update(overrides)
    return defaults


def make_distribution_run_payload(period_start="2026-08-01T00:00:00Z",
                                  period_end="2026-08-02T00:00:00Z", **overrides) -> dict:
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults
