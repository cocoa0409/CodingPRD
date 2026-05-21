"""Cumulative counter helpers on CrewMember (cumulative_block_minutes_30d / 7d)."""
from datetime import timedelta

import store
from clock import get_now, parse_iso


def increment_30d(crew_member, minutes):
    crew_member["cumulative_block_minutes_30d"] = (
        crew_member.get("cumulative_block_minutes_30d", 0) + int(minutes)
    )
    store.touch(crew_member)


def increment_7d(crew_member, minutes):
    crew_member["cumulative_duty_minutes_7d"] = (
        crew_member.get("cumulative_duty_minutes_7d", 0) + int(minutes)
    )
    store.touch(crew_member)


def debit_for_release(crew_member, pairing, assignment):
    """Debit cumulative counters per release rules.

    Per PRD §3.7:
      - debit cumulative_block_minutes_30d by Assignment.scheduled_block_minutes
        if Pairing.start_at within rolling 30d window from now.
      - debit cumulative_duty_minutes_7d by Pairing.total_duty_minutes
        if Pairing.end_at within rolling 7d window from now.
    """
    now = get_now()
    start_at = parse_iso(pairing.get("start_at")) if pairing.get("start_at") else None
    end_at = parse_iso(pairing.get("end_at")) if pairing.get("end_at") else None

    if start_at is not None:
        delta = (now - start_at).total_seconds() / 86400.0
        # within rolling 30d window: 0 <= delta <= 30 OR future (delta < 0)
        # PRD says "Pairing.start_at within rolling 30d window from now"
        # Interpret as |now - start_at| <= 30d
        if abs(delta) <= 30:
            sched = int(assignment.get("scheduled_block_minutes", 0) or 0)
            crew_member["cumulative_block_minutes_30d"] = max(
                0, crew_member.get("cumulative_block_minutes_30d", 0) - sched
            )

    if end_at is not None:
        delta_e = (now - end_at).total_seconds() / 86400.0
        if abs(delta_e) <= 7:
            duty = int(pairing.get("total_duty_minutes", 0) or 0)
            crew_member["cumulative_duty_minutes_7d"] = max(
                0, crew_member.get("cumulative_duty_minutes_7d", 0) - duty
            )

    store.touch(crew_member)


def increment_for_assignment(crew_member, pairing):
    """Increment cumulative counters when an assignment is bound.

    Add Pairing.total_block_minutes to 30d.
    Add Pairing.total_duty_minutes to 7d.
    """
    block = int(pairing.get("total_block_minutes", 0) or 0)
    duty = int(pairing.get("total_duty_minutes", 0) or 0)
    increment_30d(crew_member, block)
    increment_7d(crew_member, duty)


def recompute_for_crew(crew_member):
    """Recompute 30d / 7d counters from currently bound assignments.

    Used after a trade to ensure invariants hold.
    """
    now = get_now()
    total_block_30 = 0
    total_duty_7 = 0
    for a in store.assignments.values():
        if a["crew_member_id"] != crew_member["id"]:
            continue
        if a["status"] not in {"SCHEDULED", "IN_PROGRESS", "COMPLETED"}:
            continue
        pairing = store.pairings.get(a["pairing_id"])
        if not pairing:
            continue
        start_at = parse_iso(pairing["start_at"]) if pairing.get("start_at") else None
        end_at = parse_iso(pairing["end_at"]) if pairing.get("end_at") else None
        if start_at is not None and abs((now - start_at).total_seconds() / 86400.0) <= 30:
            total_block_30 += int(pairing.get("total_block_minutes", 0) or 0)
        if end_at is not None and abs((now - end_at).total_seconds() / 86400.0) <= 7:
            total_duty_7 += int(pairing.get("total_duty_minutes", 0) or 0)
    crew_member["cumulative_block_minutes_30d"] = total_block_30
    crew_member["cumulative_duty_minutes_7d"] = total_duty_7
    store.touch(crew_member)
