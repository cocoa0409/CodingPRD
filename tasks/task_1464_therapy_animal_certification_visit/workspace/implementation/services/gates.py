"""Gate checks: rabies vaccination, insurance adequacy, visit-creation chain."""
from datetime import timedelta, date as date_cls

from db import store
from constants import (
    PROGRAM_FLOOR_CENTS, WORKLOAD_FORWARD_CAP_MINUTES, DAILY_VISIT_LIMIT,
)
from errors import err
from services import credits
from services.records import touch
from util import now_dt, today, parse_date, parse_datetime, iso_week_key


# ---------------------------------------------------------------------------
# Rabies vaccination gate
# ---------------------------------------------------------------------------

def check_rabies(animal_id, required_date):
    """ERR_VACCINATION_MISSING when no RABIES record exists at all;
    ERR_VACCINATION_EXPIRED when records exist but none is VALID covering the date
    (a lapsed record counts as expired whether or not the sweep has run)."""
    records = [r for r in store.vaccinations.values()
               if r["animal_id"] == animal_id and r["vaccine_type"] == "RABIES"]
    if not records:
        raise err("ERR_VACCINATION_MISSING", 403,
                  "No RABIES vaccination record exists for the animal")
    for r in records:
        if r["status"] == "VALID" and parse_date(r["valid_until"]) >= required_date:
            return
    raise err("ERR_VACCINATION_EXPIRED", 403,
              "No VALID RABIES vaccination covers the required date")


def has_valid_rabies(animal_id, required_date):
    try:
        check_rabies(animal_id, required_date)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Insurance adequacy
# ---------------------------------------------------------------------------

def facility_required_cents(facility):
    base = max(PROGRAM_FLOOR_CENTS, facility.get("min_liability_coverage_cents") or 0)
    if facility.get("facility_type") == "HOSPITAL":
        # 1.5x rounded half-up to a whole cent (base is integral, so base*1.5
        # is either exact or ends in .5; half-up on .5 rounds away from zero)
        base = (base * 3 + 1) // 2
    return base


def active_policies(handler_id, on_date):
    out = []
    for p in store.policies.values():
        if p["handler_id"] != handler_id or p["status"] != "ACTIVE":
            continue
        if parse_date(p["effective_from"]) <= on_date <= parse_date(p["effective_until"]):
            out.append(p)
    return out


def check_insurance(handler_id, required_cents):
    """ERR_NO_ACTIVE_INSURANCE when no ACTIVE policy covers today;
    ERR_INSURANCE_COVERAGE_INADEQUATE when one exists but coverage falls short."""
    today_d = today()
    policies = active_policies(handler_id, today_d)
    if not policies:
        raise err("ERR_NO_ACTIVE_INSURANCE", 402,
                  "No ACTIVE insurance policy covers today")
    if any(p["coverage_cents"] >= required_cents for p in policies):
        return
    raise err("ERR_INSURANCE_COVERAGE_INADEQUATE", 402,
              "ACTIVE policy coverage is below the required amount")


def insurance_adequate(handler_id, required_cents):
    try:
        check_insurance(handler_id, required_cents)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Certification helpers
# ---------------------------------------------------------------------------

def team_certification(team_id, statuses=None):
    for c in store.certifications.values():
        if c["team_id"] != team_id:
            continue
        if statuses is None or c["status"] in statuses:
            return c
    return None


def team_active_certification(team_id):
    return team_certification(team_id, ("ACTIVE", "RENEWAL_DUE"))


# ---------------------------------------------------------------------------
# Visit-creation gate chain (POST /v1/visits and request accept)
# ---------------------------------------------------------------------------

