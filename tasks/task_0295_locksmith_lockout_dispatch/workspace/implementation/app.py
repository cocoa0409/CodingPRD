"""Locksmith & Lockout Dispatch API — Flask entry point.

All routes, validation ordering (PRD §2.6), state machines, cascades, and
calculations live here for clarity. In-memory store is empty on every boot.
"""
import os

from flask import Flask

from auth import get_principal, require_role
from db import db, lock
from domain import (
    base_record,
    touch,
    recompute_net_paid,
    recompute_lockpart_units,
)
from errors import ApiError, err
from helpers import (
    BASE_RATE_CENTS,
    BUFFER_MINUTES,
    SERVICE_TYPES,
    AUTH_KINDS,
    WARRANTY_DAYS,
    get_body,
    get_pagination,
    paginate,
    optional_bool,
    require_int,
    require_list,
    require_number,
    require_str,
    validate_minute,
    surcharge_multiplier,
    quote_estimated_total_cents,
    quote_final_total_cents,
    promised_eta_minutes,
    actual_response_minutes,
)
from response import success, error
from serialize import public, public_list

app = Flask(__name__)
app.url_map.strict_slashes = False


# =====================================================================
# Error handling
# =====================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_JOB_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error(e.error_id, e.message, e.http_status)
    return error("ERR_INVALID_REQUEST", "Internal error: %s" % e, 400)


# =====================================================================
# Existence lookups (PRD §2.5 — left-to-right, after authz)
# =====================================================================
def get_job(job_id):
    job = db.service_jobs.get(job_id)
    if job is None:
        raise err("ERR_JOB_NOT_FOUND", "ServiceJob not found")
    return job


def get_technician(tech_id):
    t = db.technicians.get(tech_id)
    if t is None:
        raise err("ERR_TECHNICIAN_NOT_FOUND", "Technician not found")
    return t


def get_bay(bay_id):
    b = db.job_bays.get(bay_id)
    if b is None:
        raise err("ERR_BAY_NOT_FOUND", "JobBay not found")
    return b


def get_quote(quote_id):
    q = db.quotes.get(quote_id)
    if q is None:
        raise err("ERR_QUOTE_NOT_FOUND", "OnSiteQuote not found")
    return q


def get_dispatch(dispatch_id):
    d = db.dispatches.get(dispatch_id)
    if d is None:
        raise err("ERR_DISPATCH_NOT_FOUND", "Dispatch not found")
    return d


def get_lockpart(part_id):
    p = db.lock_parts.get(part_id)
    if p is None:
        raise err("ERR_LOCKPART_NOT_FOUND", "LockPart not found")
    return p


def get_reservation(res_id):
    r = db.reservations.get(res_id)
    if r is None:
        raise err("ERR_RESERVATION_NOT_FOUND", "PartReservation not found")
    return r


def get_claim(claim_id):
    c = db.warranty_claims.get(claim_id)
    if c is None:
        raise err("ERR_CLAIM_NOT_FOUND", "WarrantyClaim not found")
    return c


# =====================================================================
# Derived-field helpers
# =====================================================================
def approved_quote_for_job(job_id):
    for q in db.quotes.values():
        if q["service_job_id"] == job_id and q["status"] == "APPROVED":
            return q
    return None


# =====================================================================
# ServiceJob
# =====================================================================
@app.route("/service-jobs", methods=["POST"])
def create_service_job():
    p = get_principal()
    require_role(p, {"Dispatcher"})
    body = get_body()
    customer_name = require_str(body, "customer_name")
    customer_user_id = require_str(body, "customer_user_id")
    service_type = require_str(body, "service_type")
    if service_type not in SERVICE_TYPES:
        raise err("ERR_INVALID_ENUM", "service_type must be one of LOCKOUT, REKEY, INSTALL, SAFE")
    service_address = require_str(body, "service_address")
    is_emergency = optional_bool(body, "is_emergency", False)
    requested_at_minute = require_int(body, "requested_at_minute")
    validate_minute(requested_at_minute, "requested_at_minute")

    with lock:
        rec = base_record()
        rec.update({
            "customer_name": customer_name,
            "customer_user_id": customer_user_id,
            "service_type": service_type,
            "service_address": service_address,
            "is_emergency": is_emergency,
            "requested_at_minute": requested_at_minute,
            "job_status": "INTAKE",
            "payment_status": "UNPAID",
            "amount_due_cents": 0,
            "net_paid_cents": 0,
        })
        db.service_jobs[rec["id"]] = rec
        return success(public(rec), 201)


@app.route("/service-jobs", methods=["GET"])
def list_service_jobs():
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician", "Customer", "InventoryManager", "BillingAgent"})
    from flask import request
    limit, offset = get_pagination()
    items = list(db.service_jobs.values())
    st = request.args.get("service_type")
    js = request.args.get("job_status")
    if st is not None:
        items = [j for j in items if j["service_type"] == st]
    if js is not None:
        items = [j for j in items if j["job_status"] == js]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/service-jobs/<job_id>", methods=["GET"])
