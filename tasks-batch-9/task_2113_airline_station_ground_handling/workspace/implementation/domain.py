"""Derived attributes, ledgers, cascades and serialisers."""
from decimal import Decimal

from flask import g

import constants as C
from errors import ApiError
from store import (
    as_dt, db, format_iso, new_record, now_stamp, ordered, pct2, plus_minutes,
    rhu, rhu_cents, serialize, whole_days_between, whole_minutes_between,
)


# ------------------------------------------------------------------ mutation
def bump(record):
    """Refresh updated_at and increment version, at most once per request."""
    key = (record["_kind"], record["id"])
    bumped = getattr(g, "bumped", None)
    if bumped is None:
        bumped = set()
        g.bumped = bumped
    if key in bumped:
        return
    bumped.add(key)
    record["version"] = record["version"] + 1
    record["updated_at"] = now_stamp()


def apply_changes(record, changes):
    """Write `changes`; a value that actually moved is a mutation (PRD 2.4)."""
    changed = False
    for key, value in changes.items():
        if record.get(key) != value:
            record[key] = value
            changed = True
    if changed:
        bump(record)
    return changed


# ------------------------------------------------------------- lookup helpers
def turns_of_bank(bank_id):
    return [t for t in db.turns.values() if t["flight_bank_id"] == bank_id]


def turns_of_station(station_id):
    return [t for t in db.turns.values() if t["station_id"] == station_id]


def banks_of_station(station_id):
    return [b for b in db.flight_banks.values() if b["station_id"] == station_id]


def gse_of_station(station_id):
    return [u for u in db.gse_units.values() if u["station_id"] == station_id]


def resources_of_turn(turn_id):
    return [r for r in db.turn_resources.values() if r["turn_id"] == turn_id]


def resources_of_agent(agent_id):
    return [r for r in db.turn_resources.values() if r["agent_id"] == agent_id]


def resources_of_gse(gse_unit_id):
    return [r for r in db.turn_resources.values() if r["gse_unit_id"] == gse_unit_id]


def incidents_of_station(station_id):
    return [i for i in db.incidents.values() if i["station_id"] == station_id]


def certifications_of_agent(agent_id):
    return [c for c in db.certifications.values() if c["agent_id"] == agent_id]


def lines_of_period(period_id):
    return [l for l in db.billing_lines.values() if l["billing_period_id"] == period_id]


LIVE_RESOURCE_STATUSES = ("RESERVED", "COMMITTED")
LIVE_TURN_STATUSES = ("SCHEDULED", "RESOURCED", "IN_PROGRESS")


# ------------------------------------------------- certification currency
def cert_effective_at(cert, instant):
    """PRD 3.5: VALID, issued_at <= instant, expires_at strictly after it."""
    if cert["status"] != "VALID":
        return False
    if as_dt(cert["issued_at"]) > instant:
        return False
    return as_dt(cert["expires_at"]) > instant


def currency_state(cert):
    clock = db.clock
    if cert["status"] == "REVOKED":
        return "REVOKED"
    if not cert_effective_at(cert, clock):
        return "LAPSED"
    remaining_days = (as_dt(cert["expires_at"]) - clock).total_seconds() / 86400.0
    if remaining_days <= C.EXPIRING_WINDOW_DAYS:
        return "EXPIRING"
    return "CURRENT"


def ramp_safety_certs(agent):
    return [
        c for c in certifications_of_agent(agent["id"])
        if c["cert_type"] == "RAMP_SAFETY" and c["station_id"] == agent["station_id"]
    ]


def certification_posture(agent):
    clock = db.clock
    effective = [c for c in ramp_safety_certs(agent) if cert_effective_at(c, clock)]
    if not effective:
        return "LAPSED"
    for cert in effective:
        remaining_days = (as_dt(cert["expires_at"]) - clock).total_seconds() / 86400.0
        if remaining_days > C.EXPIRING_WINDOW_DAYS:
            return "CURRENT"
    return "EXPIRING"


def agent_holds_required_certs(agent, station_id, ramp_role, instant):
    held = certifications_of_agent(agent["id"])
    for cert_type in C.REQUIRED_CERTS_BY_ROLE[ramp_role]:
        ok = any(
            c["cert_type"] == cert_type
            and c["station_id"] == station_id
            and cert_effective_at(c, instant)
            for c in held
        )
        if not ok:
            return False
    return True


# ------------------------------------------------- subcontractor compliance
def subcontractor_incidents(sub_id):
    return [i for i in db.incidents.values() if i["subcontractor_id"] == sub_id]


