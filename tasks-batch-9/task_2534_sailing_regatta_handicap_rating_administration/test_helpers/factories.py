"""Payload factories — one per creation endpoint, input fields only.

Defaults are chosen so that the resulting world is legal under the PRD and so
that every derived rating value is one of the pinned literals in constants.py.
"""

import itertools

from .constants import (
    CERT_VALID_FROM,
    CERT_VALID_UNTIL,
    MEASUREMENT_A,
    NOR_EFFECTIVE_UTC,
    SERIES_START_UTC,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short monotonically increasing suffix for globally unique columns."""
    return f"{next(_counter):04d}"


# ── Club members (PRD 3.1) ─────────────────────────────────────────────────
def create_club_member_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "full_name": f"Test Member {suffix}",
        "email": f"member{suffix}@example-yacht-club.test",
    }
    payload.update(overrides)
    return payload


def patch_club_member_payload(**overrides) -> dict:
    return dict(overrides)


# ── Boats (PRD 3.1) ────────────────────────────────────────────────────────
def create_boat_payload(owner_member_id, **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "sail_number": f"USA-{suffix}",
        "boat_name": f"Test Boat {suffix}",
        "owner_member_id": owner_member_id,
        "boat_type": "MONOHULL",
        "loa_meters": 11.3,
    }
    payload.update(overrides)
    return payload


# ── Rating certificates (PRD 3.2) ──────────────────────────────────────────
def create_certificate_payload(boat_id, expected_boat_version, **overrides) -> dict:
    payload = {
        "boat_id": boat_id,
        "rule_code": "TOD_PHRF",
        "sail_area_m2": MEASUREMENT_A["sail_area_m2"],
        "hull_length_m": MEASUREMENT_A["hull_length_m"],
        "displacement_kg": MEASUREMENT_A["displacement_kg"],
        "draft_m": MEASUREMENT_A["draft_m"],
        "valid_from": CERT_VALID_FROM,
        "valid_until": CERT_VALID_UNTIL,
        "expected_boat_version": expected_boat_version,
    }
    payload.update(overrides)
    return payload


def suspend_certificate_payload(**overrides) -> dict:
    payload = {"suspension_reason_code": "MEASUREMENT_IRREGULARITY"}
    payload.update(overrides)
    return payload


# ── Regattas (PRD 3.3) ─────────────────────────────────────────────────────
def create_regatta_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "name": f"Test Regatta {suffix}",
        "host_club_name": "Test Yacht Club",
        "scoring_system": "LOW_POINT",
        "safety_category": "CAT_4",
        "planned_race_count": 6,
        "series_start_utc": SERIES_START_UTC,
    }
    payload.update(overrides)
    return payload


# ── Race documents (PRD 3.3) ───────────────────────────────────────────────
def create_race_document_payload(regatta_id, expected_regatta_version, **overrides) -> dict:
    payload = {
        "regatta_id": regatta_id,
        "doc_type": "NOR",
        "body_summary": "Notice of race revision 1",
        "effective_utc": NOR_EFFECTIVE_UTC,
        "expected_regatta_version": expected_regatta_version,
    }
    payload.update(overrides)
    return payload


# ── Divisions (PRD 3.4) ────────────────────────────────────────────────────
def create_division_payload(regatta_id, **overrides) -> dict:
    payload = {
        "regatta_id": regatta_id,
        "code": "A",
        "boat_type_filter": "MONOHULL",
        "rating_band_low": 150.0,
        "rating_band_high": 230.0,
        "min_entries": 2,
    }
    payload.update(overrides)
    return payload


# ── Entries (PRD 3.5) ──────────────────────────────────────────────────────
def create_entry_payload(regatta_id, boat_id, certificate_id, helm_member_id, **overrides) -> dict:
    payload = {
        "regatta_id": regatta_id,
        "boat_id": boat_id,
        "certificate_id": certificate_id,
        "helm_member_id": helm_member_id,
        "declared_crew_count": 1,
    }
    payload.update(overrides)
    return payload


def add_crew_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "position": "HELM",
        "weight_kg": 84.5,
    }
    payload.update(overrides)
    return payload


def inspect_entry_payload(**overrides) -> dict:
    payload = {"outcome": "PASS"}
    payload.update(overrides)
    return payload


# ── Mark boats (PRD 3.6) ───────────────────────────────────────────────────
def create_mark_boat_payload(regatta_id, **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "regatta_id": regatta_id,
        "call_sign": f"MB-{suffix}",
        "crew_capacity": 3,
    }
    payload.update(overrides)
    return payload


# ── Duty assignments (PRD 3.6) ─────────────────────────────────────────────
def create_duty_assignment_payload(
    regatta_id, member_id, position, window_start_utc, window_end_utc, **overrides
) -> dict:
    payload = {
        "regatta_id": regatta_id,
        "member_id": member_id,
        "position": position,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    payload.update(overrides)
    return payload


def release_duty_payload(**overrides) -> dict:
    payload = {"release_reason_code": "ILLNESS"}
    payload.update(overrides)
    return payload


# ── Races (PRD 3.7) ────────────────────────────────────────────────────────
def create_race_payload(regatta_id, race_number, scheduled_start_utc, **overrides) -> dict:
    payload = {
        "regatta_id": regatta_id,
        "race_number": race_number,
        "course_code": "DISTANCE_COASTAL",
        "course_distance_nm": 6.0,
        "scheduled_start_utc": scheduled_start_utc,
    }
    payload.update(overrides)
    return payload


def start_race_payload(actual_start_utc, **overrides) -> dict:
    payload = {"actual_start_utc": actual_start_utc}
    payload.update(overrides)
    return payload


def abandon_race_payload(**overrides) -> dict:
    payload = {"reason_code": "WIND_SHIFT"}
    payload.update(overrides)
    return payload


def recall_payload(recall_type, signal_utc, **overrides) -> dict:
    payload = {
        "recall_type": recall_type,
        "signal_utc": signal_utc,
        "reason_code": "PREMATURE_START",
    }
    payload.update(overrides)
    return payload


# ── Race results (PRD 3.8) ─────────────────────────────────────────────────
def create_race_result_payload(race_id, entry_id, **overrides) -> dict:
    payload = {
        "race_id": race_id,
        "entry_id": entry_id,
        "finish_status": "FINISHED",
        "elapsed_seconds": 4800.0,
    }
    payload.update(overrides)
    return payload


# ── Jury panels (PRD 3.10) ─────────────────────────────────────────────────
def create_jury_panel_payload(regatta_id, chair_member_id, **overrides) -> dict:
    payload = {"regatta_id": regatta_id, "chair_member_id": chair_member_id}
    payload.update(overrides)
    return payload


def seat_judge_payload(member_id, **overrides) -> dict:
    payload = {"member_id": member_id}
    payload.update(overrides)
    return payload


def recuse_payload(member_id, **overrides) -> dict:
    payload = {"member_id": member_id}
    payload.update(overrides)
    return payload


# ── Protests (PRD 3.10) ────────────────────────────────────────────────────
def create_protest_payload(
    race_id, protestor_entry_id, protestee_entry_id, incident_utc, **overrides
) -> dict:
    payload = {
        "race_id": race_id,
        "protestor_entry_id": protestor_entry_id,
        "protestee_entry_id": protestee_entry_id,
        "rule_cited": "RRS_10",
        "incident_utc": incident_utc,
    }
    payload.update(overrides)
    return payload


def evidence_payload(submitted_by_entry_id, **overrides) -> dict:
    payload = {
        "kind": "GPS_TRACK",
        "summary": "Track overlay of the mark rounding",
        "submitted_by_entry_id": submitted_by_entry_id,
    }
    payload.update(overrides)
    return payload


def schedule_hearing_payload(jury_panel_id, hearing_utc, **overrides) -> dict:
    payload = {"jury_panel_id": jury_panel_id, "hearing_utc": hearing_utc}
    payload.update(overrides)
    return payload


def decide_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def invalidate_payload(**overrides) -> dict:
    payload = {"reason_code": "OUT_OF_TIME"}
    payload.update(overrides)
    return payload
