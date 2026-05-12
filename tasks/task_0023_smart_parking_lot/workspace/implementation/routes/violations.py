"""Violation endpoints: issue, read, patch (dispute/un-dispute), pay, tow."""
from datetime import timedelta

from flask import Blueprint, g

import db
from clock import now, parse_iso, iso
from errors import err
from middleware import require_auth
from response import success
from services.validation import (
    get_body, require_str, require_int, require_field, require_enum,
    require_reason,
)
from services.projection import violation_view
from services.fines import compute_fine_amount
from services.payment import create_payment
from services.revenue import (
    create_revenue_entry, compute_card_balances,
)
from services.audit import write_audit
from services.cards import is_card_valid_now
from services.billing import compute_session_fee
from services.zones import recompute_zone_counts
from routes.vehicles import recompute_vehicle_violation_state


bp = Blueprint("violations", __name__)


VIOLATION_TYPES = {"OVERSTAY", "NON_PAYING", "BLOCKING", "WRONG_ZONE"}


@bp.route("/violations", methods=["POST"])
@require_auth(roles={"EnforcementOfficer"})
def issue_violation():
    body = get_body()
    lot_id = require_str(body, "lot_id")
    vehicle_id = require_str(body, "vehicle_id")
    violation_type = require_enum(body, "violation_type", VIOLATION_TYPES)
    space_id = require_str(body, "space_id")
    require_field(body, "detected_at")
    officer_id = require_str(body, "officer_id")
    session_id = body.get("session_id")
    photo_uri = body.get("photo_uri")

    # Body FK existence (priority 4)
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise err("ERR_NOT_FOUND", "Vehicle not found")
    space = db.spaces.get(space_id)
    if space is None or space.get("lot_id") != lot_id:
        raise err("ERR_NOT_FOUND", "Space not found in lot")
    if session_id is not None:
        sess = db.sessions_tbl.get(session_id)
        if sess is None:
            raise err("ERR_NOT_FOUND", "Session not found")
    else:
        sess = None

    # Priority 7: exempt vehicle for OVERSTAY/NON_PAYING
    if vehicle.get("kind") in ("EMERGENCY", "DISABLED") and violation_type in ("OVERSTAY", "NON_PAYING"):
        raise err("ERR_EXEMPT_VEHICLE",
                  "Exempt vehicles cannot receive OVERSTAY/NON_PAYING violations")

    # Priority 14: photo required for BLOCKING/WRONG_ZONE
    if violation_type in ("BLOCKING", "WRONG_ZONE"):
        if not photo_uri or not isinstance(photo_uri, str) or not photo_uri.strip():
            raise err("ERR_PHOTO_REQUIRED",
                      "BLOCKING/WRONG_ZONE violations require photo_uri")

    try:
        det = parse_iso(body["detected_at"])
    except ValueError as e:
        raise err("ERR_BAD_REQUEST", str(e))

    # Validate detected_at is a valid timestamp string format — already done by parse_iso

    vio = {
        "lot_id": lot_id,
        "vehicle_id": vehicle_id,
        "session_id": session_id,
        "space_id": space_id,
        "violation_type": violation_type,
        "photo_uri": photo_uri,
        "status": "PENDING",
        "officer_id": officer_id,
        "detected_at": body["detected_at"],
    }
    db.stamp_create(vio)
    db.violations[vio["id"]] = vio

    # Compute fine
    amount, components = compute_fine_amount(vehicle_id, violation_type,
                                             exclude_violation_id=vio["id"])
    fine = {
        "violation_id": vio["id"],
        "amount_cents": amount,
        "components": components,
        "paid_at": None,
    }
    db.stamp_create(fine, common_fields=False)
    db.fines[fine["id"]] = fine

    # Recompute vehicle binding eligibility
    recompute_vehicle_violation_state(vehicle_id)

    # OVERSTAY against EXITED & UNPAID session → cascade DISPUTED
    if violation_type == "OVERSTAY" and sess is not None:
        if sess.get("occupancy_status") == "EXITED" and sess.get("payment_status") == "UNPAID":
            sess["payment_status"] = "DISPUTED"
            db.stamp_update(sess)

    return success(violation_view(vio), status=201)


