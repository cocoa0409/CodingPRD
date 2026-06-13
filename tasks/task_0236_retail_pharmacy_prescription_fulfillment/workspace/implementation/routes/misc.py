"""DUR alerts, prior-auth requests, PDMP reports, payment records."""
from flask import Blueprint, request

import db
from common import (
    get_body, require_field, as_string, as_int, stamp_create, touch,
    get_pagination, paginate,
)
from clock import parse_iso
from errors import err
from middleware import get_actor, require_roles
from response import object_response, array_response
from services import domain

bp = Blueprint("misc", __name__)

ALL_ROLES = ["PharmacyAdmin", "Pharmacist", "Technician", "Cashier"]


# ===========================================================================
# DurAlert (read only)
# ===========================================================================


def serialize_alert(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "fill_id": a["fill_id"], "alert_type": a["alert_type"],
        "severity": a["severity"], "detail": a["detail"], "overridden": a["overridden"],
        "override_reason": a["override_reason"],
    }


@bp.route("/dur-alerts", methods=["GET"])
def list_alerts():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    fill_id = request.args.get("fill_id")
    items = list(db.dur_alerts.values())
    if fill_id is not None:
        items = [a for a in items if a["fill_id"] == fill_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_alert(a) for a in page], limit, offset, total)


@bp.route("/dur-alerts/<rid>", methods=["GET"])
def get_alert(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    a = db.dur_alerts.get(rid)
    if a is None:
        raise err("ERR_NOT_FOUND", "DUR alert not found")
    return object_response(serialize_alert(a), 200)


# ===========================================================================
# PriorAuthRequest
# ===========================================================================


def serialize_pa(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "fill_id": p["fill_id"],
        "prescription_id": p["prescription_id"], "reason": p["reason"],
        "submitted_utc": p["submitted_utc"], "decided_utc": p["decided_utc"],
        "expires_utc": p["expires_utc"], "status": p["status"],
    }


@bp.route("/prior-auth-requests", methods=["GET"])
def list_pa():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    fill_id = request.args.get("fill_id")
    prescription_id = request.args.get("prescription_id")
    items = list(db.prior_auth_requests.values())
    if fill_id is not None:
        items = [p for p in items if p["fill_id"] == fill_id]
    if prescription_id is not None:
        items = [p for p in items if p["prescription_id"] == prescription_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_pa(p) for p in page], limit, offset, total)


@bp.route("/prior-auth-requests/<rid>", methods=["GET"])
def get_pa(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    pa = db.prior_auth_requests.get(rid)
    if pa is None:
        raise err("ERR_NOT_FOUND", "Prior-auth request not found")
    return object_response(serialize_pa(pa), 200)


@bp.route("/prior-auth-requests/<rid>/approve", methods=["POST"])
def approve_pa(rid):
    _uid, role = get_actor()
    require_roles(role, ["Pharmacist"])
    body = get_body()
    expected = as_int(require_field(body, "expected_priorauthrequest_version"),
                      "expected_priorauthrequest_version")
    with db.LOCK:
        pa = db.prior_auth_requests.get(rid)
        if pa is None:
            raise err("ERR_NOT_FOUND", "Prior-auth request not found")
        # OCC (priority 5) before state in PRD §2.8 ordering.
        if expected != pa["version"]:
            raise err("ERR_STALE_PA_VERSION", "expected_priorauthrequest_version is stale")
        if pa["status"] != "PENDING":
            raise err("ERR_PA_NOT_PENDING", "Prior-auth request is not PENDING")
        cur = parse_iso(db.current_utc())
        if cur > parse_iso(pa["expires_utc"]):
            raise err("ERR_PA_EXPIRED", "Prior-auth request has expired")
        pa["status"] = "APPROVED"
        pa["decided_utc"] = db.current_utc()
        touch(pa)
        fill = db.fills.get(pa["fill_id"])
        if fill is not None:
            fill["claim_status"] = "UNCLAIMED"
            fill["status"] = "ADJUDICATING"
            touch(fill)
    return object_response(serialize_pa(pa), 200)


@bp.route("/prior-auth-requests/<rid>/deny", methods=["POST"])
def deny_pa(rid):
    _uid, role = get_actor()
    require_roles(role, ["Pharmacist"])
    body = get_body()
    expected = as_int(require_field(body, "expected_priorauthrequest_version"),
                      "expected_priorauthrequest_version")
    with db.LOCK:
        pa = db.prior_auth_requests.get(rid)
        if pa is None:
            raise err("ERR_NOT_FOUND", "Prior-auth request not found")
        if expected != pa["version"]:
            raise err("ERR_STALE_PA_VERSION", "expected_priorauthrequest_version is stale")
        if pa["status"] != "PENDING":
            raise err("ERR_PA_NOT_PENDING", "Prior-auth request is not PENDING")
        pa["status"] = "DENIED"
        pa["decided_utc"] = db.current_utc()
        touch(pa)
        fill = db.fills.get(pa["fill_id"])
        if fill is not None:
            fill["claim_status"] = "REJECTED"
            fill["status"] = "CANCELLED"
            touch(fill)
            rx = db.prescriptions.get(fill["prescription_id"])
            if rx is not None:
                domain.recompute_refills_remaining(rx)
    return object_response(serialize_pa(pa), 200)


@bp.route("/prior-auth-requests/<rid>/expire-scan", methods=["POST"])
def expire_pa(rid):
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    with db.LOCK:
        pa = db.prior_auth_requests.get(rid)
        if pa is None:
            raise err("ERR_NOT_FOUND", "Prior-auth request not found")
        cur = parse_iso(db.current_utc())
        if pa["status"] == "PENDING" and cur > parse_iso(pa["expires_utc"]):
            pa["status"] = "EXPIRED"
            touch(pa)
            fill = db.fills.get(pa["fill_id"])
            if fill is not None:
                fill["claim_status"] = "REJECTED"
                fill["status"] = "CANCELLED"
                touch(fill)
                rx = db.prescriptions.get(fill["prescription_id"])
                if rx is not None:
                    domain.recompute_refills_remaining(rx)
    return object_response(serialize_pa(pa), 200)


# ===========================================================================
# PdmpReport
# ===========================================================================


def serialize_report(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "patient_id": r["patient_id"], "fill_id": r["fill_id"],
        "lookback_days": r["lookback_days"],
        "controlled_fill_count": r["controlled_fill_count"],
        "distinct_prescriber_count": r["distinct_prescriber_count"],
        "risk_score": r["risk_score"], "resulting_flag": r["resulting_flag"],
    }


@bp.route("/pdmp-reports", methods=["POST"])
def create_report():
    _uid, role = get_actor()
    require_roles(role, ["Pharmacist"])
    body = get_body()
    patient_id = as_string(require_field(body, "patient_id"), "patient_id")
    with db.LOCK:
        patient = db.patients.get(patient_id)
        if patient is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "patient_id does not reference a patient")
        report = domain.generate_pdmp_report(patient, None, variant="committed")
    return object_response(serialize_report(report), 201)


