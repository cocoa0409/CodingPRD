"""Dispute endpoints: raise, investigate, resolve, reopen (cyclic)."""
from flask import Blueprint, request

from clock import clock, format_iso8601
from db import db, stamp_create, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import object_response, array_response
from serializers import serialize_dispute
from pagination import paginate
from validation import get_body, require_enum
from services.accounts import validation_deadline_dt
from services.transitions import close_account_uncollectible_via_dispute

bp = Blueprint("disputes", __name__)

DISPUTE_TYPES = {"VALIDATION", "ACCURACY"}
RESOLUTIONS = {"VERIFIED", "DELETED"}


def _within_window(account):
    deadline = validation_deadline_dt(account)
    if deadline is None:
        return False
    return clock.now < deadline


@bp.route("/accounts/<aid>/disputes", methods=["POST"])
@require_roles("ComplianceOfficer")
def raise_dispute(aid):
    account = db.accounts.get(aid)
    if account is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    body = get_body()
    dispute_type = require_enum(body, "dispute_type", DISPUTE_TYPES)
    within = _within_window(account)
    d = stamp_create({
        "account_id": aid,
        "dispute_type": dispute_type,
        "raised_at": format_iso8601(clock.now),
        "within_validation_window": within,
        "resolution": None,
        "status": "OPEN",
    })
    db.disputes[d["id"]] = d
    # If VALIDATION and in-window: push account contact_status -> VALIDATION_HELD.
    if dispute_type == "VALIDATION" and within:
        if account["contact_status"] == "CONTACTABLE":
            account["contact_status"] = "VALIDATION_HELD"
            touch(account)
    return object_response(serialize_dispute(d), status=201)


@bp.route("/disputes/<did>", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "System")
def get_dispute(did):
    d = db.disputes.get(did)
    if d is None:
        raise ApiError(*ERR_NOT_FOUND, message="Dispute not found")
    return object_response(serialize_dispute(d), status=200)


@bp.route("/disputes", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "System")
def list_disputes():
    items = list(db.disputes.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id:
        items = [d for d in items if d["account_id"] == account_id]
    if status:
        items = [d for d in items if d["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_dispute(d) for d in page], limit, offset, total)


@bp.route("/disputes/<did>/investigate", methods=["POST"])
@require_roles("ComplianceOfficer")
def investigate(did):
    d = db.disputes.get(did)
    if d is None:
        raise ApiError(*ERR_NOT_FOUND, message="Dispute not found")
    if d["status"] != "OPEN":
        raise ApiError(*ERR_INVALID_STATE, message="Dispute is not OPEN")
    d["status"] = "INVESTIGATING"
    touch(d)
    return object_response(serialize_dispute(d), status=200)


@bp.route("/disputes/<did>/resolve", methods=["POST"])
@require_roles("ComplianceOfficer")
def resolve(did):
    d = db.disputes.get(did)
    if d is None:
        raise ApiError(*ERR_NOT_FOUND, message="Dispute not found")
    # state: resolve defined from OPEN, INVESTIGATING, REOPENED.
    if d["status"] not in ("OPEN", "INVESTIGATING", "REOPENED"):
        raise ApiError(*ERR_INVALID_STATE, message="Dispute cannot be resolved from its current state")
    body = get_body()
    resolution = require_enum(body, "resolution", RESOLUTIONS)
    d["status"] = "RESOLVED"
    d["resolution"] = resolution
    touch(d)
    account = db.accounts.get(d["account_id"])
    if resolution == "VERIFIED":
        if d["dispute_type"] == "VALIDATION" and account and account["contact_status"] == "VALIDATION_HELD":
            account["contact_status"] = "CONTACTABLE"
            touch(account)
    else:  # DELETED
        if account and account["work_status"] not in ("CLOSED_PAID", "CLOSED_UNCOLLECTIBLE"):
            close_account_uncollectible_via_dispute(account)
    return object_response(serialize_dispute(d), status=200)


@bp.route("/disputes/<did>/reopen", methods=["POST"])
@require_roles("ComplianceOfficer")
def reopen(did):
    d = db.disputes.get(did)
    if d is None:
        raise ApiError(*ERR_NOT_FOUND, message="Dispute not found")
    if d["status"] != "RESOLVED":
        raise ApiError(*ERR_INVALID_STATE, message="Only a RESOLVED dispute can be reopened")
    d["status"] = "REOPENED"
    d["resolution"] = None
    touch(d)
    account = db.accounts.get(d["account_id"])
    if d["dispute_type"] == "VALIDATION" and d["within_validation_window"] and account:
        if account["contact_status"] == "CONTACTABLE":
            account["contact_status"] = "VALIDATION_HELD"
            touch(account)
    return object_response(serialize_dispute(d), status=200)