@bp.route("/violations/<violation_id>", methods=["GET"])
@require_auth(roles={"EnforcementOfficer", "Driver", "Operator", "Auditor"})
def get_violation(violation_id):
    v = db.violations.get(violation_id)
    if v is None:
        raise err("ERR_NOT_FOUND", "Violation not found")
    if g.user_role == "Driver" and v.get("vehicle_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")
    return success(violation_view(v))


@bp.route("/violations/<violation_id>", methods=["PATCH"])
@require_auth(roles={"Driver", "Operator"})
def patch_violation(violation_id):
    v = db.violations.get(violation_id)
    if v is None:
        raise err("ERR_NOT_FOUND", "Violation not found")
    body = get_body()
    new_status = require_enum(body, "status", {"PENDING", "DISPUTED"})
    reason = require_reason(body)
    cur = v.get("status")
    role = g.user_role

    if role == "Driver" and v.get("vehicle_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")

    if cur == "PENDING" and new_status == "DISPUTED":
        # Driver-only transition (per RBAC PRD)
        if role != "Driver":
            raise err("ERR_FORBIDDEN", "Only Driver may dispute their PENDING violation")
        try:
            det = parse_iso(v["detected_at"])
        except Exception:
            raise err("ERR_BAD_REQUEST", "detected_at unparseable")
        if now() > det + timedelta(days=14):
            raise err("ERR_INVALID_STATE", "Dispute window has closed")
        before = {"status": cur}
        v["status"] = "DISPUTED"
        db.stamp_update(v)
        recompute_vehicle_violation_state(v["vehicle_id"])
        write_audit(
            action="BILLING_ADJUSTMENT",
            subject_kind="Violation",
            subject_id=v["id"],
            before=before,
            after={"status": "DISPUTED"},
            reason=reason,
        )
        return success(violation_view(v))
    elif cur == "DISPUTED" and new_status == "PENDING":
        # Operator-only transition
        if role != "Operator":
            raise err("ERR_FORBIDDEN", "Only Operator may flip DISPUTED back to PENDING")
        before = {"status": cur}
        v["status"] = "PENDING"
        db.stamp_update(v)
        recompute_vehicle_violation_state(v["vehicle_id"])
        # Cascade linked Session.payment_status DISPUTED → UNPAID
        if v.get("session_id"):
            sess = db.sessions_tbl.get(v["session_id"])
            if sess is not None and sess.get("payment_status") == "DISPUTED":
                sess["payment_status"] = "UNPAID"
                db.stamp_update(sess)
        write_audit(
            action="BILLING_ADJUSTMENT",
            subject_kind="Violation",
            subject_id=v["id"],
            before=before,
            after={"status": "PENDING"},
            reason=reason,
        )
        return success(violation_view(v))
    elif cur == new_status:
        # No-op transition — treat as invalid
        raise err("ERR_INVALID_STATE", "Status unchanged")
    else:
        raise err("ERR_INVALID_STATE",
                  f"Cannot transition violation from {cur} to {new_status}")


