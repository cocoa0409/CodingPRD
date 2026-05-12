"""Staff assignment validations: chain match, overlap, qualification, weekly minutes, depth."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from db import store, parse_iso
from errors import (
    raise_error,
    ERR_STAFF_CHAIN_MISMATCH, ERR_STAFF_OVERLAP_CONFLICT,
    ERR_STAFF_QUALIFICATION_MISMATCH, ERR_STAFF_WEEKLY_LIMIT_EXCEEDED,
    ERR_SUBSTITUTE_DEPTH_EXCEEDED,
)


def chain_for_staff_check(staff: dict, slot: dict):
    venue = store.venues[slot["venue_id"]]
    if staff["chain_id"] != venue["chain_id"]:
        raise_error(ERR_STAFF_CHAIN_MISMATCH, "staff chain mismatch")


def staff_overlap_check(staff_id: str, slot: dict, ignore_assignment_id: str | None = None):
    p_start = parse_iso(slot["starts_at"])
    p_end = parse_iso(slot["ends_at"])
    for a in store.staff_assignments.values():
        if a["staff_member_id"] != staff_id:
            continue
        if ignore_assignment_id and a["id"] == ignore_assignment_id:
            continue
        if a["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        # Use the assignment's slot
        a_slot = store.session_slots.get(a["slot_id"])
        if not a_slot:
            continue
        a_start = parse_iso(a_slot["starts_at"])
        a_end = parse_iso(a_slot["ends_at"])
        if max(p_start, a_start) < min(p_end, a_end):
            raise_error(ERR_STAFF_OVERLAP_CONFLICT, "staff overlap")


def qualification_check(staff: dict, slot: dict, role_type: str):
    theme = store.themes[slot["theme_id"]]
    if role_type == "HOST":
        if "HOST" not in (staff.get("roles_held") or []):
            raise_error(ERR_STAFF_QUALIFICATION_MISMATCH, "staff lacks HOST role")
        required = set(theme.get("required_host_qualifications") or [])
        held = set(staff.get("qualifications") or [])
        if not required.issubset(held):
            raise_error(ERR_STAFF_QUALIFICATION_MISMATCH, "staff lacks required HOST qualifications")
    elif role_type == "NPC":
        if "NPC" not in (staff.get("roles_held") or []):
            raise_error(ERR_STAFF_QUALIFICATION_MISMATCH, "staff lacks NPC role")
        if int(theme.get("required_npc_count", 0)) < 1:
            raise_error(ERR_STAFF_QUALIFICATION_MISMATCH, "theme requires no NPC")
    else:
        raise_error(ERR_STAFF_QUALIFICATION_MISMATCH, "invalid role_type")


def representative_tz_for_chain(chain_id: str) -> str:
    venues = [v for v in store.venues.values() if v["chain_id"] == chain_id]
    if not venues:
        return "Asia/Shanghai"
    venues.sort(key=lambda v: (v["created_at"], v["id"]))
    return venues[0].get("timezone") or "Asia/Shanghai"


def iso_week_of(starts_at_iso: str, tz: str) -> tuple[int, int]:
    dt = parse_iso(starts_at_iso)
    try:
        local = dt.astimezone(ZoneInfo(tz))
    except Exception:
        local = dt
    iso = local.isocalendar()
    return iso[0], iso[1]


def weekly_minutes_check(staff: dict, slot: dict, proposed_minutes: int,
                         ignore_assignment_id: str | None = None):
    chain_tz = representative_tz_for_chain(staff["chain_id"])
    target_week = iso_week_of(slot["starts_at"], chain_tz)

    existing = 0
    for a in store.staff_assignments.values():
        if a["staff_member_id"] != staff["id"]:
            continue
        if ignore_assignment_id and a["id"] == ignore_assignment_id:
            continue
        if a["status"] not in ("SCHEDULED", "ACTIVE", "COMPLETED"):
            continue
        a_slot = store.session_slots.get(a["slot_id"])
        if not a_slot:
            continue
        if iso_week_of(a_slot["starts_at"], chain_tz) != target_week:
            continue
        existing += int(a["assignment_minutes"])
    if existing + proposed_minutes > int(staff.get("max_weekly_minutes", 2400)):
        raise_error(ERR_STAFF_WEEKLY_LIMIT_EXCEEDED, "weekly minutes exceeded")


def depth_check(original_assignment: dict):
    if original_assignment.get("substitute_of_assignment_id") is not None:
        raise_error(ERR_SUBSTITUTE_DEPTH_EXCEEDED, "substitution depth max 1")
