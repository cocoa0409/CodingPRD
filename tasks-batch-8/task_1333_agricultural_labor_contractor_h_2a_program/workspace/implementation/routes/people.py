"""Workers, visa petitions, consular appointments."""

from flask import Blueprint, request

import calc
from calc import d, iso
from common import (ALL_ROLES, ApiError, auth, body, clock_date, created_order,
                    get_or_404, invalid, ok, ok_list, paginate,
                    parse_date_val, req_int, req_str, stamp_new, touch)
from services import (linked_workers, ser_appointment, ser_job_order,
                      ser_petition, ser_worker)
from store import db

bp = Blueprint("people", __name__)


def _order(rid):
    return get_or_404(db.job_orders, rid, "ERR_JOB_ORDER_NOT_FOUND", "job order")


def _petition(rid):
    return get_or_404(db.visa_petitions, rid, "ERR_VISA_PETITION_NOT_FOUND",
                      "visa petition")


def _worker(rid):
    return get_or_404(db.workers, rid, "ERR_WORKER_NOT_FOUND", "worker")


# ------------------------------------------------------------------- workers

@bp.post("/h2a/workers")
@auth("ContractorAdmin")
def create_worker():
    b = body()
    passport = b.get("passport_number")
    if isinstance(passport, str) and any(
            w["passport_number"] == passport for w in db.workers.values()):
        raise ApiError("ERR_DUPLICATE_PASSPORT", 409,
                       "passport_number already registered")
    full_name = req_str(b, "full_name")
    passport = req_str(b, "passport_number")
    dob = b.get("date_of_birth")
    parse_date_val(dob, "date_of_birth")
    country_code = req_str(b, "country_code")
    rec = {
        "full_name": full_name,
        "passport_number": passport,
        "date_of_birth": dob,
        "country_code": country_code,
        "status": "REGISTERED",
        "petition_id": None,
    }
    stamp_new(rec)
    db.workers[rec["id"]] = rec
    return ok(ser_worker(rec), 201)


@bp.get("/h2a/workers")
@auth(*ALL_ROLES)
def list_workers():
    q = request.args
    rows = list(db.workers.values())
    if q.get("status") is not None:
        rows = [w for w in rows if w["status"] == q.get("status")]
    if q.get("petition_id") is not None:
        rows = [w for w in rows if w["petition_id"] == q.get("petition_id")]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_worker(w) for w in page], total, limit, offset)


@bp.get("/h2a/workers/<workerId>")
@auth(*ALL_ROLES)
def get_worker(workerId):
    return ok(ser_worker(_worker(workerId)))


# ------------------------------------------------------------ visa petitions

@bp.post("/h2a/job-orders/<jobOrderId>/visa-petitions")
@auth("ContractorAdmin")
def create_petition(jobOrderId):
    o = _order(jobOrderId)
    if o["status"] not in ("CERTIFIED", "RECRUITING", "PETITIONING"):
        raise ApiError("ERR_JOB_ORDER_INVALID_STATE", 409,
                       "order must be CERTIFIED, RECRUITING, or PETITIONING")
    grower = db.growers.get(o["grower_id"])
    if grower is None or grower["status"] != "ACTIVE":
        raise ApiError("ERR_GROWER_NOT_ACTIVE", 409, "grower is not ACTIVE")
    b = body()
    receipt = b.get("receipt_code")
    if isinstance(receipt, str) and any(
            p["receipt_code"] == receipt for p in db.visa_petitions.values()):
        raise ApiError("ERR_DUPLICATE_RECEIPT_CODE", 409,
                       "receipt_code already used")
    receipt = req_str(b, "receipt_code")
    requested = req_int(b, "requested_worker_count")
    if requested < 1:
        raise invalid("requested_worker_count must be >= 1")
    rec = {
        "job_order_id": o["id"],
        "receipt_code": receipt,
        "requested_worker_count": requested,
        "approved_worker_count": None,
        "rfe_count": 0,
        "filed_on": None,
        "status": "DRAFT",
    }
    stamp_new(rec)
    db.visa_petitions[rec["id"]] = rec
    return ok(ser_petition(rec), 201)


@bp.get("/h2a/job-orders/<jobOrderId>/visa-petitions")
@auth(*ALL_ROLES)
def list_petitions(jobOrderId):
    o = _order(jobOrderId)
    q = request.args
    rows = [p for p in db.visa_petitions.values() if p["job_order_id"] == o["id"]]
    if q.get("status") is not None:
        rows = [p for p in rows if p["status"] == q.get("status")]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_petition(p) for p in page], total, limit, offset)


@bp.get("/h2a/visa-petitions/<petitionId>")
@auth(*ALL_ROLES)
def get_petition(petitionId):
    return ok(ser_petition(_petition(petitionId)))


