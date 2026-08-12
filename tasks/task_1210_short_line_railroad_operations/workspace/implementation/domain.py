"""Domain constants, calculations (PRD section 2.7 / scaffold calculations),
record factory, serializers, cascading side effects, and logical-clock sweeps.
"""

import math
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from util import iso

# ---------------------------------------------------------------------------
# Constants (scaffold calculations[].constants)
# ---------------------------------------------------------------------------

CLASS_SPEED_MPH = {
    "EXCEPTED": 10, "CLASS_1": 10, "CLASS_2": 25,
    "CLASS_3": 40, "CLASS_4": 60, "CLASS_5": 80,
}
DEFECT_CAP_MPH = {"MONITOR": 25, "CRITICAL": 10}
INSPECTION_FREQ_DAYS = {
    "EXCEPTED": 30, "CLASS_1": 7, "CLASS_2": 7,
    "CLASS_3": 3, "CLASS_4": 2, "CLASS_5": 1,
}
HOS_DAILY_LIMIT_MINUTES = 720
HOS_MONTHLY_LIMIT_MINUTES = 16560
HOS_REQUIRED_REST_MINUTES = 600
MIN_HIRE_CENTS = 3600
DEMURRAGE_PER_CAR_PER_DAY_CENTS = 7500
COMMODITY_RATE_CENTS_PER_TON = {"GRAIN": 38500, "LUMBER": 42000, "CHEMICALS": 51500}
# The spec names FRA_DAMAGE_THRESHOLD_CENTS without pinning a value; the
# real-world FRA accident-reporting damage threshold ($12,100) is used.
FRA_DAMAGE_THRESHOLD_CENTS = 1210000

CAR_TYPES = {"BOX", "HOPPER", "TANK", "FLAT", "GONDOLA"}
FRA_CLASSES = set(CLASS_SPEED_MPH.keys())
DEFECT_SEVERITIES = {"MONITOR", "CRITICAL"}
CREDIT_STATUSES = {"GOOD", "SUSPENDED"}
OWNERSHIPS = {"HOME", "FOREIGN"}
CRAFTS = {"ENGINEER", "CONDUCTOR"}
DIRECTIONS = {"RECEIVED", "DELIVERED"}
COMMODITIES = set(COMMODITY_RATE_CENTS_PER_TON.keys())
INCIDENT_TYPES = {"DERAILMENT", "COLLISION", "CROSSING", "HAZMAT", "INJURY"}
DIVISION_BASES = {"MILEAGE_PRORATE", "AGREED_PERCENTAGE"}
CALL_RESPONSES = {"ACCEPTED", "DECLINED"}

CAR_NOT_ON_LINE_STATUSES = {"INTERCHANGED_OUT", "BAD_ORDER", "HELD"}


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half up (PRD 2.7)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record factory
# ---------------------------------------------------------------------------

