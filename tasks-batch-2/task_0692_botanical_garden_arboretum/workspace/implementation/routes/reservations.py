"""Reservation routes + lifecycle (PRD §3.3)."""
from flask import Blueprint, request

import errors
from db import db, now
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize, calc, cascade
from services.common import (
    new_record, get_body, get_or_404, paginate, touch, check_owner,
    req_str, opt_str, opt_int, opt_bool,
)

bp = Blueprint("reservations", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}
WRITE_ROLES = {"Visitor", "GardenStaff"}


@bp.route("/v1/reservations", methods=["POST"])
def create_reservation():
    _, role = get_identity()
    require_role(role, WRITE_ROLES)
    body = get_body()

    garden_id = req_str(body, "garden_id")
    time_slot_id = req_str(body, "time_slot_id")
    membership_id = opt_str(body, "membership_id", "")
    member_heads = opt_int(body, "member_heads", 0)
    guest_heads = opt_int(body, "guest_heads", 0)
    paid_heads = opt_int(body, "paid_heads", 0)
    reciprocal = opt_bool(body, "reciprocal", False)

    # --- Existence, left-to-right (PRD §2.7, priority 4) -------------------
    garden = get_or_404(db.gardens, garden_id)
    slot = get_or_404(db.time_slots, time_slot_id)
    membership = None
    if membership_id:
        membership = get_or_404(db.memberships, membership_id)

    # --- Same-garden referential integrity (priority 5) -------------------
    # The time slot must belong to the path garden. The attached membership must
    # too, EXCEPT for a reciprocal reservation, where PRD §3.3 explicitly admits
    # a membership from a *different* garden in the same network (its eligibility
    # is then validated by the reciprocal check, priority 12).
    if slot["garden_id"] != garden_id:
        raise errors.cross_garden_reference()
    if (membership is not None and membership["garden_id"] != garden_id
            and not reciprocal):
        raise errors.cross_garden_reference()

    # --- Head-split well-formedness (PRD §3.3, ERR_INVALID_HEAD_SPLIT) -----
    if member_heads < 0 or guest_heads < 0 or paid_heads < 0:
        raise errors.invalid_head_split()
    if member_heads == 0 and guest_heads == 0 and paid_heads == 0:
        raise errors.invalid_head_split()
    if (member_heads > 0 or guest_heads > 0) and not membership_id:
        raise errors.invalid_head_split()

    party_size = member_heads + guest_heads + paid_heads

    # --- OCC version check (priority 7) -----------------------------------
    if membership_id:
        if "expected_membership_version" not in body or body["expected_membership_version"] is None:
            raise errors.validation("expected_membership_version is required when membership_id is set")
        expected = body["expected_membership_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.validation("expected_membership_version must be an integer")
        if expected != membership["version"]:
            raise errors.stale_membership_version()

    # --- Membership-active gate (priority 8) ------------------------------
    # Claiming member or guest heads requires the attached membership ACTIVE.
    if (member_heads > 0 or guest_heads > 0):
        if membership["status"] != "ACTIVE":
            raise errors.membership_not_active()

    # --- Guest-pass sufficiency (priority 11) -----------------------------
    if guest_heads > 0:
        if guest_heads > membership["guest_passes_remaining"]:
            raise errors.insufficient_guest_passes()

    # --- Reciprocal eligibility (priority 12) -----------------------------
    if reciprocal:
        if garden["reciprocal_network_code"] == "":
            raise errors.reciprocal_not_eligible()
        if membership is not None:
            # Attached membership must belong to a DIFFERENT garden in the same network.
            other_garden = db.gardens.get(membership["garden_id"])
            same_network = (other_garden is not None
                            and other_garden["reciprocal_network_code"]
                            == garden["reciprocal_network_code"])
            different_garden = membership["garden_id"] != garden_id
            if not (same_network and different_garden):
                raise errors.reciprocal_not_eligible()

    # --- Slot capacity (priority 14) --------------------------------------
    if slot["held_count"] + party_size > slot["capacity"]:
        raise errors.slot_capacity_exceeded()

    # --- Pricing (PRD §3.3) -----------------------------------------------
    admission_cents = calc.reservation_admission_cents(
        slot["ga_price_cents"], reciprocal,
        garden["reciprocal_discount_pct"], paid_heads)

    # --- Commit -----------------------------------------------------------
    rec = new_record({
        "garden_id": garden_id,
        "time_slot_id": time_slot_id,
        "membership_id": membership_id,
        "member_heads": member_heads,
        "guest_heads": guest_heads,
        "paid_heads": paid_heads,
        "reciprocal": reciprocal,
        "party_size": party_size,
        "admission_cents": admission_cents,
        "status": "HELD",
    })
    db.reservations[rec["id"]] = rec

    # Slot held_count += party_size; flip CLOSED if full.
    cascade.add_slot_capacity(slot, party_size)

    # Spend guest passes + bump membership version when a membership is attached.
    if membership is not None:
        if guest_heads > 0:
            membership["guest_passes_remaining"] = \
                membership["guest_passes_remaining"] - guest_heads
        touch(membership)

    return success(serialize.reservation(rec), status=201)


@bp.route("/v1/reservations/<reservation_id>", methods=["GET"])
def read_reservation(reservation_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.reservations, reservation_id)
    return success(serialize.reservation(rec), status=200)


@bp.route("/v1/reservations", methods=["GET"])
def list_reservations():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    time_slot_id = request.args.get("time_slot_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    records = list(db.reservations.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if time_slot_id is not None:
        records = [r for r in records if r["time_slot_id"] == time_slot_id]
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.reservation(r) for r in page],
                        limit, offset, total)


@bp.route("/v1/reservations/<reservation_id>/check-in", methods=["POST"])
def check_in_reservation(reservation_id):
    _, role = get_identity()
    require_role(role, {"GardenStaff"})
    rec = get_or_404(db.reservations, reservation_id)
    # State (priority 6): only HELD may check in.
    if rec["status"] != "HELD":
        raise errors.invalid_state()
    slot = db.time_slots.get(rec["time_slot_id"])
    current = now()
    # Within slot window: starts_at <= now < ends_at.
    if slot is None or not (slot["starts_at"] <= current < slot["ends_at"]):
        raise errors.invalid_state()
    # Membership-active gate (priority 8) if attached.
    if rec["membership_id"]:
        m = db.memberships.get(rec["membership_id"])
        if m is None or m["status"] != "ACTIVE":
            raise errors.membership_not_active()
    rec["status"] = "CHECKED_IN"
    touch(rec)
    # Check-in does NOT release capacity; heads remain in held_count.
    return success(serialize.reservation(rec), status=200)


@bp.route("/v1/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    rec = get_or_404(db.reservations, reservation_id)
    # Ownership (priority 3): owning membership is the reservation's membership_id.
    check_owner(role, user_id, rec["membership_id"])
    if rec["status"] != "HELD":
        raise errors.invalid_state()

    rec["status"] = "CANCELLED"
    touch(rec)
    slot = db.time_slots.get(rec["time_slot_id"])
    if slot is not None:
        cascade.release_slot_capacity(slot, rec["party_size"])
    # Refund spent guest passes to the membership (PRD §3.3).
    if rec["membership_id"] and rec["guest_heads"] > 0:
        m = db.memberships.get(rec["membership_id"])
        if m is not None:
            m["guest_passes_remaining"] = \
                m["guest_passes_remaining"] + rec["guest_heads"]
            touch(m)
    return success(serialize.reservation(rec), status=200)
