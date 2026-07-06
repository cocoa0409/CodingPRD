"""Violation lifecycle: report, confirm, fine, appeal, adjudicate, resolve."""

from datetime import timedelta

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now, get_now_iso, sweep_time_transitions
from entities import bump, new_violation
from errors import raise_error
from response import success
from services import homeowner as homeowner_svc
from utils import (paginate, parse_iso, require_enum, require_fields,
                   require_int, require_str, require_json)

bp = Blueprint("violations", __name__)


# ---------------- Report ---------------- #

@bp.route("/violations", methods=["POST"])
@require_role("ComplianceOfficer", "HOAManager", "BoardMember")
def report_violation():
    body = require_json(request)
    require_fields(body, "property_id", "category")
    property_id = require_str(body, "property_id")
    category = require_enum(body, "category", {"NUISANCE", "LANDSCAPE", "STRUCTURAL", "SAFETY"})

    if property_id not in db.properties:
        raise_error("ERR_FK_NOT_FOUND", "property_id does not resolve")

    now_iso = get_now_iso()
    row = new_violation(property_id, category, now_iso)
    db.violations[row["id"]] = row
    return success(row, status=201)


@bp.route("/violations/<vid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager", "ComplianceOfficer")
def get_violation(vid):
    sweep_time_transitions()
    v = db.violations.get(vid)
    if not v:
        raise_error("ERR_NOT_FOUND", "violation not found")
    return success(v)


# ---------------- Confirm ---------------- #

@bp.route("/violations/<vid>/confirm", methods=["POST"])
@require_role("ComplianceOfficer")
def confirm_violation(vid):
    require_json(request)
    v = db.violations.get(vid)
    if not v:
        raise_error("ERR_NOT_FOUND", "violation not found")
    if v["status"] != "REPORTED":
        raise_error("ERR_INVALID_STATE", "violation must be REPORTED to confirm")
    v["status"] = "CONFIRMED"
    bump(v, get_now_iso())
    return success(v)


# ---------------- Fine ---------------- #

@bp.route("/violations/<vid>/fine", methods=["POST"])
@require_role("ComplianceOfficer")
def fine_violation(vid):
    body = require_json(request)
    # PRD §2.8: malformed payloads are 400 "before the sequence begins".
    require_fields(body, "fine_amount_cents")
    amount = require_int(body, "fine_amount_cents", minimum=2500, maximum=500000)
    v = db.violations.get(vid)
    if not v:
        raise_error("ERR_NOT_FOUND", "violation not found")
    if v["status"] != "CONFIRMED":
        raise_error("ERR_INVALID_STATE", "violation must be CONFIRMED to fine")
    now_iso = get_now_iso()
    v["fine_amount_cents"] = amount
    v["fine_balance_cents"] = amount
    v["fined_at"] = now_iso
    v["status"] = "FINED"
    bump(v, now_iso)
    # Cascade: Property.fine_balance_cents + total_outstanding_cents.
    homeowner_svc.recompute_owner_and_property(v["property_id"], now_iso)
    return success(v)


# ---------------- Appeal ---------------- #

@bp.route("/violations/<vid>/appeal", methods=["POST"])
@require_role("Homeowner")
def appeal_violation(vid):
    require_json(request)
    sweep_time_transitions()
    v = db.violations.get(vid)
    if not v:
        raise_error("ERR_NOT_FOUND", "violation not found")

    if v["status"] != "FINED":
        raise_error("ERR_INVALID_STATE", "violation must be FINED to appeal")

    # Priority 13 gate — SAFETY non-appealable.
    if v["category"] == "SAFETY":
        raise_error("ERR_APPEAL_NON_APPEALABLE", "safety fines are non-appealable")

    # Priority 17 gate — appeal window.
    fined_at = parse_iso(v["fined_at"])
    if get_now() > fined_at + timedelta(days=14):
        raise_error("ERR_APPEAL_WINDOW_EXPIRED", "appeal window has expired")

    v["status"] = "APPEALED"
    bump(v, get_now_iso())
    return success(v)


# ---------------- Adjudicate ---------------- #

@bp.route("/violations/<vid>/adjudicate", methods=["POST"])
@require_role("ComplianceOfficer")
def adjudicate_violation(vid):
    body = require_json(request)
    require_fields(body, "outcome")
    outcome = require_enum(body, "outcome", {"UPHOLD", "OVERTURN"})
    v = db.violations.get(vid)
    if not v:
        raise_error("ERR_NOT_FOUND", "violation not found")
    if v["status"] != "APPEALED":
        raise_error("ERR_INVALID_STATE", "violation must be APPEALED to adjudicate")
    now_iso = get_now_iso()
    if outcome == "UPHOLD":
        v["status"] = "UPHELD"
    else:
        v["status"] = "OVERTURNED"
        v["fine_balance_cents"] = 0
    bump(v, now_iso)
    homeowner_svc.recompute_owner_and_property(v["property_id"], now_iso)
    return success(v)


# ---------------- Resolve (cure) ---------------- #

@bp.route("/violations/<vid>/resolve", methods=["POST"])
@require_role("ComplianceOfficer")
def resolve_violation(vid):
    body = require_json(request)
    require_fields(body, "outcome")
    outcome = require_enum(body, "outcome", {"CURED"})
    v = db.violations.get(vid)
    if not v:
        raise_error("ERR_NOT_FOUND", "violation not found")
    if v["status"] != "CONFIRMED":
        raise_error("ERR_INVALID_STATE", "violation must be CONFIRMED to resolve")
    v["status"] = "CURED"
    bump(v, get_now_iso())
    return success(v)