@bp.post("/h2a/visa-petitions/<petitionId>/file")
@auth("ContractorAdmin")
def file_petition(petitionId):
    p = _petition(petitionId)
    if p["status"] != "DRAFT":
        raise ApiError("ERR_PETITION_INVALID_STATE", 409,
                       "petition is not DRAFT")
    o = db.job_orders[p["job_order_id"]]
    if o["status"] != "PETITIONING":
        raise ApiError("ERR_JOB_ORDER_INVALID_STATE", 409,
                       "parent order is not PETITIONING")
    if p["requested_worker_count"] > \
            o["workers_requested"] - sum(
                1 for a in db.domestic_applications.values()
                if a["job_order_id"] == o["id"] and a["status"] == "HIRED"):
        raise ApiError("ERR_PETITION_EXCEEDS_VISA_CEILING", 409,
                       "requested_worker_count exceeds visa_worker_ceiling")
    p["status"] = "FILED"
    p["filed_on"] = iso(clock_date())
    touch(p)
    return ok(ser_petition(p))


@bp.post("/h2a/visa-petitions/<petitionId>/link-worker")
@auth("ContractorAdmin")
def link_worker(petitionId):
    p = _petition(petitionId)
    b = body()
    worker_id = b.get("worker_id")
    if worker_id is None:
        raise invalid("worker_id is required")
    w = _worker(worker_id)
    if p["status"] not in ("DRAFT", "FILED"):
        raise ApiError("ERR_PETITION_INVALID_STATE", 409,
                       "petition must be DRAFT or FILED to link workers")
    if w["status"] != "REGISTERED":
        raise ApiError("ERR_WORKER_INVALID_STATE", 409,
                       "worker must be REGISTERED to link")
    if len(linked_workers(p["id"])) + 1 > p["requested_worker_count"]:
        raise ApiError("ERR_PETITION_WORKER_OVERFLOW", 409,
                       "linked workers would exceed requested_worker_count")
    w["status"] = "PETITIONED"
    w["petition_id"] = p["id"]
    touch(w)
    return ok(ser_petition(p))


@bp.post("/h2a/visa-petitions/<petitionId>/issue-rfe")
@auth("ProgramReviewer")
def issue_rfe(petitionId):
    p = _petition(petitionId)
    if p["status"] != "FILED":
        raise ApiError("ERR_PETITION_INVALID_STATE", 409,
                       "petition is not FILED")
    if p["rfe_count"] >= calc.MAX_RFE_COUNT:
        raise ApiError("ERR_RFE_LIMIT_REACHED", 409,
                       "petition has already reached 2 RFEs")
    p["status"] = "RFE"
    p["rfe_count"] += 1
    touch(p)
    return ok(ser_petition(p))


@bp.post("/h2a/visa-petitions/<petitionId>/respond-rfe")
@auth("ContractorAdmin")
def respond_rfe(petitionId):
    p = _petition(petitionId)
    if p["status"] != "RFE":
        raise ApiError("ERR_PETITION_INVALID_STATE", 409,
                       "petition is not RFE")
    p["status"] = "FILED"
    touch(p)
    return ok(ser_petition(p))


@bp.post("/h2a/visa-petitions/<petitionId>/adjudicate")
@auth("ProgramReviewer")
def adjudicate(petitionId):
    p = _petition(petitionId)
    if p["status"] not in ("FILED", "RFE"):
        raise ApiError("ERR_PETITION_INVALID_STATE", 409,
                       "petition must be FILED or RFE to adjudicate")
    b = body()
    decision = b.get("decision")
    if not isinstance(decision, str) or \
            decision not in calc.DECISION_PETITION_ENUM:
        raise invalid("decision must be APPROVE or DENY")
    if decision == "APPROVE":
        approved = b.get("approved_worker_count")
        linked = len(linked_workers(p["id"]))
        if isinstance(approved, int) and not isinstance(approved, bool) \
                and approved != linked:
            raise ApiError("ERR_APPROVED_COUNT_MISMATCH", 409,
                           "approved_worker_count must equal the number of "
                           "linked workers")
        if isinstance(approved, bool) or not isinstance(approved, int):
            raise invalid("approved_worker_count is required and must be an "
                          "integer")
        if approved < 1 or approved > p["requested_worker_count"]:
            raise invalid("approved_worker_count must be in "
                          "[1, requested_worker_count]")
        p["status"] = "APPROVED"
        p["approved_worker_count"] = approved
        touch(p)
    else:  # DENY
        p["status"] = "DENIED"
        touch(p)
        for w in linked_workers(p["id"]):
            if w["status"] == "PETITIONED":
                w["status"] = "REGISTERED"
                w["petition_id"] = None
                touch(w)
    return ok(ser_petition(p))


# ------------------------------------------------------ consular appointments

