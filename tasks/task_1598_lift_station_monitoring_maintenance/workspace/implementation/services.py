"""Business logic: posture derivation, firm capacity, auto-alarms, callout
selection, risk scores, grease analytics, SSO volume, alternation (PRD §3)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    ApiError,
    ERR_STATION_FROZEN,
    ERR_STATION_EMERGENCY,
    ERR_NO_ELIGIBLE_OPERATOR,
    ERR_NO_PUMPS_TO_ALTERNATE,
)

# SsoEvent states that force EMERGENCY posture and count as the "active" set
# for last_sso_occurred_at (PRD 2.7 / 3.8).
ACTIVE_SSO_STATES = ("OPEN", "CONTAINED", "REPORT_DRAFT", "REPORT_SUBMITTED")

# GeneratorTest states driving DEGRADED when scheduled_for is in the past
# (PRD 3.7: "an overdue (or running, or failed) test whose planned time has
# passed" — plus a still-SCHEDULED test past its planned start).
GEN_DEGRADE_STATES = ("SCHEDULED", "RUNNING", "FAILED", "OVERDUE")

ALTERNATION_THRESHOLD_HOURS = Decimal("24.0")
SURFACE_WATER_MULTIPLIER = Decimal("1.20")
TARGET_DEPTH_INCHES = Decimal("6.0")
RECENCY_BONUS = 15
RESILIENCE_BONUS = 10
AGE_SCORE_CAP = 25


# --------------------------------------------------------------------- stations


def compute_firm_capacity(station):
    """N-1 criterion (calculation firm_capacity_n_minus_1)."""
    in_service = [
        p for p in db.pumps.values()
        if p["station_id"] == station["id"] and p["status"] == "IN_SERVICE"
    ]
    if not in_service:
        return 0
    total = sum(p["rated_gpm"] for p in in_service)
    return total - max(p["rated_gpm"] for p in in_service)


def derive_posture(station):
    """Calculation station_posture: FROZEN sticky; EMERGENCY > DEGRADED > NORMAL."""
    if station["_frozen"]:
        return "FROZEN"
    sid = station["id"]
    for ev in db.sso_events.values():
        if ev["station_id"] == sid and ev["status"] in ACTIVE_SSO_STATES:
            return "EMERGENCY"
    if station["firm_capacity_available_gpm"] < station["design_capacity_gpm"]:
        return "DEGRADED"
    for p in db.pumps.values():
        if p["station_id"] == sid and p["status"] == "REBUILD":
            return "DEGRADED"
    now = db.now()
    for t in db.generator_tests.values():
        if (t["station_id"] == sid and t["status"] in GEN_DEGRADE_STATES
                and t["scheduled_for"] < now):
            return "DEGRADED"
    return "NORMAL"


def auto_alarm(station_id, alarm_class, alarm_code):
    """Fire an automatic AlarmTicket (PRD 2.10); enters OPEN like any ticket."""
    ticket = {
        "id": db.new_id(),
        "station_id": station_id,
        "alarm_class": alarm_class,
        "alarm_code": alarm_code,
        "raised_at": db.now(),
        "status": "OPEN",
        "assigned_operator_id": None,
        "acked_at": None,
        "dispatched_at": None,
        "cleared_at": None,
        "response_minutes": None,
        "is_sso_related": False,
    }
    db.stamp(ticket)
    db.alarm_tickets[ticket["id"]] = ticket
    return ticket


def sync_station(station, force_bump=False):
    """Recompute firm capacity, last_sso_occurred_at, and posture; bump the
    station version once when anything changed (or when the triggering
    endpoint declares an explicit increment). Fires STATION_DEGRADED on a
    NORMAL -> DEGRADED transition only."""
    changed = False
    cap = compute_firm_capacity(station)
    if cap != station["firm_capacity_available_gpm"]:
        station["firm_capacity_available_gpm"] = cap
        changed = True
    # last_sso_occurred_at tracks the most recent SSO occurrence at the
    # station (PRD 3.1 "null until an overflow occurs"; 3.8 creation sets it
    # to the event's started_at; acceptance/closure merely recompute it — the
    # field is persistent history feeding the 365-day recency bonus in 3.10,
    # not a function of the posture-forcing set).
    events = [
        e for e in db.sso_events.values()
        if e["station_id"] == station["id"]
    ]
    last = max((e["started_at"] for e in events), default=None)
    if last != station["last_sso_occurred_at"]:
        station["last_sso_occurred_at"] = last
        changed = True
    new_posture = derive_posture(station)
    old_posture = station["operational_posture"]
    if new_posture != old_posture:
        station["operational_posture"] = new_posture
        changed = True
        if old_posture == "NORMAL" and new_posture == "DEGRADED":
            auto_alarm(station["id"], "MAJOR", "STATION_DEGRADED")
    if changed or force_bump:
        db.touch(station)
    return changed


def check_posture(station, allow_emergency=False):
    """Posture gate for child mutations (PRD 2.7). FROZEN blocks everything;
    EMERGENCY blocks all but SSO-lifecycle and alarm-ticket actions."""
    posture = station["operational_posture"]
    if posture == "FROZEN":
        raise ApiError(
            ERR_STATION_FROZEN, 409,
            "Station %s is FROZEN; child mutations are refused" % station["id"],
        )
    if posture == "EMERGENCY" and not allow_emergency:
        raise ApiError(
            ERR_STATION_EMERGENCY, 409,
            "Station %s is in EMERGENCY; only SSO and alarm actions are permitted"
            % station["id"],
        )


# --------------------------------------------------------------------- operators


def operator_active_ticket_count(operator_id):
    return sum(
        1 for t in db.alarm_tickets.values()
        if t["assigned_operator_id"] == operator_id
        and t["status"] in ("DISPATCHED", "ON_SCENE")
    )


def operator_callouts_24h(operator):
    cutoff = db.now() - timedelta(hours=24)
    return sum(1 for ts in operator["_dispatch_times"] if ts >= cutoff)


def select_callout_operator(station, alarm_class):
    """Calculation operator_callout_selection: eligibility filter, weighted
    score, highest score wins with earliest created_at breaking ties."""
    pool = []
    for op in db.operators.values():
        if not op["is_active"]:
            continue
        atc = operator_active_ticket_count(op["id"])
        if atc >= 3:
            continue
        if alarm_class == "CRITICAL" and "COLLECTIONS_2" not in op["certifications"]:
            continue
        score = (100 if op["home_zone"] == station["service_zone"] else 0)
        score -= 50 * atc
        score -= 10 * operator_callouts_24h(op)
        pool.append((op, score))
    if not pool:
        raise ApiError(
            ERR_NO_ELIGIBLE_OPERATOR, 422,
            "No active, under-capacity, cert-qualified operator is eligible",
        )
    pool.sort(key=lambda x: (-x[1], x[0]["created_at"], x[0]["_seq"]))
    return pool[0][0]


# --------------------------------------------------------------------- capital


def compute_risk_score(project, station):
    """Calculation capital_risk_score (2dp, round-half-up, capped at 100)."""
    base = project["consequence_of_failure"] * project["likelihood_of_failure"]
    recency = 0
    last = station["last_sso_occurred_at"]
    if last is not None and (db.now() - last).days < 365:
        recency = RECENCY_BONUS
    resilience = 0 if station["has_backup_generator"] else RESILIENCE_BONUS
    age_days = (db.now() - station["created_at"]).days
    age_score = min(AGE_SCORE_CAP, math.floor(age_days / 365.25))
    if age_score < 0:
        age_score = 0
    total = min(100, base + recency + resilience + age_score)
    return Decimal(total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def plan_allocated(plan_id):
    """Sum of estimated_cost_usd over projects in PROPOSED/RANKED/APPROVED."""
    total = Decimal("0.00")
    for p in db.capital_projects.values():
        if p["plan_id"] == plan_id and p["status"] in ("PROPOSED", "RANKED", "APPROVED"):
            total += p["estimated_cost_usd"]
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sync_plan_budget(plan):
    """Refresh the plan's derived budget field; bump version when it changed."""
    alloc = plan_allocated(plan["id"])
    if alloc != plan["budget_allocated_usd"]:
        plan["budget_allocated_usd"] = alloc
        db.touch(plan)
        return True
    return False


