"""Job orders and domestic applications."""

from datetime import timedelta

from flask import Blueprint, request

import calc
from calc import d, iso
from common import (ALL_ROLES, ApiError, auth, body, clock_date, created_order,
                    get_or_404, invalid, ok, ok_list, paginate,
                    parse_date_val, req_int, req_str, stamp_new, touch)
from services import (domestic_hired_count, ser_application, ser_job_order,
                      withdraw_order_cascade)
from store import db

bp = Blueprint("orders", __name__)

PATCHABLE = (
    "work_start_date", "work_end_date", "daily_standard_hours",
    "workers_requested", "offered_hourly_cents",
    "offered_piece_rate_cents_per_unit", "inbound_transport_cents",
    "outbound_transport_cents",
)


def _order(rid):
    return get_or_404(db.job_orders, rid, "ERR_JOB_ORDER_NOT_FOUND", "job order")


def _validate_order_domain(start_s, end_s, daily_hours, workers, offered,
                           piece, inbound, outbound):
    if not isinstance(daily_hours, int) or isinstance(daily_hours, bool) \
            or not (1 <= daily_hours <= 12):
        raise invalid("daily_standard_hours must be an integer in 1..12")
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise invalid("workers_requested must be an integer >= 1")
    if not isinstance(offered, int) or isinstance(offered, bool) or offered <= 0:
        raise invalid("offered_hourly_cents must be a positive integer")
    if piece is not None:
        if isinstance(piece, bool) or not isinstance(piece, int) or piece <= 0:
            raise invalid("offered_piece_rate_cents_per_unit must be positive")
    for name, val in (("inbound_transport_cents", inbound),
                      ("outbound_transport_cents", outbound)):
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise invalid(f"{name} must be a non-negative integer")
    start = parse_date_val(start_s, "work_start_date")
    end = parse_date_val(end_s, "work_end_date")
    if end < start:
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "work_end_date must not precede work_start_date")


@bp.post("/h2a/job-orders")
@auth("ContractorAdmin")
def create_job_order():
    b = body()
    grower_id = b.get("grower_id")
    if grower_id is not None:
        get_or_404(db.growers, grower_id, "ERR_GROWER_NOT_FOUND", "grower")
    det_id = b.get("wage_determination_id")
    if det_id is not None:
        get_or_404(db.wage_determinations, det_id,
                   "ERR_WAGE_DETERMINATION_NOT_FOUND", "wage determination")
    if grower_id is None:
        raise invalid("grower_id is required")
    if det_id is None:
        raise invalid("wage_determination_id is required")
    title = req_str(b, "title")
    crop = req_str(b, "crop")
    activity = b.get("activity")
    if not isinstance(activity, str) or activity not in calc.ACTIVITY_ENUM:
        raise invalid("activity must be one of HARVEST, PACKING, PLANTING, GENERAL")
    worksite_state = req_str(b, "worksite_state")
    _validate_order_domain(
        b.get("work_start_date"), b.get("work_end_date"),
        b.get("daily_standard_hours"), b.get("workers_requested"),
        b.get("offered_hourly_cents"),
        b.get("offered_piece_rate_cents_per_unit"),
        b.get("inbound_transport_cents"), b.get("outbound_transport_cents"))
    rec = {
        "grower_id": grower_id,
        "wage_determination_id": det_id,
        "title": title,
        "crop": crop,
        "activity": activity,
        "worksite_state": worksite_state,
        "work_start_date": b["work_start_date"],
        "work_end_date": b["work_end_date"],
        "daily_standard_hours": b["daily_standard_hours"],
        "workers_requested": b["workers_requested"],
        "offered_hourly_cents": b["offered_hourly_cents"],
        "offered_piece_rate_cents_per_unit":
            b.get("offered_piece_rate_cents_per_unit"),
        "inbound_transport_cents": b["inbound_transport_cents"],
        "outbound_transport_cents": b["outbound_transport_cents"],
        "status": "DRAFT",
        "deficiency_note": None,
        "locked_aewr_hourly_cents": None,
        "locked_prevailing_hourly_cents": None,
        "locked_prevailing_piece_rate_cents_per_unit": None,
    }
    stamp_new(rec)
    db.job_orders[rec["id"]] = rec
    return ok(ser_job_order(rec), 201)


@bp.get("/h2a/job-orders")
@auth(*ALL_ROLES)
def list_job_orders():
    q = request.args
    rows = list(db.job_orders.values())
    if q.get("grower_id") is not None:
        rows = [o for o in rows if o["grower_id"] == q.get("grower_id")]
    if q.get("wage_determination_id") is not None:
        rows = [o for o in rows
                if o["wage_determination_id"] == q.get("wage_determination_id")]
    if q.get("status") is not None:
        rows = [o for o in rows if o["status"] == q.get("status")]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_job_order(o) for o in page], total, limit, offset)


@bp.get("/h2a/job-orders/<jobOrderId>")
@auth(*ALL_ROLES)
def get_job_order(jobOrderId):
    return ok(ser_job_order(_order(jobOrderId)))