def new_record(fields):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = store.now
    rec["updated_at"] = store.now
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version by exactly 1
    (PRD 2.5 / 2.10), including system cascades."""
    rec["updated_at"] = store.now
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Track segments: speed, overdue, restriction cascade (PRD 3.6, 2.10)
# ---------------------------------------------------------------------------

def recompute_segment_speed(seg):
    base = CLASS_SPEED_MPH[seg["fra_class"]]
    if seg["defect_open"]:
        seg["effective_speed_mph"] = min(base, DEFECT_CAP_MPH[seg["open_defect_severity"]])
    else:
        seg["effective_speed_mph"] = base


def segment_is_overdue(seg, now):
    deadline = seg["last_inspection_at"] + timedelta(days=INSPECTION_FREQ_DAYS[seg["fra_class"]])
    # strictly greater; exactly at the deadline is NOT overdue (second precision)
    return now > deadline


def cascade_segment_restricted(seg):
    """PRD 2.10 / 3.4: PLANNED/READY movements over the segment are annulled
    (their CALLED/ACCEPTED crew calls expire); DEPARTED movements are held."""
    for mv in store.movements.values():
        if seg["id"] not in mv["route_segment_ids"]:
            continue
        if mv["status"] in ("PLANNED", "READY"):
            mv["status"] = "ANNULLED"
            touch(mv)
            for call in store.crew_calls.values():
                if call["movement_id"] == mv["id"] and call["status"] in ("CALLED", "ACCEPTED"):
                    call["status"] = "EXPIRED"
                    touch(call)
        elif mv["status"] == "DEPARTED":
            mv["status"] = "HELD"
            touch(mv)


def restrict_segment(seg):
    """IN_SERVICE -> RESTRICTED with the movement cascade. Returns True if it transitioned."""
    if seg["status"] != "IN_SERVICE":
        return False
    seg["status"] = "RESTRICTED"
    cascade_segment_restricted(seg)
    return True


# ---------------------------------------------------------------------------
# Logical clock sweeps (PRD 2.4): overdue inspections, crew rest, siding expiry
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    now = store.now
    swept_segments = 0
    swept_crew = 0
    swept_sidings = 0

    for seg in store.track_segments.values():
        overdue = segment_is_overdue(seg, now)
        changed = False
        if seg["is_overdue"] != overdue:
            seg["is_overdue"] = overdue
            changed = True
        if overdue and seg["status"] == "IN_SERVICE":
            restrict_segment(seg)
            swept_segments += 1
            changed = True
        if changed:
            touch(seg)

    for member in store.crew_members.values():
        if member["status"] == "RESTING" and member["rest_start_at"] is not None:
            elapsed = (now - member["rest_start_at"]).total_seconds()
            if elapsed >= HOS_REQUIRED_REST_MINUTES * 60:
                member["status"] = "AVAILABLE"
                member["rest_minutes_completed"] = None
                member["rest_start_at"] = None
                touch(member)
                swept_crew += 1

    for siding in store.sidings.values():
        if (siding["maintenance_agreement_status"] == "ACTIVE"
                and siding["agreement_expires_on"] is not None
                and now >= siding["agreement_expires_on"]):
            siding["maintenance_agreement_status"] = "EXPIRED"
            touch(siding)
            swept_sidings += 1

    return swept_segments, swept_crew, swept_sidings


# ---------------------------------------------------------------------------
# Car orders / fleet (PRD 3.1, 3.2, 3.3)
# ---------------------------------------------------------------------------

def cars_furnished_count(order_id):
    return sum(1 for c in store.railcars.values() if c["assigned_order_id"] == order_id)


# ---------------------------------------------------------------------------
# Crew HOS (PRD 3.7 / calculations.hos_availability)
# ---------------------------------------------------------------------------

def hos_available_minutes(member):
    daily_remaining = max(0, HOS_DAILY_LIMIT_MINUTES - member["on_duty_minutes_rolling_24h"])
    monthly_remaining = max(0, HOS_MONTHLY_LIMIT_MINUTES - member["on_duty_minutes_month"])
    return min(daily_remaining, monthly_remaining)


# ---------------------------------------------------------------------------
# Car hire (PRD 3.3 / calculations.car_hire_accrual)
# ---------------------------------------------------------------------------

def statement_accrued_hours(stmt):
    end = stmt["hire_accrual_end"] if stmt["hire_accrual_end"] is not None else store.now
    seconds = (end - stmt["hire_accrual_start"]).total_seconds()
    return int(math.floor(seconds / 3600.0))


def statement_provisional_cents(stmt):
    """Time-based only; mileage excluded; no minimum; recomputed on each read."""
    car = store.railcars.get(stmt["railcar_id"])
    rate = car["hire_rate_per_hour_cents"] if car else 0
    return statement_accrued_hours(stmt) * rate


def statement_final_cents(stmt):
    """Each component rounded to whole cents first (exact: integer cent rates),
    then summed, then the MIN_HIRE_CENTS floor is applied."""
    car = store.railcars.get(stmt["railcar_id"])
    hour_rate = car["hire_rate_per_hour_cents"] if car else 0
    mile_rate = car["hire_rate_per_mile_cents"] if car else 0
    time_component = round_half_up_cents(Decimal(statement_accrued_hours(stmt)) * Decimal(hour_rate))
    mileage_component = round_half_up_cents(Decimal(stmt["accrued_miles"]) * Decimal(mile_rate))
    return max(MIN_HIRE_CENTS, time_component + mileage_component)


# ---------------------------------------------------------------------------
# Revenue division (PRD 3.5 / calculations.revenue_division_share)
# ---------------------------------------------------------------------------

def division_shares(basis, agreed_pct, total_charge_cents, our_miles, total_miles):
    """our_share_cents is rounded half up to whole cents FIRST; the connecting
    road receives the unrounded remainder (never rounded independently)."""
    if basis == "MILEAGE_PRORATE":
        if total_miles:
            share = round_half_up_cents(
                Decimal(total_charge_cents) * Decimal(our_miles) / Decimal(total_miles))
        else:
            share = 0
    else:  # AGREED_PERCENTAGE
        share = round_half_up_cents(Decimal(total_charge_cents) * Decimal(str(agreed_pct)))
    return share, total_charge_cents - share


def division_exists_for(waybill_id):
    return any(d["waybill_id"] == waybill_id for d in store.revenue_divisions.values())


def create_division(waybill, basis, agreed_pct):
    our_share, connecting_share = division_shares(
        basis, agreed_pct,
        waybill["total_freight_charge_cents"],
        waybill["our_miles"], waybill["total_miles"])
    div = new_record({
        "waybill_id": waybill["id"],
        "basis": basis,
        "agreed_pct": agreed_pct,
        "our_miles": waybill["our_miles"],
        "total_miles": waybill["total_miles"],
        "total_charge_cents": waybill["total_freight_charge_cents"],
        "our_share_cents": our_share,
        "connecting_share_cents": connecting_share,
        "status": "DRAFT",
    })
    store.revenue_divisions[div["id"]] = div
    return div


# ---------------------------------------------------------------------------
# Waybill rating (PRD 3.5 / calculations.waybill_rating)
# ---------------------------------------------------------------------------

def waybill_rate_cents(commodity, weight_tons):
    return weight_tons * COMMODITY_RATE_CENTS_PER_TON[commodity]


# ---------------------------------------------------------------------------
# Grant projects (PRD 3.9 / calculations.grant_drawdown, project_percent_complete)
# ---------------------------------------------------------------------------

def project_milestones(project_id):
    return [m for m in store.grant_milestones.values() if m["project_id"] == project_id]


def project_committed_cents(project_id):
    return sum(m["drawdown_cents"] for m in project_milestones(project_id)
               if m["status"] == "APPROVED" and m["drawdown_cents"] is not None)


def project_drawn_cents(project_id):
    return sum(m["drawdown_cents"] for m in project_milestones(project_id)
               if m["status"] == "PAID" and m["drawdown_cents"] is not None)


def compute_drawdown(project, milestone):
    """Pinned waterfall (calculations.grant_drawdown): cost basis rounded half up
    to whole cents; cap at milestone value; cap at award remaining computed from
    project aggregates read BEFORE this milestone's drawdown is added."""
    cost_basis = round_half_up_cents(
        Decimal(milestone["actual_cost_cents"])
        * (Decimal("100") - Decimal(str(project["required_match_pct"]))) / Decimal("100"))
    capped_by_value = min(milestone["milestone_value_cents"], cost_basis)
    award_remaining_before = (project["award_amount_cents"]
                              - project_committed_cents(project["id"])
                              - project_drawn_cents(project["id"]))
    return min(capped_by_value, award_remaining_before)


