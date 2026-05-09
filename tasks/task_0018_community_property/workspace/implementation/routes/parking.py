"""Parking spaces, applications, and access logs."""
from __future__ import annotations

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OWNER_DELINQUENT,
    ERR_PARKING_KIND_MISMATCH,
    ERR_PARKING_QUOTA_EXCEEDED,
    ERR_PARKING_SPACE_TAKEN,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.common import bump, stamp_create
from services.fees import issue_parking_first_bill
from utils import get_body, iso_format, parse_iso, require_field, to_decimal
from routes.residents import _owner_is_delinquent

bp = Blueprint("parking", __name__)

VALID_KINDS = {"FIXED", "TEMPORARY", "VISITOR"}
VALID_DIRECTIONS = {"ENTRY", "EXIT"}


# ---------------------------------------------------------------------------
# Parking spaces
# ---------------------------------------------------------------------------
@bp.post("/parking-spaces")
@require_roles("PropertyManager")
def create_space():
    body = get_body()
    space_no = require_field(body, "space_no")
    kind = require_field(body, "kind")
    monthly_fee = body.get("monthly_fee", 0)

    if kind not in VALID_KINDS:
        raise APIError(ERR_VALIDATION, "Invalid kind.", 422)
    fee_d = to_decimal(monthly_fee)
    if fee_d < 0:
        raise APIError(ERR_VALIDATION, "monthly_fee must be >= 0.", 422)

    for s in db.parking_spaces.values():
        if s.get("space_no") == space_no:
            raise APIError(ERR_VALIDATION, "space_no already exists.", 422)

    space = {
        "space_no": space_no,
        "kind": kind,
        "monthly_fee": float(fee_d),
        "status": "AVAILABLE",
    }
    stamp_create(space)
    db.parking_spaces[space["id"]] = space
    return success(space, status=201)


# ---------------------------------------------------------------------------
# Parking applications
# ---------------------------------------------------------------------------
@bp.post("/parking-applications")
@require_roles("Owner")
def apply_for_parking():
    body = get_body()
    property_id = require_field(body, "property_id")
    requested_kind = require_field(body, "requested_kind")
    license_plate = require_field(body, "license_plate")

    if requested_kind not in VALID_KINDS:
        raise APIError(ERR_VALIDATION, "Invalid requested_kind.", 422)
    prop = db.properties.get(property_id)
    if prop is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"Property {property_id} not found.", 404)
    if prop.get("owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Owner does not own this property.", 403)

    if _owner_is_delinquent(g.user_id):
        raise APIError(ERR_OWNER_DELINQUENT, "Owner has overdue bills.", 403)

    app = {
        "owner_id": g.user_id,
        "property_id": property_id,
        "requested_kind": requested_kind,
        "license_plate": license_plate,
        "status": "PENDING",
        "allocated_space_id": None,
        "started_at": None,
    }
    stamp_create(app)
    db.parking_applications[app["id"]] = app
    return success(app, status=201)


