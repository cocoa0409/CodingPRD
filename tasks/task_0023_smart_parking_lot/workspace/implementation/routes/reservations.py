"""Reservation endpoints: create, read, update, cancel."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from clock import now, parse_iso, iso
from errors import err
from middleware import require_auth
from response import success
from services.validation import (
    get_body, require_str, require_field, check_version, require_reason,
)
from services.projection import reservation_view
from services.reservations import (
    select_space, intervals_overlap, cancel_window_penalty_cents,
)
from services.zones import recompute_zone_counts
from services.audit import write_audit
from services.payment import create_payment
from services.revenue import create_revenue_entry
from services.cards import is_card_valid_now


bp = Blueprint("reservations", __name__)


def _check_driver_owns(role, user_id, vehicle_id):
    if role == "Driver" and vehicle_id != user_id:
        raise err("ERR_FORBIDDEN", "Driver can only act on their own vehicle's reservation")


def _check_window(scheduled_start_at, scheduled_end_at):
    if not (scheduled_end_at > scheduled_start_at):
        raise err("ERR_INVALID_RESERVATION_WINDOW",
                  "scheduled_end_at must be > scheduled_start_at")
    if scheduled_start_at < now() - timedelta(minutes=5):
        raise err("ERR_INVALID_RESERVATION_WINDOW",
                  "scheduled_start_at must be within 5 minutes of past")


@bp.route("/lots/<lot_id>/reservations", methods=["POST"])
@require_auth(roles={"Driver", "Operator"})
def create_reservation(lot_id):
    from flask import g
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    body = get_body()
    zone_id = require_str(body, "zone_id")
    vehicle_id = require_str(body, "vehicle_id")
    require_field(body, "scheduled_start_at")
    require_field(body, "scheduled_end_at")
    card_id = body.get("card_id")

    # Body FK existence checks (priority 4)
    zone = db.zones.get(zone_id)
    if zone is None or zone.get("lot_id") != lot_id:
        raise err("ERR_NOT_FOUND", "Zone not found in lot")
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise err("ERR_NOT_FOUND", "Vehicle not found")
    if card_id is not None:
        card = db.cards.get(card_id)
        if card is None:
            raise err("ERR_NOT_FOUND", "Card not found")
    # Driver scope
    _check_driver_owns(g.user_role, g.user_id, vehicle_id)

    # Parse times
    try:
        sched_start = parse_iso(body["scheduled_start_at"])
        sched_end = parse_iso(body["scheduled_end_at"])
    except ValueError as e:
        raise err("ERR_INVALID_RESERVATION_WINDOW", str(e))

    # Priority 8: vehicle binding eligibility
    if not vehicle.get("binding_eligible", True):
        raise err("ERR_VEHICLE_HAS_OPEN_VIOLATIONS",
                  "Vehicle has open violations and cannot reserve")

    # Card validity (PRD §2.7: card validity (ERR_CARD_EXPIRED) is part of the
    # business-rule priority ordering applied to every request that references
    # a card). A reservation that pins an EXPIRED card or a card whose validity
    # window does not include the current instant is rejected here.
    if card_id is not None:
        pinned_card = db.cards.get(card_id)
        if pinned_card is not None and (
            pinned_card.get("status") == "EXPIRED"
            or not is_card_valid_now(pinned_card)
        ):
            raise err("ERR_CARD_EXPIRED",
                      "Pinned card is expired or outside validity window")

    # Priority 15: window check (scheduled_end > scheduled_start; scheduled_start >= now - 5m)
    _check_window(sched_start, sched_end)

    # Priority 9 / 10: overlap and bookable distinctions BEFORE selector
    # Determine the candidate result with classification:
    overlap_blocked = False
    grace_blocked = False
    any_in_zone = False
    tow_grace = int(lot.get("tow_grace_minutes", 5))
    for s in db.spaces.values():
        if s.get("zone_id") != zone_id:
            continue
        any_in_zone = True
        # Check overlap with HELD/MATCHED on this space
        for r in db.reservations.values():
            if r.get("space_id") != s["id"]:
                continue
            if r.get("status") not in ("HELD", "MATCHED"):
                continue
            try:
                rs = parse_iso(r["scheduled_start_at"])
                re_ = parse_iso(r["scheduled_end_at"])
            except Exception:
                continue
            if intervals_overlap(sched_start, sched_end, rs, re_):
                overlap_blocked = True
        if s.get("occupancy_status") != "FREE":
            continue
        last_exit = s.get("last_exited_at")
        if last_exit is not None:
            try:
                le = parse_iso(last_exit)
                if sched_start < le + timedelta(minutes=tow_grace):
                    grace_blocked = True
            except Exception:
                pass

    # If a viable space exists, the selector will succeed; otherwise classify error.
    try:
        chosen = select_space(lot, zone_id, sched_start, sched_end)
    except Exception as e:
        if not any_in_zone:
            raise err("ERR_NO_SPACE_AVAILABLE", "No spaces in zone")
        if overlap_blocked:
            raise err("ERR_RESERVATION_OVERLAP",
                      "Requested interval overlaps an existing reservation")
        if grace_blocked:
            raise err("ERR_SPACE_NOT_BOOKABLE",
                      "All candidate spaces inside tow-grace buffer")
        raise

    # Payer card: required when zone_type=STANDARD with no_show_penalty>0
    if zone.get("zone_type") == "STANDARD" and int(lot.get("no_show_penalty_cents", 0)) > 0 and card_id is None:
        raise err("ERR_BAD_REQUEST",
                  "card_id required for STANDARD zone with no_show_penalty>0")

    res = {
        "lot_id": lot_id,
        "zone_id": zone_id,
        "space_id": chosen["id"],
        "vehicle_id": vehicle_id,
        "card_id": card_id,
        "scheduled_start_at": body["scheduled_start_at"],
        "scheduled_end_at": body["scheduled_end_at"],
        "status": "HELD",
        "matched_session_id": None,
        "penalty_charged_cents": 0,
    }
    db.stamp_create(res)
    db.reservations[res["id"]] = res
    # Transition the chosen space.reservation_lock to RESERVED
    chosen["reservation_lock"] = "RESERVED"
    db.stamp_update(chosen)
    recompute_zone_counts(chosen["zone_id"])
    return success(reservation_view(res), status=201)


@bp.route("/reservations/<reservation_id>", methods=["GET"])
@require_auth(roles={"Driver", "Operator", "ParkingPartner", "Auditor"})
def get_reservation(reservation_id):
    from flask import g
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "Reservation not found")
    if g.user_role == "Driver" and r.get("vehicle_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")
    return success(reservation_view(r))


@bp.route("/reservations/<reservation_id>", methods=["PATCH"])
@require_auth(roles={"Driver", "Operator"})
def patch_reservation(reservation_id):
    from flask import g
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "Reservation not found")
    body = get_body()

    # OCC priority 5
    check_version(body, r["version"])

    # state priority 6 — only HELD permits edits
    if r.get("status") != "HELD":
        raise err("ERR_INVALID_STATE", "Only HELD reservations can be edited")

    # priority 18 — reason required
    reason = require_reason(body)

    if g.user_role == "Driver" and r.get("vehicle_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")

    new_start = r.get("scheduled_start_at")
    new_end = r.get("scheduled_end_at")
    new_vehicle = r.get("vehicle_id")
    if "scheduled_start_at" in body and body["scheduled_start_at"] is not None:
        new_start = body["scheduled_start_at"]
    if "scheduled_end_at" in body and body["scheduled_end_at"] is not None:
        new_end = body["scheduled_end_at"]
    if "vehicle_id" in body and body["vehicle_id"] is not None:
        new_vehicle = body["vehicle_id"]

    veh = db.vehicles.get(new_vehicle)
    if veh is None:
        raise err("ERR_NOT_FOUND", "Vehicle not found")
    if not veh.get("binding_eligible", True):
        raise err("ERR_VEHICLE_HAS_OPEN_VIOLATIONS",
                  "Vehicle has open violations and cannot reserve")

    # Driver who patches changing vehicle: scope check on the new vehicle too
    if g.user_role == "Driver" and new_vehicle != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")

    try:
        sched_start = parse_iso(new_start)
        sched_end = parse_iso(new_end)
    except ValueError as e:
        raise err("ERR_INVALID_RESERVATION_WINDOW", str(e))

    _check_window(sched_start, sched_end)

    # Re-check overlap on this space (excluding self)
    space = db.spaces.get(r["space_id"]) if r.get("space_id") else None
    if space is None:
        raise err("ERR_NOT_FOUND", "Reserved space missing")
    for r2 in db.reservations.values():
        if r2["id"] == r["id"]:
            continue
        if r2.get("space_id") != space["id"]:
            continue
        if r2.get("status") not in ("HELD", "MATCHED"):
            continue
        try:
            rs = parse_iso(r2["scheduled_start_at"])
            re_ = parse_iso(r2["scheduled_end_at"])
        except Exception:
            continue
        if intervals_overlap(sched_start, sched_end, rs, re_):
            raise err("ERR_RESERVATION_OVERLAP",
                      "Updated window overlaps another reservation")

    before = {
        "scheduled_start_at": r.get("scheduled_start_at"),
        "scheduled_end_at": r.get("scheduled_end_at"),
        "vehicle_id": r.get("vehicle_id"),
    }
    r["scheduled_start_at"] = new_start
    r["scheduled_end_at"] = new_end
    r["vehicle_id"] = new_vehicle
    db.stamp_update(r)
    after = {
        "scheduled_start_at": r.get("scheduled_start_at"),
        "scheduled_end_at": r.get("scheduled_end_at"),
        "vehicle_id": r.get("vehicle_id"),
    }
    write_audit(
        action="RESERVATION_CHANGE",
        subject_kind="Reservation",
        subject_id=r["id"],
        before=before,
        after=after,
        reason=reason,
    )
    return success(reservation_view(r))


@bp.route("/reservations/<reservation_id>/cancel", methods=["POST"])
@require_auth(roles={"Driver", "Operator"})
def cancel_reservation(reservation_id):
    from flask import g
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "Reservation not found")
    if r.get("status") != "HELD":
        raise err("ERR_INVALID_STATE", "Only HELD reservations can be cancelled")
    if g.user_role == "Driver" and r.get("vehicle_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")
    body = get_body() if True else {}
    # PRD: cancel transition is unconditional on time — no reason required to cancel.
    # But the audit row is written, capturing whatever reason was supplied (optional).
    reason = body.get("reason") if isinstance(body, dict) else None
    if reason is None:
        reason = ""

    lot = db.parking_lots.get(r["lot_id"])
    try:
        sched_start = parse_iso(r["scheduled_start_at"])
    except Exception:
        sched_start = now()
    no_cancel_threshold = sched_start - timedelta(minutes=30)
    inside_window = now() >= no_cancel_threshold

    penalty = 0
    if inside_window:
        penalty = cancel_window_penalty_cents(lot)

    before = {
        "status": r.get("status"),
        "penalty_charged_cents": r.get("penalty_charged_cents"),
    }
    r["status"] = "CANCELLED"
    r["penalty_charged_cents"] = penalty
    db.stamp_update(r)
    after = {
        "status": r.get("status"),
        "penalty_charged_cents": r.get("penalty_charged_cents"),
    }

    # Free the space
    if r.get("space_id"):
        space = db.spaces.get(r["space_id"])
        if space and space.get("reservation_lock") == "RESERVED":
            space["reservation_lock"] = "UNRESERVED"
            db.stamp_update(space)
            recompute_zone_counts(space["zone_id"])

    if penalty > 0:
        card_id = r.get("card_id")
        try:
            create_payment(
                kind="NO_SHOW_PENALTY",
                subject_id=r["id"],
                amount_cents=penalty,
                card_id=card_id,
            )
        except Exception:
            pass
        zone_id = None
        if r.get("space_id"):
            sp = db.spaces.get(r["space_id"])
            zone_id = sp.get("zone_id") if sp else r.get("zone_id")
        else:
            zone_id = r.get("zone_id")
        create_revenue_entry(
            lot_id=r["lot_id"],
            zone_id=zone_id,
            billing_type="NO_SHOW_PENALTY",
            source_kind="RESERVATION",
            source_id=r["id"],
            gross_amount_cents=penalty,
        )

    write_audit(
        action="RESERVATION_CHANGE",
        subject_kind="Reservation",
        subject_id=r["id"],
        before=before,
        after=after,
        reason=reason,
    )
    return success(reservation_view(r))