def project_completion_check(project):
    """Bubble-up: at least one milestone and every milestone PAID -> COMPLETED."""
    if project["status"] != "ACTIVE":
        return
    milestones = project_milestones(project["id"])
    if milestones and all(m["status"] == "PAID" for m in milestones):
        project["status"] = "COMPLETED"
        touch(project)


# ---------------------------------------------------------------------------
# Serializers (field order per scaffold entities; datetimes -> ISO strings)
# ---------------------------------------------------------------------------

def customer_view(c):
    return {
        "id": c["id"], "name": c["name"], "billing_email": c["billing_email"],
        "demurrage_free_days": c["demurrage_free_days"], "credit_status": c["credit_status"],
        "created_at": iso(c["created_at"]), "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def siding_view(s):
    return {
        "id": s["id"], "customer_id": s["customer_id"], "name": s["name"],
        "capacity_cars": s["capacity_cars"],
        "serving_track_segment_id": s["serving_track_segment_id"],
        "agreement_expires_on": iso(s["agreement_expires_on"]),
        "maintenance_agreement_status": s["maintenance_agreement_status"],
        "created_at": iso(s["created_at"]), "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def car_order_view(o):
    return {
        "id": o["id"], "customer_id": o["customer_id"], "siding_id": o["siding_id"],
        "car_type": o["car_type"], "quantity": o["quantity"],
        "needed_by_date": iso(o["needed_by_date"]), "status": o["status"],
        "cars_furnished_count": cars_furnished_count(o["id"]),
        "furnished_at": iso(o["furnished_at"]), "released_at": iso(o["released_at"]),
        "created_at": iso(o["created_at"]), "updated_at": iso(o["updated_at"]),
        "version": o["version"],
    }


def railcar_view(c):
    return {
        "id": c["id"], "reporting_mark": c["reporting_mark"], "car_type": c["car_type"],
        "ownership": c["ownership"], "home_road_mark": c["home_road_mark"],
        "status": c["status"],
        "current_location_segment_id": c["current_location_segment_id"],
        "assigned_order_id": c["assigned_order_id"],
        "hire_rate_per_hour_cents": c["hire_rate_per_hour_cents"],
        "hire_rate_per_mile_cents": c["hire_rate_per_mile_cents"],
        "created_at": iso(c["created_at"]), "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def switch_job_view(j):
    return {
        "id": j["id"], "car_order_id": j["car_order_id"],
        "scheduled_date": j["scheduled_date"], "notes": j["notes"],
        "crew_call_id": j["crew_call_id"], "status": j["status"],
        "created_at": iso(j["created_at"]), "updated_at": iso(j["updated_at"]),
        "version": j["version"],
    }


def movement_view(m):
    return {
        "id": m["id"], "symbol": m["symbol"], "route_segment_ids": list(m["route_segment_ids"]),
        "origin_interchange_id": m["origin_interchange_id"], "status": m["status"],
        "max_speed_mph": m["max_speed_mph"],
        "departed_at": iso(m["departed_at"]), "arrived_at": iso(m["arrived_at"]),
        "created_at": iso(m["created_at"]), "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def interchange_event_view(e):
    return {
        "id": e["id"], "class_i_partner": e["class_i_partner"], "direction": e["direction"],
        "railcar_id": e["railcar_id"], "waybill_id": e["waybill_id"],
        "occurred_at": iso(e["occurred_at"]),
        "miles_traveled_on_line": e["miles_traveled_on_line"], "status": e["status"],
        "created_at": iso(e["created_at"]), "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def car_hire_statement_view(s):
    return {
        "id": s["id"], "railcar_id": s["railcar_id"], "period_month": s["period_month"],
        "hire_accrual_start": iso(s["hire_accrual_start"]),
        "hire_accrual_end": iso(s["hire_accrual_end"]),
        "accrued_hours": statement_accrued_hours(s),
        "accrued_miles": s["accrued_miles"],
        "provisional_amount_cents": statement_provisional_cents(s),
        "final_amount_cents": s["final_amount_cents"], "status": s["status"],
        "created_at": iso(s["created_at"]), "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def waybill_view(w):
    return {
        "id": w["id"], "railcar_id": w["railcar_id"],
        "origin_customer_id": w["origin_customer_id"], "car_order_id": w["car_order_id"],
        "movement_id": w["movement_id"], "destination": w["destination"],
        "commodity": w["commodity"], "weight_tons": w["weight_tons"],
        "through_route": w["through_route"], "our_miles": w["our_miles"],
        "total_miles": w["total_miles"],
        "total_freight_charge_cents": w["total_freight_charge_cents"],
        "status": w["status"],
        "created_at": iso(w["created_at"]), "updated_at": iso(w["updated_at"]),
        "version": w["version"],
    }


def division_view(d):
    return {
        "id": d["id"], "waybill_id": d["waybill_id"], "basis": d["basis"],
        "agreed_pct": d["agreed_pct"], "our_miles": d["our_miles"],
        "total_miles": d["total_miles"], "total_charge_cents": d["total_charge_cents"],
        "our_share_cents": d["our_share_cents"],
        "connecting_share_cents": d["connecting_share_cents"], "status": d["status"],
        "created_at": iso(d["created_at"]), "updated_at": iso(d["updated_at"]),
        "version": d["version"],
    }


def segment_view(s):
    return {
        "id": s["id"], "name": s["name"],
        "milepost_start": s["milepost_start"], "milepost_end": s["milepost_end"],
        "fra_class": s["fra_class"], "effective_speed_mph": s["effective_speed_mph"],
        "defect_open": s["defect_open"], "open_defect_severity": s["open_defect_severity"],
        "is_overdue": s["is_overdue"], "status": s["status"],
        "last_inspection_at": iso(s["last_inspection_at"]),
        "created_at": iso(s["created_at"]), "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def inspection_view(i):
    return {
        "id": i["id"], "segment_id": i["segment_id"], "scheduled_date": i["scheduled_date"],
        "status": i["status"], "defect_found": i["defect_found"],
        "defect_severity": i["defect_severity"], "findings": i["findings"],
        "filed_at": iso(i["filed_at"]),
        "created_at": iso(i["created_at"]), "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def crew_member_view(m):
    return {
        "id": m["id"], "name": m["name"], "craft": m["craft"], "status": m["status"],
        "on_duty_minutes_rolling_24h": m["on_duty_minutes_rolling_24h"],
        "on_duty_minutes_month": m["on_duty_minutes_month"],
        "rest_minutes_completed": m["rest_minutes_completed"],
        "rest_start_at": iso(m["rest_start_at"]),
        "hos_available_minutes": hos_available_minutes(m),
        "created_at": iso(m["created_at"]), "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def crew_call_view(c):
    return {
        "id": c["id"], "crew_member_id": c["crew_member_id"],
        "movement_id": c["movement_id"], "switch_job_id": c["switch_job_id"],
        "scheduled_start_at": iso(c["scheduled_start_at"]),
        "scheduled_end_at": iso(c["scheduled_end_at"]), "status": c["status"],
        "on_duty_at": iso(c["on_duty_at"]), "off_duty_at": iso(c["off_duty_at"]),
        "actual_on_duty_minutes": c["actual_on_duty_minutes"],
        "created_at": iso(c["created_at"]), "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def incident_view(i):
    return {
        "id": i["id"], "incident_type": i["incident_type"], "segment_id": i["segment_id"],
        "movement_id": i["movement_id"], "occurred_at": iso(i["occurred_at"]),
        "estimated_damage_cents": i["estimated_damage_cents"],
        "injuries_count": i["injuries_count"], "status": i["status"],
        "fra_reportable": i["fra_reportable"], "fra_report_number": i["fra_report_number"],
        "created_at": iso(i["created_at"]), "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def grant_project_view(p):
    committed = project_committed_cents(p["id"])
    drawn = project_drawn_cents(p["id"])
    remaining = p["award_amount_cents"] - committed - drawn
    included = sum(m["milestone_value_cents"] for m in project_milestones(p["id"])
                   if m["status"] in ("APPROVED", "PAID"))
    if p["award_amount_cents"]:
        pct = float((Decimal(included) * Decimal("100") / Decimal(p["award_amount_cents"]))
                    .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:
        pct = 0.0
    return {
        "id": p["id"], "title": p["title"], "grantor": p["grantor"],
        "award_amount_cents": p["award_amount_cents"],
        "required_match_pct": p["required_match_pct"], "status": p["status"],
        "committed_cents": committed, "drawn_cents": drawn,
        "remaining_cents": remaining, "percent_complete": pct,
        "created_at": iso(p["created_at"]), "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def milestone_view(m):
    return {
        "id": m["id"], "project_id": m["project_id"], "name": m["name"],
        "milestone_value_cents": m["milestone_value_cents"],
        "actual_cost_cents": m["actual_cost_cents"], "status": m["status"],
        "drawdown_cents": m["drawdown_cents"], "submitted_at": iso(m["submitted_at"]),
        "created_at": iso(m["created_at"]), "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }
