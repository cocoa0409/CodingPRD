"""Payload factories — one per entity, input fields only (PRD request payloads)."""
from .constants import REFERENCE_TARIFF, TEST_DEFAULTS

_seq = 0


def _unique(tag: str) -> str:
    global _seq
    _seq += 1
    return f"{tag}-{_seq}"


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("Facility"),
        "total_spaces": TEST_DEFAULTS["FACILITY_TOTAL_SPACES"],
        "monthly_capacity": TEST_DEFAULTS["FACILITY_MONTHLY_CAPACITY"],
        "event_pool_spaces": TEST_DEFAULTS["FACILITY_EVENT_POOL_SPACES"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "label": _unique("Tariff"),
        "cap_mode": "CALENDAR_DAY",
        "effective_from": "2026-08-01T00:00:00Z",
    }
    defaults.update(REFERENCE_TARIFF)
    defaults.update(overrides)
    return defaults


def create_access_device_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "device_label": _unique("Entry Lane"),
        "device_kind": "ENTRY_GATE",
    }
    defaults.update(overrides)
    return defaults


def create_parker_account_payload(**overrides) -> dict:
    tag = _unique("parker")
    defaults = {
        "full_name": f"Test Parker {tag}",
        "email": f"{tag}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_monthly_agreement_payload(facility_id: str, parker_account_id: str,
                                     **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "parker_account_id": parker_account_id,
        "tier": "STANDARD",
        "monthly_rate_cents": TEST_DEFAULTS["MONTHLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "credential_type": "BADGE",
        "deposit_cents": TEST_DEFAULTS["CREDENTIAL_DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_parking_session_payload(facility_id: str, entry_device_id: str,
                                   **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "entry_device_id": entry_device_id,
        "ticket_barcode": _unique("T"),
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "opening_float_cents": TEST_DEFAULTS["OPENING_FLOAT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def close_shift_payload(counted_cash_cents: int, **overrides) -> dict:
    defaults = {"counted_cash_cents": counted_cash_cents}
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(shift_id: str, **overrides) -> dict:
    defaults = {"shift_id": shift_id}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "level_scope": "L1",
        "scheduled_for": "2026-08-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def report_inspection_payload(load_bearing_rating: int = 5,
                              waterproofing_rating: int = 5,
                              surface_rating: int = 5,
                              **overrides) -> dict:
    defaults = {
        "load_bearing_rating": load_bearing_rating,
        "waterproofing_rating": waterproofing_rating,
        "surface_rating": surface_rating,
    }
    defaults.update(overrides)
    return defaults


def create_repair_project_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "title": _unique("Repair"),
        "level_scope": "L1",
        "estimated_cost_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "level": "L1",
        "window_type": "SWEEPING",
        "start_at": "2026-08-05T06:00:00Z",
        "end_at": "2026-08-05T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_patrol_round_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "scheduled_start": "2026-08-01T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_patrol_round_payload(checkpoints_completed: int = 1, **overrides) -> dict:
    defaults = {"checkpoints_completed": checkpoints_completed}
    defaults.update(overrides)
    return defaults


def create_incident_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "incident_type": "SECURITY",
        "severity": "LOW",
        "description": _unique("Incident"),
    }
    defaults.update(overrides)
    return defaults


def create_ev_charger_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "charger_label": _unique("EV"),
        "max_kw": TEST_DEFAULTS["CHARGER_MAX_KW"],
    }
    defaults.update(overrides)
    return defaults


def create_charging_session_payload(charger_id: str, **overrides) -> dict:
    defaults = {"charger_id": charger_id}
    defaults.update(overrides)
    return defaults


def create_event_booking_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "event_name": _unique("Event"),
        "start_at": "2026-08-20T18:00:00Z",
        "end_at": "2026-08-20T23:00:00Z",
        "presale_allocation": 0,
        "min_staff": 0,
    }
    defaults.update(overrides)
    return defaults