def compliance_scores(sub):
    linked = subcontractor_incidents(sub["id"])
    clock = db.clock

    rolling_penalty = Decimal("0")
    closed_liable = 0
    for inc in linked:
        if inc["status"] != "CLOSED" or inc["liability_party"] != "SUBCONTRACTOR":
            continue
        closed_liable += 1
        age_days = whole_days_between(as_dt(inc["occurred_at"]), clock)
        if age_days <= C.DECAY_FULL_MAX_AGE_DAYS:
            decay = Decimal("1")
        elif age_days <= C.DECAY_HALF_MAX_AGE_DAYS:
            decay = Decimal("0.5")
        else:
            decay = Decimal("0")
        rolling_penalty += C.SEVERITY_WEIGHT[inc["severity"]] * decay

    audit_penalty = sum(
        (C.SEVERITY_WEIGHT[i["severity"]] for i in linked), Decimal("0")
    )

    rolling = pct2(Decimal("100") - rolling_penalty)
    if rolling < 0:
        rolling = Decimal("0.00")
    audit = pct2(Decimal("100") - audit_penalty)
    if audit < 0:
        audit = Decimal("0.00")
    return {
        "total_incident_count": len(linked),
        "closed_liable_incident_count": closed_liable,
        "compliance_score": rolling,
        "audit_compliance_score": audit,
        "oversight_flag": rolling < C.OVERSIGHT_FLAG_THRESHOLD,
    }


def audit_score(sub):
    return compliance_scores(sub)["audit_compliance_score"]


# ------------------------------------------------------------ station roll-ups
def recompute_station_posture(station):
    incidents = incidents_of_station(station["id"])
    open_critical = sum(
        1 for i in incidents if i["severity"] == "CRITICAL" and i["status"] != "CLOSED"
    )
    open_major = sum(
        1 for i in incidents if i["severity"] == "MAJOR" and i["status"] != "CLOSED"
    )
    if open_critical >= 1:
        posture = "RESTRICTED"
    elif open_major >= 1 or (
        station["completed_turn_count"] >= C.ENHANCED_MIN_COMPLETED_TURNS
        and station["otp_rolling_pct"] < station["otp_target_pct"]
    ):
        posture = "ENHANCED"
    else:
        posture = "NORMAL"
    apply_changes(station, {
        "open_critical_incident_count": open_critical,
        "open_major_incident_count": open_major,
        "oversight_posture": posture,
    })


def recompute_station_otp(station):
    turns = turns_of_station(station["id"])
    completed = sum(
        1 for t in turns
        if t["status"] == "COMPLETED" and t["otp_result"] in ("ON_TIME", "DELAYED")
    )
    on_time = sum(
        1 for t in turns if t["status"] == "COMPLETED" and t["otp_result"] == "ON_TIME"
    )
    if completed == 0:
        rolling = Decimal("100.00")
    else:
        rolling = pct2(Decimal(100) * Decimal(on_time) / Decimal(completed))
    apply_changes(station, {
        "completed_turn_count": completed,
        "on_time_turn_count": on_time,
        "otp_rolling_pct": rolling,
    })
    recompute_station_posture(station)


# --------------------------------------------------------------- bank roll-ups
def recompute_bank_rollup(bank):
    turns = turns_of_bank(bank["id"])
    required = sum(
        C.REQUIRED_AGENTS[t["turn_type"]] for t in turns
        if t["status"] in ("SCHEDULED", "RESOURCED", "IN_PROGRESS", "COMPLETED")
    )
    turn_count = sum(1 for t in turns if t["status"] != "CANCELLED")
    if required == 0:
        coverage = C.EMPTY_BANK_COVERAGE_PCT
    else:
        coverage = pct2(
            Decimal(100) * Decimal(bank["planned_headcount"]) / Decimal(required)
        )
    apply_changes(bank, {
        "required_headcount": required,
        "turn_count": turn_count,
        "staffing_coverage_pct": coverage,
    })
    return coverage


def bank_staffing_fallback(bank):
    """The system edge APPROVED -> REVISION_REQUIRED (PRD 3.3)."""
    if bank["staffing_status"] != "APPROVED":
        return False
    apply_changes(bank, {"staffing_status": "REVISION_REQUIRED"})
    recompute_bank_rollup(bank)
    return True


# ------------------------------------------------------------------- ledgers
def recompute_agent_ledger(agent):
    total = sum(
        r["occupied_minutes"] for r in resources_of_agent(agent["id"])
        if r["status"] in LIVE_RESOURCE_STATUSES
    )
    apply_changes(agent, {"assigned_duty_minutes": total})


def recompute_gse_ledger(unit):
    total = sum(
        r["occupied_minutes"] for r in resources_of_gse(unit["id"])
        if r["status"] in LIVE_RESOURCE_STATUSES
    )
    apply_changes(unit, {"committed_occupation_minutes": total})


