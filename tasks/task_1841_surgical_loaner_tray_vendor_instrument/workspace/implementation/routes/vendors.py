"""Vendor + VendorRep routes."""

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body, req_str, opt_int, req_enum, req_int
from response import success_object, success_list, parse_pagination
from services import core

bp = Blueprint("vendors", __name__)

ANY = ["VendorCoordinator", "ORScheduler", "SterileProcessingTech", "ORCirculatorNurse", "VendorRep"]
OR_ACCESS_LEVELS = {"NONE", "OBSERVER", "SCRUB_ASSIST"}


def _get_vendor_or_404(vendor_id):
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise_err("ERR_VENDOR_NOT_FOUND", "Vendor not found")
    return vendor


def _get_rep_or_404(rep_id):
    rep = db.reps.get(rep_id)
    if rep is None:
        raise_err("ERR_REP_NOT_FOUND", "Representative not found")
    return rep


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@bp.post("/vendors")
def create_vendor():
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["VendorCoordinator"])

    vendor_name = req_str(body, "vendor_name")
    vendor_code = req_str(body, "vendor_code")
    late_grace_minutes = opt_int(body, "late_grace_minutes", default=15, min_value=0)
    late_rate_per_hour_cents = req_int(body, "late_rate_per_hour_cents", min_value=1)
    late_penalty_cap_cents = req_int(body, "late_penalty_cap_cents", min_value=1)
    delay_surcharge_per_minute_cents = opt_int(
        body, "delay_surcharge_per_minute_cents", default=0, min_value=0
    )

    for v in db.vendors.values():
        if v["vendor_code"] == vendor_code:
            raise_err("ERR_DUPLICATE_VENDOR_CODE", "vendor_code already exists")

    vendor = {
        "vendor_name": vendor_name,
        "vendor_code": vendor_code,
        "status": "ACTIVE",
        "late_grace_minutes": late_grace_minutes,
        "late_rate_per_hour_cents": late_rate_per_hour_cents,
        "late_penalty_cap_cents": late_penalty_cap_cents,
        "delay_surcharge_per_minute_cents": delay_surcharge_per_minute_cents,
        "outstanding_penalty_cents": 0,
        "outstanding_liability_cents": 0,
    }
    core.stamp_new(vendor)
    db.vendors[vendor["id"]] = vendor
    return success_object(core.serialize(vendor), status=201)


