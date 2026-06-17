"""Rework-claim endpoints and the rework-spawn cascade (PRD §3.8)."""
from flask import Blueprint, request

import auth
import clock
import db
from domain import touch, recompute_outstanding, recompute_projected
from errors import err
from recordutil import base_versioned, sorted_by_creation
from response import object_response, array_response
from serialize import serialize, serialize_list
from timeutil import add_days
from validation import get_body, require_str, require_int, parse_pagination, paginate

bp = Blueprint("rework", __name__)


def _uid():
    return request.headers.get("X-User-ID")


def _within_window(orig):
    """filed_within_window: claim.created_at strictly before
    original.vehicle_release_utc + guarantee_days. Uses the current clock for
    the filing instant (the claim's created_at at filing time)."""
    pkg = None
    for p in db.packages.values():
        if p["tier"] == orig["tier"]:
            pkg = p
            break
    guarantee_days = pkg["guarantee_days"] if pkg else 0
    window_end = add_days(orig["vehicle_release_utc"], guarantee_days)
    return clock.now() < window_end, window_end


@bp.route("/detailing/rework-claims", methods=["POST"])
def file_claim():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "ShopManager"})
    body = get_body()
    original_id = require_str(body, "original_appointment_id")
    orig = db.appointments.get(original_id)
    # ownership (priority 3) for a Customer is established through the original
    # appointment's customer_id; checked before FK existence only when it resolves.
    if orig is not None:
        auth.require_owner(role, _uid(), orig["customer_id"])
    if orig is None:
        raise err("ERR_FK_NOT_FOUND", "original_appointment_id not found")
    reason = require_str(body, "reason")
    # the original appointment must be RELEASED.
    if orig["work_status"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "original appointment is not RELEASED")
    rec = base_versioned()
    within, _ = _within_window(orig)
    rec.update({
        "original_appointment_id": original_id,
        "reason": reason,
        "status": "SUBMITTED",
        "rework_appointment_id": None,
        "filed_within_window": within,
    })
    db.rework_claims[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/rework-claims/<rid>", methods=["GET"])
def get_claim(rid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager"})
    rec = db.rework_claims.get(rid)
    if not rec:
        raise err("ERR_NOT_FOUND", "rework claim not found")
    orig = db.appointments.get(rec["original_appointment_id"])
    if orig:
        auth.require_owner(role, _uid(), orig["customer_id"])
    return object_response(serialize(rec))


@bp.route("/detailing/rework-claims", methods=["GET"])
def list_claims():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager"})
    limit, offset = parse_pagination()
    rows = list(db.rework_claims.values())
    for f in ("original_appointment_id", "rework_appointment_id"):
        val = request.args.get(f)
        if val is not None:
            rows = [c for c in rows if c.get(f) == val]
    if role == "Customer":
        uid = _uid()
        rows = [c for c in rows
                if (db.appointments.get(c["original_appointment_id"]) or {}).get("customer_id") == uid]
    rows = sorted_by_creation(rows)
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


@bp.route("/detailing/rework-claims/<rid>/approve", methods=["POST"])
def approve(rid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    rec = db.rework_claims.get(rid)
    if not rec:
        raise err("ERR_NOT_FOUND", "rework claim not found")
    body = get_body()
    expected = require_int(body, "expected_claim_version")
    # PRD §2.7: a second approval still carrying the pre-approval version is
    # rejected with ERR_STALE_CLAIM_VERSION specifically to prevent a duplicate
    # free appointment spawn — so the OCC version check is evaluated before the
    # SUBMITTED state check.
    if expected != rec["version"]:
        raise err("ERR_STALE_CLAIM_VERSION", "claim version mismatch")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "approve requires SUBMITTED")
    orig = db.appointments.get(rec["original_appointment_id"])
    within, _ = _within_window(orig)
    if not within:
        raise err("ERR_GUARANTEE_EXPIRED", "guarantee window expired")
    if orig["work_status"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "original appointment is not RELEASED")

    rec["status"] = "APPROVED"
    # spawn a zero-cost, PAID, BOOKED clone.
    spawned = base_versioned()
    spawned.update({
        "customer_id": orig["customer_id"],
        "tier": orig["tier"],
        "vehicle_size": orig["vehicle_size"],
        "location_mode": orig["location_mode"],
        "service_bay_id": orig["service_bay_id"],
        "mobile_unit_id": orig["mobile_unit_id"],
        "scheduled_start_utc": orig["scheduled_start_utc"],
        "occupancy_end_utc": orig["occupancy_end_utc"],
        "vehicle_release_utc": orig["vehicle_release_utc"],
        "use_membership_credit": False,
        "work_status": "BOOKED",
        "payment_status": "PAID",
        "is_member_at_booking": orig["is_member_at_booking"],
        "credit_applied_cents": 0,
        "provisional_total_cents": 0,
        "final_total_cents": 0,
        "amount_charged_cents": 0,
        "amount_refunded_cents": 0,
        "outstanding_balance_cents": 0,
        "spawned_from_rework_claim_id": rec["id"],
    })
    db.appointments[spawned["id"]] = spawned
    rec["rework_appointment_id"] = spawned["id"]
    touch(rec)
    recompute_projected(spawned["customer_id"])
    return object_response(serialize(rec))


@bp.route("/detailing/rework-claims/<rid>/reject", methods=["POST"])
def reject(rid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    rec = db.rework_claims.get(rid)
    if not rec:
        raise err("ERR_NOT_FOUND", "rework claim not found")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "reject requires SUBMITTED")
    rec["status"] = "REJECTED"
    touch(rec)
    return object_response(serialize(rec))
