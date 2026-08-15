"""Safety audit request endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, require_fields, get_str, get_enum, get_datetime, get_list, touch,
)
from services.serializers import safety_audit_view

bp = Blueprint("safety_audits", __name__)


AUDIT_TYPES = ("DOT_COMPLIANCE", "SAFETY_RATING", "INSURANCE_VERIFICATION", "FULL_OPERATIONAL")
RATINGS = ("SATISFACTORY", "CONDITIONAL", "UNSATISFACTORY")


@bp.route("/api/v1/safety-audits", methods=["POST"])
def create_audit():
    user_id, role = require_roles("Customer", "SafetyOfficer")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, "customer_id", "audit_type", "requested_date")
    customer_id = get_str(payload, "customer_id", required=True)
    audit_type = get_enum(payload, "audit_type", AUDIT_TYPES, required=True)
    requested_date = get_datetime(payload, "requested_date", required=True)

    if db.customers.get(customer_id) is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")
    if role == "Customer" and user_id != customer_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only request audits for themselves")

    aid = db.new_id()
    now = db.iso_now()
    a = {
        "id": aid,
        "customer_id": customer_id,
        "audit_type": audit_type,
        "status": "REQUESTED",
        "requested_date": db.to_iso(requested_date),
        "completed_date": None,
        "auditor_notes": None,
        "findings": [],
        "overall_rating": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.safety_audits[aid] = a
    return success_object(safety_audit_view(a), status=201)


@bp.route("/api/v1/safety-audits", methods=["GET"])
def list_audits():
    require_roles("SafetyOfficer", "PlatformAdmin")
    limit, offset = get_pagination()
    status = request.args.get("status")
    customer_id = request.args.get("customer_id")
    items = sorted(db.safety_audits.values(), key=lambda x: x["created_at"])
    if status:
        items = [a for a in items if a.get("status") == status]
    if customer_id:
        items = [a for a in items if a.get("customer_id") == customer_id]
    page, total = paginate(items, limit, offset)
    return success_list([safety_audit_view(a) for a in page], limit, offset, total)


@bp.route("/api/v1/safety-audits/<aid>", methods=["GET"])
def get_audit(aid):
    require_roles("SafetyOfficer", "PlatformAdmin")
    a = db.safety_audits.get(aid)
    if a is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "audit not found")
    return success_object(safety_audit_view(a))


@bp.route("/api/v1/safety-audits/<aid>/begin-review", methods=["POST"])
def begin_review(aid):
    require_roles("SafetyOfficer")
    a = db.safety_audits.get(aid)
    if a is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "audit not found")
    if a["status"] != "REQUESTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"audit is in state {a['status']}, cannot begin review")
    a["status"] = "IN_REVIEW"
    touch(a)
    return success_object(safety_audit_view(a))


@bp.route("/api/v1/safety-audits/<aid>/approve", methods=["POST"])
def approve_audit(aid):
    require_roles("SafetyOfficer")
    a = db.safety_audits.get(aid)
    if a is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "audit not found")
    if a["status"] != "IN_REVIEW":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"audit is in state {a['status']}, cannot approve")
    payload = request.get_json(silent=True) or {}
    overall_rating = payload.get("overall_rating")
    if overall_rating not in ("SATISFACTORY", "CONDITIONAL"):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "overall_rating must be SATISFACTORY or CONDITIONAL")
    notes = payload.get("notes")
    if notes is None:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "notes is required")
    findings = get_list(payload, "findings", default=[]) or []

    a["overall_rating"] = overall_rating
    a["auditor_notes"] = notes
    a["findings"] = findings
    a["status"] = "APPROVED"
    touch(a)
    return success_object(safety_audit_view(a))


@bp.route("/api/v1/safety-audits/<aid>/reject", methods=["POST"])
def reject_audit(aid):
    require_roles("SafetyOfficer")
    a = db.safety_audits.get(aid)
    if a is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "audit not found")
    if a["status"] != "IN_REVIEW":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"audit is in state {a['status']}, cannot reject")
    payload = request.get_json(silent=True) or {}
    notes = payload.get("notes")
    if notes is None:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "notes is required")
    findings = get_list(payload, "findings", default=[]) or []

    a["overall_rating"] = "UNSATISFACTORY"
    a["auditor_notes"] = notes
    a["findings"] = findings
    a["status"] = "REJECTED"
    touch(a)

    # Suspend customer
    customer = db.customers.get(a["customer_id"])
    if customer:
        customer["credit_status"] = "SUSPENDED"
        touch(customer)

    return success_object(safety_audit_view(a))


@bp.route("/api/v1/safety-audits/<aid>/finalize", methods=["POST"])
def finalize_audit(aid):
    require_roles("SafetyOfficer")
    a = db.safety_audits.get(aid)
    if a is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "audit not found")
    if a["status"] != "APPROVED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"audit is in state {a['status']}, cannot finalize")
    a["completed_date"] = db.iso_now()
    a["status"] = "COMPLETED"
    touch(a)
    return success_object(safety_audit_view(a))
