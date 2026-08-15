"""Entity serialization: internal dicts (datetimes as datetime) -> wire dicts.

Computed-on-read fields resolved here:
- Carrier.credit_available_cents (CALC carrier_credit_availability)
- Carrier.ytd_billed_cents (PAID invoice totals in the current UTC year)
- Escort.active_assignment_count (assignments in ACCEPTED/ACTIVE)
"""

import db
from util import fmt_dt

QUOTED_HOLD_JOB_STATES = ("BOOKED", "CLEARED", "SCHEDULED", "EN_ROUTE", "ON_HOLD")
OUTSTANDING_INVOICE_STATES = ("FINALIZED", "DISPUTED")


def _dt(value):
    return fmt_dt(value) if value is not None else None


def carrier_ytd_billed(carrier):
    year = db.now().year
    total = 0
    for inv in db.invoices.values():
        if inv["invoice_status"] != "PAID" or inv["paid_at"] is None:
            continue
        if inv["paid_at"].year != year:
            continue
        job = db.jobs.get(inv["job_id"])
        if job is not None and job["carrier_id"] == carrier["id"]:
            total += inv["total_cents"]
    return total


def carrier_credit_available(carrier):
    outstanding_quoted = sum(
        j["quoted_cents"] or 0
        for j in db.jobs.values()
        if j["carrier_id"] == carrier["id"] and j["job_status"] in QUOTED_HOLD_JOB_STATES
    )
    outstanding_billed = sum(
        inv["total_cents"]
        for inv in db.invoices.values()
        if inv["invoice_status"] in OUTSTANDING_INVOICE_STATES
        and (db.jobs.get(inv["job_id"]) or {}).get("carrier_id") == carrier["id"]
    )
    return carrier["credit_limit_cents"] - outstanding_quoted - outstanding_billed


def escort_active_count(escort):
    return sum(
        1
        for a in db.assignments.values()
        if a["escort_id"] == escort["id"] and a["assignment_status"] in ("ACCEPTED", "ACTIVE")
    )


def ser_carrier(c):
    return {
        "id": c["id"],
        "created_at": _dt(c["created_at"]),
        "updated_at": _dt(c["updated_at"]),
        "version": c["version"],
        "carrier_name": c["carrier_name"],
        "credit_limit_cents": c["credit_limit_cents"],
        "ytd_billed_cents": carrier_ytd_billed(c),
        "credit_available_cents": carrier_credit_available(c),
    }


def ser_escort(e):
    return {
        "id": e["id"],
        "created_at": _dt(e["created_at"]),
        "updated_at": _dt(e["updated_at"]),
        "version": e["version"],
        "operator_name": e["operator_name"],
        "certified_state_codes": list(e["certified_state_codes"]),
        "has_height_pole": e["has_height_pole"],
        "height_pole_max_inches": e["height_pole_max_inches"],
        "reliability_score": e["reliability_score"],
        "escort_status": e["escort_status"],
        "active_assignment_count": escort_active_count(e),
    }


def ser_job(j):
    return {
        "id": j["id"],
        "created_at": _dt(j["created_at"]),
        "updated_at": _dt(j["updated_at"]),
        "version": j["version"],
        "carrier_id": j["carrier_id"],
        "load_description": j["load_description"],
        "width_inches": j["width_inches"],
        "height_inches": j["height_inches"],
        "length_inches": j["length_inches"],
        "gross_weight_lbs": j["gross_weight_lbs"],
        "window_start_at": _dt(j["window_start_at"]),
        "window_end_at": _dt(j["window_end_at"]),
        "legs": [
            {
                "state_code": spec["state_code"],
                "sequence_index": spec["sequence_index"],
                "distance_miles": spec["distance_miles"],
                "planned_entry_at": _dt(spec["planned_entry_at"]),
                "planned_exit_at": _dt(spec["planned_exit_at"]),
                "map_min_clearance_inches": spec["map_min_clearance_inches"],
            }
            for spec in j["legs"]
        ],
        "job_status": j["job_status"],
        "quoted_cents": j["quoted_cents"],
        "quoted_at": _dt(j["quoted_at"]),
        "quote_expires_at": _dt(j["quote_expires_at"]),
        "booked_at": _dt(j["booked_at"]),
        "departed_at": _dt(j["departed_at"]),
        "delivered_at": _dt(j["delivered_at"]),
        "cancelled_at": _dt(j["cancelled_at"]),
        "cancel_fee_cents": j["cancel_fee_cents"],
        "cancel_fee_tier": j["cancel_fee_tier"],
        "total_escort_positions": j["total_escort_positions"],
    }


def ser_leg(leg):
    return {
        "id": leg["id"],
        "created_at": _dt(leg["created_at"]),
        "updated_at": _dt(leg["updated_at"]),
        "version": leg["version"],
        "job_id": leg["job_id"],
        "state_code": leg["state_code"],
        "sequence_index": leg["sequence_index"],
        "distance_miles": leg["distance_miles"],
        "planned_entry_at": _dt(leg["planned_entry_at"]),
        "planned_exit_at": _dt(leg["planned_exit_at"]),
        "map_min_clearance_inches": leg["map_min_clearance_inches"],
        "leg_status": leg["leg_status"],
        "required_front_escorts": leg["required_front_escorts"],
        "required_rear_escorts": leg["required_rear_escorts"],
        "requires_height_pole": leg["requires_height_pole"],
        "requires_police_escort": leg["requires_police_escort"],
        "requires_route_survey": leg["requires_route_survey"],
        "police_confirmed": leg["police_confirmed"],
        "clearance_verdict": leg["clearance_verdict"],
        "survey_min_clearance_inches": leg["survey_min_clearance_inches"],
    }


