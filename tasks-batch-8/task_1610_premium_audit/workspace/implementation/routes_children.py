"""Child resource routes: records requests, appointments, allocations,
subcontractor exposures, certificates of insurance."""
import db
import services
from db import (
    policies, work_orders, records_requests, appointments, allocations,
    exposures, certificates,
)
from errors import raise_err, validation
from middleware import (
    Ctx, authenticate, require_role, get_body, check_allowed,
    req_str, req_bool, req_enum, req_dt, parse_pagination,
)
from response import ok, created, ok_list

from flask import Blueprint

bp = Blueprint("children", __name__)

REJECTION_REASONS = {"INSUFFICIENT_COVERAGE", "EXPIRED", "OTHER"}


def _insured_scope_for_wo(wo):
    if Ctx.role == "Insured" and wo["policy_id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE",
                  "Insured may only access own policy graph")


def _auditor_scope_for_wo(wo):
    if Ctx.role == "Auditor" and wo["assigned_auditor_id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE",
                  "Auditor may only mutate assigned work orders")


# --- records requests -------------------------------------------------------------

def _load_records_request(rr_id):
    rr = records_requests.get(rr_id)
    if rr is None:
        raise_err("ERR_RECORDS_REQUEST_NOT_FOUND",
                  "RecordsRequest id does not exist")
    return rr


