"""Payload factories — one per entity, input fields only (PRD §3)."""

_athlete_seq = {"n": 0}
_staff_seq = {"n": 0}
_name_seq = {"n": 0}


def _next(seq):
    seq["n"] += 1
    return seq["n"]


def create_staff_payload(**overrides) -> dict:
    n = _next(_staff_seq)
    defaults = {
        "full_name": f"Staff Member {n}",
        "role_type": "ATHLETIC_TRAINER",
    }
    defaults.update(overrides)
    return defaults


def create_athlete_payload(**overrides) -> dict:
    n = _next(_athlete_seq)
    defaults = {
        "full_name": f"Athlete {n}",
        "date_of_birth": "2009-05-01",
        "grade": 11,
        "sex": "M",
        "primary_sport": "SOCCER",
        "team_level": "VARSITY",
        "guardian_name": f"Guardian {n}",
        "guardian_user_id": f"guardian-{n:04d}",
        "guardian_email": f"guardian{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_physical_payload(**overrides) -> dict:
    defaults = {
        "athlete_id": None,
        "exam_date": "2026-07-01",
        "examining_physician_name": "Dr X",
        "outcome": "CLEARED",
        "validity_policy": "DISTRICT_13MO",
    }
    defaults.update(overrides)
    return defaults


def create_baseline_payload(**overrides) -> dict:
    defaults = {
        "athlete_id": None,
        "test_date": "2026-07-15",
        "instrument": "SCAT6",
        "symptom_score": 0,
        "memory_index": 95.0,
        "reaction_time_ms": 250.0,
        "balance_errors": 1,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    n = _next(_name_seq)
    defaults = {
        "venue_name": f"Venue {n}",
        "venue_type": "OUTDOOR",
        "surface": "GRASS",
        "address": f"{n} School Rd",
    }
    defaults.update(overrides)
    return defaults


def create_eap_payload(**overrides) -> dict:
    n = _next(_name_seq)
    defaults = {
        "venue_id": None,
        "version_label": f"2026-fall-v{n}",
        "evacuation_route": "Gate A",
        "aed_location": "Lobby",
        "ems_contact": "911",
        "nearest_hospital": "General Hospital",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    n = _next(_name_seq)
    defaults = {
        "event_name": f"Event {n}",
        "sport": "SOCCER",
        "team_level": "VARSITY",
        "event_type": "PRACTICE",
        "venue_id": None,
        "scheduled_start": "2026-08-02T14:00:00Z",
        "scheduled_end": "2026-08-02T15:30:00Z",
        "expected_attendance": 0,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_assignment_payload(**overrides) -> dict:
    defaults = {
        "event_id": None,
        "staff_id": None,
        "coverage_role": "PRIMARY",
    }
    defaults.update(overrides)
    return defaults


def create_weather_reading_payload(**overrides) -> dict:
    defaults = {
        "venue_id": None,
        "reading_type": "HEAT_WBGT",
        "value_wbgt_f": 82.5,
        "recorded_at": "2026-08-02T13:00:00Z",
        "source": "ON_SITE_SENSOR",
    }
    defaults.update(overrides)
    return defaults


def create_injury_payload(**overrides) -> dict:
    defaults = {
        "athlete_id": None,
        "body_region": "ANKLE_FOOT",
        "injury_type": "SPRAIN",
        "severity": "MINOR",
        "mechanism": "inversion in practice",
        "evaluated_at": "2026-07-31T10:00:00Z",
        "restricted_activities": ["PRACTICE"],
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "injury_id": None,
        "physician_staff_id": None,
        "reason": "specialist evaluation",
        "urgency": "ROUTINE",
    }
    defaults.update(overrides)
    return defaults


def create_supply_item_payload(**overrides) -> dict:
    n = _next(_name_seq)
    defaults = {
        "item_name": f"Supply Item {n}",
        "category": "TAPE",
        "unit": "ROLL",
        "par_level": 50,
        "reorder_threshold": 15,
        "unit_cost_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_transaction_payload(**overrides) -> dict:
    defaults = {
        "supply_item_id": None,
        "txn_type": "RESTOCK",
        "quantity": 1,
        "occurred_at": "2026-08-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_restock_order_payload(**overrides) -> dict:
    defaults = {
        "supply_item_id": None,
        "quantity": 4,
        "unit_cost_cents": 500,
        "fiscal_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_supply_budget_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": 2026,
        "total_budget_cents": 100000,
    }
    defaults.update(overrides)
    return defaults
