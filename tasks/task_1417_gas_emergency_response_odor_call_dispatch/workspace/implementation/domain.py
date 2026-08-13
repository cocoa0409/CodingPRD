"""Domain logic: computed fields, calculations (scaffold §1.3), side-effect helpers,
and entity serializers. Stored records are plain dicts holding datetimes internally;
serializers convert to the wire format."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from clock import iso

# ---------------------------------------------------------------------------
# Constants from the calculation rules table
# ---------------------------------------------------------------------------
PRIORITY_RANK = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}  # P1 is highest
PRIORITIES = ("P1", "P2", "P3", "P4")

PROVISIONAL_MATRIX = {
    "OUTSIDE_COMPANY": {"P1": 150000, "P2": 90000, "P3": 45000, "P4": 20000},
    "INSIDE_CUSTOMER": {"P1": 0, "P2": 0, "P3": 0, "P4": 0},
    "SHARED": {"P1": 75000, "P2": 45000, "P3": 22500, "P4": 10000},
    "UNDETERMINED": {"P1": 60000, "P2": 60000, "P3": 60000, "P4": 60000},
}

ACTIVE_ASSIGNMENT_STATUSES = ("EN_ROUTE", "ON_SCENE")
RESERVED_WO_STATUSES = ("SCHEDULED", "IN_PROGRESS", "ON_HOLD")
TRAVEL_BUFFER = timedelta(minutes=30)

LOCATION_CONTEXTS = {"INSIDE_STRUCTURE", "OUTSIDE_STRUCTURE", "METER_AREA", "PUBLIC_SPACE", "UNKNOWN"}
OCCUPANCY_TYPES = {"SINGLE_FAMILY", "MULTI_FAMILY", "PUBLIC_ASSEMBLY", "SCHOOL", "HOSPITAL"}
PAUSE_REASONS = {"CUSTOMER_NOT_HOME", "ACCESS_BLOCKED"}
READING_CONTEXTS = {"INSIDE", "OUTSIDE", "CONFINED_SPACE"}
ACTION_TYPES = {"VENTILATE", "SHUT_APPLIANCE_VALVE", "EVACUATE", "SECURE_AREA", "OTHER"}
ENTRY_METHODS = {"CUSTOMER_CONSENT", "EMERGENCY_FORCED", "WARRANT"}
ENTRY_STATUSES = {"NOT_REQUIRED", "AWAITING_AUTHORIZATION", "AUTHORIZED", "FORCED", "REFUSED"}
SHUTOFF_SCOPES = {"METER", "APPLIANCE", "SERVICE_LINE"}
RESPONSIBILITIES = {"INSIDE_CUSTOMER", "OUTSIDE_COMPANY", "SHARED"}
DETERMINATION_BASES = {"METER_LOCATION", "BARHOLE_SURVEY", "CUSTOMER_APPLIANCE_TRACE", "EXCAVATION"}
NOTIFICATION_CHANNELS = {"MEDIA", "PUBLIC_ALERT", "AGENCY_NOTICE"}


# ---------------------------------------------------------------------------
# Generic record helpers
# ---------------------------------------------------------------------------
def new_record(common_fields=True):
    now = clock.now()
    rec = {"id": db.new_id(), "_seq": db.next_seq(), "created_at": now}
    if common_fields:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def bump(rec):
    """Increment version and refresh updated_at on a versioned record."""
    rec["version"] += 1
    rec["updated_at"] = clock.now()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def calls_of(incident_id):
    return [c for c in db.calls.values() if c["incident_id"] == incident_id]


def readings_of(incident_id):
    return [r for r in db.readings.values() if r["incident_id"] == incident_id]


def actions_of(incident_id):
    return [a for a in db.actions.values() if a["incident_id"] == incident_id]


def assignments_of_incident(incident_id):
    return [a for a in db.assignments.values() if a["incident_id"] == incident_id]


def assignments_of_technician(technician_id):
    return [a for a in db.assignments.values() if a["technician_id"] == technician_id]


def pauses_of(incident_id):
    return [p for p in db.pauses.values() if p["incident_id"] == incident_id]


def shutoffs_of(incident_id):
    return [s for s in db.shutoffs.values() if s["incident_id"] == incident_id]


def determinations_of(incident_id):
    return [d for d in db.determinations.values() if d["incident_id"] == incident_id]


def work_orders_of_incident(incident_id):
    return [w for w in db.work_orders.values() if w["incident_id"] == incident_id]


def active_assignment_on(incident_id, technician_id):
    """The technician's active (EN_ROUTE/ON_SCENE) assignment on the incident, if any."""
    for a in db.assignments.values():
        if (a["incident_id"] == incident_id and a["technician_id"] == technician_id
                and a["status"] in ACTIVE_ASSIGNMENT_STATUSES):
            return a
    return None