@bp.route("/records-requests/<rr_id>", methods=["GET"])
def get_records_request(rr_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    rr = _load_records_request(rr_id)
    wo = work_orders.get(rr["audit_work_order_id"])
    if wo:
        _insured_scope_for_wo(wo)
    return ok(db.serialize(rr))


@bp.route("/records-requests/<rr_id>/receive", methods=["POST"])
def receive_records_request(rr_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Auditor")
    rr = _load_records_request(rr_id)
    wo = work_orders.get(rr["audit_work_order_id"])
    _auditor_scope_for_wo(wo)
    if rr["status"] not in ("OPEN", "OVERDUE"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only OPEN or OVERDUE requests can be received")
    rr["status"] = "RECEIVED"
    rr["received_at"] = db.now_iso()
    db.touch(rr)
    return ok(db.serialize(rr))


@bp.route("/records-requests/<rr_id>/waive", methods=["POST"])
def waive_records_request(rr_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    rr = _load_records_request(rr_id)
    if rr["status"] not in ("OPEN", "OVERDUE"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only OPEN or OVERDUE requests can be waived")
    rr["status"] = "WAIVED"
    db.touch(rr)
    return ok(db.serialize(rr))


# --- appointments --------------------------------------------------------------------

def _load_appointment(appt_id):
    appt = appointments.get(appt_id)
    if appt is None:
        raise_err("ERR_APPOINTMENT_NOT_FOUND", "AuditAppointment id does not exist")
    return appt


@bp.route("/appointments/<appt_id>", methods=["GET"])
def get_appointment(appt_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    appt = _load_appointment(appt_id)
    wo = work_orders.get(appt["audit_work_order_id"])
    if wo:
        _insured_scope_for_wo(wo)
    return ok(db.serialize(appt))


@bp.route("/appointments/<appt_id>/confirm", methods=["POST"])
def confirm_appointment(appt_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Insured", "Auditor")
    appt = _load_appointment(appt_id)
    wo = work_orders.get(appt["audit_work_order_id"])
    if Ctx.role == "Insured":
        if wo is None or wo["policy_id"] != Ctx.user_id:
            raise_err("ERR_FORBIDDEN_SCOPE",
                      "Insured caller must own the audited policy")
    else:
        if appt["auditor_id"] != Ctx.user_id:
            raise_err("ERR_FORBIDDEN_SCOPE",
                      "Auditor caller must be the appointment's auditor")
    if appt["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SCHEDULED appointments can be confirmed")
    appt["status"] = "CONFIRMED"
    db.touch(appt)
    return ok(db.serialize(appt))


@bp.route("/appointments/<appt_id>/complete", methods=["POST"])
def complete_appointment(appt_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Auditor")
    appt = _load_appointment(appt_id)
    if appt["auditor_id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE",
                  "Caller must be the appointment's auditor")
    if appt["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SCHEDULED or CONFIRMED appointments can be completed")
    appt["status"] = "COMPLETED"
    db.touch(appt)
    wo = work_orders.get(appt["audit_work_order_id"])
    if wo is not None and wo["status"] == "APPOINTMENT_SCHEDULED":
        wo["status"] = "FIELD_WORK_DONE"
        db.touch(wo)
    return ok(db.serialize(appt))


@bp.route("/appointments/<appt_id>/no-show", methods=["POST"])
def no_show_appointment(appt_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Auditor")
    appt = _load_appointment(appt_id)
    if appt["auditor_id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE",
                  "Caller must be the appointment's auditor")
    if appt["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SCHEDULED or CONFIRMED appointments can be no-show")
    appt["status"] = "NO_SHOW"
    db.touch(appt)
    wo = work_orders.get(appt["audit_work_order_id"])
    if wo is not None:
        wo["no_show_count"] = wo.get("no_show_count", 0) + 1
        db.touch(wo)
    return ok(db.serialize(appt))


# --- payroll allocations --------------------------------------------------------------

def _load_allocation(alloc_id):
    a = allocations.get(alloc_id)
    if a is None:
        raise_err("ERR_ALLOCATION_NOT_FOUND", "PayrollAllocation id does not exist")
    return a


@bp.route("/payroll-allocations/<alloc_id>", methods=["GET"])
def get_allocation(alloc_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    a = _load_allocation(alloc_id)
    wo = work_orders.get(a["audit_work_order_id"])
    if wo:
        _insured_scope_for_wo(wo)
    return ok(db.serialize(a))


def _resolve_allocation(alloc_id, target):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Auditor")
    a = _load_allocation(alloc_id)
    wo = work_orders.get(a["audit_work_order_id"])
    _auditor_scope_for_wo(wo)
    if a["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only DRAFT allocations can be verified or rejected")
    if wo is None or wo["status"] not in services.ALLOC_MUTATION_WO_STATES:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Parent work order is not in an allocation-mutable state")
    a["status"] = target
    db.touch(a)
    services.recompute_wo_base(wo)
    return ok(db.serialize(a))


@bp.route("/payroll-allocations/<alloc_id>/verify", methods=["POST"])
def verify_allocation(alloc_id):
    return _resolve_allocation(alloc_id, "VERIFIED")


@bp.route("/payroll-allocations/<alloc_id>/reject", methods=["POST"])
def reject_allocation(alloc_id):
    return _resolve_allocation(alloc_id, "REJECTED")


# --- subcontractor exposures & certificates ----------------------------------------------

def _load_exposure(exposure_id):
    e = exposures.get(exposure_id)
    if e is None:
        raise_err("ERR_SUB_EXPOSURE_NOT_FOUND",
                  "SubcontractorExposure id does not exist")
    return e


@bp.route("/subcontractor-exposures/<exposure_id>", methods=["GET"])
def get_exposure(exposure_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    e = _load_exposure(exposure_id)
    wo = work_orders.get(e["audit_work_order_id"])
    if wo:
        _insured_scope_for_wo(wo)
    return ok(db.serialize(e))


@bp.route("/subcontractor-exposures/<exposure_id>/certificates", methods=["POST"])
def create_certificate(exposure_id):
    authenticate()
    body = get_body()
    check_allowed(body, {"insurer_name", "wc_coverage_present",
                         "gl_coverage_present", "coverage_effective_date",
                         "coverage_expiration_date"})
    vals = {
        "insurer_name": req_str(body, "insurer_name"),
        "wc_coverage_present": req_bool(body, "wc_coverage_present"),
        "gl_coverage_present": req_bool(body, "gl_coverage_present"),
        "coverage_effective_date": req_dt(body, "coverage_effective_date"),
        "coverage_expiration_date": req_dt(body, "coverage_expiration_date"),
    }
    if db.parse_dt(vals["coverage_effective_date"]) > \
            db.parse_dt(vals["coverage_expiration_date"]):
        validation("coverage_effective_date must be at or before "
                   "coverage_expiration_date")
    require_role("Insured", "Auditor")
    e = _load_exposure(exposure_id)
    wo = work_orders.get(e["audit_work_order_id"])
    if Ctx.role == "Insured":
        _insured_scope_for_wo(wo)
    else:
        _auditor_scope_for_wo(wo)
    if wo is None or wo["status"] not in services.ALLOC_MUTATION_WO_STATES:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Parent work order is not in a certificate-mutable state")
    ent = db.new_entity({
        "subcontractor_exposure_id": e["id"],
        "insurer_name": vals["insurer_name"],
        "wc_coverage_present": vals["wc_coverage_present"],
        "gl_coverage_present": vals["gl_coverage_present"],
        "coverage_effective_date": vals["coverage_effective_date"],
        "coverage_expiration_date": vals["coverage_expiration_date"],
        "status": "SUBMITTED",
        "rejection_reason": None,
    })
    certificates[ent["id"]] = ent
    return created(db.serialize(ent))


@bp.route("/subcontractor-exposures/<exposure_id>/certificates", methods=["GET"])
def list_certificates(exposure_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    e = _load_exposure(exposure_id)
    wo = work_orders.get(e["audit_work_order_id"])
    if wo:
        _insured_scope_for_wo(wo)
    limit, offset = parse_pagination()
    items = services.certs_of_exposure(e["id"])
    items = [db.serialize(c) for c in db.by_created(items)]
    return ok_list(items, limit, offset)


def _load_certificate(cert_id):
    c = certificates.get(cert_id)
    if c is None:
        raise_err("ERR_CERTIFICATE_NOT_FOUND",
                  "CertificateOfInsurance id does not exist")
    return c


@bp.route("/certificates/<cert_id>/verify", methods=["POST"])
def verify_certificate(cert_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Auditor")
    cert = _load_certificate(cert_id)
    exposure = services.exposure_of_cert(cert)
    wo = work_orders.get(exposure["audit_work_order_id"]) if exposure else None
    if wo:
        _auditor_scope_for_wo(wo)
    if cert["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SUBMITTED certificates can be verified")
    policy = policies.get(wo["policy_id"]) if wo else None
    if policy is not None:
        if policy["coverage_line"] == "WC" and not cert["wc_coverage_present"]:
            raise_err("ERR_CERT_INSUFFICIENT_COVERAGE",
                      "WC policy requires wc_coverage_present")
        if policy["coverage_line"] == "GL" and not cert["gl_coverage_present"]:
            raise_err("ERR_CERT_INSUFFICIENT_COVERAGE",
                      "GL policy requires gl_coverage_present")
    if wo is not None:
        p_start = db.parse_dt(wo["audit_period_start"])
        p_end = db.parse_dt(wo["audit_period_end"])
        c_start = db.parse_dt(cert["coverage_effective_date"])
        c_end = db.parse_dt(cert["coverage_expiration_date"])
        if not (c_start <= p_end and p_start <= c_end):
            raise_err("ERR_CERT_WINDOW_INSUFFICIENT",
                      "Certificate coverage interval is disjoint from the "
                      "audit period")
    cert["status"] = "VERIFIED"
    db.touch(cert)
    services.recompute_exposure(exposure)
    return ok(db.serialize(cert))


@bp.route("/certificates/<cert_id>/reject", methods=["POST"])
def reject_certificate(cert_id):
    authenticate()
    body = get_body()
    check_allowed(body, {"reason"})
    reason = req_enum(body, "reason", REJECTION_REASONS)
    require_role("Auditor")
    cert = _load_certificate(cert_id)
    exposure = services.exposure_of_cert(cert)
    wo = work_orders.get(exposure["audit_work_order_id"]) if exposure else None
    if wo:
        _auditor_scope_for_wo(wo)
    if cert["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SUBMITTED certificates can be rejected")
    cert["status"] = "REJECTED"
    cert["rejection_reason"] = reason
    db.touch(cert)
    services.recompute_exposure(exposure)
    return ok(db.serialize(cert))