def get_service_job(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician", "Customer", "InventoryManager", "BillingAgent"})
    job = get_job(job_id)
    return success(public(job), 200)


@app.route("/service-jobs/<job_id>/cancel", methods=["POST"])
def cancel_service_job(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    job = get_job(job_id)
    if job["job_status"] not in ("INTAKE", "DISPATCHED", "ON_SITE"):
        raise err("ERR_JOB_NOT_CANCELLABLE", "Job is not in a cancellable state")
    with lock:
        # Cascade: dispatches
        for d in db.dispatches.values():
            if d["service_job_id"] == job_id and d["status"] != "CANCELLED":
                d["status"] = "CANCELLED"
                touch(d)
        # Cascade: non-terminal quotes -> VOIDED, releasing their RESERVED reservations
        for q in db.quotes.values():
            if q["service_job_id"] == job_id and q["status"] in ("DRAFTED", "SUBMITTED", "APPROVED"):
                q["status"] = "VOIDED"
                touch(q)
                _release_reserved_for_quote(q["id"])
        # Cascade: bay bookings
        for bk in db.bay_bookings.values():
            if bk["service_job_id"] == job_id and bk["status"] == "BOOKED":
                bk["status"] = "RELEASED"
                touch(bk)
        job["job_status"] = "CANCELLED"
        touch(job)
        return success(public(job), 200)


def _release_reserved_for_quote(quote_id):
    """Every RESERVED reservation under quote -> RELEASED; restock part."""
    for r in db.reservations.values():
        if r["on_site_quote_id"] == quote_id and r["status"] == "RESERVED":
            r["status"] = "RELEASED"
            touch(r)
            part = db.lock_parts.get(r["lock_part_id"])
            if part is not None:
                recompute_lockpart_units(part)
                touch(part)


@app.route("/service-jobs/<job_id>/complete-work", methods=["POST"])
def complete_work(job_id):
    p = get_principal()
    require_role(p, {"Technician"})
    job = get_job(job_id)
    if job["job_status"] != "ON_SITE":
        raise err("ERR_JOB_NOT_ON_SITE", "Job is not ON_SITE")
    quote = approved_quote_for_job(job_id)
    if quote is None:
        raise err("ERR_NO_APPROVED_QUOTE", "Job has no APPROVED quote")
    with lock:
        # Commit reserved parts of the approved quote
        for r in db.reservations.values():
            if r["on_site_quote_id"] == quote["id"] and r["status"] == "RESERVED":
                r["status"] = "COMMITTED"
                touch(r)
                part = db.lock_parts.get(r["lock_part_id"])
                if part is not None:
                    recompute_lockpart_units(part)
                    touch(part)
        job["job_status"] = "WORK_COMPLETE"
        touch(job)
        return success(public(job), 200)


@app.route("/service-jobs/<job_id>/close", methods=["POST"])
def close_service_job(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    job = get_job(job_id)
    if job["job_status"] != "WORK_COMPLETE":
        raise err("ERR_JOB_NOT_FULLY_PAID", "Job is not in WORK_COMPLETE state")
    if job["payment_status"] != "PAID":
        raise err("ERR_JOB_NOT_FULLY_PAID", "Job is not fully paid")
    with lock:
        job["job_status"] = "CLOSED"
        touch(job)
        return success(public(job), 200)


# =====================================================================
# Payment
# =====================================================================
@app.route("/service-jobs/<job_id>/payments", methods=["POST"])
def capture_payment(job_id):
    p = get_principal()
    require_role(p, {"BillingAgent"})
    job = get_job(job_id)
    body = get_body()
    captured = require_int(body, "captured_amount_cents")
    if captured < 1:
        raise err("ERR_INVALID_REQUEST", "captured_amount_cents must be >= 1")
    # State: requires an APPROVED quote
    if approved_quote_for_job(job_id) is None:
        raise err("ERR_NO_APPROVED_QUOTE", "Job has no APPROVED quote")
    # Fiscal: must not push net_paid above amount_due
    prospective = job["net_paid_cents"] + captured
    if prospective > job["amount_due_cents"]:
        raise err("ERR_PAYMENT_EXCEEDS_DUE", "Capture would exceed amount due")
    with lock:
        rec = base_record()
        rec.update({
            "service_job_id": job_id,
            "captured_amount_cents": captured,
            "refunded_amount_cents": 0,
            "status": "CAPTURED",
        })
        db.payments[rec["id"]] = rec
        recompute_net_paid(job)
        if job["net_paid_cents"] == job["amount_due_cents"]:
            job["payment_status"] = "PAID"
        else:
            job["payment_status"] = "PARTIALLY_PAID"
        touch(job)
        return success(public(rec), 201)


@app.route("/service-jobs/<job_id>/payments", methods=["GET"])
def list_payments(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "BillingAgent", "Customer"})
    get_job(job_id)
    limit, offset = get_pagination()
    items = [r for r in db.payments.values() if r["service_job_id"] == job_id]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


# =====================================================================
# KeyAuthorizationRecord
# =====================================================================
@app.route("/service-jobs/<job_id>/key-authorizations", methods=["POST"])
def file_key_authorization(job_id):
    p = get_principal()
    require_role(p, {"Technician"})
    get_job(job_id)
    body = get_body()
    auth_kind = require_str(body, "auth_kind")
    if auth_kind not in AUTH_KINDS:
        raise err("ERR_INVALID_ENUM", "auth_kind must be one of KEY_DUPLICATION, CODE_RESET, RESTRICTED_BLANK")
    authorizing_party = require_str(body, "authorizing_party")
    id_document_ref = require_str(body, "id_document_ref")
    with lock:
        rec = base_record(common_fields=False)
        rec.update({
            "service_job_id": job_id,
            "auth_kind": auth_kind,
            "authorizing_party": authorizing_party,
            "id_document_ref": id_document_ref,
        })
        db.key_authorizations[rec["id"]] = rec
        return success(public(rec), 201)


@app.route("/service-jobs/<job_id>/key-authorizations", methods=["GET"])
def list_key_authorizations(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician", "InventoryManager"})
    get_job(job_id)
    limit, offset = get_pagination()
    items = [r for r in db.key_authorizations.values() if r["service_job_id"] == job_id]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


# =====================================================================
# WarrantyClaim (file + list under job; get/approve/deny by id)
# =====================================================================
@app.route("/service-jobs/<job_id>/warranty-claims", methods=["POST"])
def file_warranty_claim(job_id):
    p = get_principal()
    require_role(p, {"Customer"})
    job = get_job(job_id)
    # Ownership (priority 4, before state/business)
    if job["customer_user_id"] != p.user_id:
        raise err("ERR_NOT_JOB_OWNER", "Customer does not own this job")
    body = get_body()
    filed_at_minute = require_int(body, "filed_at_minute")
    validate_minute(filed_at_minute, "filed_at_minute")
    days_since_close = require_int(body, "days_since_close")
    if days_since_close < 0:
        raise err("ERR_INVALID_REQUEST", "days_since_close must be >= 0")
    reason = require_str(body, "reason")
    refund_amount_cents = require_int(body, "refund_amount_cents")
    if refund_amount_cents < 1:
        raise err("ERR_INVALID_REQUEST", "refund_amount_cents must be >= 1")
    with lock:
        rec = base_record()
        rec.update({
            "service_job_id": job_id,
            "filed_at_minute": filed_at_minute,
            "days_since_close": days_since_close,
            "reason": reason,
            "refund_amount_cents": refund_amount_cents,
            "status": "FILED",
        })
        db.warranty_claims[rec["id"]] = rec
        return success(public(rec), 201)


@app.route("/service-jobs/<job_id>/warranty-claims", methods=["GET"])
def list_warranty_claims(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Customer"})
    get_job(job_id)
    limit, offset = get_pagination()
    items = [r for r in db.warranty_claims.values() if r["service_job_id"] == job_id]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/warranty-claims/<claim_id>", methods=["GET"])
def get_warranty_claim(claim_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Customer"})
    claim = get_claim(claim_id)
    return success(public(claim), 200)


@app.route("/warranty-claims/<claim_id>/approve", methods=["POST"])
def approve_warranty_claim(claim_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    claim = get_claim(claim_id)
    if claim["status"] != "FILED":
        raise err("ERR_CLAIM_INVALID_STATE", "Claim is not in FILED state")
    job = get_job(claim["service_job_id"])
    if job["job_status"] != "CLOSED":
        raise err("ERR_JOB_NOT_CLOSED", "Parent job is not CLOSED")
    if claim["days_since_close"] > WARRANTY_DAYS:
        raise err("ERR_WARRANTY_EXPIRED", "Warranty window has expired")
    if claim["refund_amount_cents"] > job["net_paid_cents"]:
        raise err("ERR_REFUND_EXCEEDS_PAID", "Refund exceeds net paid")
    with lock:
        # Select refund target: CAPTURED payment with captured >= refund_amount,
        # lowest captured_amount first, ties by created_at ASC.
        candidates = [
            pay for pay in db.payments.values()
            if pay["service_job_id"] == job["id"]
            and pay["status"] == "CAPTURED"
            and pay["captured_amount_cents"] >= claim["refund_amount_cents"]
        ]
        candidates.sort(key=lambda pay: (pay["captured_amount_cents"], pay["created_at"], pay["_seq"]))
        target = candidates[0]
        target["status"] = "REFUNDED"
        target["refunded_amount_cents"] = target["captured_amount_cents"]
        touch(target)
        recompute_net_paid(job)
        job["payment_status"] = "REFUNDED"
        touch(job)
        claim["status"] = "APPROVED"
        touch(claim)
        return success(public(claim), 200)


@app.route("/warranty-claims/<claim_id>/deny", methods=["POST"])
def deny_warranty_claim(claim_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    claim = get_claim(claim_id)
    if claim["status"] != "FILED":
        raise err("ERR_CLAIM_INVALID_STATE", "Claim is not in FILED state")
    with lock:
        claim["status"] = "DENIED"
        touch(claim)
        return success(public(claim), 200)


# =====================================================================
# Dispatch
# =====================================================================
def _live_dispatches_for_tech(tech_id, exclude_id=None):
    out = []
    for d in db.dispatches.values():
        if d["technician_id"] != tech_id:
            continue
        if exclude_id is not None and d["id"] == exclude_id:
            continue
        if d["status"] in ("ASSIGNED", "EN_ROUTE"):
            out.append(d)
    return out


def _eta_overlaps(new_start, new_end, tech_id):
    """Half-open windows extended forward by BUFFER_MINUTES. Collide iff
    new_start < (e0 + BUFFER) AND s0 < (new_end + BUFFER)."""
    for d in _live_dispatches_for_tech(tech_id):
        s0 = d["eta_start_minute"]
        e0 = d["eta_end_minute"]
        if new_start < (e0 + BUFFER_MINUTES) and s0 < (new_end + BUFFER_MINUTES):
            return True
    return False


@app.route("/service-jobs/<job_id>/dispatches", methods=["POST"])
def create_dispatch(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    job = get_job(job_id)
    body = get_body()
    technician_id = require_str(body, "technician_id")
    eta_start = require_int(body, "eta_start_minute")
    eta_end = require_int(body, "eta_end_minute")
    # Existence of referenced technician (priority 3)
    tech = get_technician(technician_id)
    # Time-window validity (well-formedness, §3.15): minutes in range, order
    validate_minute(eta_start, "eta_start_minute")
    validate_minute(eta_end, "eta_end_minute")
    if eta_end <= eta_start:
        raise err("ERR_INVALID_TIME_WINDOW", "eta_end_minute must be > eta_start_minute")
    # State (priority 5): job must be INTAKE
    if job["job_status"] != "INTAKE":
        raise err("ERR_JOB_NOT_DISPATCHABLE", "Job is not in INTAKE state")
    # Business constraint (priority 6): technician availability + certification
    if tech["status"] != "ON_DUTY":
        raise err("ERR_TECHNICIAN_UNAVAILABLE", "Technician is not ON_DUTY")
    if job["service_type"] not in tech["certified_for"]:
        raise err("ERR_TECHNICIAN_NOT_CERTIFIED", "Technician not certified for service type")
    # Business temporal (priority 7): ETA window overlap
    if _eta_overlaps(eta_start, eta_end, technician_id):
        raise err("ERR_ETA_WINDOW_OVERLAP", "ETA window overlaps another live dispatch")
    with lock:
        live = _live_dispatches_for_tech(technician_id)
        rec = base_record()
        rec.update({
            "service_job_id": job_id,
            "technician_id": technician_id,
            "eta_start_minute": eta_start,
            "eta_end_minute": eta_end,
            "promised_eta_minutes": promised_eta_minutes(tech, len(live)),
            "actual_response_minutes": None,
            "arrived_at_minute": None,
            "status": "ASSIGNED",
        })
        db.dispatches[rec["id"]] = rec
        job["job_status"] = "DISPATCHED"
        touch(job)
        return success(public(rec), 201)


@app.route("/service-jobs/<job_id>/dispatches", methods=["GET"])
def list_job_dispatches(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    get_job(job_id)
    limit, offset = get_pagination()
    items = [d for d in db.dispatches.values() if d["service_job_id"] == job_id]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/dispatches", methods=["GET"])
def list_dispatches():
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    from flask import request
    limit, offset = get_pagination()
    items = list(db.dispatches.values())
    tid = request.args.get("technician_id")
    sjid = request.args.get("service_job_id")
    status = request.args.get("status")
    if tid is not None:
        items = [d for d in items if d["technician_id"] == tid]
    if sjid is not None:
        items = [d for d in items if d["service_job_id"] == sjid]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/dispatches/<dispatch_id>", methods=["GET"])
def get_dispatch_route(dispatch_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    d = get_dispatch(dispatch_id)
    return success(public(d), 200)


@app.route("/dispatches/<dispatch_id>/depart", methods=["POST"])
def depart_dispatch(dispatch_id):
    p = get_principal()
    require_role(p, {"Technician"})
    d = get_dispatch(dispatch_id)
    if d["status"] != "ASSIGNED":
        raise err("ERR_DISPATCH_NOT_ASSIGNED", "Dispatch is not ASSIGNED")
    with lock:
        d["status"] = "EN_ROUTE"
        touch(d)
        return success(public(d), 200)


@app.route("/dispatches/<dispatch_id>/arrive", methods=["POST"])
def arrive_dispatch(dispatch_id):
    p = get_principal()
    require_role(p, {"Technician"})
    d = get_dispatch(dispatch_id)
    body = get_body()
    arrived_at = require_int(body, "arrived_at_minute")
    validate_minute(arrived_at, "arrived_at_minute")
    if d["status"] != "EN_ROUTE":
        raise err("ERR_DISPATCH_NOT_EN_ROUTE", "Dispatch is not EN_ROUTE")
    job = get_job(d["service_job_id"])
    with lock:
        d["status"] = "ARRIVED"
        d["arrived_at_minute"] = arrived_at
        d["actual_response_minutes"] = actual_response_minutes(arrived_at, job["requested_at_minute"])
        touch(d)
        job["job_status"] = "ON_SITE"
        touch(job)
        return success(public(d), 200)


@app.route("/dispatches/<dispatch_id>/cancel", methods=["POST"])
def cancel_dispatch(dispatch_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    d = get_dispatch(dispatch_id)
    if d["status"] not in ("ASSIGNED", "EN_ROUTE"):
        raise err("ERR_DISPATCH_NOT_CANCELLABLE", "Dispatch is not cancellable")
    with lock:
        d["status"] = "CANCELLED"
        touch(d)
        return success(public(d), 200)


# =====================================================================
# Technician
# =====================================================================
@app.route("/technicians", methods=["POST"])
def create_technician():
    p = get_principal()
    require_role(p, {"Dispatcher"})
    body = get_body()
    full_name = require_str(body, "full_name")
    certified_for = require_list(body, "certified_for")
    for v in certified_for:
        if not isinstance(v, str):
            raise err("ERR_INVALID_REQUEST", "certified_for must be an array of strings")
        if v not in SERVICE_TYPES:
            raise err("ERR_INVALID_ENUM", "certified_for contains an invalid service_type")
    base_travel = require_int(body, "base_travel_minutes")
    if base_travel < 0:
        raise err("ERR_INVALID_REQUEST", "base_travel_minutes must be >= 0")
    with lock:
        rec = base_record()
        rec.update({
            "full_name": full_name,
            "certified_for": certified_for,
            "status": "ON_DUTY",
            "base_travel_minutes": base_travel,
        })
        db.technicians[rec["id"]] = rec
        return success(public(rec), 201)


@app.route("/technicians", methods=["GET"])
def list_technicians():
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    from flask import request
    limit, offset = get_pagination()
    items = list(db.technicians.values())
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/technicians/<tech_id>", methods=["GET"])
def get_technician_route(tech_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    t = get_technician(tech_id)
    return success(public(t), 200)


@app.route("/technicians/<tech_id>/set-off-duty", methods=["POST"])
def set_off_duty(tech_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    t = get_technician(tech_id)
    with lock:
        t["status"] = "OFF_DUTY"
        touch(t)
        return success(public(t), 200)


@app.route("/technicians/<tech_id>/set-on-duty", methods=["POST"])
def set_on_duty(tech_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    t = get_technician(tech_id)
    with lock:
        t["status"] = "ON_DUTY"
        touch(t)
        return success(public(t), 200)


# =====================================================================
# JobBay & BayBooking
# =====================================================================
@app.route("/job-bays", methods=["POST"])
def create_job_bay():
    p = get_principal()
    require_role(p, {"Dispatcher"})
    body = get_body()
    bay_name = require_str(body, "bay_name")
    with lock:
        rec = base_record()
        rec.update({"bay_name": bay_name, "status": "OPEN"})
        db.job_bays[rec["id"]] = rec
        return success(public(rec), 201)


@app.route("/job-bays", methods=["GET"])
def list_job_bays():
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    limit, offset = get_pagination()
    page, meta = paginate(list(db.job_bays.values()), limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/job-bays/<bay_id>", methods=["GET"])
def get_job_bay(bay_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    b = get_bay(bay_id)
    return success(public(b), 200)


@app.route("/job-bays/<bay_id>/close-for-maint", methods=["POST"])
def close_bay(bay_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    b = get_bay(bay_id)
    with lock:
        b["status"] = "CLOSED_FOR_MAINT"
        touch(b)
        return success(public(b), 200)


@app.route("/job-bays/<bay_id>/reopen", methods=["POST"])
def reopen_bay(bay_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    b = get_bay(bay_id)
    with lock:
        b["status"] = "OPEN"
        touch(b)
        return success(public(b), 200)


def _bay_slot_overlaps(new_start, new_end, bay_id):
    """Closed intervals, inclusive endpoints, no buffer. Collide iff
    new_start <= e0 AND s0 <= new_end."""
    for bk in db.bay_bookings.values():
        if bk["job_bay_id"] != bay_id or bk["status"] != "BOOKED":
            continue
        s0 = bk["slot_start_minute"]
        e0 = bk["slot_end_minute"]
        if new_start <= e0 and s0 <= new_end:
            return True
    return False


@app.route("/bay-bookings", methods=["POST"])
def create_bay_booking():
    p = get_principal()
    require_role(p, {"Dispatcher"})
    body = get_body()
    service_job_id = require_str(body, "service_job_id")
    job_bay_id = require_str(body, "job_bay_id")
    slot_start = require_int(body, "slot_start_minute")
    slot_end = require_int(body, "slot_end_minute")
    # Existence left-to-right: job, then bay
    get_job(service_job_id)
    bay = get_bay(job_bay_id)
    # Time-window validity
    validate_minute(slot_start, "slot_start_minute")
    validate_minute(slot_end, "slot_end_minute")
    if slot_end < slot_start:
        raise err("ERR_INVALID_TIME_WINDOW", "slot_end_minute must be >= slot_start_minute")
    # State: bay must be OPEN
    if bay["status"] != "OPEN":
        raise err("ERR_BAY_NOT_OPEN", "Bay is not OPEN")
    # Business temporal: slot overlap
    if _bay_slot_overlaps(slot_start, slot_end, job_bay_id):
        raise err("ERR_BAY_SLOT_OVERLAP", "Bay slot overlaps another booking")
    with lock:
        rec = base_record()
        rec.update({
            "service_job_id": service_job_id,
            "job_bay_id": job_bay_id,
            "slot_start_minute": slot_start,
            "slot_end_minute": slot_end,
            "status": "BOOKED",
        })
        db.bay_bookings[rec["id"]] = rec
        return success(public(rec), 201)


@app.route("/bay-bookings", methods=["GET"])
def list_bay_bookings():
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    from flask import request
    limit, offset = get_pagination()
    items = list(db.bay_bookings.values())
    sjid = request.args.get("service_job_id")
    bid = request.args.get("job_bay_id")
    status = request.args.get("status")
    if sjid is not None:
        items = [b for b in items if b["service_job_id"] == sjid]
    if bid is not None:
        items = [b for b in items if b["job_bay_id"] == bid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/bay-bookings/<booking_id>", methods=["GET"])
def get_bay_booking(booking_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician"})
    bk = db.bay_bookings.get(booking_id)
    if bk is None:
        raise err("ERR_BAY_NOT_FOUND", "BayBooking not found")
    return success(public(bk), 200)


@app.route("/bay-bookings/<booking_id>/release", methods=["POST"])
def release_bay_booking(booking_id):
    p = get_principal()
    require_role(p, {"Dispatcher"})
    bk = db.bay_bookings.get(booking_id)
    if bk is None:
        raise err("ERR_BAY_NOT_FOUND", "BayBooking not found")
    with lock:
        bk["status"] = "RELEASED"
        touch(bk)
        return success(public(bk), 200)


# =====================================================================
# OnSiteQuote
# =====================================================================
def _validate_part_lines(part_lines):
    """Validate the shape of part_lines entries (well-formedness)."""
    for line in part_lines:
        if not isinstance(line, dict):
            raise err("ERR_INVALID_REQUEST", "part_lines entries must be objects")
        if "lock_part_id" not in line or not isinstance(line.get("lock_part_id"), str):
            raise err("ERR_INVALID_REQUEST", "part_lines entry missing lock_part_id")
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err("ERR_INVALID_REQUEST", "part_lines entry quantity must be an integer")
        up = line.get("unit_price_cents")
        if isinstance(up, bool) or not isinstance(up, int):
            raise err("ERR_INVALID_REQUEST", "part_lines entry unit_price_cents must be an integer")


@app.route("/service-jobs/<job_id>/quotes", methods=["POST"])
def create_quote(job_id):
    p = get_principal()
    require_role(p, {"Technician"})
    job = get_job(job_id)
    body = get_body()
    labor_hours = require_number(body, "labor_hours")
    if labor_hours < 0:
        raise err("ERR_INVALID_REQUEST", "labor_hours must be >= 0")
    part_lines = require_list(body, "part_lines")
    _validate_part_lines(part_lines)
    with lock:
        rec = base_record()
        rec.update({
            "service_job_id": job_id,
            "labor_hours": labor_hours,
            "part_lines": part_lines,
            "estimated_total_cents": quote_estimated_total_cents(job),
            "final_total_cents": None,
            "status": "DRAFTED",
        })
        db.quotes[rec["id"]] = rec
        return success(public(rec), 201)


@app.route("/service-jobs/<job_id>/quotes", methods=["GET"])
def list_job_quotes(job_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician", "Customer"})
    get_job(job_id)
    from flask import request
    limit, offset = get_pagination()
    items = [q for q in db.quotes.values() if q["service_job_id"] == job_id]
    status = request.args.get("status")
    if status is not None:
        items = [q for q in items if q["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/quotes/<quote_id>", methods=["GET"])
def get_quote_route(quote_id):
    p = get_principal()
    require_role(p, {"Dispatcher", "Technician", "Customer"})
    q = get_quote(quote_id)
    return success(public(q), 200)


@app.route("/quotes/<quote_id>", methods=["PUT"])
def update_quote(quote_id):
    p = get_principal()
    require_role(p, {"Technician"})
    q = get_quote(quote_id)
    if q["status"] != "DRAFTED":
        raise err("ERR_QUOTE_INVALID_STATE", "Quote is not DRAFTED")
    body = get_body()
    job = get_job(q["service_job_id"])
    with lock:
        if "labor_hours" in body and body["labor_hours"] is not None:
            lh = require_number(body, "labor_hours")
            if lh < 0:
                raise err("ERR_INVALID_REQUEST", "labor_hours must be >= 0")
            q["labor_hours"] = lh
        if "part_lines" in body and body["part_lines"] is not None:
            pl = require_list(body, "part_lines")
            _validate_part_lines(pl)
            q["part_lines"] = pl
        q["estimated_total_cents"] = quote_estimated_total_cents(job)
        touch(q)
        return success(public(q), 200)


@app.route("/quotes/<quote_id>/submit", methods=["POST"])
def submit_quote(quote_id):
    p = get_principal()
    require_role(p, {"Technician"})
    q = get_quote(quote_id)
    job = get_job(q["service_job_id"])
    # State: quote must be DRAFTED
    if q["status"] != "DRAFTED":
        raise err("ERR_QUOTE_INVALID_STATE", "Quote is not DRAFTED")
    # Parent job must be ON_SITE
    if job["job_status"] != "ON_SITE":
        raise err("ERR_JOB_NOT_ON_SITE", "Parent job is not ON_SITE")
    # Completeness: labor_hours and part_lines present
    if q.get("labor_hours") is None or q.get("part_lines") is None:
        raise err("ERR_QUOTE_INCOMPLETE", "Quote labor_hours/part_lines missing")
    with lock:
        q["final_total_cents"] = quote_final_total_cents(job, q["labor_hours"], q["part_lines"])
        q["status"] = "SUBMITTED"
        touch(q)
        return success(public(q), 200)


def _customer_owns_quote(principal, quote):
    job = db.service_jobs.get(quote["service_job_id"])
    if job is None or job["customer_user_id"] != principal.user_id:
        raise err("ERR_NOT_JOB_OWNER", "Customer does not own the parent job")
    return job


@app.route("/quotes/<quote_id>/approve", methods=["POST"])
def approve_quote(quote_id):
    p = get_principal()
    require_role(p, {"Customer"})
    q = get_quote(quote_id)
    job = _customer_owns_quote(p, q)
    if q["status"] != "SUBMITTED":
        raise err("ERR_QUOTE_INVALID_STATE", "Quote is not SUBMITTED")
    if approved_quote_for_job(job["id"]) is not None:
        raise err("ERR_QUOTE_ALREADY_APPROVED", "Another quote is already approved on this job")
    with lock:
        q["status"] = "APPROVED"
        touch(q)
        job["amount_due_cents"] = q["final_total_cents"]
        touch(job)
        return success(public(q), 200)


@app.route("/quotes/<quote_id>/reject", methods=["POST"])
def reject_quote(quote_id):
    p = get_principal()
    require_role(p, {"Customer"})
    q = get_quote(quote_id)
    _customer_owns_quote(p, q)
    if q["status"] != "SUBMITTED":
        raise err("ERR_QUOTE_INVALID_STATE", "Quote is not SUBMITTED")
    with lock:
        q["status"] = "REJECTED"
        touch(q)
        _release_reserved_for_quote(q["id"])
        return success(public(q), 200)


@app.route("/quotes/<quote_id>/request-revision", methods=["POST"])
def request_revision(quote_id):
    p = get_principal()
    require_role(p, {"Customer"})
    q = get_quote(quote_id)
    _customer_owns_quote(p, q)
    if q["status"] != "SUBMITTED":
        raise err("ERR_QUOTE_INVALID_STATE", "Quote is not SUBMITTED")
    with lock:
        q["status"] = "DRAFTED"
        touch(q)
        return success(public(q), 200)


@app.route("/quotes/<quote_id>/reopen", methods=["POST"])
def reopen_quote(quote_id):
    p = get_principal()
    require_role(p, {"Technician"})
    q = get_quote(quote_id)
    if q["status"] != "REJECTED":
        raise err("ERR_QUOTE_INVALID_STATE", "Quote is not REJECTED")
    job = get_job(q["service_job_id"])
    if job["job_status"] != "ON_SITE":
        raise err("ERR_JOB_NOT_ON_SITE", "Parent job is not ON_SITE")
    with lock:
        q["status"] = "DRAFTED"
        touch(q)
        return success(public(q), 200)


# =====================================================================
# LockPart & PartReservation
# =====================================================================
@app.route("/lock-parts", methods=["POST"])
def create_lock_part():
    p = get_principal()
    require_role(p, {"InventoryManager"})
    body = get_body()
    sku = require_str(body, "sku")
    part_status = body.get("part_status", "STOCKED")
    if part_status is None:
        part_status = "STOCKED"
    if part_status not in ("STOCKED", "DISCONTINUED"):
        raise err("ERR_INVALID_ENUM", "part_status must be STOCKED or DISCONTINUED")
    restricted_blank = optional_bool(body, "restricted_blank", False)
    units_total = require_int(body, "units_total")
    if units_total < 0:
        raise err("ERR_INVALID_REQUEST", "units_total must be >= 0")
    with lock:
        rec = base_record()
        rec.update({
            "sku": sku,
            "part_status": part_status,
            "restricted_blank": restricted_blank,
            "units_total": units_total,
            "units_available": units_total,
            "units_reserved": 0,
            "units_committed": 0,
        })
        db.lock_parts[rec["id"]] = rec
        return success(public(rec), 201)


@app.route("/lock-parts", methods=["GET"])
def list_lock_parts():
    p = get_principal()
    require_role(p, {"InventoryManager", "Dispatcher", "Technician"})
    from flask import request
    limit, offset = get_pagination()
    items = list(db.lock_parts.values())
    status = request.args.get("part_status")
    if status is not None:
        items = [x for x in items if x["part_status"] == status]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/lock-parts/<part_id>", methods=["GET"])
def get_lock_part(part_id):
    p = get_principal()
    require_role(p, {"InventoryManager", "Dispatcher", "Technician"})
    part = get_lockpart(part_id)
    return success(public(part), 200)


@app.route("/lock-parts/<part_id>", methods=["PUT"])
def update_lock_part(part_id):
    p = get_principal()
    require_role(p, {"InventoryManager"})
    part = get_lockpart(part_id)
    body = get_body()
    expected = require_int(body, "expected_lockpart_version")
    # OCC check before mutation
    if expected != part["version"]:
        raise err("ERR_STALE_LOCKPART_VERSION", "expected_lockpart_version does not match")
    new_total = None
    new_status = None
    if "units_total" in body and body["units_total"] is not None:
        new_total = require_int(body, "units_total")
        if new_total < 0:
            raise err("ERR_INVALID_REQUEST", "units_total must be >= 0")
    if "part_status" in body and body["part_status"] is not None:
        new_status = body["part_status"]
        if new_status not in ("STOCKED", "DISCONTINUED"):
            raise err("ERR_INVALID_ENUM", "part_status must be STOCKED or DISCONTINUED")
    with lock:
        if new_total is not None:
            part["units_total"] = new_total
        if new_status is not None:
            part["part_status"] = new_status
        recompute_lockpart_units(part)
        touch(part)
        return success(public(part), 200)


@app.route("/part-reservations", methods=["POST"])
def create_part_reservation():
    p = get_principal()
    require_role(p, {"Technician"})
    body = get_body()
    on_site_quote_id = require_str(body, "on_site_quote_id")
    lock_part_id = require_str(body, "lock_part_id")
    quantity = require_int(body, "quantity")
    expected = require_int(body, "expected_lockpart_version")
    # Existence left-to-right: quote, then part
    quote = get_quote(on_site_quote_id)
    part = get_lockpart(lock_part_id)
    # Priority order after existence (PRD §3.7):
    # 1) OCC version check
    if expected != part["version"]:
        raise err("ERR_STALE_LOCKPART_VERSION", "expected_lockpart_version does not match")
    # 2) restricted-blank authorization
    if part["restricted_blank"]:
        job_id = quote["service_job_id"]
        has_auth = any(
            a["service_job_id"] == job_id and a["auth_kind"] == "RESTRICTED_BLANK"
            for a in db.key_authorizations.values()
        )
        if not has_auth:
            raise err("ERR_AUTHORIZATION_MISSING", "Restricted-blank authorization missing")
    # 3) part not discontinued, quantity positive
    if part["part_status"] == "DISCONTINUED":
        raise err("ERR_PART_DISCONTINUED", "LockPart is DISCONTINUED")
    if quantity < 1:
        raise err("ERR_INVALID_QUANTITY", "quantity must be >= 1")
    # 4) stock sufficiency
    if part["units_available"] < quantity:
        raise err("ERR_INSUFFICIENT_STOCK", "Insufficient stock")
    with lock:
        rec = base_record()
        rec.update({
            "on_site_quote_id": on_site_quote_id,
            "lock_part_id": lock_part_id,
            "quantity": quantity,
            "status": "RESERVED",
        })
        db.reservations[rec["id"]] = rec
        recompute_lockpart_units(part)
        touch(part)
        return success(public(rec), 201)


@app.route("/part-reservations", methods=["GET"])
def list_part_reservations():
    p = get_principal()
    require_role(p, {"Technician", "InventoryManager", "Dispatcher"})
    from flask import request
    limit, offset = get_pagination()
    items = list(db.reservations.values())
    qid = request.args.get("on_site_quote_id")
    pid = request.args.get("lock_part_id")
    status = request.args.get("status")
    if qid is not None:
        items = [r for r in items if r["on_site_quote_id"] == qid]
    if pid is not None:
        items = [r for r in items if r["lock_part_id"] == pid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success(public_list(page), 200, meta)


@app.route("/part-reservations/<res_id>", methods=["GET"])
def get_part_reservation(res_id):
    p = get_principal()
    require_role(p, {"Technician", "InventoryManager", "Dispatcher"})
    r = get_reservation(res_id)
    return success(public(r), 200)


# =====================================================================
# Main
# =====================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
