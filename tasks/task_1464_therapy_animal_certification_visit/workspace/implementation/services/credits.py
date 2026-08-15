"""Volunteer hour ledger, recognition tiers, and animal workload bookkeeping."""
from datetime import timedelta

from db import store
from constants import TIER_THRESHOLDS, WINDOW_PAST_DAYS, WINDOW_FUTURE_DAYS
from errors import err
from services.records import new_ledger_row, touch
from util import now_dt, parse_datetime, round_half_up, round_to_unit_half_up


# ---------------------------------------------------------------------------
# Rest requirement (per completed visit's actual_minutes)
# ---------------------------------------------------------------------------

def rest_requirement_minutes(actual_minutes):
    if actual_minutes <= 30:
        return 60
    if actual_minutes <= 60:
        return 120
    return 240


# ---------------------------------------------------------------------------
# Recognition tier
# ---------------------------------------------------------------------------

def tier_for(lifetime_minutes):
    for name, threshold in TIER_THRESHOLDS:
        if lifetime_minutes >= threshold:
            return name
    return "NONE"


def recompute_handler_recognition(handler):
    """lifetime_minutes = floored algebraic sum over ALL ledger rows."""
    total = sum(
        row["minutes"] for row in store.hour_credits.values()
        if row["handler_id"] == handler["id"]
    )
    if total < 0:
        total = 0
    changed = (handler.get("lifetime_minutes") != total
               or handler.get("recognition_tier") != tier_for(total))
    handler["lifetime_minutes"] = total
    handler["recognition_tier"] = tier_for(total)
    if changed:
        touch(handler)


def post_credit(handler_id, visit_id, kind, minutes, note=None):
    row = new_ledger_row({
        "handler_id": handler_id,
        "visit_id": visit_id,
        "kind": kind,
        "minutes": minutes,
        "note": note,
    })
    handler = store.handlers.get(handler_id)
    if handler is not None:
        recompute_handler_recognition(handler)
    return row


def post_adjustment(handler, minutes, reason):
    """Manual adjustment: minutes != 0 and the resulting lifetime may not go below 0."""
    if minutes == 0:
        raise err("ERR_INVALID_ADJUSTMENT", 422, "Adjustment minutes must be non-zero")
    current = handler.get("lifetime_minutes", 0)
    if current + minutes < 0:
        raise err("ERR_INVALID_ADJUSTMENT", 422,
                  "Adjustment would take lifetime_minutes below 0")
    return post_credit(handler["id"], None, "ADJUSTMENT", minutes, note=reason)


# ---------------------------------------------------------------------------
# Visit credit calculation (visit_credit_minutes)
# ---------------------------------------------------------------------------

def scheduled_minutes_of(visit):
    start = parse_datetime(visit["scheduled_start"])
    end = parse_datetime(visit["scheduled_end"])
    return int((end - start).total_seconds() // 60)


def effective_cap_minutes(facility, agreement):
    cap = 120
    if facility is not None and facility.get("max_visit_minutes") is not None:
        cap = min(cap, facility["max_visit_minutes"])
    if agreement is not None and agreement.get("agreed_max_visit_minutes") is not None:
        cap = min(cap, agreement["agreed_max_visit_minutes"])
    return cap


def covering_active_agreement(facility_id, on_date):
    """The ACTIVE agreement covering the given calendar date (inclusive span)."""
    for ag in store.agreements.values():
        if ag["facility_id"] != facility_id or ag["status"] != "ACTIVE":
            continue
        from util import parse_date
        if parse_date(ag["start_on"]) <= on_date <= parse_date(ag["end_on"]):
            return ag
    return None


def final_credit_minutes(visit, base_minutes):
    """FINAL variant: round_half_up(min(base, scheduled, cap)/15)*15."""
    facility = store.facilities.get(visit["facility_id"])
    sched_date = parse_datetime(visit["scheduled_start"]).date()
    agreement = covering_active_agreement(visit["facility_id"], sched_date)
    cap = effective_cap_minutes(facility, agreement)
    sched = scheduled_minutes_of(visit)
    return round_to_unit_half_up(min(base_minutes, sched, cap), 15)


def reconcile_final_credit(visit, base_minutes):
    """REVERSAL of the provisional amount followed by the FINAL posting."""
    team = store.teams.get(visit["team_id"])
    if team is None:
        return
    handler_id = team["handler_id"]
    provisional = None
    for row in store.hour_credits.values():
        if row.get("visit_id") == visit["id"] and row["kind"] == "PROVISIONAL":
            provisional = row
            break
    prov_amount = provisional["minutes"] if provisional else 0
    if prov_amount:
        post_credit(handler_id, visit["id"], "REVERSAL", -prov_amount,
                    note="verification reversal")
    final_minutes = final_credit_minutes(visit, base_minutes)
    post_credit(handler_id, visit["id"], "FINAL", final_minutes,
                note="verification final")


# ---------------------------------------------------------------------------
# Animal workload figures (welfare_workload_minutes)
# ---------------------------------------------------------------------------

def _animal_visits(animal_id):
    team_ids = [t["id"] for t in store.teams.values() if t["animal_id"] == animal_id]
    return [v for v in store.visits.values() if v["team_id"] in team_ids]


def forward_workload_minutes(animal_id):
    """FORWARD_LOOKING: [now-7d, now+7d) — SCHEDULED/IN_PROGRESS at scheduled
    minutes plus COMPLETED at actual_minutes."""
    now = now_dt()
    lo = now - timedelta(days=WINDOW_PAST_DAYS)
    hi = now + timedelta(days=WINDOW_FUTURE_DAYS)
    total = 0
    for v in _animal_visits(animal_id):
        status = v["lifecycle_status"]
        if status in ("SCHEDULED", "IN_PROGRESS"):
            moment = parse_datetime(v["scheduled_start"])
            if lo <= moment < hi:
                total += scheduled_minutes_of(v)
        elif status == "COMPLETED":
            if v.get("actual_end") is None:
                continue
            moment = parse_datetime(v["actual_end"])
            if lo <= moment < hi:
                total += v.get("actual_minutes") or 0
    return total


def audit_workload_minutes(animal_id):
    """AUDIT: actual_end within [now-7d, now]; COMPLETED at actual_minutes only."""
    now = now_dt()
    lo = now - timedelta(days=WINDOW_PAST_DAYS)
    total = 0
    for v in _animal_visits(animal_id):
        if v["lifecycle_status"] != "COMPLETED" or v.get("actual_end") is None:
            continue
        moment = parse_datetime(v["actual_end"])
        if lo <= moment <= now:
            total += v.get("actual_minutes") or 0
    return total


def recompute_animal_workloads(animal):
    fwd = forward_workload_minutes(animal["id"])
    aud = audit_workload_minutes(animal["id"])
    if animal.get("forward_workload_minutes") != fwd or animal.get("audit_workload_minutes") != aud:
        animal["forward_workload_minutes"] = fwd
        animal["audit_workload_minutes"] = aud
        touch(animal)


def animal_for_team(team):
    return store.animals.get(team["animal_id"])