def recompute_resource_ledger(resource):
    if resource["resource_kind"] == "AGENT":
        agent = db.agents.get(resource["agent_id"])
        if agent:
            recompute_agent_ledger(agent)
    else:
        unit = db.gse_units.get(resource["gse_unit_id"])
        if unit:
            recompute_gse_ledger(unit)


# ------------------------------------------------------------ turn coverage
def recompute_turn_coverage(turn):
    rows = resources_of_turn(turn["id"])
    agent_count = sum(
        1 for r in rows
        if r["resource_kind"] == "AGENT" and r["status"] in LIVE_RESOURCE_STATUSES
    )
    gse_count = sum(
        1 for r in rows
        if r["resource_kind"] == "GSE" and r["status"] in LIVE_RESOURCE_STATUSES
    )
    apply_changes(turn, {
        "assigned_agent_count": agent_count,
        "assigned_gse_count": gse_count,
    })
    covered = (
        agent_count >= turn["required_agent_count"]
        and gse_count >= turn["required_gse_count"]
    )
    if turn["status"] == "SCHEDULED" and covered:
        apply_changes(turn, {"status": "RESOURCED"})
    elif turn["status"] == "RESOURCED" and not covered:
        apply_changes(turn, {"status": "SCHEDULED"})
        bank = db.flight_banks.get(turn["flight_bank_id"])
        if bank:
            bank_staffing_fallback(bank)


# --------------------------------------------------------------- cascades
def cancel_resource(resource, reason):
    if resource["status"] not in LIVE_RESOURCE_STATUSES:
        return False
    apply_changes(resource, {"status": "CANCELLED", "cancel_reason": reason})
    recompute_resource_ledger(resource)
    turn = db.turns.get(resource["turn_id"])
    if turn:
        recompute_turn_coverage(turn)
    return True


def cancel_resources_of_turn(turn, reason):
    for resource in ordered(resources_of_turn(turn["id"])):
        cancel_resource(resource, reason)


def cancel_resources_of_agent(agent, reason):
    for resource in ordered(resources_of_agent(agent["id"])):
        cancel_resource(resource, reason)


def cancel_resources_of_gse(unit, reason):
    for resource in ordered(resources_of_gse(unit["id"])):
        cancel_resource(resource, reason)


def suspend_agent(agent):
    """ACTIVE -> SUSPENDED driven by certification currency (PRD 3.5)."""
    if agent["status"] != "ACTIVE":
        return
    apply_changes(agent, {"status": "SUSPENDED"})
    cancel_resources_of_agent(agent, C.CANCEL_AGENT_SUSPENDED)
    recompute_agent_ledger(agent)


def quarantine_gse(unit):
    """AVAILABLE|IN_MAINTENANCE -> QUARANTINED with its occupation cascade."""
    if unit["status"] not in ("AVAILABLE", "IN_MAINTENANCE"):
        return False
    apply_changes(unit, {"status": "QUARANTINED"})
    cancel_resources_of_gse(unit, C.CANCEL_GSE_QUARANTINED)
    recompute_gse_ledger(unit)
    return True


def set_service_hold(unit, start, end):
    apply_changes(unit, {
        "service_hold_start": format_iso(start),
        "service_hold_end": format_iso(end),
    })


def station_suspend_cascade(station):
    """Four hops, each firing only because the previous one did (PRD 3.1)."""
    hop1 = []
    for bank in ordered(banks_of_station(station["id"])):
        if bank["bank_status"] == "PUBLISHED":
            apply_changes(bank, {"bank_status": "LOCKED"})
            hop1.append(bank)
    hop2 = []
    for bank in hop1:
        if bank["staffing_status"] == "APPROVED":
            apply_changes(bank, {"staffing_status": "REVISION_REQUIRED"})
            hop2.append(bank)
    hop3 = []
    for bank in hop2:
        for turn in ordered(turns_of_bank(bank["id"])):
            if turn["status"] in ("SCHEDULED", "RESOURCED"):
                apply_changes(turn, {"status": "DISRUPTED"})
                hop3.append(turn)
    for turn in hop3:
        cancel_resources_of_turn(turn, C.CANCEL_STATION_SUSPENDED)
    for bank in hop2:
        recompute_bank_rollup(bank)


def station_close_cascade(station):
    for bank in ordered(banks_of_station(station["id"])):
        if bank["bank_status"] != "ARCHIVED":
            apply_changes(bank, {"bank_status": "ARCHIVED"})
    for unit in ordered(gse_of_station(station["id"])):
        if unit["status"] != "RETIRED":
            apply_changes(unit, {"status": "RETIRED"})


