"""Payload factories — one per entity, input fields only (PRD §3)."""

EVENT_COUNTER = {"n": 0}


def _next_suffix() -> int:
    EVENT_COUNTER["n"] += 1
    return EVENT_COUNTER["n"]


def create_event_payload(**overrides) -> dict:
    n = _next_suffix()
    defaults = {
        "event_code": f"EV-{n:04d}",
        "event_name": f"Test Event {n}",
        "season_year": 2026,
        "start_date": "2026-04-01T08:00:00Z",
        "end_date": "2026-04-04T18:00:00Z",
        "team_capacity": 40,
        "match_cycle_minutes": 7,
        "field_count": 1,
        "championship_slots": 2,
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(**overrides) -> dict:
    defaults = {
        "kind": "KICKOFF",
        "scheduled_at": "2026-01-10T17:00:00Z",
        "window_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(**overrides) -> dict:
    n = _next_suffix()
    defaults = {"team_number": 1000 + n, "nickname": f"Team-{n}"}
    defaults.update(overrides)
    return defaults


def create_person_payload(**overrides) -> dict:
    n = _next_suffix()
    defaults = {
        "team_id": None,
        "full_name": f"Person {n}",
        "email": f"person{n}@example.com",
        "role_kind": "MENTOR",
    }
    defaults.update(overrides)
    return defaults


def create_screening_record_payload(**overrides) -> dict:
    n = _next_suffix()
    defaults = {
        "submission_channel": "FIRST_YPP",
        "vendor_reference": f"VND-{n}",
        "submitted_at": "2026-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_part_order_payload(**overrides) -> dict:
    n = _next_suffix()
    defaults = {"sku": f"SKU-{n}", "quantity": 2, "unit_cost_cents": 1500}
    defaults.update(overrides)
    return defaults


def create_robot_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspector_id": None,  # caller must supply a real Person id
        "weight_kg": 50.0,
        "frame_perimeter_cm": 280,
        "bumper_compliant": True,
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(**overrides) -> dict:
    defaults = {
        "source_kind": "FIELD_SAFETY",
        "severity": "MINOR",
        "description": "violation report",
        "opened_by_person_id": None,  # caller must supply a real Person id
    }
    defaults.update(overrides)
    return defaults


def create_match_payload(**overrides) -> dict:
    n = _next_suffix()
    defaults = {
        "match_number": 9000 + n,
        "series": "QUALIFICATION",
        "scheduled_at": "2026-04-02T12:00:00Z",
        "field_index": 1,
        "red_alliance_id": None,  # caller must supply
        "blue_alliance_id": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults


def create_score_breakdown_payload(**overrides) -> dict:
    defaults = {
        "alliance_color": "RED",
        "auto_points": 10,
        "teleop_points": 40,
        "endgame_points": 10,
        "foul_points_awarded": 0,
        "tech_foul_count": 0,
        "card_issued": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_queue_slot_payload(**overrides) -> dict:
    defaults = {"team_id": None, "position": "RED_1"}  # caller must supply team_id
    defaults.update(overrides)
    return defaults


def create_alliance_payload(**overrides) -> dict:
    defaults = {"seed": 1, "captain_team_id": None}  # caller must supply captain
    defaults.update(overrides)
    return defaults


def create_award_payload(**overrides) -> dict:
    defaults = {"award_kind": "CHAIRMANS", "requires_interview": False}
    defaults.update(overrides)
    return defaults


def create_interview_slot_payload(**overrides) -> dict:
    defaults = {
        "team_id": None,   # caller must supply
        "judge_id": None,  # caller must supply
        "starts_at": "2026-04-02T10:00:00Z",
        "duration_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_travel_booking_payload(**overrides) -> dict:
    defaults = {
        "mode": "AIR",
        "booked_at": "2026-04-05T00:00:00Z",
        "cost_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults
