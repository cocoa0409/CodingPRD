"""Applicants, records requests, and the training-footprint read."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from services import (
    ATP_MINIMUM_HOURS, RECORDS_RESPONSE_WINDOW_DAYS, bump, footprint,
    get_applicant, get_records_request, has_valid_first_medical, new_id,
    ser_applicant, ser_records_request, stamp_new, touch,
)
from util import (
    EMAIL_RE, get_body, pagination_params, req_int, req_str, sort_rows,
    success_list, success_object,
)
from datetime import timedelta

bp = Blueprint("applicants", __name__)

READ_ROLES = ("Recruiter", "CrewScheduler", "TrainingCoordinator", "SystemAdmin")


# ---- Applicants ---------------------------------------------------------------

@bp.post("/applicants")
def create_applicant():
    require_roles("Recruiter", "SystemAdmin")
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    license_number = req_str(body, "license_number")
    total_flight_hours = req_int(body, "total_flight_hours")
    if not EMAIL_RE.match(email):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'email' must be a well-formed RFC-5322 address")
    if any(a["email"] == email for a in store.applicants.values()):
        raise ApiError("ERR_DUPLICATE_EMAIL", "An applicant with email %s already exists" % email)
    applicant = stamp_new({
        "full_name": full_name,
        "email": email,
        "license_number": license_number,
        "total_flight_hours": total_flight_hours,
        "status": "SCREENING",
        "seniority_number": None,
        "current_equipment_id": None,
        "cleared_at": None,
        "ledger_balance_cents": 0,
    })
    store.applicants[applicant["id"]] = applicant
    return success_object(ser_applicant(applicant), 201)


@bp.get("/applicants")
def list_applicants():
    require_roles(*READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.applicants.values())
    status = request.args.get("status")
    email = request.args.get("email")
    equipment = request.args.get("current_equipment_id")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    if email is not None:
        rows = [a for a in rows if a["email"] == email]
    if equipment is not None:
        rows = [a for a in rows if a["current_equipment_id"] == equipment]
    rows = sort_rows(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_applicant(a) for a in page], limit, offset, total)


@bp.get("/applicants/<aid>")
def read_applicant(aid):
    user_id, role = require_roles("Recruiter", "CrewScheduler", "TrainingCoordinator", "Pilot", "SystemAdmin")
    if role == "Pilot" and aid != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Pilot may read only their own applicant record")
    return success_object(ser_applicant(get_applicant(aid)))


@bp.post("/applicants/<aid>/advance-screening")
def advance_screening(aid):
    require_roles("Recruiter", "SystemAdmin")
    applicant = get_applicant(aid)
    if applicant["status"] != "SCREENING":
        raise ApiError("ERR_APPLICANT_INVALID_STATE",
                       "advance-screening requires status SCREENING, found %s" % applicant["status"])
    if applicant["total_flight_hours"] < ATP_MINIMUM_HOURS:
        raise ApiError("ERR_INSUFFICIENT_FLIGHT_HOURS",
                       "ATP screening gate requires total_flight_hours >= %d" % ATP_MINIMUM_HOURS)
    applicant["status"] = "PRIA_PENDING"
    bump(applicant)
    return success_object(ser_applicant(applicant))


@bp.post("/applicants/<aid>/clear")
def clear_applicant(aid):
    require_roles("Recruiter", "SystemAdmin")
    applicant = get_applicant(aid)
    if applicant["status"] != "PRIA_VERIFIED":
        raise ApiError("ERR_APPLICANT_INVALID_STATE",
                       "clear requires status PRIA_VERIFIED, found %s" % applicant["status"])
    requests = [r for r in store.records_requests.values() if r["applicant_id"] == aid]
    if (not requests or not all(r["status"] == "VERIFIED" for r in requests)
            or not any(r["request_type"] == "PRIA" for r in requests)):
        raise ApiError("ERR_RECORDS_INCOMPLETE",
                       "Every records request must be VERIFIED and at least one must be PRIA")
    if not has_valid_first_medical(aid):
        raise ApiError("ERR_NO_VALID_MEDICAL", "A VALID FIRST-class medical certificate is required")
    applicant["status"] = "CLEARED"
    applicant["cleared_at"] = store.now()
    applicant["seniority_number"] = 1 + sum(
        1 for a in store.applicants.values() if a["seniority_number"] is not None
    )
    bump(applicant)
    return success_object(ser_applicant(applicant))


@bp.post("/applicants/<aid>/reject")
def reject_applicant(aid):
    require_roles("Recruiter", "SystemAdmin")
    get_body()  # optional 'reason' accepted; no field stores it
    applicant = get_applicant(aid)
    if applicant["status"] not in ("SCREENING", "PRIA_PENDING", "PRIA_VERIFIED"):
        raise ApiError("ERR_APPLICANT_INVALID_STATE",
                       "reject requires a pre-clear status, found %s" % applicant["status"])
    applicant["status"] = "REJECTED"
    bump(applicant)
    return success_object(ser_applicant(applicant))


@bp.post("/applicants/<aid>/appeal")
def appeal_applicant(aid):
    require_roles("Recruiter", "SystemAdmin")
    applicant = get_applicant(aid)
    if applicant["status"] != "REJECTED":
        raise ApiError("ERR_APPLICANT_INVALID_STATE",
                       "appeal requires status REJECTED, found %s" % applicant["status"])
    applicant["status"] = "SCREENING"
    bump(applicant)
    return success_object(ser_applicant(applicant))


@bp.post("/applicants/<aid>/withdraw")
def withdraw_applicant(aid):
    user_id, role = require_roles("Recruiter", "Pilot", "SystemAdmin")
    if role == "Pilot" and aid != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Pilot may withdraw only their own application")
    applicant = get_applicant(aid)
    if applicant["status"] not in ("SCREENING", "PRIA_PENDING", "PRIA_VERIFIED"):
        raise ApiError("ERR_APPLICANT_INVALID_STATE",
                       "withdraw requires a pre-clear status, found %s" % applicant["status"])
    # Cascade: open records requests (DRAFT/SENT) -> EXPIRED (system cascade:
    # updated_at refreshed, no version bump).
    for r in store.records_requests.values():
        if r["applicant_id"] == aid and r["status"] in ("DRAFT", "SENT"):
            r["status"] = "EXPIRED"
            touch(r)
    applicant["status"] = "WITHDRAWN"
    bump(applicant)
    return success_object(ser_applicant(applicant))


@bp.get("/applicants/<aid>/training-footprint")
def training_footprint(aid):
    require_roles("Recruiter", "CrewScheduler", "TrainingCoordinator", "SystemAdmin")
    get_applicant(aid)
    variant = request.args.get("variant", "provisional")
    if variant not in ("provisional", "final"):
        raise ApiError("ERR_INVALID_REQUEST", "variant must be 'provisional' or 'final'")
    result = footprint(aid)
    return success_object({
        "applicant_id": result["applicant_id"],
        "variant": variant,
        "provisional_total_cents": result["provisional_total_cents"],
        "final_total_cents": result["final_total_cents"],
        "entry_count": result["entry_count"],
    })


# ---- Records requests ----------------------------------------------------------

@bp.post("/records-requests")
def create_records_request():
    require_roles("Recruiter", "SystemAdmin")
    body = get_body()
    applicant_id = req_str(body, "applicant_id")
    request_type = body.get("request_type")
    get_applicant(applicant_id)
    if request_type not in ("PRIA", "DRUG_TEST", "TRAINING_HISTORY"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "request_type must be one of PRIA, DRUG_TEST, TRAINING_HISTORY")
    rec = stamp_new({
        "applicant_id": applicant_id,
        "request_type": request_type,
        "status": "DRAFT",
        "sent_at": None,
        "due_at": None,
        "response_received_at": None,
        "failure_reason": None,
    })
    store.records_requests[rec["id"]] = rec
    return success_object(ser_records_request(rec), 201)


@bp.get("/records-requests")
def list_records_requests():
    require_roles("Recruiter", "SystemAdmin")
    limit, offset = pagination_params()
    rows = list(store.records_requests.values())
    applicant_id = request.args.get("applicant_id")
    status = request.args.get("status")
    if applicant_id is not None:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_records_request(r) for r in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/records-requests/<rid>")
def read_records_request(rid):
    require_roles("Recruiter", "SystemAdmin")
    return success_object(ser_records_request(get_records_request(rid)))


@bp.post("/records-requests/<rid>/send")
def send_records_request(rid):
    require_roles("Recruiter", "SystemAdmin")
    rec = get_records_request(rid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_RECORDS_REQUEST_INVALID_STATE",
                       "send requires status DRAFT, found %s" % rec["status"])
    now = store.now()
    rec["status"] = "SENT"
    rec["sent_at"] = now
    rec["due_at"] = now + timedelta(days=RECORDS_RESPONSE_WINDOW_DAYS)
    bump(rec)
    return success_object(ser_records_request(rec))


@bp.post("/records-requests/<rid>/receive")
def receive_records_request(rid):
    require_roles("Recruiter", "SystemAdmin")
    rec = get_records_request(rid)
    if rec["status"] != "SENT":
        raise ApiError("ERR_RECORDS_REQUEST_INVALID_STATE",
                       "receive requires status SENT, found %s" % rec["status"])
    # Constraint-band (priority 16) payload checks run after state guards.
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("RECEIVED", "FAILED"):
        raise ApiError("ERR_INVALID_REQUEST", "outcome must be one of RECEIVED, FAILED")
    failure_reason = body.get("failure_reason")
    if failure_reason is not None and not isinstance(failure_reason, str):
        raise ApiError("ERR_INVALID_REQUEST", "failure_reason must be a string or null")
    rec["status"] = outcome  # RECEIVED or FAILED
    rec["response_received_at"] = store.now()
    if outcome == "FAILED":
        rec["failure_reason"] = failure_reason
    bump(rec)
    return success_object(ser_records_request(rec))


@bp.post("/records-requests/<rid>/verify")
def verify_records_request(rid):
    require_roles("Recruiter", "SystemAdmin")
    rec = get_records_request(rid)
    if rec["status"] != "RECEIVED":
        raise ApiError("ERR_RECORDS_REQUEST_INVALID_STATE",
                       "verify requires status RECEIVED, found %s" % rec["status"])
    rec["status"] = "VERIFIED"
    bump(rec)
    # Bubble-up: all requests VERIFIED and >= 1 PRIA moves a PRIA_PENDING
    # applicant to PRIA_VERIFIED.
    applicant = store.applicants.get(rec["applicant_id"])
    if applicant is not None and applicant["status"] == "PRIA_PENDING":
        requests = [r for r in store.records_requests.values() if r["applicant_id"] == applicant["id"]]
        if (requests and all(r["status"] == "VERIFIED" for r in requests)
                and any(r["request_type"] == "PRIA" for r in requests)):
            applicant["status"] = "PRIA_VERIFIED"
            bump(applicant)
    return success_object(ser_records_request(rec))
