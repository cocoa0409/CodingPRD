"""Payload factories — one per creatable resource, input fields only (PRD §4)."""
import itertools

from .constants import (
    DEFAULT_MUSIC_BUDGET_CENTS,
    DEFAULT_REPAIR_BUDGET_CENTS,
)

_serial = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_serial):04d}"


def create_program_payload(**overrides) -> dict:
    defaults = {
        "season_name": _uniq("Season"),
        "music_budget_cents": DEFAULT_MUSIC_BUDGET_CENTS,
        "repair_budget_cents": DEFAULT_REPAIR_BUDGET_CENTS,
    }
    defaults.update(overrides)
    return defaults


def advance_program_payload(to_state: str) -> dict:
    return {"to_state": to_state}


def patch_program_payload(expected_program_version: int, **overrides) -> dict:
    payload = {"expected_program_version": expected_program_version}
    payload.update(overrides)
    return payload


def create_student_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "full_name": _uniq("Student"),
        "grade": 10,
        "section": "BRASS",
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "serial_number": _uniq("SN"),
        "instrument_type": "TRUMPET",
        "replacement_value_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_instrument_assignment_payload(student_id: str, instrument_id: str,
                                         due_date: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "instrument_id": instrument_id,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def return_assignment_payload(inspection_result: str = "PASS") -> dict:
    return {"inspection_result": inspection_result}


def renew_assignment_payload(new_due_date: str) -> dict:
    return {"new_due_date": new_due_date}


def create_uniform_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "garment_type": "JACKET",
        "size_label": "M",
    }
    defaults.update(overrides)
    return defaults


def create_uniform_assignment_payload(student_id: str, uniform_id: str) -> dict:
    return {"student_id": student_id, "uniform_id": uniform_id}


def return_uniform_assignment_payload(soiling_level: str = "NORMAL") -> dict:
    return {"soiling_level": soiling_level}


def create_cleaning_batch_payload(program_id: str) -> dict:
    return {"program_id": program_id}


def cleaning_batch_item_payload(uniform_id: str) -> dict:
    return {"uniform_id": uniform_id}


def create_arrangement_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "title": _uniq("Chart"),
        "arranger": "A. Arranger",
        "license_type": "STANDARD",
        "cost_cents": 10000,
        "rights_end": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "event_type": "REHEARSAL",
        "facility": _uniq("FACILITY"),
        "starts_at": "2026-08-10T10:00:00Z",
        "ends_at": "2026-08-10T12:00:00Z",
        "is_outdoor": True,
    }
    defaults.update(overrides)
    return defaults


def postpone_event_payload(new_starts_at: str, new_ends_at: str) -> dict:
    return {"new_starts_at": new_starts_at, "new_ends_at": new_ends_at}


def create_trip_payload(event_id: str, expected_event_version: int, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "expected_event_version": expected_event_version,
        "capacity": 5,
        "estimated_cost_cents": 10000,
        "departure_at": "2026-09-15T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_trip_enrollment_payload(trip_id: str, student_id: str) -> dict:
    return {"trip_id": trip_id, "student_id": student_id}


def mark_attendance_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def create_payment_payload(student_id: str, kind: str, amount_cents: int,
                           **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_fundraiser_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": _uniq("Fundraiser"),
        "goal_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def close_fundraiser_payload(raised_cents: int, participant_hours: list) -> dict:
    return {"raised_cents": raised_cents, "participant_hours": participant_hours}


def create_audition_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "section": "BRASS",
        "chair_capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_audition_entry_payload(audition_id: str, student_id: str) -> dict:
    return {"audition_id": audition_id, "student_id": student_id}


def judge_score_payload(judge_id: str, musicianship: int, marching: int,
                        leadership: int) -> dict:
    return {
        "judge_id": judge_id,
        "musicianship": musicianship,
        "marching": marching,
        "leadership": leadership,
    }


def publish_placements_payload(expected_audition_version: int) -> dict:
    return {"expected_audition_version": expected_audition_version}


def challenge_payload(entry_id: str, **overrides) -> dict:
    defaults = {"entry_id": entry_id}
    defaults.update(overrides)
    return defaults


def create_truck_charter_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "vehicle_label": _uniq("TRUCK"),
        "capacity_weight_lb": 4000,
        "capacity_volume_cuft": 400,
        "window_start": "2026-09-01T04:00:00Z",
        "window_end": "2026-09-02T02:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def truck_load_payload(description: str, weight_lb: int, volume_cuft: int,
                       **overrides) -> dict:
    defaults = {
        "description": description,
        "weight_lb": weight_lb,
        "volume_cuft": volume_cuft,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def complete_maintenance_payload(repair_cost_cents: int) -> dict:
    return {"repair_cost_cents": repair_cost_cents}