@bp.get("/vendors")
def list_vendors():
    get_auth()
    status = flask_request.args.get("status")
    items = sorted(db.vendors.values(), key=lambda v: v["_seq"])
    if status:
        items = [v for v in items if v["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(v) for v in page], limit, offset, total)


@bp.get("/vendors/<id>")
def get_vendor(id):
    get_auth()
    vendor = _get_vendor_or_404(id)
    return success_object(core.serialize(vendor))


@bp.post("/vendors/<id>/suspend")
def suspend_vendor(id):
    _, role = get_auth()
    require_role(role, ["VendorCoordinator"])
    vendor = _get_vendor_or_404(id)
    if vendor["status"] != "ACTIVE":
        raise_err("ERR_VENDOR_NOT_ACTIVE", "Vendor is not ACTIVE")
    vendor["status"] = "SUSPENDED"
    core.touch(vendor)
    return success_object(core.serialize(vendor))


@bp.post("/vendors/<id>/reinstate")
def reinstate_vendor(id):
    _, role = get_auth()
    require_role(role, ["VendorCoordinator"])
    vendor = _get_vendor_or_404(id)
    if vendor["status"] != "SUSPENDED":
        raise_err("ERR_VENDOR_NOT_ACTIVE", "Vendor is not SUSPENDED")
    vendor["status"] = "ACTIVE"
    core.touch(vendor)
    return success_object(core.serialize(vendor))


@bp.post("/vendors/<id>/terminate")
def terminate_vendor(id):
    _, role = get_auth()
    require_role(role, ["VendorCoordinator"])
    vendor = _get_vendor_or_404(id)
    if vendor["status"] not in {"ACTIVE", "SUSPENDED"}:
        raise_err("ERR_VENDOR_NOT_ACTIVE", "Vendor is already TERMINATED")
    # Open-work guards
    for r in db.requests.values():
        if r["vendor_id"] == id and r["status"] in {"DRAFT", "SUBMITTED", "APPROVED"}:
            raise_err("ERR_VENDOR_HAS_OPEN_WORK", "Vendor has open loaner requests")
    vendor_request_ids = {r["id"] for r in db.requests.values() if r["vendor_id"] == id}
    for p in db.penalties.values():
        if p["request_id"] in vendor_request_ids and p["status"] in {"ACCRUING", "ASSESSED"}:
            raise_err("ERR_VENDOR_HAS_OPEN_WORK", "Vendor has open penalty assessments")
    for c in db.claims.values():
        if c["request_id"] in vendor_request_ids and c["status"] in {"FILED", "APPORTIONED", "DISPUTED"}:
            raise_err("ERR_VENDOR_HAS_OPEN_WORK", "Vendor has open damage/loss claims")
    vendor["status"] = "TERMINATED"
    core.touch(vendor)
    return success_object(core.serialize(vendor))


# ---------------------------------------------------------------------------
# VendorReps
# ---------------------------------------------------------------------------

@bp.post("/vendors/<vendorId>/reps")
def create_rep(vendorId):
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["VendorCoordinator"])
    vendor = _get_vendor_or_404(vendorId)

    full_name = req_str(body, "full_name")
    rep_email = req_str(body, "rep_email")
    credential_doc_ref = req_str(body, "credential_doc_ref")

    rep = {
        "vendor_id": vendor["id"],
        "full_name": full_name,
        "rep_email": rep_email,
        "credential_doc_ref": credential_doc_ref,
        "credential_status": "PENDING_VERIFICATION",
        "credential_expires_at": None,
        "or_access_level": None,
    }
    core.stamp_new(rep)
    db.reps[rep["id"]] = rep
    return success_object(core.serialize(rep), status=201)


@bp.get("/reps")
def list_reps():
    get_auth()
    vendor_id = flask_request.args.get("vendor_id")
    credential_status = flask_request.args.get("credential_status")
    items = sorted(db.reps.values(), key=lambda r: r["_seq"])
    if vendor_id:
        items = [r for r in items if r["vendor_id"] == vendor_id]
    if credential_status:
        items = [r for r in items if r["credential_status"] == credential_status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(r) for r in page], limit, offset, total)


@bp.get("/reps/<id>")
def get_rep(id):
    get_auth()
    rep = _get_rep_or_404(id)
    return success_object(core.serialize(rep))


@bp.post("/reps/<id>/approve-credential")
def approve_credential(id):
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["VendorCoordinator"])
    rep = _get_rep_or_404(id)

    credential_expires_at_raw = body.get("credential_expires_at")
    expires = db.parse_dt(credential_expires_at_raw)
    if expires is None:
        raise_err("ERR_VALIDATION", "credential_expires_at must be a valid ISO 8601 datetime")
    or_access_level = req_enum(body, "or_access_level", OR_ACCESS_LEVELS)

    if rep["credential_status"] not in {"PENDING_VERIFICATION", "EXPIRED", "ACTIVE"}:
        raise_err("ERR_REP_CREDENTIAL_NOT_ACTIVE", "Rep credential is REVOKED")
    if expires <= db.now_dt():
        raise_err("ERR_CREDENTIAL_EXPIRY_PAST", "credential_expires_at must be in the future")

    rep["credential_status"] = "ACTIVE"
    rep["credential_expires_at"] = db.fmt_ts(expires)
    rep["or_access_level"] = or_access_level
    core.touch(rep)
    return success_object(core.serialize(rep))


@bp.post("/reps/<id>/revoke-credential")
def revoke_credential(id):
    _, role = get_auth()
    require_role(role, ["VendorCoordinator"])
    rep = _get_rep_or_404(id)

    if rep["credential_status"] not in {"PENDING_VERIFICATION", "ACTIVE", "EXPIRED"}:
        raise_err("ERR_REP_CREDENTIAL_NOT_ACTIVE", "Rep credential is already REVOKED")
    rep["credential_status"] = "REVOKED"
    core.touch(rep)

    # Cascade: passes REQUESTED -> DENIED (reason credential_revoked);
    # APPROVED -> REVOKED.
    for p in db.access_passes.values():
        if p["rep_id"] != id:
            continue
        if p["status"] == "REQUESTED":
            p["status"] = "DENIED"
            p["denial_reason"] = "credential_revoked"
            core.touch(p)
        elif p["status"] == "APPROVED":
            p["status"] = "REVOKED"
            core.touch(p)
    return success_object(core.serialize(rep))