@bp.route("/violations/<violation_id>/pay", methods=["POST"])
@require_auth(roles={"Driver", "Operator"})
def pay_violation(violation_id):
    v = db.violations.get(violation_id)
    if v is None:
        raise err("ERR_NOT_FOUND", "Violation not found")
    if g.user_role == "Driver" and v.get("vehicle_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")
    body = get_body()
    amount = require_int(body, "amount_cents", ge=0)
    card_id = body.get("card_id")
    external_ref = body.get("external_ref")

    if card_id is not None:
        card = db.cards.get(card_id)
        if card is None:
            raise err("ERR_NOT_FOUND", "Card not found")
        if not is_card_valid_now(card):
            raise err("ERR_CARD_EXPIRED", "Card expired or outside validity window")

    # priority 6: only PENDING admits payment
    if v.get("status") != "PENDING":
        raise err("ERR_INVALID_STATE", f"Cannot pay a {v.get('status')} violation")

    # Find Fine
    fine = None
    for f in db.fines.values():
        if f.get("violation_id") == v["id"]:
            fine = f
            break
    if fine is None:
        raise err("ERR_INVALID_STATE", "Fine record missing for violation")

    if amount != int(fine["amount_cents"]):
        raise err("ERR_BAD_REQUEST",
                  f"amount_cents must equal Fine.amount_cents ({fine['amount_cents']})")

    # priority 16: insufficient balance for STORED_VALUE card
    if card_id is not None:
        card = db.cards.get(card_id)
        if card is not None and card.get("card_type") == "STORED_VALUE":
            prov, _ = compute_card_balances(card["id"])
            if prov < amount:
                raise err("ERR_INSUFFICIENT_BALANCE", "Card balance below required amount")

    create_payment(
        kind="FINE_PAYMENT",
        subject_id=v["id"],
        amount_cents=amount,
        card_id=card_id,
        external_ref=external_ref,
    )

    v["status"] = "PAID"
    db.stamp_update(v)
    fine["paid_at"] = iso(now())

    # Vehicle counts
    recompute_vehicle_violation_state(v["vehicle_id"])

    # Revenue entry
    space = db.spaces.get(v.get("space_id")) if v.get("space_id") else None
    zone_id = space.get("zone_id") if space else None
    create_revenue_entry(
        lot_id=v["lot_id"],
        zone_id=zone_id,
        billing_type="FINE",
        source_kind="VIOLATION",
        source_id=v["id"],
        gross_amount_cents=amount,
    )

    # Linked Session DISPUTED → UNPAID cascade
    if v.get("session_id"):
        sess = db.sessions_tbl.get(v["session_id"])
        if sess is not None and sess.get("payment_status") == "DISPUTED":
            sess["payment_status"] = "UNPAID"
            db.stamp_update(sess)

    return success(violation_view(v))


@bp.route("/violations/<violation_id>/tow", methods=["POST"])
@require_auth(roles={"Operator"})
def tow_violation(violation_id):
    v = db.violations.get(violation_id)
    if v is None:
        raise err("ERR_NOT_FOUND", "Violation not found")
    body = get_body()
    reason = require_reason(body)

    if v.get("status") != "PENDING":
        raise err("ERR_INVALID_STATE", "Tow only applies to PENDING violations")
    if v.get("violation_type") not in ("BLOCKING", "WRONG_ZONE", "OVERSTAY"):
        raise err("ERR_INVALID_STATE",
                  "Tow only applies to BLOCKING/WRONG_ZONE/OVERSTAY violations")
    try:
        det = parse_iso(v["detected_at"])
    except Exception:
        raise err("ERR_INVALID_STATE", "detected_at unparseable")
    if now() < det + timedelta(hours=24):
        raise err("ERR_INVALID_STATE",
                  "Tow allowed only after 24h from detected_at")

    before = {"status": v.get("status")}
    v["status"] = "TOWED_AWAY"
    db.stamp_update(v)
    recompute_vehicle_violation_state(v["vehicle_id"])

    # If linked session is ACTIVE: force-exit it
    if v.get("session_id"):
        sess = db.sessions_tbl.get(v["session_id"])
        if sess is not None and sess.get("occupancy_status") == "ACTIVE":
            sess["exit_at"] = iso(now())
            fee, kind = compute_session_fee(sess, variant="final")
            sess["final_fee_cents"] = int(fee)
            sess["billing_kind"] = kind
            sess["occupancy_status"] = "EXITED"
            db.stamp_update(sess)
            space = db.spaces.get(sess.get("space_id")) if sess.get("space_id") else None
            if space is not None:
                space["occupancy_status"] = "FREE"
                space["last_exited_at"] = sess["exit_at"]
                space["current_session_id"] = None
                db.stamp_update(space)
                recompute_zone_counts(space["zone_id"])

    write_audit(
        action="BILLING_ADJUSTMENT",
        subject_kind="Violation",
        subject_id=v["id"],
        before=before,
        after={"status": "TOWED_AWAY"},
        reason=reason,
    )
    return success(violation_view(v))