def ser_permit(p):
    return {
        "id": p["id"],
        "created_at": _dt(p["created_at"]),
        "updated_at": _dt(p["updated_at"]),
        "version": p["version"],
        "leg_id": p["leg_id"],
        "permit_number": p["permit_number"],
        "valid_from": _dt(p["valid_from"]),
        "valid_until": _dt(p["valid_until"]),
        "holiday_closure_dates": list(p["holiday_closure_dates"]),
        "permit_status": p["permit_status"],
        "issued_at": _dt(p["issued_at"]),
    }


def ser_survey(s):
    return {
        "id": s["id"],
        "created_at": _dt(s["created_at"]),
        "updated_at": _dt(s["updated_at"]),
        "version": s["version"],
        "leg_id": s["leg_id"],
        "survey_status": s["survey_status"],
        "surveyed_min_clearance_inches": s["surveyed_min_clearance_inches"],
        "submitted_at": _dt(s["submitted_at"]),
        "decided_at": _dt(s["decided_at"]),
        "decided_by_user_id": s["decided_by_user_id"],
        "rejection_reason": s["rejection_reason"],
    }


def ser_obstruction(o):
    return {
        "id": o["id"],
        "created_at": _dt(o["created_at"]),
        "survey_id": o["survey_id"],
        "milepost": o["milepost"],
        "obstruction_type": o["obstruction_type"],
        "measured_clearance_inches": o["measured_clearance_inches"],
        "disposition": o["disposition"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "created_at": _dt(a["created_at"]),
        "updated_at": _dt(a["updated_at"]),
        "version": a["version"],
        "leg_id": a["leg_id"],
        "escort_id": a["escort_id"],
        "position": a["position"],
        "assignment_status": a["assignment_status"],
        "offered_at": _dt(a["offered_at"]),
        "accepted_at": _dt(a["accepted_at"]),
        "activated_at": _dt(a["activated_at"]),
        "completed_at": _dt(a["completed_at"]),
        "released_at": _dt(a["released_at"]),
        "release_cause": a["release_cause"],
        "billable_hours": a["billable_hours"],
        "assignment_fee_cents": a["assignment_fee_cents"],
        "last_checkin_at": _dt(a["last_checkin_at"]),
    }


def ser_delay_event(d):
    return {
        "id": d["id"],
        "created_at": _dt(d["created_at"]),
        "updated_at": _dt(d["updated_at"]),
        "version": d["version"],
        "job_id": d["job_id"],
        "cause": d["cause"],
        "started_at": _dt(d["started_at"]),
        "ended_at": _dt(d["ended_at"]),
        "delay_status": d["delay_status"],
        "raw_minutes": d["raw_minutes"],
        "billable_minutes": d["billable_minutes"],
        "standby_amount_cents": d["standby_amount_cents"],
    }


def ser_incident(i):
    return {
        "id": i["id"],
        "created_at": _dt(i["created_at"]),
        "updated_at": _dt(i["updated_at"]),
        "version": i["version"],
        "job_id": i["job_id"],
        "assignment_id": i["assignment_id"],
        "incident_type": i["incident_type"],
        "description": i["description"],
        "claimed_amount_cents": i["claimed_amount_cents"],
        "reporter_role": i["reporter_role"],
        "reporter_user_id": i["reporter_user_id"],
        "incident_status": i["incident_status"],
        "escort_fault_share_pct": i["escort_fault_share_pct"],
        "assessed_amount_cents": i["assessed_amount_cents"],
        "escort_share_cents": i["escort_share_cents"],
        "assessed_by_user_id": i["assessed_by_user_id"],
        "settled_at": _dt(i["settled_at"]),
    }


def ser_invoice(inv):
    return {
        "id": inv["id"],
        "created_at": _dt(inv["created_at"]),
        "updated_at": _dt(inv["updated_at"]),
        "version": inv["version"],
        "job_id": inv["job_id"],
        "invoice_status": inv["invoice_status"],
        "base_charges_cents": inv["base_charges_cents"],
        "equipment_charges_cents": inv["equipment_charges_cents"],
        "standby_total_cents": inv["standby_total_cents"],
        "subtotal_cents": inv["subtotal_cents"],
        "volume_discount_cents": inv["volume_discount_cents"],
        "fuel_surcharge_cents": inv["fuel_surcharge_cents"],
        "cancellation_fee_cents": inv["cancellation_fee_cents"],
        "incident_chargebacks_cents": inv["incident_chargebacks_cents"],
        "adjustment_delta_cents": inv["adjustment_delta_cents"],
        "total_cents": inv["total_cents"],
        "generated_by_user_id": inv["generated_by_user_id"],
        "finalized_at": _dt(inv["finalized_at"]),
        "dispute_reason": inv["dispute_reason"],
        "adjustment_note": inv["adjustment_note"],
        "paid_at": _dt(inv["paid_at"]),
    }