@bp.post("/parking-applications/<aid>/approve")
@require_roles("PropertyManager")
def approve(aid):
    app = db.parking_applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, f"Application {aid} not found.", 404)
    body = get_body()
    allocated_space_id = require_field(body, "allocated_space_id")

    if app["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, "Application is not PENDING.", 409)

    space = db.parking_spaces.get(allocated_space_id)
    if space is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"ParkingSpace {allocated_space_id} not found.", 404)

    with db.mutation_lock:
        # Validation order per PRD §3.9:
        # 1. quota (only for FIXED)
        if app["requested_kind"] == "FIXED":
            prop = db.properties.get(app["property_id"])
            quota = int(prop.get("parking_quota", 0)) if prop else 0
            current = sum(
                1 for a in db.parking_applications.values()
                if a.get("status") == "APPROVED"
                and a.get("property_id") == app["property_id"]
                and a.get("requested_kind") == "FIXED"
            )
            if current >= quota:
                raise APIError(ERR_PARKING_QUOTA_EXCEEDED, "Parking quota exceeded.", 422)

        # 2. kind mismatch
        if space.get("kind") != app["requested_kind"]:
            raise APIError(ERR_PARKING_KIND_MISMATCH, "Space kind does not match requested kind.", 422)

        # 3. space available
        if space.get("status") != "AVAILABLE":
            raise APIError(ERR_PARKING_SPACE_TAKEN, "Parking space is not available.", 409)

        # 4. owner not delinquent
        owner = db.owners.get(app["owner_id"])
        if owner is not None and owner.get("voting_status") == "INELIGIBLE_DELINQUENT":
            raise APIError(ERR_FORBIDDEN, "Delinquent owner cannot receive a fixed allocation.", 403)

        now = db.now()
        app["allocated_space_id"] = allocated_space_id
        app["started_at"] = iso_format(now)
        app["status"] = "APPROVED"
        bump(app)

        space["status"] = "ALLOCATED"
        bump(space)

        # FIXED kind: schedule first prorated bill
        if app["requested_kind"] == "FIXED":
            prop = db.properties.get(app["property_id"])
            if prop is not None:
                issue_parking_first_bill(prop=prop, parking_space=space, started_at=now)
    return success(app)


@bp.post("/parking-applications/<aid>/reject")
@require_roles("PropertyManager")
def reject(aid):
    app = db.parking_applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, f"Application {aid} not found.", 404)
    body = get_body()
    rejection_reason = require_field(body, "rejection_reason")
    if app["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, "Application is not PENDING.", 409)
    app["status"] = "REJECTED"
    app["rejection_reason"] = rejection_reason
    bump(app)
    return success(app)


@bp.post("/parking-applications/<aid>/terminate")
@require_roles("PropertyManager")
def terminate(aid):
    app = db.parking_applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, f"Application {aid} not found.", 404)
    if app["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, "Application is not APPROVED.", 409)
    space = db.parking_spaces.get(app.get("allocated_space_id"))
    if space is not None:
        space["status"] = "AVAILABLE"
        bump(space)
    app["status"] = "TERMINATED"
    bump(app)
    return success(app)


# ---------------------------------------------------------------------------
# Access logs (gate ingestion)
# ---------------------------------------------------------------------------
@bp.post("/access-logs")
@require_roles("PropertyManager")
def ingest_access_log():
    body = get_body()
    license_plate = require_field(body, "license_plate")
    direction = require_field(body, "direction")
    occurred_at = require_field(body, "occurred_at")

    if direction not in VALID_DIRECTIONS:
        raise APIError(ERR_VALIDATION, "Invalid direction.", 422)
    occ_dt = parse_iso(occurred_at, field="occurred_at")

    # Resolve binding: APPROVED applications whose plate matches and started_at <= occurred_at.
    matched_app = None
    matched_space = None
    for a in db.parking_applications.values():
        if a.get("status") != "APPROVED":
            continue
        if a.get("license_plate") != license_plate:
            continue
        started_str = a.get("started_at")
        if not started_str:
            continue
        if parse_iso(started_str, field="started_at") > occ_dt:
            continue
        space = db.parking_spaces.get(a.get("allocated_space_id"))
        if space is None:
            continue
        if space.get("kind") in ("FIXED", "TEMPORARY"):
            matched_app = a
            matched_space = space
            break
        if space.get("kind") == "VISITOR" and matched_app is None:
            matched_app = a
            matched_space = space

    if matched_app is None:
        classification = "UNAUTHORIZED"
        parking_space_id = None
    elif matched_space.get("kind") == "VISITOR":
        classification = "VISITOR_OK"
        parking_space_id = matched_space["id"]
    else:
        classification = "BOUND"
        parking_space_id = matched_space["id"]

    log = {
        "id": db.new_id(),
        "created_at": iso_format(db.now()),
        "license_plate": license_plate,
        "direction": direction,
        "occurred_at": iso_format(occ_dt),
        "parking_space_id": parking_space_id,
        "classification": classification,
    }
    db.access_logs[log["id"]] = log
    return success(log, status=201)