def rank_projects(plan):
    """Calculation capital_project_ranking: risk DESC, cost ASC, created ASC,
    id ASC; assign 1-based priority_rank and cascade PROPOSED -> RANKED."""
    projects = [
        p for p in db.capital_projects.values()
        if p["plan_id"] == plan["id"] and p["status"] == "PROPOSED"
    ]
    for p in projects:
        station = db.stations.get(p["station_id"])
        p["risk_score"] = compute_risk_score(p, station) if station else Decimal("0.00")
    projects.sort(key=lambda p: (
        -p["risk_score"], p["estimated_cost_usd"], p["created_at"], p["id"],
    ))
    for idx, p in enumerate(projects, start=1):
        p["priority_rank"] = idx
        p["status"] = "RANKED"
        db.touch(p)
    return projects


# --------------------------------------------------------------------- SSO volume


def compute_sso_volume(event, station):
    """Calculation sso_volume_estimate: whole minutes x firm capacity, x1.20
    when the overflow reached surface water; round-half-up to whole gallons."""
    seconds = (event["stopped_at"] - event["started_at"]).total_seconds()
    duration_minutes = math.floor(seconds / 60)
    base = Decimal(duration_minutes) * Decimal(station["firm_capacity_available_gpm"])
    if event["reached_surface_water"]:
        base = base * SURFACE_WATER_MULTIPLIER
    return int(base.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------- grease


def completed_cleanings(station_id):
    comps = [
        c for c in db.wet_well_cleanings.values()
        if c["station_id"] == station_id and c["status"] == "COMPLETED"
    ]
    return sorted(comps, key=lambda c: (c["completed_at"], c["_seq"]))


def grease_accumulation_rate(station_id):
    """Calculation grease_accumulation_rate (calendar-day variant, 3dp)."""
    comps = completed_cleanings(station_id)
    if len(comps) < 2:
        return None
    total_inches = sum(
        (c["grease_depth_inches_pre"] for c in comps[1:]), Decimal("0.0")
    )
    days = (comps[-1]["completed_at"] - comps[0]["completed_at"]).days
    if days == 0:
        return None
    rate = total_inches / Decimal(days)
    return rate.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def next_cleaning_due(station_id):
    """Calculation next_cleaning_due: last completion + days for the grease cap
    to grow from the latest post depth to the 6.0-inch threshold at `rate`."""
    rate = grease_accumulation_rate(station_id)
    if rate is None or rate <= 0:
        return None
    comps = completed_cleanings(station_id)
    last = comps[-1]
    current_depth = last["grease_depth_inches_post"]
    days_to_target = (TARGET_DEPTH_INCHES - current_depth) / rate
    seconds = float(days_to_target) * 86400.0
    due = last["completed_at"] + timedelta(seconds=int(round(seconds)))
    return due.replace(second=0, microsecond=0)


# --------------------------------------------------------------------- alternation


def run_alternation(station):
    """Calculation pump_alternation_selection; swaps lead/lag positions when
    the candidate's runtime exceeds the lead's by the 24.0h threshold."""
    candidates = [
        p for p in db.pumps.values()
        if p["station_id"] == station["id"] and p["status"] == "IN_SERVICE"
    ]
    if len(candidates) < 2:
        raise ApiError(
            ERR_NO_PUMPS_TO_ALTERNATE, 422,
            "Fewer than two IN_SERVICE pumps at station %s" % station["id"],
        )
    lead = min(candidates, key=lambda p: (p["position_index"], p["_seq"]))
    others = [p for p in candidates if p["id"] != lead["id"]]
    nxt = min(
        others,
        key=lambda p: (p["runtime_since_rebuild_hours"], p["created_at"], p["_seq"]),
    )
    if nxt["runtime_since_rebuild_hours"] >= (
        lead["runtime_since_rebuild_hours"] + ALTERNATION_THRESHOLD_HOURS
    ):
        lead["position_index"], nxt["position_index"] = (
            nxt["position_index"], lead["position_index"],
        )
        nxt["last_alternation_at"] = db.now()
        db.touch(lead)
        db.touch(nxt)
        return nxt
    return lead
