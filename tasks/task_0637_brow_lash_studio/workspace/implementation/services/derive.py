"""Derived / computed field reconciliation (PRD §2.7, §3.2, §3.3, §3.6).

These are pure read-time computations against current state + logical clock.
They do NOT mutate or version-bump on their own; callers that perform a write
(e.g. recording a no-show) bump version explicitly per PRD §2.5.
"""
from datetime import timedelta

from clock import clock, parse_iso8601
from db import store

SANITATION_VALIDITY_HOURS = 12
PATCH_TEST_VALIDITY_DAYS = 365


# --------------------------------------------------------------------------
# LashTech.station_sanitized_through_utc (PRD §3.2)
# --------------------------------------------------------------------------
def station_sanitized_through_utc(tech_id):
    """Latest valid_through_utc among the tech's COMPLETED sanitation logs
    (voided logs excluded); None if no such log."""
    best = None
    for log in store.sanitation_logs.values():
        if log["lash_tech_id"] != tech_id:
            continue
        if log["status"] != "COMPLETED":
            continue
        vt = log["valid_through_utc"]  # tz-aware datetime
        if best is None or vt > best:
            best = vt
    return best


def sanitation_valid_through(sanitized_at):
    return sanitized_at + timedelta(hours=SANITATION_VALIDITY_HOURS)


# --------------------------------------------------------------------------
# Member.noshow_strike_count (PRD §3.3 / calculations.noshow_strike_count)
# --------------------------------------------------------------------------
def noshow_strike_count(member):
    """Count of this member's NO_SHOW appointments whose start_utc is within
    Studio.noshow_strike_window_days before the current clock."""
    studio = store.studios.get(member["studio_id"])
    window_days = studio["noshow_strike_window_days"] if studio else 90
    now = clock.now()
    window_start = now - timedelta(days=window_days)
    count = 0
    for appt in store.appointments.values():
        if appt["member_id"] != member["id"]:
            continue
        if appt["status"] != "NO_SHOW":
            continue
        if appt["start_utc"] >= window_start:
            count += 1
    return count


# --------------------------------------------------------------------------
# Member.last_premium_completed_utc (PRD §3.3, §3.8)
# --------------------------------------------------------------------------
def last_premium_completed_utc(member):
    """start_utc of the member's most recent COMPLETED appointment whose
    ServiceType.category == PREMIUM; None if none."""
    best = None
    for appt in store.appointments.values():
        if appt["member_id"] != member["id"]:
            continue
        if appt["status"] != "COMPLETED":
            continue
        st = store.service_types.get(appt["service_type_id"])
        if not st or st["category"] != "PREMIUM":
            continue
        if best is None or appt["start_utc"] > best:
            best = appt["start_utc"]
    return best


# --------------------------------------------------------------------------
# ConsentPatchTest auto-expiry (PRD §3.3)
# --------------------------------------------------------------------------
def effective_patch_test_status(pt):
    """A patch test is treated as EXPIRED once the current clock is strictly
    past its valid_through_utc (only from VALID; REVOKED stays REVOKED)."""
    if pt["status"] == "VALID" and clock.now() > pt["valid_through_utc"]:
        return "EXPIRED"
    return pt["status"]