def ever_assigned(incident_id, technician_id):
    return any(a["incident_id"] == incident_id and a["technician_id"] == technician_id
               for a in db.assignments.values())


# ---------------------------------------------------------------------------
# Technician computed fields
# ---------------------------------------------------------------------------
def tech_on_shift(tech):
    now = clock.now()
    return any(s["technician_id"] == tech["id"] and s["shift_start"] <= now < s["shift_end"]
               for s in db.shifts.values())


def tech_active_assignments(tech_id):
    return [a for a in db.assignments.values()
            if a["technician_id"] == tech_id and a["status"] in ACTIVE_ASSIGNMENT_STATUSES]


def tech_active_count(tech_id):
    return len(tech_active_assignments(tech_id))


def tech_weighted_load(tech_id):
    total = 0
    for a in tech_active_assignments(tech_id):
        inc = db.incidents.get(a["incident_id"])
        if inc is not None:
            total += PRIORITY_RANK[inc["priority"]]
    return total


def tech_last_cleared_at(tech_id):
    cleared = [a["cleared_at"] for a in db.assignments.values()
               if a["technician_id"] == tech_id and a["status"] == "CLEARED" and a["cleared_at"]]
    return max(cleared) if cleared else None


# ---------------------------------------------------------------------------
# Incident computed fields: response clock, threshold, breach (PRD §2.7)
# ---------------------------------------------------------------------------
def segment_pauses(incident):
    """Pauses belonging to the current response segment (started at or after segment start)."""
    start = incident["response_clock_started_at"]
    return [p for p in db.pauses.values()
            if p["incident_id"] == incident["id"] and p["started_at"] >= start]


def elapsed(incident, now=None):
    """Returns (raw_elapsed_seconds, pause_total_seconds, adjusted_elapsed_seconds)."""
    if now is None:
        now = clock.now()
    end = incident["first_arrival_at"] or now
    raw = int((end - incident["response_clock_started_at"]).total_seconds())
    pause_total = 0
    for p in segment_pauses(incident):
        p_end = p["ended_at"] or now
        pause_total += int((p_end - p["started_at"]).total_seconds())
    adjusted = max(0, raw - pause_total)
    return raw, pause_total, adjusted


def threshold_minutes(incident):
    territory = db.territories.get(incident["territory_id"])
    key = "%s_threshold_minutes" % incident["priority"].lower()
    return territory[key]


def breach_class(incident, now=None):
    _, _, adjusted = elapsed(incident, now)
    threshold_seconds = threshold_minutes(incident) * 60
    if adjusted > threshold_seconds:  # strictly greater; equality is compliant
        return "RESPONDED_LATE" if incident["first_arrival_at"] else "NO_RESPONSE"
    return "NONE"


def awaiting_dispatch(incident):
    if incident["lifecycle_status"] != "DISPATCHED":
        return False
    return not any(a["status"] in ACTIVE_ASSIGNMENT_STATUSES
                   for a in assignments_of_incident(incident["id"]))


def evacuation_required(incident):
    return any(r["pct_lel"] >= 10.0 for r in readings_of(incident["id"]))


def gas_flow_stopped(incident):
    return any(s["status"] in ("EXECUTED", "RESTORED") for s in shutoffs_of(incident["id"]))


def final_determination(incident_id):
    for d in determinations_of(incident_id):
        if d["status"] == "FINAL":
            return d
    return None


def incident_responsibility(incident):
    d = final_determination(incident["id"])
    return d["responsibility"] if d else None


