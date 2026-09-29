"""Cleaner selection: zone fit, skill headroom, daily load and overlap buffers.

PRD 3.4 and 2.6.
"""

from datetime import timedelta

from db import db, ordered
from services.money import dec, round_half_up
from services.window import (
    CROSS_ZONE_BUFFER_MINUTES,
    SAME_ZONE_BUFFER_MINUTES,
    local_date,
)

W_QUALITY = dec("0.50")
W_ZONE = dec("0.30")
W_SKILL = dec("0.20")
SKILL_HEADROOM_DIVISOR = dec(4)

NON_TERMINAL_ASSIGNMENT_STATUSES = ("OFFERED", "ACCEPTED", "ACTIVE")


def zone_match_factor(cleaner, prop):
    if cleaner["home_zone_code"] == prop["zone_code"]:
        return dec("1.0")
    if prop["zone_code"] in cleaner["secondary_zone_codes"]:
        return dec("0.4")
    return dec("0.0")


def serves_zone(cleaner, prop):
    if cleaner["home_zone_code"] == prop["zone_code"]:
        return True
    if prop["zone_code"] in cleaner["secondary_zone_codes"]:
        return True
    return bool(cleaner["accepts_cross_zone"])


def match_score(cleaner, prop):
    normalized_quality = dec(cleaner["quality_score"]) / dec(100)
    headroom = (dec(cleaner["skill_level"] - prop["min_skill_level"] + 1)
                / SKILL_HEADROOM_DIVISOR)
    if headroom > dec(1):
        headroom = dec(1)
    total = (W_QUALITY * normalized_quality
             + W_ZONE * zone_match_factor(cleaner, prop)
             + W_SKILL * headroom)
    return round_half_up(total, 4)


def _cleaner_assignments(cleaner_id, exclude_turnover_id):
    result = []
    for assignment in ordered(db.assignments.values()):
        if assignment["cleaner_id"] != cleaner_id:
            continue
        if assignment["status"] not in NON_TERMINAL_ASSIGNMENT_STATUSES:
            continue
        if exclude_turnover_id is not None and assignment["turnover_id"] == exclude_turnover_id:
            continue
        result.append(assignment)
    return result


def daily_load(cleaner_id, turnover):
    """Count of the cleaner's non-terminal assignments on the turnover's
    property-local calendar date (PRD 3.4)."""
    prop = db.properties[turnover["property_id"]]
    target = local_date(turnover["window_start_at"], prop["local_utc_offset_minutes"])
    count = 0
    for assignment in _cleaner_assignments(cleaner_id, turnover["id"]):
        other = db.turnovers.get(assignment["turnover_id"])
        if other is None or other.get("window_start_at") is None:
            continue
        other_prop = db.properties[other["property_id"]]
        if local_date(other["window_start_at"], other_prop["local_utc_offset_minutes"]) == target:
            count += 1
    return count


def daily_cap_reached(cleaner, turnover):
    return daily_load(cleaner["id"], turnover) >= cleaner["max_daily_turnovers"]


def windows_conflict(turnover_a, turnover_b):
    prop_a = db.properties[turnover_a["property_id"]]
    prop_b = db.properties[turnover_b["property_id"]]
    buffer_minutes = (SAME_ZONE_BUFFER_MINUTES
                      if prop_a["zone_code"] == prop_b["zone_code"]
                      else CROSS_ZONE_BUFFER_MINUTES)
    buffer_delta = timedelta(minutes=buffer_minutes)
    return (turnover_a["window_start_at"] < turnover_b["window_end_at"] + buffer_delta
            and turnover_b["window_start_at"] < turnover_a["window_end_at"] + buffer_delta)


def has_schedule_conflict(cleaner, turnover):
    for assignment in _cleaner_assignments(cleaner["id"], turnover["id"]):
        other = db.turnovers.get(assignment["turnover_id"])
        if other is None or other.get("window_start_at") is None:
            continue
        if windows_conflict(turnover, other):
            return True
    return False


def candidate_pool(turnover, prop, exclude_ids):
    excluded = set(exclude_ids or [])
    pool = []
    for cleaner in ordered(db.cleaners.values()):
        if cleaner["id"] in excluded:
            continue
        if cleaner["status"] != "ACTIVE":
            continue
        if not serves_zone(cleaner, prop):
            continue
        if cleaner["skill_level"] < prop["min_skill_level"]:
            continue
        if daily_cap_reached(cleaner, turnover):
            continue
        if has_schedule_conflict(cleaner, turnover):
            continue
        pool.append(cleaner)
    return pool


def rank_pool(pool, turnover, prop):
    """Highest match_score wins; ties broken by higher skill_level, then lower
    daily load, then earlier cleaner created_at (never the identifier)."""
    def sort_key(cleaner):
        return (
            -match_score(cleaner, prop),
            -cleaner["skill_level"],
            daily_load(cleaner["id"], turnover),
            cleaner["created_at"],
            cleaner["_seq"],
        )

    return sorted(pool, key=sort_key)