@bp.patch("/h2a/job-orders/<jobOrderId>")
@auth("ContractorAdmin")
def patch_job_order(jobOrderId):
    o = _order(jobOrderId)
    if o["status"] not in ("DRAFT", "DEFICIENCY"):
        raise ApiError("ERR_JOB_ORDER_INVALID_STATE", 409,
                       "only DRAFT or DEFICIENCY job orders may be updated")
    b = body()
    expected = b.get("expected_job_order_version")
    if expected is None:
        raise invalid("expected_job_order_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid("expected_job_order_version must be an integer")
    if expected != o["version"]:
        raise ApiError("ERR_STALE_JOB_ORDER_VERSION", 412,
                       "job order version does not match expected value")
    new = {k: b.get(k, o[k]) for k in PATCHABLE}
    _validate_order_domain(
        new["work_start_date"], new["work_end_date"],
        new["daily_standard_hours"], new["workers_requested"],
        new["offered_hourly_cents"], new["offered_piece_rate_cents_per_unit"],
        new["inbound_transport_cents"], new["outbound_transport_cents"])
    for k in PATCHABLE:
        if k in b:
            o[k] = b[k]
    touch(o)
    return ok(ser_job_order(o))


def _transition(o, allowed):
    if o["status"] not in allowed:
        raise ApiError("ERR_JOB_ORDER_INVALID_STATE", 409,
                       f"job order in status {o['status']} does not permit "
                       "this operation")


@bp.post("/h2a/job-orders/<jobOrderId>/submit")
@auth("ContractorAdmin")
def submit_job_order(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("DRAFT", "DEFICIENCY"))
    grower = db.growers.get(o["grower_id"])
    if grower is None or grower["status"] != "ACTIVE":
        raise ApiError("ERR_GROWER_NOT_ACTIVE", 409, "grower is not ACTIVE")
    det = db.wage_determinations.get(o["wage_determination_id"])
    if det is None or det["status"] != "PUBLISHED":
        raise ApiError("ERR_WAGE_DETERMINATION_NOT_PUBLISHED", 409,
                       "referenced wage determination is not PUBLISHED")
    if d(o["work_end_date"]) < d(o["work_start_date"]):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "work_end_date must not precede work_start_date")
    o["locked_aewr_hourly_cents"] = det["aewr_hourly_cents"]
    o["locked_prevailing_hourly_cents"] = det["prevailing_hourly_cents"]
    o["locked_prevailing_piece_rate_cents_per_unit"] = \
        det["prevailing_piece_rate_cents_per_unit"]
    o["status"] = "SUBMITTED"
    o["deficiency_note"] = None
    touch(o)
    return ok(ser_job_order(o))


@bp.post("/h2a/job-orders/<jobOrderId>/flag-deficiency")
@auth("ProgramReviewer")
def flag_deficiency(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("SUBMITTED",))
    b = body()
    note = req_str(b, "note")
    o["status"] = "DEFICIENCY"
    o["deficiency_note"] = note
    touch(o)
    return ok(ser_job_order(o))


@bp.post("/h2a/job-orders/<jobOrderId>/certify")
@auth("ProgramReviewer")
def certify_job_order(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("SUBMITTED",))
    if clock_date() > d(o["work_start_date"]) - timedelta(days=calc.CERT_LEAD_DAYS):
        raise ApiError("ERR_CERTIFICATION_LEAD_TIME", 409,
                       "certification requires clock date at least 30 days "
                       "before work_start_date")
    o["status"] = "CERTIFIED"
    touch(o)
    return ok(ser_job_order(o))


@bp.post("/h2a/job-orders/<jobOrderId>/begin-recruitment")
@auth("ContractorAdmin")
def begin_recruitment(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("CERTIFIED",))
    o["status"] = "RECRUITING"
    touch(o)
    return ok(ser_job_order(o))


@bp.post("/h2a/job-orders/<jobOrderId>/close-recruitment")
@auth("ContractorAdmin")
def close_recruitment(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("RECRUITING",))
    if any(a["job_order_id"] == o["id"] and a["status"] == "APPLIED"
           for a in db.domestic_applications.values()):
        raise ApiError("ERR_UNDECIDED_APPLICATIONS_REMAIN", 409,
                       "applications still APPLIED for this order")
    o["status"] = "PETITIONING"
    touch(o)
    return ok(ser_job_order(o))


@bp.post("/h2a/job-orders/<jobOrderId>/activate")
@auth("ContractorAdmin")
def activate_job_order(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("PETITIONING",))
    if not any(p["job_order_id"] == o["id"] and p["status"] == "APPROVED"
               for p in db.visa_petitions.values()):
        raise ApiError("ERR_NO_APPROVED_PETITION", 409,
                       "no APPROVED petition for this order")
    if clock_date() < d(o["work_start_date"]):
        raise ApiError("ERR_ORDER_NOT_YET_STARTED", 409,
                       "clock date precedes work_start_date")
    o["status"] = "ACTIVE"
    touch(o)
    return ok(ser_job_order(o))