# ---------------------------------------------------------------------------
# Severity score (incident_severity_score calculation)
# ---------------------------------------------------------------------------
def severity_score(incident):
    readings = readings_of(incident["id"])
    max_lel = max((r["pct_lel"] for r in readings), default=0)
    max_co = max((r["co_ppm"] for r in readings), default=0)
    if max_lel >= 10.0:
        lel_factor = Decimal("1.0")
    elif max_lel >= 5.0:
        lel_factor = Decimal("0.5")
    elif max_lel > 0:
        lel_factor = Decimal("0.2")
    else:
        lel_factor = Decimal("0.0")
    if max_co >= 70:
        co_factor = Decimal("1.0")
    elif max_co >= 35:
        co_factor = Decimal("0.5")
    else:
        co_factor = Decimal("0.0")
    if incident["occupancy_type"] in ("PUBLIC_ASSEMBLY", "SCHOOL", "HOSPITAL"):
        occupancy_factor = Decimal("1.0")
    elif incident["occupancy_type"] == "MULTI_FAMILY":
        occupancy_factor = Decimal("0.6")
    else:
        occupancy_factor = Decimal("0.3")
    symptom = any(c["symptoms_reported"] for c in calls_of(incident["id"]))
    symptom_factor = Decimal("1.0") if symptom else Decimal("0.0")
    total = (Decimal(40) * lel_factor + Decimal(25) * co_factor
             + Decimal(20) * occupancy_factor + Decimal(15) * symptom_factor)
    score = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(100, max(0, score))


# ---------------------------------------------------------------------------
# Automatic notification rules (PRD §3.8) and report staleness (PRD §3.8)
# ---------------------------------------------------------------------------
def create_notification(incident, channel, origin, headline, body):
    rec = new_record(common_fields=True)
    rec.update({
        "incident_id": incident["id"],
        "channel": channel,
        "headline": headline,
        "body": body,
        "origin": origin,
        "status": "DRAFT",
        "issued_at": None,
        "retracted_at": None,
    })
    db.notifications[rec["id"]] = rec
    return rec


def auto_priority_notify(incident):
    """Fires when the incident's priority reaches P1 while the flag is false."""
    if incident["priority"] == "P1" and not incident["auto_notification_created"]:
        create_notification(incident, "PUBLIC_ALERT", "AUTO_PRIORITY",
                            "Priority 1 gas emergency", "Incident reached priority P1.")
        incident["auto_notification_created"] = True


def auto_severity_notify(incident, channel):
    if not incident["auto_notification_created"]:
        create_notification(incident, channel, "AUTO_SEVERITY",
                            "Severe gas incident", "Incident severity reached the notification threshold.")
        incident["auto_notification_created"] = True


def mark_reports_stale(incident, extra_times=()):
    """Flag covering DRAFT/REJECTED reports as needing regeneration (PRD §3.8)."""
    times = [incident["response_clock_started_at"]] + list(extra_times)
    for rep in db.reports.values():
        if rep["status"] not in ("DRAFT", "REJECTED"):
            continue
        if rep["territory_id"] != incident["territory_id"]:
            continue
        if any(rep["period_start"] <= t < rep["period_end"] for t in times if t is not None):
            if not rep["needs_regeneration"]:
                rep["needs_regeneration"] = True
                bump(rep)


# ---------------------------------------------------------------------------
# Work order helpers
# ---------------------------------------------------------------------------
def provisional_estimate(responsibility, priority):
    row = responsibility if responsibility in PROVISIONAL_MATRIX else "UNDETERMINED"
    return PROVISIONAL_MATRIX[row][priority]


def territory_reserved_cents(territory_id):
    """Sum of current_estimate_cents over the territory's work orders in SCHEDULED/IN_PROGRESS/ON_HOLD."""
    total = 0
    for w in db.work_orders.values():
        if w["status"] not in RESERVED_WO_STATUSES:
            continue
        inc = db.incidents.get(w["incident_id"])
        if inc is not None and inc["territory_id"] == territory_id:
            total += w["current_estimate_cents"]
    return total


