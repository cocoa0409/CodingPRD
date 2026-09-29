"""Block ledger, room turnover, staffing matrix and recovery-bay projection."""
from datetime import timedelta
from decimal import Decimal

from db import db, touch
from services.domain import (COMMITTING_CASE_STATUSES, LEVEL_RANK,
                             PRIVILEGE_ADMITS, RECOVERY_MINUTES_BY_LEVEL,
                             get_block, get_practice, get_staff, open_permit,
                             ordered)
from timeutil import parse_date, r2, whole_minutes


def duration_minutes(start_raw, end_raw):
    return whole_minutes(parse_date(start_raw), parse_date(end_raw))


def block_duration(block):
    return int(block["block_duration_minutes"])


def committed_minutes_of(block):
    total = 0
    for case in db.cases.values():
        if case.get("block_id") != block["id"]:
            continue
        if case["scheduling_status"] in COMMITTING_CASE_STATUSES:
            total += int(case["duration_minutes"])
    return total


def recompute_block(block):
    """calculations.block_utilization; released_minutes is a stored, monotonic counter."""
    duration = block_duration(block)
    committed = committed_minutes_of(block)
    released = int(block.get("released_minutes") or 0)
    block["committed_minutes"] = committed
    block["open_minutes"] = max(0, duration - committed - released)
    if duration <= 0:
        block["utilization_pct"] = float(Decimal("0.00"))
    else:
        block["utilization_pct"] = float(r2(Decimal(100) * Decimal(committed) / Decimal(duration)))
    return block


def touch_block(block):
    recompute_block(block)
    touch(block)
    return block


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def privilege_admits(privilege_state, level):
    return level in PRIVILEGE_ADMITS.get(privilege_state, ("LOCAL_ONLY",))


def permit_rank_sufficient(practice_id, level):
    required = LEVEL_RANK.get(level, 0)
    if required == 0:
        return True
    permit = open_permit(practice_id)
    if permit is None or permit["status"] not in ("ACTIVE", "PROBATION"):
        return False
    return LEVEL_RANK.get(permit["permit_level"], 0) >= required


def room_turnover_conflict(case, block, practice):
    """Buffer appended to BOTH the incumbent and the candidate window."""
    buffer = timedelta(minutes=int(practice.get("turnover_buffer_minutes") or 0))
    start = parse_date(case["planned_start"])
    end = parse_date(case["planned_end"]) + buffer
    room_code = block["room_code"]
    for other in ordered(list(db.cases.values())):
        if other["id"] == case["id"]:
            continue
        if other["practice_id"] != case["practice_id"]:
            continue
        if other["scheduling_status"] not in COMMITTING_CASE_STATUSES:
            continue
        other_block = get_block(other.get("block_id")) if other.get("block_id") else None
        if other_block is None or other_block["room_code"] != room_code:
            continue
        other_start = parse_date(other["planned_start"])
        other_end = parse_date(other["planned_end"]) + buffer
        if intervals_overlap(start, end, other_start, other_end):
            return True
    return False


def monitor_double_booked(case):
    """No buffer applies to people: back-to-back monitoring is legal."""
    monitor_id = case.get("monitor_staff_id")
    if not monitor_id:
        return False
    start = parse_date(case["planned_start"])
    end = parse_date(case["planned_end"])
    for other in ordered(list(db.cases.values())):
        if other["id"] == case["id"]:
            continue
        if other.get("monitor_staff_id") != monitor_id:
            continue
        if other["scheduling_status"] not in ("BLOCK_HELD", "CONFIRMED", "IN_RECOVERY"):
            continue
        if intervals_overlap(start, end,
                             parse_date(other["planned_start"]),
                             parse_date(other["planned_end"])):
            return True
    return False


def staffing_unmet(case, practice):
    """calculations.sedation_staffing_requirement checks 1-5, in order."""
    level = case["planned_anesthesia_level"]
    monitor_required = level != "LOCAL_ONLY"
    must_be_certified = level in ("MODERATE_SEDATION", "DEEP_SEDATION_GENERAL")
    acls_required = must_be_certified
    nurse_required = level == "DEEP_SEDATION_GENERAL"

    if monitor_required and not case.get("monitor_staff_id"):
        return True
    if monitor_required:
        monitor = get_staff(case.get("monitor_staff_id"))
        if monitor is None or monitor["role_type"] != "ANESTHESIA_MONITOR":
            return True
        if must_be_certified and not monitor.get("monitoring_certified"):
            return True
    if acls_required:
        surgeon = get_staff(case.get("primary_surgeon_id"))
        acls = surgeon.get("acls_expires_on") if surgeon else None
        if not acls:
            return True
        if parse_date(acls) <= parse_date(case["planned_start"]):
            return True
    if nurse_required:
        nurses = [s for s in db.staff.values()
                  if s["practice_id"] == case["practice_id"] and s["role_type"] == "RECOVERY_NURSE"]
        if not nurses:
            return True
    return False


def recovery_interval(case):
    minutes = int(case.get("recovery_minutes_required") or 0)
    start = parse_date(case["planned_end"])
    return start, start + timedelta(minutes=minutes), minutes


def recovery_capacity_exceeded(case, practice):
    """calculations.recovery_capacity_projection - peak concurrency inside the candidate window."""
    start, end, minutes = recovery_interval(case)
    if minutes <= 0:
        return False
    occupying = []
    for other in db.cases.values():
        if other["id"] == case["id"]:
            continue
        if other["practice_id"] != case["practice_id"]:
            continue
        if other["scheduling_status"] not in ("CONFIRMED", "IN_RECOVERY"):
            continue
        o_start, o_end, o_minutes = recovery_interval(other)
        if o_minutes <= 0:
            continue
        if intervals_overlap(start, end, o_start, o_end):
            occupying.append((o_start, o_end, other))
    occupying.sort(key=lambda item: (item[2]["planned_end"], item[2]["created_at"], item[2]["_seq"]))
    instants = [start]
    for o_start, _o_end, _other in occupying:
        if start <= o_start < end:
            instants.append(o_start)
    peak = 0
    for moment in instants:
        concurrent = 1
        for o_start, o_end, _other in occupying:
            if o_start <= moment < o_end:
                concurrent += 1
        peak = max(peak, concurrent)
    return peak > int(practice["recovery_bay_count"])
