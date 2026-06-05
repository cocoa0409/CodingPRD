"""Referral endpoints and authorization windows (PRD §3.8)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

import db
from db import format_iso, parse_iso, stamp_create, touch
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_NO_PCP_BOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REFERRAL_EXPIRED,
)
from middleware import require
from response import ok_array, ok_object
from routes.common import lookup_or_404, paginate, parse_pagination, sort_by_created
from services import derive
from validation import get_body, optional_enum, require_enum, require_str

bp = Blueprint("referrals", __name__)

TARGET_SPECIALTIES = {"CARDIOLOGY", "DERMATOLOGY", "ORTHOPEDICS", "ENDOCRINOLOGY"}
PRIORITIES = {"ROUTINE", "URGENT"}
ROUTINE_AUTH_DAYS = 90
URGENT_AUTH_DAYS = 14


@bp.route("/referrals", methods=["POST"])
def create_referral():
    require(["Provider"])
    body = get_body()

    # Priority 4: body FK existence (patient_id, referring_provider_id).
    pid_raw = body.get("patient_id")
    prov_raw = body.get("referring_provider_id")
    if isinstance(pid_raw, str) and pid_raw not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")
    if isinstance(prov_raw, str) and prov_raw not in db.providers:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "referring_provider_id does not resolve")

    patient_id = require_str(body, "patient_id")
    referring_provider_id = require_str(body, "referring_provider_id")
    target_specialty = require_enum(body, "target_specialty", TARGET_SPECIALTIES)
    priority = optional_enum(body, "priority", PRIORITIES, default="ROUTINE")

    if patient_id not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")
    if referring_provider_id not in db.providers:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "referring_provider_id does not resolve")

    rec = stamp_create({
        "patient_id": patient_id,
        "referring_provider_id": referring_provider_id,
        "target_specialty": target_specialty,
        "priority": priority,
        "status": "REQUESTED",
        "authorization_expires_at": None,
    })
    db.referrals[rec["id"]] = rec
    return ok_object(derive.serialize_referral(rec), 201)


@bp.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    require(["Provider", "FrontDesk", "Patient"])
    rec = lookup_or_404(db.referrals, rid, "Referral")
    if g.user_role == "Patient" and g.user_id != rec["patient_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Patient may only read own referrals")
    return ok_object(derive.serialize_referral(rec), 200)


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    require(["Provider", "FrontDesk"])
    limit, offset = parse_pagination()
    items = list(db.referrals.values())
    for key in ("patient_id", "referring_provider_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_referral(r) for r in window], limit, offset, total)


@bp.route("/referrals/<rid>/authorize", methods=["POST"])
def authorize_referral(rid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.referrals, rid, "Referral")
    if rec["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Referral is not REQUESTED")
    # Priority 11: patient must have a bound PCP.
    patient = db.patients.get(rec["patient_id"])
    if not patient or patient.get("pcp_id") is None:
        raise APIError(ERR_NO_PCP_BOUND, 409, "Patient has no bound PCP")

    days = URGENT_AUTH_DAYS if rec["priority"] == "URGENT" else ROUTINE_AUTH_DAYS
    expires = db.clock.now() + timedelta(days=days)
    rec["authorization_expires_at"] = format_iso(expires)
    rec["status"] = "AUTHORIZED"
    touch(rec)
    return ok_object(derive.serialize_referral(rec), 200)


@bp.route("/referrals/<rid>/deny", methods=["POST"])
def deny_referral(rid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.referrals, rid, "Referral")
    if rec["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Referral is not REQUESTED")
    rec["status"] = "DENIED"
    touch(rec)
    return ok_object(derive.serialize_referral(rec), 200)


@bp.route("/referrals/<rid>/schedule", methods=["POST"])
def schedule_referral(rid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.referrals, rid, "Referral")
    if rec["status"] != "AUTHORIZED":
        raise APIError(ERR_INVALID_STATE, 409, "Referral is not AUTHORIZED")
    # Priority 15: scheduling requires clock strictly before expiry.
    expires = parse_iso(rec["authorization_expires_at"])
    if db.clock.now() >= expires:
        raise APIError(ERR_REFERRAL_EXPIRED, 409, "Referral authorization window has elapsed")
    rec["status"] = "SCHEDULED"
    touch(rec)
    return ok_object(derive.serialize_referral(rec), 200)


@bp.route("/referrals/<rid>/expire", methods=["POST"])
def expire_referral(rid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.referrals, rid, "Referral")
    if rec["status"] != "AUTHORIZED":
        raise APIError(ERR_INVALID_STATE, 409, "Referral is not AUTHORIZED")
    # Requires clock to have reached/passed expiry.
    expires = parse_iso(rec["authorization_expires_at"])
    if db.clock.now() < expires:
        raise APIError(ERR_INVALID_STATE, 409, "Authorization window has not yet elapsed")
    rec["status"] = "EXPIRED"
    touch(rec)
    return ok_object(derive.serialize_referral(rec), 200)


@bp.route("/referrals/<rid>/complete", methods=["POST"])
def complete_referral(rid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.referrals, rid, "Referral")
    if rec["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Referral is not SCHEDULED")
    rec["status"] = "COMPLETED"
    touch(rec)
    return ok_object(derive.serialize_referral(rec), 200)


@bp.route("/referrals/<rid>/cancel", methods=["POST"])
def cancel_referral(rid):
    require(["Provider"])
    rec = lookup_or_404(db.referrals, rid, "Referral")
    if rec["status"] not in ("REQUESTED", "AUTHORIZED"):
        raise APIError(ERR_INVALID_STATE, 409, "Referral cannot be cancelled from its state")
    # Priority 7: only the referring provider may cancel.
    if g.user_id != rec["referring_provider_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Only the referring provider may cancel")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(derive.serialize_referral(rec), 200)