def compute_final_cost(lines, labor_minutes, crew_hourly_rate_cents):
    """repair_cost_final: per-line rounding first, then labor, then sum. Never sum-then-round."""
    parts_total = 0
    for line in lines:
        qty = Decimal(str(line["quantity"]))
        price = Decimal(str(line["unit_price_cents"]))
        disc = Decimal(str(line["discount_pct"]))
        line_total = (qty * price * (Decimal(1) - disc)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        parts_total += int(line_total)
    labor_billed_minutes = int(math.ceil(labor_minutes / 15.0)) * 15 if labor_minutes > 0 else 0
    labor_cost = int((Decimal(labor_billed_minutes) / Decimal(60)
                      * Decimal(crew_hourly_rate_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return parts_total, labor_billed_minutes, labor_cost, parts_total + labor_cost


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_territory(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "p1_threshold_minutes": t["p1_threshold_minutes"],
        "p2_threshold_minutes": t["p2_threshold_minutes"],
        "p3_threshold_minutes": t["p3_threshold_minutes"],
        "p4_threshold_minutes": t["p4_threshold_minutes"],
        "recurrence_window_hours": t["recurrence_window_hours"],
        "repair_budget_cap_cents": t["repair_budget_cap_cents"],
        "repair_reserved_cents": territory_reserved_cents(t["id"]),
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def ser_technician(t):
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "badge_number": t["badge_number"],
        "home_territory_id": t["home_territory_id"],
        "hourly_rate_cents": t["hourly_rate_cents"],
        "is_active": t["is_active"],
        "on_shift": tech_on_shift(t),
        "active_assignment_count": tech_active_count(t["id"]),
        "weighted_load": tech_weighted_load(t["id"]),
        "last_cleared_at": iso(tech_last_cleared_at(t["id"])),
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def ser_shift(s):
    return {
        "id": s["id"],
        "technician_id": s["technician_id"],
        "shift_start": iso(s["shift_start"]),
        "shift_end": iso(s["shift_end"]),
        "created_at": iso(s["created_at"]),
    }


def ser_crew(c):
    return {
        "id": c["id"],
        "crew_code": c["crew_code"],
        "territory_id": c["territory_id"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "is_active": c["is_active"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_call(c):
    return {
        "id": c["id"],
        "caller_name": c["caller_name"],
        "caller_phone": c["caller_phone"],
        "address_line": c["address_line"],
        "city": c["city"],
        "territory_id": c["territory_id"],
        "location_context": c["location_context"],
        "occupancy_type": c["occupancy_type"],
        "odor_reported": c["odor_reported"],
        "symptoms_reported": c["symptoms_reported"],
        "hissing_reported": c["hissing_reported"],
        "implied_priority": c["implied_priority"],
        "classification": c["classification"],
        "is_duplicate": c["is_duplicate"],
        "incident_id": c["incident_id"],
        "received_at": iso(c["received_at"]),
        "created_at": iso(c["created_at"]),
    }


def ser_incident(i):
    now = clock.now()
    raw, pause_total, adjusted = elapsed(i, now)
    responsibility = incident_responsibility(i)
    return {
        "id": i["id"],
        "territory_id": i["territory_id"],
        "normalized_address": i["normalized_address"],
        "occupancy_type": i["occupancy_type"],
        "lifecycle_status": i["lifecycle_status"],
        "entry_status": i["entry_status"],
        "priority": i["priority"],
        "severity_score": i["severity_score"],
        "linked_call_count": len(calls_of(i["id"])),
        "reopen_count": i["reopen_count"],
        "response_clock_started_at": iso(i["response_clock_started_at"]),
        "first_arrival_at": iso(i["first_arrival_at"]),
        "prior_segment_adjusted_seconds": i["prior_segment_adjusted_seconds"],
        "pause_total_seconds": pause_total,
        "raw_elapsed_seconds": raw,
        "adjusted_elapsed_seconds": adjusted,
        "threshold_minutes": threshold_minutes(i),
        "breach_class": breach_class(i, now),
        "awaiting_dispatch": awaiting_dispatch(i),
        "evacuation_required": evacuation_required(i),
        "make_safe_completed": i["make_safe_completed"],
        "leak_confirmed": i["leak_confirmed"],
        "gas_flow_stopped": gas_flow_stopped(i),
        "responsibility": responsibility,
        "customer_referral_required": responsibility == "INSIDE_CUSTOMER",
        "auto_notification_created": i["auto_notification_created"],
        "closed_at": iso(i["closed_at"]),
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "incident_id": a["incident_id"],
        "technician_id": a["technician_id"],
        "status": a["status"],
        "sla_threshold_minutes": a["sla_threshold_minutes"],
        "dispatched_at": iso(a["dispatched_at"]),
        "arrived_at": iso(a["arrived_at"]),
        "cleared_at": iso(a["cleared_at"]),
        "preempt_reason": a["preempt_reason"],
        "notes": a["notes"],
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_pause(p):
    now = clock.now()
    end = p["ended_at"] or now
    return {
        "id": p["id"],
        "incident_id": p["incident_id"],
        "reason": p["reason"],
        "started_at": iso(p["started_at"]),
        "ended_at": iso(p["ended_at"]),
        "status": "CLOSED" if p["ended_at"] else "OPEN",
        "duration_seconds": int((end - p["started_at"]).total_seconds()),
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_reading(r):
    return {
        "id": r["id"],
        "incident_id": r["incident_id"],
        "technician_id": r["technician_id"],
        "pct_lel": r["pct_lel"],
        "co_ppm": r["co_ppm"],
        "reading_context": r["reading_context"],
        "taken_at": iso(r["taken_at"]),
        "created_at": iso(r["created_at"]),
    }


def ser_action(a):
    return {
        "id": a["id"],
        "incident_id": a["incident_id"],
        "technician_id": a["technician_id"],
        "action_type": a["action_type"],
        "notes": a["notes"],
        "performed_at": iso(a["performed_at"]),
        "created_at": iso(a["created_at"]),
    }


def ser_authorization(a):
    return {
        "id": a["id"],
        "incident_id": a["incident_id"],
        "method": a["method"],
        "authorized_by_name": a["authorized_by_name"],
        "recorded_by_user_id": a["recorded_by_user_id"],
        "created_at": iso(a["created_at"]),
    }


def ser_shutoff(s):
    return {
        "id": s["id"],
        "incident_id": s["incident_id"],
        "scope": s["scope"],
        "entry_required": s["entry_required"],
        "reason": s["reason"],
        "status": s["status"],
        "requested_by_user_id": s["requested_by_user_id"],
        "authorized_by_user_id": s["authorized_by_user_id"],
        "executed_by_technician_id": s["executed_by_technician_id"],
        "executed_at": iso(s["executed_at"]),
        "restored_at": iso(s["restored_at"]),
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_determination(d):
    return {
        "id": d["id"],
        "incident_id": d["incident_id"],
        "responsibility": d["responsibility"],
        "basis": d["basis"],
        "notes": d["notes"],
        "status": d["status"],
        "drafted_by_user_id": d["drafted_by_user_id"],
        "finalized_by_user_id": d["finalized_by_user_id"],
        "finalized_at": iso(d["finalized_at"]),
        "created_at": iso(d["created_at"]),
        "updated_at": iso(d["updated_at"]),
        "version": d["version"],
    }


def ser_work_order(w):
    return {
        "id": w["id"],
        "incident_id": w["incident_id"],
        "origin": w["origin"],
        "status": w["status"],
        "crew_id": w["crew_id"],
        "provisional_estimate_cents": w["provisional_estimate_cents"],
        "current_estimate_cents": w["current_estimate_cents"],
        "scheduled_window_start": iso(w["scheduled_window_start"]),
        "scheduled_window_end": iso(w["scheduled_window_end"]),
        "lines": w["lines"],
        "labor_minutes": w["labor_minutes"],
        "labor_billed_minutes": w["labor_billed_minutes"],
        "final_cost_cents": w["final_cost_cents"],
        "completed_at": iso(w["completed_at"]),
        "cancel_reason": w["cancel_reason"],
        "created_at": iso(w["created_at"]),
        "updated_at": iso(w["updated_at"]),
        "version": w["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "territory_id": r["territory_id"],
        "period_start": iso(r["period_start"]),
        "period_end": iso(r["period_end"]),
        "status": r["status"],
        "generated_at": iso(r["generated_at"]),
        "submitted_at": iso(r["submitted_at"]),
        "incident_count": r["incident_count"],
        "determined_count": r["determined_count"],
        "pending_count": r["pending_count"],
        "compliant_count_raw": r["compliant_count_raw"],
        "compliant_count_adjusted": r["compliant_count_adjusted"],
        "compliance_rate_raw": r["compliance_rate_raw"],
        "compliance_rate_adjusted": r["compliance_rate_adjusted"],
        "needs_regeneration": r["needs_regeneration"],
        "regeneration_count": r["regeneration_count"],
        "reject_reason": r["reject_reason"],
        "stats": r["stats"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_notification(n):
    return {
        "id": n["id"],
        "incident_id": n["incident_id"],
        "channel": n["channel"],
        "headline": n["headline"],
        "body": n["body"],
        "origin": n["origin"],
        "status": n["status"],
        "issued_at": iso(n["issued_at"]),
        "retracted_at": iso(n["retracted_at"]),
        "created_at": iso(n["created_at"]),
        "updated_at": iso(n["updated_at"]),
        "version": n["version"],
    }