def season_rollover_cascade(station, outgoing_season):
    hop1 = []
    for bank in ordered(banks_of_station(station["id"])):
        if bank["season_code"] == outgoing_season and bank["bank_status"] in (
            "DRAFT", "PUBLISHED", "LOCKED"
        ):
            apply_changes(bank, {"bank_status": "ARCHIVED"})
            hop1.append(bank)
    hop2 = []
    for bank in hop1:
        for turn in ordered(turns_of_bank(bank["id"])):
            if turn["status"] in ("SCHEDULED", "RESOURCED"):
                apply_changes(turn, {"status": "CANCELLED"})
                hop2.append(turn)
    for turn in hop2:
        cancel_resources_of_turn(turn, C.CANCEL_SEASON_ROLLOVER)
    for bank in hop1:
        recompute_bank_rollup(bank)


def subcontractor_terminate_cascade(sub):
    for agent in ordered([a for a in db.agents.values() if a["subcontractor_id"] == sub["id"]]):
        if agent["status"] == "TERMINATED":
            continue
        apply_changes(agent, {"status": "TERMINATED"})
        cancel_resources_of_agent(agent, C.CANCEL_SUBCONTRACTOR_TERMINATED)
        recompute_agent_ledger(agent)


# ------------------------------------------------- gse interval arithmetic
def gse_occupation_conflict(unit, new_start, new_end, buffer_minutes, skip_id=None):
    """Buffered half-open test (PRD 3.6)."""
    for row in resources_of_gse(unit["id"]):
        if row["status"] not in LIVE_RESOURCE_STATUSES:
            continue
        if skip_id and row["id"] == skip_id:
            continue
        row_start = as_dt(row["window_start"])
        row_end = as_dt(row["window_end"])
        if new_start < plus_minutes(row_end, buffer_minutes) and \
           row_start < plus_minutes(new_end, buffer_minutes):
            return True
    return False


def gse_service_hold_conflict(unit, new_start, new_end):
    """Closed interval, no buffer (PRD 3.6)."""
    if not unit.get("service_hold_start"):
        return False
    hold_start = as_dt(unit["service_hold_start"])
    hold_end = as_dt(unit["service_hold_end"]) if unit.get("service_hold_end") else hold_start
    return new_start <= hold_end and hold_start <= new_end


def agent_duty_conflict(agent, new_start, new_end, skip_id=None):
    """Bare closed interval, no buffer (PRD 3.7)."""
    for row in resources_of_agent(agent["id"]):
        if row["status"] not in LIVE_RESOURCE_STATUSES:
            continue
        if skip_id and row["id"] == skip_id:
            continue
        row_start = as_dt(row["window_start"])
        row_end = as_dt(row["window_end"])
        if new_start <= row_end and row_start <= new_end:
            return True
    return False


def agent_projected_daily_minutes(agent, new_start, new_minutes):
    duty_date = new_start.date()
    total = 0
    for row in resources_of_agent(agent["id"]):
        if row["status"] not in LIVE_RESOURCE_STATUSES:
            continue
        if as_dt(row["window_start"]).date() == duty_date:
            total += row["occupied_minutes"]
    return total + new_minutes


def select_gse_unit(station, turn, gse_type, new_start, new_end):
    """gse_unit_selector (PRD 3.6).  Returns None on an empty candidate pool."""
    buffer_minutes = station["gse_reposition_buffer_minutes"]
    candidates = []
    for unit in gse_of_station(turn["station_id"]):
        if unit["gse_type"] != gse_type:
            continue
        if unit["status"] != "AVAILABLE":
            continue
        if gse_occupation_conflict(unit, new_start, new_end, buffer_minutes):
            continue
        if gse_service_hold_conflict(unit, new_start, new_end):
            continue
        candidates.append(unit)
    if not candidates:
        return None
    candidates.sort(key=lambda u: (
        -(u["service_interval_cycles"] - u["cycles_since_service"]),
        -u["condition_score"],
        u["created_at"],
        u["_seq"],
    ))
    return candidates[0]


# ---------------------------------------------------------------- serialisers
def serialize_station(station):
    return serialize(station)


def serialize_subcontractor(sub):
    return serialize(sub, compliance_scores(sub))


def serialize_flight_bank(bank):
    return serialize(bank)


def serialize_turn(turn):
    return serialize(turn)


def serialize_agent(agent):
    return serialize(agent, {"certification_posture": certification_posture(agent)})


def serialize_certification(cert):
    return serialize(cert, {"currency_state": currency_state(cert)})


def serialize_gse_unit(unit):
    return serialize(unit)


def serialize_turn_resource(resource):
    return serialize(resource)


def serialize_incident(incident):
    return serialize(incident)


def serialize_billing_period(period):
    return serialize(period)


def serialize_billing_line(line):
    return serialize(line)
