"""Vendor lifecycle endpoints (PRD §3.2, §3.5, §3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import clock
import config as C
import envelope
import models
import services
import validators
from auth import authenticate, check_vendor_scope
from errors import ApiError
from routes.common import listing, need
from store import db, ordered

bp = Blueprint("vendors", __name__)

STAFF_ROLES = (C.ROLE_ANALYST, C.ROLE_SUPERVISOR, C.ROLE_INVESTIGATOR)


@bp.post("/vendors")
def create_vendor():
    authenticate(C.ROLE_ANALYST)
    payload = validators.body()
    store_name = validators.req_string(payload, "store_name")
    store_type = validators.req_enum(payload, "store_type", C.STORE_TYPES)
    volume = validators.req_int(payload, "reported_monthly_redemption_cents", minimum=0)
    record = models.vendor(
        store_name=store_name,
        store_type=store_type,
        reported_monthly_redemption_cents=volume,
    )
    db.vendors[record["id"]] = record
    return envelope.success(record, 201)


@bp.get("/vendors/<entity_id>")
def read_vendor(entity_id):
    caller = authenticate(*STAFF_ROLES, C.ROLE_VENDOR_OPERATOR)
    check_vendor_scope(caller, entity_id)
    return envelope.success(need(db.vendors, entity_id, "ERR_VENDOR_NOT_FOUND"))


@bp.get("/vendors")
def list_vendors():
    authenticate(*STAFF_ROLES)
    return listing(
        ordered(db.vendors),
        {
            "peer_group_id": "peer_group_id",
            "authorization_status": "authorization_status",
            "risk_tier": "risk_tier",
        },
    )


@bp.get("/vendors/<entity_id>/risk-profile")
def risk_profile(entity_id):
    authenticate(*STAFF_ROLES)
    vendor = need(db.vendors, entity_id, "ERR_VENDOR_NOT_FOUND")
    basis = request.args.get("basis")
    if basis is None:
        basis = "ROLLING"
    if basis not in ("ROLLING", "EPOCH"):
        raise validators.invalid("Query parameter 'basis' must be ROLLING or EPOCH.")

    if basis == "EPOCH":
        window_end = vendor["risk_epoch_at"]
        if window_end is None:
            body = {
                "vendor_id": vendor["id"],
                "basis": basis,
                "window_start": None,
                "window_end": None,
                "evaluated_line_count": 0,
                "evaluated_visit_count": 0,
                "edit_rejection_rate_pct": Decimal("0.0"),
                "price_excess_pct": Decimal("0.0"),
                "failed_visit_pct": Decimal("0.0"),
                "sanction_points": vendor["sanction_points"],
                "risk_score": vendor["risk_score"],
                "risk_tier": vendor["risk_tier"],
            }
            return envelope.success(body)
    else:
        window_end = clock.now()

    components = calc.risk_components(vendor, window_end)
    body = {"vendor_id": vendor["id"], "basis": basis}
    body.update(components)
    return envelope.success(body)


@bp.post("/vendors/<entity_id>/record-training")
def record_training(entity_id):
    authenticate(C.ROLE_ANALYST)
    vendor = need(db.vendors, entity_id, "ERR_VENDOR_NOT_FOUND")
    payload = validators.body()
    training_type = validators.req_enum(payload, "training_type", C.TRAINING_TYPES)
    completed_at = validators.req_instant(payload, "completed_at")
    services.update(
        vendor,
        training_type=training_type,
        training_completed_at=completed_at,
        training_expires_at=clock.add_months(completed_at, C.TRAINING_VALID_MONTHS),
    )
    return envelope.success(vendor)


@bp.post("/vendors/<entity_id>/submit-application")
def submit_application(entity_id):
    authenticate(C.ROLE_ANALYST)
    vendor = need(db.vendors, entity_id, "ERR_VENDOR_NOT_FOUND")
    if vendor["authorization_status"] != "APPLICANT":
        raise ApiError("ERR_INVALID_VENDOR_STATE")
    if services.disqualification_live(vendor):
        raise ApiError("ERR_VENDOR_DISQUALIFIED")
    candidates = calc.peer_group_candidates(vendor)
    if not candidates:
        raise ApiError("ERR_NO_PEER_GROUP_MATCH")
    services.update(
        vendor,
        authorization_status="IN_REVIEW",
        peer_group_id=candidates[0]["id"],
        authorization_blocked_reason=None,
    )
    services.refresh_completeness(vendor)
    return envelope.success(vendor)


@bp.post("/vendors/<entity_id>/authorize")
def authorize_vendor(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    vendor = need(db.vendors, entity_id, "ERR_VENDOR_NOT_FOUND")
    if vendor["authorization_status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_VENDOR_STATE")
    if not services.training_current(vendor):
        raise ApiError("ERR_VENDOR_TRAINING_EXPIRED")
    if services.has_open_case(vendor["id"]):
        raise ApiError("ERR_OPEN_SANCTION_CASE_EXISTS")
    peer_group = db.peer_groups.get(vendor["peer_group_id"]) if vendor["peer_group_id"] else None
    if peer_group is None or peer_group["status"] != "ACTIVE":
        raise ApiError("ERR_PEER_GROUP_RETIRED")
    # PRD §3.5 authorize reads the stored readiness flag; unlike
    # complete-reauthorization it is not stated to recompute it here.
    if not vendor["price_submission_complete"]:
        raise ApiError("ERR_PRICE_SUBMISSIONS_INCOMPLETE")

    now = clock.now()
    services.update(
        vendor,
        authorization_status="AUTHORIZED",
        authorized_at=now,
        reauthorization_due_at=clock.add_months(now, C.REAUTH_CYCLE_MONTHS),
        authorization_blocked_reason=None,
    )
    services.sync_member_count(vendor["peer_group_id"])
    services.refresh_avg_redemption(vendor)
    return envelope.success(vendor)


@bp.post("/vendors/<entity_id>/deny")
def deny_vendor(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    vendor = need(db.vendors, entity_id, "ERR_VENDOR_NOT_FOUND")
    payload = validators.body()
    reason = validators.req_string(payload, "denial_reason")
    if vendor["authorization_status"] not in ("IN_REVIEW", "REAUTH_PENDING"):
        raise ApiError("ERR_INVALID_VENDOR_STATE")
    services.update(vendor, authorization_status="DENIED", denial_reason=reason)
    services.sync_member_count(vendor["peer_group_id"])
    services.void_open_submissions(vendor, "VENDOR_DISQUALIFIED")
    return envelope.success(vendor)


@bp.post("/vendors/<entity_id>/start-reauthorization")
def start_reauthorization(entity_id):
    authenticate(C.ROLE_ANALYST)
    vendor = need(db.vendors, entity_id, "ERR_VENDOR_NOT_FOUND")
    if vendor["authorization_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_VENDOR_STATE")
    due = vendor["reauthorization_due_at"]
    if due is None or clock.now() < clock.add_days(due, -C.REAUTH_WINDOW_DAYS):
        raise ApiError("ERR_REAUTH_WINDOW_NOT_OPEN")
    services.update(
        vendor,
        authorization_status="REAUTH_PENDING",
        reauth_blocked_reason=(
            C.REASON_PENDING_COMPLIANCE_BUY if vendor["reauthorization_hold"] else None
        ),
    )
    services.refresh_completeness(vendor)
    return envelope.success(vendor)


@bp.post("/vendors/<entity_id>/complete-reauthorization")
def complete_reauthorization(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    vendor = need(db.vendors, entity_id, "ERR_VENDOR_NOT_FOUND")
    if vendor["authorization_status"] != "REAUTH_PENDING":
        raise ApiError("ERR_INVALID_VENDOR_STATE")
    if not services.training_current(vendor):
        raise ApiError("ERR_VENDOR_TRAINING_EXPIRED")
    if services.has_open_case(vendor["id"]):
        raise ApiError("ERR_OPEN_SANCTION_CASE_EXISTS")
    if vendor["reauthorization_hold"]:
        raise ApiError("ERR_REAUTHORIZATION_HOLD")
    peer_group = db.peer_groups.get(vendor["peer_group_id"]) if vendor["peer_group_id"] else None
    if peer_group is None or peer_group["status"] != "ACTIVE":
        raise ApiError("ERR_PEER_GROUP_RETIRED")
    services.refresh_completeness(vendor)
    if not vendor["price_submission_complete"]:
        raise ApiError("ERR_PRICE_SUBMISSIONS_INCOMPLETE")

    previous = vendor["reauthorization_due_at"]
    services.update(
        vendor,
        authorization_status="AUTHORIZED",
        reauthorization_due_at=clock.add_months(previous, C.REAUTH_CYCLE_MONTHS)
        if previous is not None
        else None,
        reauth_completed_count=vendor["reauth_completed_count"] + 1,
        reauth_blocked_reason=None,
    )
    return envelope.success(vendor)