def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap; bare adjacency allowed."""
    return a_start < b_end and b_start < a_end


def run_visit_gates(team, facility, sched_start, sched_end, exclude_visit_id=None):
    """Run the full visit-creation gate chain in pipeline order.

    Assumes auth (1-3), path existence (4), body schema (5), and OCC (6) have
    already been handled by the caller. This runs categories 7-12.
    """
    now = now_dt()
    today_d = now.date()
    animal = store.animals.get(team["animal_id"])
    handler = store.handlers.get(team["handler_id"])

    # --- 7. State preconditions ---
    if team["status"] != "ACTIVE":
        raise err("ERR_TEAM_NOT_ACTIVE", 409, "Team is not ACTIVE")
    if facility["status"] != "ACTIVE":
        raise err("ERR_FACILITY_NOT_ACTIVE", 409, "Facility is not ACTIVE")
    if animal is None or animal["status"] != "ACTIVE":
        raise err("ERR_ANIMAL_NOT_ACTIVE", 409, "Animal is not ACTIVE")

    duration_minutes = int((sched_end - sched_start).total_seconds() // 60)

    # --- 8. Animal welfare and biosafety ---
    if animal["status"] == "WELFARE_HOLD":
        raise err("ERR_ANIMAL_WELFARE_HOLD", 403, "Animal is in WELFARE_HOLD")
    blocked_until = animal.get("welfare_blocked_until")
    if blocked_until and sched_start < parse_datetime(blocked_until):
        raise err("ERR_ANIMAL_REST_PERIOD", 403,
                  "The animal's rest block has not elapsed")
    existing_forward = credits.forward_workload_minutes(animal["id"])
    if existing_forward + duration_minutes > WORKLOAD_FORWARD_CAP_MINUTES:
        raise err("ERR_WORKLOAD_LIMIT_EXCEEDED", 403,
                  "Forward workload cap of 240 minutes would be exceeded")
    # daily visit limit: 2 visits in SCHEDULED/IN_PROGRESS/COMPLETED per UTC day
    day = sched_start.date()
    daily = 0
    for v in store.visits.values():
        if v["id"] == exclude_visit_id:
            continue
        v_team = store.teams.get(v["team_id"])
        if v_team is None or v_team["animal_id"] != animal["id"]:
            continue
        if v["lifecycle_status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        if parse_datetime(v["scheduled_start"]).date() == day:
            daily += 1
    if daily >= DAILY_VISIT_LIMIT:
        raise err("ERR_DAILY_VISIT_LIMIT_EXCEEDED", 403,
                  "Animal already has 2 visits on that day")
    if animal["species"] not in facility["allowed_species"]:
        raise err("ERR_SPECIES_NOT_PERMITTED", 403,
                  "Animal species is not permitted at this facility")
    check_rabies(animal["id"], day)

    # --- 9. Cross-entity referential integrity ---
    cert = team_active_certification(team["id"])
    if cert is None:
        raise err("ERR_CERT_NOT_ACTIVE", 409,
                  "Team certification is not ACTIVE or RENEWAL_DUE")
    sched_date = sched_start.date()
    agreement = credits.covering_active_agreement(facility["id"], sched_date)
    if agreement is None:
        raise err("ERR_NO_ACTIVE_AGREEMENT", 409,
                  "No ACTIVE agreement covers the facility on the scheduled date")
    orientation_ok = False
    for o in store.orientations.values():
        if (o["team_id"] == team["id"] and o["facility_id"] == facility["id"]
                and o["status"] == "COMPLETED"
                and o.get("expires_on") and parse_date(o["expires_on"]) >= today_d):
            orientation_ok = True
            break
    if not orientation_ok:
        raise err("ERR_ORIENTATION_NOT_COMPLETED", 409,
                  "Orientation is not COMPLETED and unexpired for this team/facility")
    waiver_ok = False
    for w in store.waivers.values():
        if (w["team_id"] == team["id"] and w["facility_id"] == facility["id"]
                and w["status"] == "SIGNED"
                and w["waiver_version"] == facility.get("required_waiver_version")):
            waiver_ok = True
            break
    if not waiver_ok:
        raise err("ERR_WAIVER_NOT_ON_FILE", 409,
                  "No SIGNED waiver matches the facility's required_waiver_version")

    # --- 10. Temporal windows ---
    if sched_start < now:
        raise err("ERR_VISIT_IN_PAST", 409, "scheduled_start lies in the past")
    for v in store.visits.values():
        if v["id"] == exclude_visit_id or v["team_id"] != team["id"]:
            continue
        if v["lifecycle_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if _overlaps(sched_start, sched_end,
                     parse_datetime(v["scheduled_start"]), parse_datetime(v["scheduled_end"])):
            raise err("ERR_TEAM_SCHEDULING_CONFLICT", 409,
                      "The visit overlaps another visit of the same team")

    # --- 11. Fiscal adequacy ---
    check_insurance(handler["id"], facility_required_cents(facility))

    # --- 12. Capacity / minimums ---
    if duration_minutes < 30:
        raise err("ERR_VISIT_DURATION_INVALID", 422,
                  "Visit duration must be at least 30 minutes")
    cap = credits.effective_cap_minutes(facility, agreement)
    if duration_minutes > cap:
        raise err("ERR_VISIT_DURATION_EXCEEDS_CAP", 422,
                  "Visit duration exceeds the effective cap")
    # overlap capacity at the facility
    if _facility_overlap_would_exceed(facility, sched_start, sched_end, exclude_visit_id):
        raise err("ERR_FACILITY_CAPACITY_EXCEEDED", 422,
                  "Facility overlapping-visit capacity would be exceeded")
    # ISO weekly cap
    week = iso_week_key(sched_start)
    weekly = 0
    for v in store.visits.values():
        if v["id"] == exclude_visit_id or v["facility_id"] != facility["id"]:
            continue
        if v["lifecycle_status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        if iso_week_key(parse_datetime(v["scheduled_start"])) == week:
            weekly += 1
    if weekly >= facility["visits_per_week_cap"]:
        raise err("ERR_FACILITY_WEEKLY_CAP_EXCEEDED", 422,
                  "Facility weekly visit cap reached")

    return agreement


def _facility_overlap_would_exceed(facility, sched_start, sched_end, exclude_visit_id):
    """True if adding [sched_start, sched_end) makes the maximum number of visits
    overlapping at any instant exceed max_overlapping_teams."""
    intervals = [(sched_start, sched_end)]
    for v in store.visits.values():
        if v["id"] == exclude_visit_id or v["facility_id"] != facility["id"]:
            continue
        if v["lifecycle_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        intervals.append((parse_datetime(v["scheduled_start"]),
                          parse_datetime(v["scheduled_end"])))
    events = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    # End events sort before start events at the same instant (half-open).
    events.sort(key=lambda x: (x[0], x[1]))
    concurrent = 0
    peak = 0
    for _, delta in events:
        concurrent += delta
        peak = max(peak, concurrent)
    return peak > facility["max_overlapping_teams"]


# ---------------------------------------------------------------------------
# Visit materialization (shared by direct scheduling and request acceptance)
# ---------------------------------------------------------------------------

def create_visit(team, facility, sched_start, sched_end, request_id=None):
    from services.records import new_record
    visit = new_record(store.visits, {
        "team_id": team["id"],
        "facility_id": facility["id"],
        "request_id": request_id,
        "scheduled_start": sched_start.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (sched_start.microsecond // 1000)) + "Z",
        "scheduled_end": sched_end.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (sched_end.microsecond // 1000)) + "Z",
        "actual_start": None,
        "actual_end": None,
        "actual_minutes": None,
        "lifecycle_status": "SCHEDULED",
        "verification_status": "UNVERIFIED",
        "cancel_reason": None,
        "cancelled_at": None,
        "verified_at": None,
        "approved_minutes": None,
    })
    # Booking mutates the team's workload bookkeeping: version increments by 1.
    touch(team)
    animal = store.animals.get(team["animal_id"])
    if animal is not None:
        credits.recompute_animal_workloads(animal)
    return visit