@bp.post("/h2a/job-orders/<jobOrderId>/close")
@auth("ContractorAdmin")
def close_job_order(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("ACTIVE",))
    if clock_date() < d(o["work_end_date"]):
        raise ApiError("ERR_ORDER_PERIOD_NOT_ENDED", 409,
                       "clock date precedes work_end_date")
    for a in db.worker_assignments.values():
        if a["job_order_id"] == o["id"] and \
                a["status"] not in calc.TERMINAL_ASSIGNMENT:
            raise ApiError("ERR_OPEN_ASSIGNMENTS_REMAIN", 409,
                           "order has non-terminal worker assignments")
    o["status"] = "CLOSING"
    touch(o)
    return ok(ser_job_order(o))


@bp.post("/h2a/job-orders/<jobOrderId>/finalize")
@auth("ContractorAdmin")
def finalize_job_order(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("CLOSING",))
    for a in db.worker_assignments.values():
        if a["job_order_id"] != o["id"]:
            continue
        for r in db.wage_reconciliations.values():
            if r["worker_assignment_id"] == a["id"] and r["status"] != "FINALIZED":
                raise ApiError("ERR_UNFINALIZED_RECONCILIATIONS_REMAIN", 409,
                               "order has unfinalized wage reconciliations")
    o["status"] = "CLOSED"
    touch(o)
    return ok(ser_job_order(o))


@bp.post("/h2a/job-orders/<jobOrderId>/withdraw")
@auth("ContractorAdmin")
def withdraw_job_order(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("DRAFT", "SUBMITTED", "DEFICIENCY", "CERTIFIED",
                    "RECRUITING", "PETITIONING"))
    if any(p["job_order_id"] == o["id"]
           and p["status"] in ("FILED", "RFE", "APPROVED")
           for p in db.visa_petitions.values()):
        raise ApiError("ERR_OPEN_PETITIONS_EXIST", 409,
                       "order has petitions in FILED, RFE, or APPROVED")
    withdraw_order_cascade(o)
    return ok(ser_job_order(o))


# ------------------------------------------------------ domestic applications

@bp.post("/h2a/job-orders/<jobOrderId>/domestic-applications")
@auth("ContractorAdmin")
def create_application(jobOrderId):
    o = _order(jobOrderId)
    _transition(o, ("RECRUITING",))
    b = body()
    name = req_str(b, "applicant_name")
    phone = req_str(b, "contact_phone")
    rec = {
        "job_order_id": o["id"],
        "applicant_name": name,
        "contact_phone": phone,
        "applied_on": iso(clock_date()),
        "status": "APPLIED",
        "qualification": None,
        "decided_on": None,
    }
    stamp_new(rec)
    db.domestic_applications[rec["id"]] = rec
    return ok(ser_application(rec), 201)


@bp.get("/h2a/job-orders/<jobOrderId>/domestic-applications")
@auth(*ALL_ROLES)
def list_applications(jobOrderId):
    o = _order(jobOrderId)
    q = request.args
    rows = [a for a in db.domestic_applications.values()
            if a["job_order_id"] == o["id"]]
    if q.get("status") is not None:
        rows = [a for a in rows if a["status"] == q.get("status")]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_application(a) for a in page], total, limit, offset)


@bp.post("/h2a/domestic-applications/<applicationId>/decide")
@auth("ContractorAdmin")
def decide_application(applicationId):
    a = get_or_404(db.domestic_applications, applicationId,
                   "ERR_DOMESTIC_APPLICATION_NOT_FOUND", "domestic application")
    if a["status"] != "APPLIED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "application is not APPLIED")
    b = body()
    decision = b.get("decision")
    if not isinstance(decision, str) or decision not in calc.DECISION_APP_ENUM:
        raise invalid("decision must be HIRE or REJECT")
    o = db.job_orders[a["job_order_id"]]
    if decision == "HIRE":
        if domestic_hired_count(o["id"]) >= o["workers_requested"]:
            raise ApiError("ERR_WORKER_CEILING_EXCEEDED", 409,
                           "domestic_hired_count already equals "
                           "workers_requested")
    else:  # REJECT
        if b.get("qualification") == "QUALIFIED" and \
                d(a["applied_on"]) <= calc.recruitment_cutoff(o):
            raise ApiError("ERR_DOMESTIC_PREFERENCE_VIOLATION", 422,
                           "QUALIFIED applicant inside the preference window "
                           "may not be rejected")
    qualification = b.get("qualification")
    if not isinstance(qualification, str) or \
            qualification not in calc.QUALIFICATION_ENUM:
        raise invalid("qualification must be QUALIFIED or UNQUALIFIED")
    a["status"] = "HIRED" if decision == "HIRE" else "REJECTED"
    a["qualification"] = qualification
    a["decided_on"] = iso(clock_date())
    touch(a)
    return ok(ser_application(a))