@bp.route("/pdmp-reports", methods=["GET"])
def list_reports():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin", "Pharmacist"])
    limit, offset = get_pagination()
    patient_id = request.args.get("patient_id")
    fill_id = request.args.get("fill_id")
    items = list(db.pdmp_reports.values())
    if patient_id is not None:
        items = [r for r in items if r["patient_id"] == patient_id]
    if fill_id is not None:
        items = [r for r in items if r["fill_id"] == fill_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_report(r) for r in page], limit, offset, total)


@bp.route("/pdmp-reports/<rid>", methods=["GET"])
def get_report(rid):
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin", "Pharmacist"])
    r = db.pdmp_reports.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "PDMP report not found")
    return object_response(serialize_report(r), 200)


# ===========================================================================
# PaymentRecord
# ===========================================================================


def serialize_payment(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "fill_id": p["fill_id"],
        "amount_cents": p["amount_cents"], "tendered_by": p["tendered_by"],
        "refunded": p["refunded"],
    }


@bp.route("/payment-records", methods=["POST"])
def create_payment():
    _uid, role = get_actor()
    require_roles(role, ["Cashier", "Technician"])
    body = get_body()
    fill_id = as_string(require_field(body, "fill_id"), "fill_id")
    amount = as_int(require_field(body, "amount_cents"), "amount_cents", minimum=0)
    tendered_by = as_string(require_field(body, "tendered_by"), "tendered_by")
    with db.LOCK:
        fill = db.fills.get(fill_id)
        if fill is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "fill_id does not reference a fill")
        rx = db.prescriptions[fill["prescription_id"]]
        patient = db.patients[rx["patient_id"]]
        # Insured: amount must equal final_copay_cents; cash: equal gross.
        if patient["plan_id"] is not None:
            owed = fill["final_copay_cents"]
        else:
            owed = fill["gross_amount_cents"]
        if owed is None or amount != owed:
            raise err("ERR_PAYMENT_AMOUNT_MISMATCH",
                      "amount_cents does not match the owed amount")
        payment = {
            "fill_id": fill_id, "amount_cents": amount,
            "tendered_by": tendered_by, "refunded": False,
        }
        stamp_create(payment)
        db.payment_records[payment["id"]] = payment
    return object_response(serialize_payment(payment), 201)


@bp.route("/payment-records", methods=["GET"])
def list_payments():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    fill_id = request.args.get("fill_id")
    items = list(db.payment_records.values())
    if fill_id is not None:
        items = [p for p in items if p["fill_id"] == fill_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_payment(p) for p in page], limit, offset, total)


@bp.route("/payment-records/<rid>", methods=["GET"])
def get_payment(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    p = db.payment_records.get(rid)
    if p is None:
        raise err("ERR_NOT_FOUND", "Payment record not found")
    return object_response(serialize_payment(p), 200)
