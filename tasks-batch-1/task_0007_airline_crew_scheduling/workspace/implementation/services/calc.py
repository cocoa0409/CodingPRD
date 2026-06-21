"""Calculation rules from SCAFFOLD §1.3 / PRD §2.7, §2.8, §3.1, §3.4."""
from __future__ import annotations

from datetime import timedelta

import db
from services.constants import (
    REPORT_BUFFER_MIN, DEBRIEF_BUFFER_MIN,
    WINDOW_HOURS, FAA_DUTY_CAP_7D_MIN, FAA_FLIGHT_CAP_7D_MIN,
    MIN_REST_MINUTES,
)
from services.timeutil import parse_iso, diff_minutes_floor


# ---------------------------------------------------------------------
# pairing_duty_window (SCAFFOLD §1.3 / PRD §3.1)
# ---------------------------------------------------------------------

def pairing_duty_window(pairing: dict) -> tuple[int, int]:
    """Returns (total_duty_minutes, total_flight_minutes) per PRD §3.1.

    total_duty_minutes = window minutes + REPORT_BUFFER + DEBRIEF_BUFFER (90 min)
    total_flight_minutes = sum over child REVENUE FlightLegs of flight_minutes
    """
    start = parse_iso(pairing["scheduled_start_utc"])
    end = parse_iso(pairing["scheduled_end_utc"])
    window_min = diff_minutes_floor(end, start)
    total_duty = window_min + REPORT_BUFFER_MIN + DEBRIEF_BUFFER_MIN

    total_flight = 0
    for leg in db.flight_legs.values():
        if leg["pairing_id"] == pairing["id"] and leg["leg_type"] == "REVENUE":
            total_flight += int(leg["flight_minutes"])
    return total_duty, total_flight


# ---------------------------------------------------------------------
# pairing_credit_block (SCAFFOLD §1.3 / PRD §3.1)
# ---------------------------------------------------------------------

def scheduled_block_minutes(pairing: dict) -> int:
    """planned-window minutes minus REPORT and DEBRIEF buffers (PRD §3.1)."""
    start = parse_iso(pairing["scheduled_start_utc"])
    end = parse_iso(pairing["scheduled_end_utc"])
    window_min = diff_minutes_floor(end, start)
    return window_min - REPORT_BUFFER_MIN - DEBRIEF_BUFFER_MIN


def actual_block_minutes(pairing_id: str) -> int:
    """floor(sum(actual_duty_end - actual_duty_start) / count) over COMPLETED
    child Assignments (PRD §3.1).
    """
    durations = []
    for a in db.assignments.values():
        if (
            a["pairing_id"] == pairing_id
            and a["state"] == "COMPLETED"
            and a["actual_duty_start_utc"]
            and a["actual_duty_end_utc"]
        ):
            s = parse_iso(a["actual_duty_start_utc"])
            e = parse_iso(a["actual_duty_end_utc"])
            durations.append(diff_minutes_floor(e, s))
    if not durations:
        return 0
    return sum(durations) // len(durations)


# ---------------------------------------------------------------------
# rolling_duty_window (SCAFFOLD §1.3 / PRD §2.7)
# ---------------------------------------------------------------------

def crew_rolling_totals(crew_id: str) -> tuple[int, int]:
    """Persisted form (completed_actual): sum of credited minutes over the
    crew's COMPLETED Assignments whose actual_duty_end_utc lies in
    (current_utc - 168h, current_utc]. Returns (duty_min_7d, flight_min_7d).
    """
    cutoff = db.current_utc - timedelta(hours=WINDOW_HOURS)
    duty = 0
    flight = 0
    for a in db.assignments.values():
        if a["crew_member_id"] != crew_id:
            continue
        if a["state"] != "COMPLETED":
            continue
        if not a["actual_duty_end_utc"]:
            continue
        end = parse_iso(a["actual_duty_end_utc"])
        if end >= cutoff and end <= db.current_utc:
            duty += int(a.get("duty_minutes_credited") or 0)
            flight += int(a.get("flight_minutes_credited") or 0)
    return duty, flight


def faa_preview_violations(crew: dict, candidate_pairing: dict) -> tuple[bool, bool]:
    """Preview form: persisted totals + candidate pairing's projected totals.
    Returns (duty_exceeds, flight_exceeds). Strict greater-than per PRD §2.7.
    """
    pers_duty, pers_flight = crew["total_duty_minutes_7d"], crew["total_flight_minutes_7d"]
    proj_duty = pers_duty + int(candidate_pairing.get("total_duty_minutes") or 0)
    proj_flight = pers_flight + int(candidate_pairing.get("total_flight_minutes") or 0)
    return (proj_duty > FAA_DUTY_CAP_7D_MIN, proj_flight > FAA_FLIGHT_CAP_7D_MIN)


# ---------------------------------------------------------------------
# crew_rest_interval (SCAFFOLD §1.3 / PRD §2.8)
# ---------------------------------------------------------------------

def crew_rest_passes(crew: dict, candidate_pairing: dict) -> bool:
    """PRD §2.8: null last_off_duty_utc → pass; otherwise inclusive >= 600 min."""
    last_off = crew.get("last_off_duty_utc")
    if last_off is None:
        return True
    last_off_dt = parse_iso(last_off)
    start = parse_iso(candidate_pairing["scheduled_start_utc"])
    rest = diff_minutes_floor(start, last_off_dt)
    return rest >= MIN_REST_MINUTES


# ---------------------------------------------------------------------
# reserve_selector (SCAFFOLD §1.3 / PRD §3.4)
# ---------------------------------------------------------------------

def select_reserve(pairing: dict, required_seat: str, excluded_ids: set) -> dict | None:
    """Filter candidates and rank by (total_duty_minutes_7d ASC,
    seniority_number ASC, created_at ASC). Returns the chosen CrewMember dict
    or None if no candidate survives.
    """
    candidates = []
    for cm in db.crew_members.values():
        if cm["line_type"] != "RESERVE":
            continue
        if cm["status"] != "AVAILABLE":
            continue
        # rank must be compatible with required seat (PRD §3.2 rank-seat table)
        from services.constants import rank_seat_compatible
        if not rank_seat_compatible(cm["rank"], required_seat):
            continue
        if cm["base_airport"] != pairing["origin_base"]:
            continue
        if cm["id"] in excluded_ids:
            continue
        candidates.append(cm)
    if not candidates:
        return None
    candidates.sort(
        key=lambda c: (
            int(c["total_duty_minutes_7d"]),
            int(c["seniority_number"]),
            c["created_at"],
        )
    )
    return candidates[0]
