"""Serializers and cross-entity side effects (cascades, reconciliation)."""

from datetime import timedelta

import calc
from calc import d, iso
from common import (ApiError, clock_date, stamp_immutable, stamp_new, touch)
from store import db


# ------------------------------------------------------------- serializers

def ser_grower(g):
    return {
        "id": g["id"],
        "legal_name": g["legal_name"],
        "fein": g["fein"],
        "state_code": g["state_code"],
        "status": g["status"],
        "debarment_ends_on": g["debarment_ends_on"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_wage_determination(w):
    return {
        "id": w["id"],
        "state_code": w["state_code"],
        "crop": w["crop"],
        "activity": w["activity"],
        "effective_year": w["effective_year"],
        "aewr_hourly_cents": w["aewr_hourly_cents"],
        "prevailing_hourly_cents": w["prevailing_hourly_cents"],
        "prevailing_piece_rate_cents_per_unit": w["prevailing_piece_rate_cents_per_unit"],
        "piece_unit_name": w["piece_unit_name"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def domestic_hired_count(order_id):
    return sum(1 for a in db.domestic_applications.values()
               if a["job_order_id"] == order_id and a["status"] == "HIRED")


def live_determination(det):
    """The currently-PUBLISHED determination sharing det's survey key; a
    superseding determination replaces the referenced row for live reads."""
    if det is None or det["status"] == "PUBLISHED":
        return det
    for w in db.wage_determinations.values():
        if (w["status"] == "PUBLISHED"
                and w["state_code"] == det["state_code"]
                and w["crop"].lower() == det["crop"].lower()
                and w["activity"] == det["activity"]
                and w["effective_year"] == det["effective_year"]):
            return w
    return det


def ser_job_order(o):
    det = db.wage_determinations.get(o["wage_determination_id"])
    live = live_determination(det)
    floor = calc.required_hourly_floor(o, det, live) if det else None
    piece = calc.effective_piece_rate(o, det, live) if det else None
    hired = domestic_hired_count(o["id"])
    return {
        "id": o["id"],
        "grower_id": o["grower_id"],
        "wage_determination_id": o["wage_determination_id"],
        "title": o["title"],
        "crop": o["crop"],
        "activity": o["activity"],
        "worksite_state": o["worksite_state"],
        "work_start_date": o["work_start_date"],
        "work_end_date": o["work_end_date"],
        "daily_standard_hours": o["daily_standard_hours"],
        "workers_requested": o["workers_requested"],
        "offered_hourly_cents": o["offered_hourly_cents"],
        "offered_piece_rate_cents_per_unit": o["offered_piece_rate_cents_per_unit"],
        "inbound_transport_cents": o["inbound_transport_cents"],
        "outbound_transport_cents": o["outbound_transport_cents"],
        "status": o["status"],
        "deficiency_note": o["deficiency_note"],
        "locked_aewr_hourly_cents": o["locked_aewr_hourly_cents"],
        "locked_prevailing_hourly_cents": o["locked_prevailing_hourly_cents"],
        "locked_prevailing_piece_rate_cents_per_unit":
            o["locked_prevailing_piece_rate_cents_per_unit"],
        "required_hourly_floor_cents": floor,
        "effective_piece_rate_cents_per_unit": piece,
        "total_calendar_days": calc.total_calendar_days(o),
        "total_workdays": calc.workday_count(d(o["work_start_date"]),
                                             d(o["work_end_date"])),
        "recruitment_cutoff_date": iso(calc.recruitment_cutoff(o)),
        "transport_threshold_date": iso(calc.recruitment_cutoff(o)),
        "domestic_hired_count": hired,
        "visa_worker_ceiling": o["workers_requested"] - hired,
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_application(a):
    return {
        "id": a["id"],
        "job_order_id": a["job_order_id"],
        "applicant_name": a["applicant_name"],
        "contact_phone": a["contact_phone"],
        "applied_on": a["applied_on"],
        "status": a["status"],
        "qualification": a["qualification"],
        "decided_on": a["decided_on"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_worker(w):
    return {
        "id": w["id"],
        "full_name": w["full_name"],
        "passport_number": w["passport_number"],
        "date_of_birth": w["date_of_birth"],
        "country_code": w["country_code"],
        "status": w["status"],
        "petition_id": w["petition_id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ser_petition(p):
    return {
        "id": p["id"],
        "job_order_id": p["job_order_id"],
        "receipt_code": p["receipt_code"],
        "requested_worker_count": p["requested_worker_count"],
        "approved_worker_count": p["approved_worker_count"],
        "rfe_count": p["rfe_count"],
        "filed_on": p["filed_on"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_appointment(a):
    return {
        "id": a["id"],
        "worker_id": a["worker_id"],
        "petition_id": a["petition_id"],
        "consulate_code": a["consulate_code"],
        "appointment_date": a["appointment_date"],
        "status": a["status"],
        "outcome": a["outcome"],
        "completed_on": a["completed_on"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def occupied_count(unit_id):
    return sum(1 for h in db.housing_assignments.values()
               if h["housing_unit_id"] == unit_id and h["status"] == "OCCUPIED")


def ser_housing_unit(u):
    certified_on = u["certified_on"]
    valid_until = None
    if u["inspection_status"] == "CERTIFIED" and certified_on is not None:
        valid_until = iso(d(certified_on) + timedelta(days=365))
    return {
        "id": u["id"],
        "grower_id": u["grower_id"],
        "name": u["name"],
        "capacity": u["capacity"],
        "inspection_status": u["inspection_status"],
        "certified_on": certified_on,
        "certification_valid_until": valid_until,
        "occupied_count": occupied_count(u["id"]),
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def ser_inspection(i):
    return {
        "id": i["id"],
        "housing_unit_id": i["housing_unit_id"],
        "inspected_on": i["inspected_on"],
        "result": i["result"],
        "deficiency_codes": i["deficiency_codes"],
        "created_at": i["created_at"],
    }


def ser_housing_assignment(h):
    return {
        "id": h["id"],
        "housing_unit_id": h["housing_unit_id"],
        "worker_id": h["worker_id"],
        "worker_assignment_id": h["worker_assignment_id"],
        "move_in_date": h["move_in_date"],
        "move_out_date": h["move_out_date"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "worker_id": a["worker_id"],
        "job_order_id": a["job_order_id"],
        "started_on": a["started_on"],
        "ended_on": a["ended_on"],
        "end_reason": a["end_reason"],
        "guarantee_eligible": a["end_reason"] not in ("FOR_CAUSE", "ABANDONED"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_work_log(lg):
    hours = lg["hours_worked"]
    if isinstance(hours, float) and hours == int(hours):
        hours = int(hours)
    return {
        "id": lg["id"],
        "worker_assignment_id": lg["worker_assignment_id"],
        "work_date": lg["work_date"],
        "hours_worked": hours,
        "units_picked": lg["units_picked"],
        "created_at": lg["created_at"],
    }


def ser_reconciliation(r):
    return {
        "id": r["id"],
        "worker_assignment_id": r["worker_assignment_id"],
        "status": r["status"],
        "computed_through_date": r["computed_through_date"],
        "total_units": r["total_units"],
        "piece_earnings_cents": r["piece_earnings_cents"],
        "hourly_floor_earnings_cents": r["hourly_floor_earnings_cents"],
        "makeup_pay_cents": r["makeup_pay_cents"],
        "guarantee_basis_workdays": r["guarantee_basis_workdays"],
        "guaranteed_quarters": r["guaranteed_quarters"],
        "worked_quarters": r["worked_quarters"],
        "shortfall_quarters": r["shortfall_quarters"],
        "guarantee_pay_cents": r["guarantee_pay_cents"],
        "guarantee_applied": r["guarantee_applied"],
        "inbound_transport_owed_cents": r["inbound_transport_owed_cents"],
        "outbound_transport_owed_cents": r["outbound_transport_owed_cents"],
        "total_due_cents": r["total_due_cents"],
        "finalized_on": r["finalized_on"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_transfer(t):
    return {
        "id": t["id"],
        "worker_id": t["worker_id"],
        "from_assignment_id": t["from_assignment_id"],
        "to_job_order_id": t["to_job_order_id"],
        "reason": t["reason"],
        "requested_by_user_id": t["requested_by_user_id"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_audit_case(c):
    return {
        "id": c["id"],
        "grower_id": c["grower_id"],
        "job_order_id": c["job_order_id"],
        "trigger_source": c["trigger_source"],
        "note": c["note"],
        "opened_on": c["opened_on"],
        "status": c["status"],
        "findings": c["findings"],
        "provisional_exposure_cents": c["provisional_exposure_cents"],
        "final_penalty_cents": c["final_penalty_cents"],
        "debarment_years": c["debarment_years"],
        "closed_on": c["closed_on"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# ------------------------------------------------------------ look-ups

def assignment_logs(assignment_id):
    return sorted(
        (lg for lg in db.work_logs.values()
         if lg["worker_assignment_id"] == assignment_id),
        key=lambda lg: lg["_seq"],
    )


def recon_for(assignment_id):
    for r in db.wage_reconciliations.values():
        if r["worker_assignment_id"] == assignment_id:
            return r
    return None


def linked_workers(petition_id):
    return [w for w in db.workers.values() if w["petition_id"] == petition_id]


# ------------------------------------------------------- reconciliation ops

def recompute_recon(recon, final=False):
    """Update computed fields without touching version (caller touches)."""
    a = db.worker_assignments[recon["worker_assignment_id"]]
    o = db.job_orders[a["job_order_id"]]
    logs = assignment_logs(a["id"])
    fields = calc.recon_compute(o, a, logs, final, clock_date())
    recon.update(fields)


def create_recon(assignment):
    recon = {
        "worker_assignment_id": assignment["id"],
        "status": "OPEN",
        "finalized_on": None,
    }
    stamp_new(recon)
    recompute_recon(recon, final=False)
    db.wage_reconciliations[recon["id"]] = recon
    return recon


# ------------------------------------------------------------ cascades

def vacate_housing_for_assignment(assignment_id, move_out_iso):
    for h in db.housing_assignments.values():
        if (h["worker_assignment_id"] == assignment_id
                and h["status"] == "OCCUPIED"):
            h["status"] = "VACATED"
            h["move_out_date"] = move_out_iso
            touch(h)


def maybe_depart_worker(worker, exclude_assignment_id=None):
    """WORKING -> DEPARTED when no other PLANNED/ACTIVE assignment remains."""
    if worker["status"] != "WORKING":
        return
    for a in db.worker_assignments.values():
        if (a["worker_id"] == worker["id"]
                and a["id"] != exclude_assignment_id
                and a["status"] in calc.LIVE_ASSIGNMENT):
            return
    worker["status"] = "DEPARTED"
    touch(worker)


def end_active_assignment(a, reason, today):
    """COMPLETED / FOR_CAUSE / ABANDONED endings of an ACTIVE assignment."""
    a["status"] = "COMPLETED" if reason == "COMPLETED" else "TERMINATED"
    a["ended_on"] = iso(today)
    a["end_reason"] = reason
    touch(a)
    vacate_housing_for_assignment(a["id"], a["ended_on"])
    recon = recon_for(a["id"])
    if recon is not None and recon["status"] == "OPEN":
        recompute_recon(recon, final=False)
        touch(recon)
    worker = db.workers[a["worker_id"]]
    if reason == "ABANDONED":
        worker["status"] = "ABANDONED"
        touch(worker)
    else:
        maybe_depart_worker(worker, exclude_assignment_id=a["id"])


def withdraw_order_cascade(order):
    """JobOrder -> WITHDRAWN plus petition/application cascades."""
    order["status"] = "WITHDRAWN"
    touch(order)
    for p in db.visa_petitions.values():
        if p["job_order_id"] == order["id"] and p["status"] == "DRAFT":
            p["status"] = "WITHDRAWN"
            touch(p)
            for w in db.workers.values():
                if w["petition_id"] == p["id"] and w["status"] == "PETITIONED":
                    w["status"] = "REGISTERED"
                    w["petition_id"] = None
                    touch(w)
    for a in db.domestic_applications.values():
        if a["job_order_id"] == order["id"] and a["status"] == "APPLIED":
            a["status"] = "WITHDRAWN"
            touch(a)


def debar_grower_cascade(grower, years, today):
    if grower["status"] == "DEBARRED":
        return
    grower["status"] = "DEBARRED"
    grower["debarment_ends_on"] = iso(
        today + timedelta(days=years * calc.DAYS_PER_DEBARMENT_YEAR))
    touch(grower)
    for order in db.job_orders.values():
        if (order["grower_id"] == grower["id"]
                and order["status"] in ("DRAFT", "SUBMITTED", "DEFICIENCY",
                                        "CERTIFIED", "RECRUITING")):
            withdraw_order_cascade(order)


def open_abandonment_audit_case(order):
    case = {
        "grower_id": order["grower_id"],
        "job_order_id": order["id"],
        "trigger_source": "ABANDONMENT",
        "note": None,
        "opened_on": iso(clock_date()),
        "status": "OPEN",
        "findings": [],
        "provisional_exposure_cents": None,
        "final_penalty_cents": None,
        "debarment_years": None,
        "closed_on": None,
    }
    stamp_new(case)
    db.audit_cases[case["id"]] = case
    return case