@bp.post("/h2a/consular-appointments")
@auth("ContractorAdmin")
def create_appointment():
    b = body()
    worker_id = b.get("worker_id")
    petition_id = b.get("petition_id")
    if worker_id is None:
        raise invalid("worker_id is required")
    w = _worker(worker_id)
    if petition_id is None:
        raise invalid("petition_id is required")
    p = _petition(petition_id)
    if p["status"] != "APPROVED":
        raise ApiError("ERR_PETITION_INVALID_STATE", 409,
                       "petition must be APPROVED")
    if w["status"] != "PETITIONED":
        raise ApiError("ERR_WORKER_INVALID_STATE", 409,
                       "worker must be PETITIONED")
    appt_date_s = b.get("appointment_date")
    appt_date = parse_date_val(appt_date_s, "appointment_date")
    if appt_date <= clock_date():
        raise ApiError("ERR_APPOINTMENT_DATE_NOT_FUTURE", 409,
                       "appointment_date must be strictly after the clock date")
    if w["petition_id"] != p["id"]:
        raise ApiError("ERR_WORKER_NOT_ON_PETITION", 409,
                       "worker is not linked to this petition")
    consulate_code = req_str(b, "consulate_code")
    existing = sum(
        1 for a in db.consular_appointments.values()
        if a["status"] == "SCHEDULED"
        and a["consulate_code"] == consulate_code
        and a["appointment_date"] == appt_date_s)
    if existing >= calc.MAX_DAILY_CONSULAR_SLOTS:
        raise ApiError("ERR_CONSULATE_CAPACITY_FULL", 409,
                       "daily consular slot quota reached")
    if any(a["worker_id"] == w["id"] and a["status"] == "SCHEDULED"
           for a in db.consular_appointments.values()):
        raise ApiError("ERR_WORKER_HAS_ACTIVE_APPOINTMENT", 409,
                       "worker already has a SCHEDULED appointment")
    rec = {
        "worker_id": w["id"],
        "petition_id": p["id"],
        "consulate_code": consulate_code,
        "appointment_date": appt_date_s,
        "status": "SCHEDULED",
        "outcome": None,
        "completed_on": None,
    }
    stamp_new(rec)
    db.consular_appointments[rec["id"]] = rec
    return ok(ser_appointment(rec), 201)


@bp.get("/h2a/consular-appointments")
@auth(*ALL_ROLES)
def list_appointments():
    q = request.args
    rows = list(db.consular_appointments.values())
    for key in ("worker_id", "petition_id", "consulate_code",
                "appointment_date", "status"):
        if q.get(key) is not None:
            rows = [a for a in rows if a[key] == q.get(key)]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_appointment(a) for a in page], total, limit, offset)


@bp.get("/h2a/consular-appointments/<appointmentId>")
@auth(*ALL_ROLES)
def get_appointment(appointmentId):
    a = get_or_404(db.consular_appointments, appointmentId,
                   "ERR_CONSULAR_APPOINTMENT_NOT_FOUND", "consular appointment")
    return ok(ser_appointment(a))


@bp.post("/h2a/consular-appointments/<appointmentId>/complete")
@auth("VisaOfficer")
def complete_appointment(appointmentId):
    a = get_or_404(db.consular_appointments, appointmentId,
                   "ERR_CONSULAR_APPOINTMENT_NOT_FOUND", "consular appointment")
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_INVALID_STATE", 409,
                       "appointment is not SCHEDULED")
    if clock_date() < d(a["appointment_date"]):
        raise ApiError("ERR_APPOINTMENT_NOT_YET_DUE", 409,
                       "clock date has not reached appointment_date")
    b = body()
    outcome = b.get("outcome")
    if not isinstance(outcome, str) or outcome not in calc.OUTCOME_ENUM:
        raise invalid("outcome must be ISSUED, REFUSED, or NO_SHOW")
    a["status"] = "COMPLETED"
    a["outcome"] = outcome
    a["completed_on"] = iso(clock_date())
    touch(a)
    w = db.workers[a["worker_id"]]
    if outcome == "ISSUED":
        if w["status"] == "PETITIONED":
            w["status"] = "VISA_ISSUED"
            touch(w)
    elif outcome == "REFUSED":
        w["status"] = "REGISTERED"
        w["petition_id"] = None
        touch(w)
    return ok(ser_appointment(a))


@bp.post("/h2a/consular-appointments/<appointmentId>/cancel")
@auth("ContractorAdmin")
def cancel_appointment(appointmentId):
    a = get_or_404(db.consular_appointments, appointmentId,
                   "ERR_CONSULAR_APPOINTMENT_NOT_FOUND", "consular appointment")
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_INVALID_STATE", 409,
                       "appointment is not SCHEDULED")
    a["status"] = "CANCELLED"
    touch(a)
    return ok(ser_appointment(a))
