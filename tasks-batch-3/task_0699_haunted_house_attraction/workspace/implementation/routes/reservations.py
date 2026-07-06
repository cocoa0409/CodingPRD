"""Reservation and Ticket endpoints (PRD §3.5–§3.7)."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import (
    get_identity, require_role, get_json_body, parse_pagination, require_owner,
)
from services import lookup
from services.common import (
    require_str, require_int, require_enum, touch, base_record, sort_and_paginate,
)
from services.serialize import (
    serialize_reservation, serialize_ticket, venue_operational_state,
    waiver_effective_status,
)
from services import reservation as resvc

bp = Blueprint("reservations", __name__)

READ_ROLES = {"OpsManager", "BoxOffice", "Guest"}
WRITE_ROLES = {"BoxOffice", "Guest"}


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------
@bp.route("/reservations", methods=["POST"])
def create_reservation():
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    body = get_json_body()
    venue_id = require_str(body, "venue_id")
    guest_id = require_str(body, "guest_id")
    pass_id = body.get("pass_id")
    if pass_id is not None and not isinstance(pass_id, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "pass_id must be a string when provided.")

    # Ownership: a Guest may only create their own reservation.
    require_owner(role, user_id, guest_id)

    # Existence of body FKs.
    lookup.venue(venue_id)
    lookup.guest(guest_id)
    if pass_id is not None:
        lookup.issued_pass(pass_id)

    res = base_record()
    res.update({
        "venue_id": venue_id,
        "guest_id": guest_id,
        "pass_id": pass_id,
        "party_size": 0,
        "entry_status": "HELD",
        "payment_status": "UNPAID",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
    })
    db.reservations[res["id"]] = res
    return response.success(serialize_reservation(res), 201)


@bp.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    res = lookup.reservation(reservation_id)
    require_owner(role, user_id, res["guest_id"])
    return response.success(serialize_reservation(res), 200)


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    guest_id = request.args.get("guest_id")
    venue_id = request.args.get("venue_id")
    pass_id = request.args.get("pass_id")
    records = list(db.reservations.values())
    if guest_id is not None:
        records = [r for r in records if r["guest_id"] == guest_id]
    if venue_id is not None:
        records = [r for r in records if r["venue_id"] == venue_id]
    if pass_id is not None:
        records = [r for r in records if r["pass_id"] == pass_id]
    if role == "Guest":
        records = [r for r in records if r["guest_id"] == user_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_reservation(r) for r in page], limit, offset, total, 200
    )


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
@bp.route("/reservations/<reservation_id>/tickets", methods=["POST"])
def add_ticket(reservation_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    res = lookup.reservation(reservation_id)
    require_owner(role, user_id, res["guest_id"])
    body = get_json_body()
    time_slot_id = require_str(body, "time_slot_id")
    guest_age = require_int(body, "guest_age", minimum=0)
    max_scare_level = require_int(body, "max_scare_level", minimum=1, maximum=5)
    tier = require_enum(body, "tier", {"GA", "FAST_PASS", "VIP"})

    # State: tickets are added to a HELD reservation (PRD §3.5).
    if res["entry_status"] != "HELD":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Tickets may only be added to a HELD reservation.")

    # Existence of the body FK slot, then its attraction.
    slot = lookup.time_slot(time_slot_id)
    attraction = resvc.attraction_of_slot(slot)
    if attraction is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced attraction does not exist.")

    # Business rules in priority order (PRD §2.11):
    # age (6) -> scare (8) -> sales-posture VIP (15) -> venue mismatch (17).
    if guest_age < attraction["min_age"]:
        raise ApiError(errors.ERR_AGE_BELOW_MINIMUM, 422,
                       "Ticket guest_age is below the attraction's min_age.")
    if max_scare_level < attraction["scare_level"]:
        raise ApiError(errors.ERR_SCARE_LEVEL_TOO_LOW, 422,
                       "Ticket max_scare_level is below the attraction's scare_level.")
    if tier == "VIP":
        venue = db.venues.get(res["venue_id"])
        if venue is not None and venue_operational_state(venue) in ("RESTRICTED", "SHUTDOWN"):
            raise ApiError(errors.ERR_SALES_BLOCKED, 409,
                           "VIP ticket additions are blocked under the current venue posture.")
    if attraction["venue_id"] != res["venue_id"]:
        raise ApiError(errors.ERR_TICKET_VENUE_MISMATCH, 422,
                       "Ticket slot belongs to an attraction in a different venue.")

    ticket = base_record()
    ticket.update({
        "reservation_id": res["id"],
        "time_slot_id": slot["id"],
        "guest_age": guest_age,
        "max_scare_level": max_scare_level,
        "tier": tier,
        "price_cents": 0,
        "queue_priority": resvc.QUEUE_PRIORITY[tier],
    })
    db.tickets[ticket["id"]] = ticket

    # party_size += 1 (PRD §3.5). updated_at/version bump on the reservation.
    res["party_size"] += 1
    touch(res)
    return response.success(serialize_ticket(ticket), 201)


@bp.route("/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    ticket = lookup.ticket(ticket_id)
    res = db.reservations.get(ticket["reservation_id"])
    if res is not None:
        require_owner(role, user_id, res["guest_id"])
    return response.success(serialize_ticket(ticket), 200)


@bp.route("/tickets", methods=["GET"])
def list_tickets():
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    reservation_id = request.args.get("reservation_id")
    time_slot_id = request.args.get("time_slot_id")
    records = list(db.tickets.values())
    if reservation_id is not None:
        records = [t for t in records if t["reservation_id"] == reservation_id]
    if time_slot_id is not None:
        records = [t for t in records if t["time_slot_id"] == time_slot_id]
    if role == "Guest":
        owned = {r["id"] for r in db.reservations.values() if r["guest_id"] == user_id}
        records = [t for t in records if t["reservation_id"] in owned]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_ticket(t) for t in page], limit, offset, total, 200
    )


# ---------------------------------------------------------------------------
# Confirm (HELD -> RESERVED)
# ---------------------------------------------------------------------------
@bp.route("/reservations/<reservation_id>/confirm", methods=["POST"])
def confirm_reservation(reservation_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    res = lookup.reservation(reservation_id)
    require_owner(role, user_id, res["guest_id"])
    body = get_json_body()

    # State (priority 5): must be HELD.
    if res["entry_status"] != "HELD":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a HELD reservation can be confirmed.")

    tickets = resvc.tickets_of(reservation_id)
    # Empty reservation check (PRD §3.6).
    if not tickets:
        raise ApiError(errors.ERR_EMPTY_RESERVATION, 422,
                       "Cannot confirm a reservation with zero tickets.")

    # Resolve slots/attractions for each ticket.
    slot_by_ticket = {}
    attraction_by_ticket = {}
    for t in tickets:
        slot = db.time_slots.get(t["time_slot_id"])
        if slot is None:
            raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced time slot does not exist.")
        attraction = resvc.attraction_of_slot(slot)
        if attraction is None:
            raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced attraction does not exist.")
        slot_by_ticket[t["id"]] = slot
        attraction_by_ticket[t["id"]] = attraction

    # State precondition: every referenced slot must be SCHEDULED.
    for t in tickets:
        if slot_by_ticket[t["id"]]["status"] != "SCHEDULED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "A referenced time slot is not SCHEDULED.")

    # Age (priority 6) then scare (priority 8), re-checked at confirm.
    for t in tickets:
        attraction = attraction_by_ticket[t["id"]]
        if t["guest_age"] < attraction["min_age"]:
            raise ApiError(errors.ERR_AGE_BELOW_MINIMUM, 422,
                           "Ticket guest_age is below the attraction's min_age.")
    for t in tickets:
        attraction = attraction_by_ticket[t["id"]]
        if t["max_scare_level"] < attraction["scare_level"]:
            raise ApiError(errors.ERR_SCARE_LEVEL_TOO_LOW, 422,
                           "Ticket max_scare_level is below the attraction's scare_level.")

    # Sales posture (priority 15): blocked while venue SHUTDOWN.
    venue = db.venues.get(res["venue_id"])
    if venue is not None and venue_operational_state(venue) == "SHUTDOWN":
        raise ApiError(errors.ERR_SALES_BLOCKED, 409,
                       "Confirmation is blocked while the venue is shut down.")

    # Pass eligibility (priority 16) and ownership (priority 18).
    applied_pass = None
    if res["pass_id"] is not None:
        applied_pass = db.passes.get(res["pass_id"])
        if applied_pass is None:
            raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced pass does not exist.")
        product = db.pass_products.get(applied_pass["pass_product_id"])
        if applied_pass["status"] != "ACTIVE" or (
            product is not None and applied_pass["redemptions_used"] >= product["max_redemptions"]
        ):
            raise ApiError(errors.ERR_PASS_EXHAUSTED, 409,
                           "Applied pass is not ACTIVE or has no remaining redemptions.")

    # Referential: ticket venue mismatch (priority 17).
    for t in tickets:
        attraction = attraction_by_ticket[t["id"]]
        if attraction["venue_id"] != res["venue_id"]:
            raise ApiError(errors.ERR_TICKET_VENUE_MISMATCH, 422,
                           "Ticket slot belongs to an attraction in a different venue.")

    # Pass ownership (priority 18).
    if applied_pass is not None and applied_pass["guest_id"] != res["guest_id"]:
        raise ApiError(errors.ERR_PASS_NOT_OWNED, 422,
                       "Applied pass is not owned by the reservation's guest.")

    # OCC (priority 19): expected_time_slot_version must match each referenced
    # TimeSlot.version (PRD §2.10).
    expected = require_int(body, "expected_time_slot_version")
    distinct_slots = {slot_by_ticket[t["id"]]["id"]: slot_by_ticket[t["id"]] for t in tickets}
    for slot in distinct_slots.values():
        if slot["version"] != expected:
            raise ApiError(errors.ERR_STALE_TIME_SLOT_VERSION, 412,
                           "expected_time_slot_version does not match a referenced slot version.")

    # Live capacity (priority 20): check ALL slots before committing any change.
    party_on_slot = {}
    for t in tickets:
        sid = slot_by_ticket[t["id"]]["id"]
        party_on_slot[sid] = party_on_slot.get(sid, 0) + 1
    for sid, new_party in party_on_slot.items():
        slot = distinct_slots[sid]
        if slot["reserved_count"] + slot["admitted_count"] + new_party > slot["capacity"]:
            raise ApiError(errors.ERR_SLOT_CAPACITY_EXCEEDED, 409,
                           "Confirmation would exceed a slot's capacity.")

    # --- All checks passed; commit atomically. ---
    # Freeze each ticket price from the demand_ratio BEFORE this confirm's
    # increment (snapshot pre-increment per slot).
    ratio_snapshot = {sid: resvc.slot_demand_ratio(slot) for sid, slot in distinct_slots.items()}
    for t in tickets:
        slot = slot_by_ticket[t["id"]]
        attraction = attraction_by_ticket[t["id"]]
        rule = resvc.select_pricing_rule(attraction["id"], t["tier"])
        ratio = ratio_snapshot[slot["id"]]
        if rule is None:
            # No pricing rule -> price freezes at 0 (no rule defines a price).
            price = 0
        else:
            price = resvc.dynamic_ticket_price(rule, ratio)
        t["price_cents"] = price
        touch(t)

    # subtotal = sum of frozen prices.
    subtotal = sum(t["price_cents"] for t in tickets)

    # Pass discount (calc pass_discount): round PER LINE ITEM then sum.
    discount = 0
    if applied_pass is not None:
        product = db.pass_products.get(applied_pass["pass_product_id"])
        eligible = True
        if applied_pass["status"] != "ACTIVE":
            eligible = False
        elif product is not None and product["kind"] == "GROUP" and res["party_size"] < product["min_party"]:
            eligible = False
        if eligible and product is not None:
            from services.common import round_half_up
            discount = sum(
                round_half_up(t["price_cents"] * product["discount_pct"] / 100)
                for t in tickets
            )

    total = max(0, subtotal - discount)
    res["subtotal_cents"] = subtotal
    res["discount_cents"] = discount
    res["total_cents"] = total

    # Consume slot capacity: reserved_count += new party; version += 1.
    for sid, new_party in party_on_slot.items():
        slot = distinct_slots[sid]
        slot["reserved_count"] += new_party
        touch(slot)

    # Pass redemption.
    if applied_pass is not None:
        product = db.pass_products.get(applied_pass["pass_product_id"])
        applied_pass["redemptions_used"] += 1
        if product is not None and applied_pass["redemptions_used"] >= product["max_redemptions"]:
            applied_pass["status"] = "EXHAUSTED"
        touch(applied_pass)

    res["entry_status"] = "RESERVED"
    touch(res)
    return response.success(serialize_reservation(res), 200)


# ---------------------------------------------------------------------------
# Pay (UNPAID -> PAID)
# ---------------------------------------------------------------------------
@bp.route("/reservations/<reservation_id>/pay", methods=["POST"])
def pay_reservation(reservation_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    res = lookup.reservation(reservation_id)
    require_owner(role, user_id, res["guest_id"])

    # State: paid only while entry_status RESERVED and payment_status UNPAID.
    if res["entry_status"] != "RESERVED" or res["payment_status"] != "UNPAID":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Reservation must be RESERVED and UNPAID to be paid.")

    # Apply wallet credit first (calc wallet_apply).
    guest = db.guests.get(res["guest_id"])
    if guest is not None:
        applied = min(guest["wallet_credit_cents"], res["total_cents"])
        if applied > 0:
            guest["wallet_credit_cents"] -= applied
            touch(guest)

    res["payment_status"] = "PAID"
    touch(res)
    return response.success(serialize_reservation(res), 200)


# ---------------------------------------------------------------------------
# Admit (RESERVED -> ADMITTED)
# ---------------------------------------------------------------------------
@bp.route("/reservations/<reservation_id>/admit", methods=["POST"])
def admit_reservation(reservation_id):
    _, role = get_identity()
    require_role(role, {"BoxOffice"})
    res = lookup.reservation(reservation_id)

    # State: RESERVED and PAID.
    if res["entry_status"] != "RESERVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a RESERVED reservation can be admitted.")
    if res["payment_status"] != "PAID":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Reservation must be PAID to be admitted.")

    tickets = resvc.tickets_of(reservation_id)
    if not tickets:
        raise ApiError(errors.ERR_EMPTY_RESERVATION, 422,
                       "Cannot admit a reservation with zero tickets.")

    slot_by_ticket = {}
    attraction_by_ticket = {}
    for t in tickets:
        slot = db.time_slots.get(t["time_slot_id"])
        attraction = resvc.attraction_of_slot(slot) if slot is not None else None
        if slot is None or attraction is None:
            raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced slot/attraction does not exist.")
        slot_by_ticket[t["id"]] = slot
        attraction_by_ticket[t["id"]] = attraction

    # Domain rules in priority order (PRD §2.11):
    # age (6) -> waiver (7) -> scare (8) -> zone staffing (9) -> entry window (10).
    for t in tickets:
        attraction = attraction_by_ticket[t["id"]]
        if t["guest_age"] < attraction["min_age"]:
            raise ApiError(errors.ERR_AGE_BELOW_MINIMUM, 422,
                           "Ticket guest_age is below the attraction's min_age.")

    # Waiver sufficiency (priority 7): each ticketed guest holds a SIGNED,
    # non-expired Waiver with max_scare_level >= attraction.scare_level when the
    # attraction requires a waiver. The reservation's owning guest is the bearer.
    for t in tickets:
        attraction = attraction_by_ticket[t["id"]]
        if attraction["requires_waiver"]:
            if not _has_sufficient_waiver(res["guest_id"], attraction["scare_level"]):
                raise ApiError(errors.ERR_WAIVER_REQUIRED, 422,
                               "A required SIGNED non-expired sufficient waiver is missing.")

    # Scare clearance (priority 8).
    for t in tickets:
        attraction = attraction_by_ticket[t["id"]]
        if t["max_scare_level"] < attraction["scare_level"]:
            raise ApiError(errors.ERR_SCARE_LEVEL_TOO_LOW, 422,
                           "Ticket max_scare_level is below the attraction's scare_level.")

    # Zone staffing (priority 9): every ScareZone of each ticketed attraction
    # must be STAFFED.
    from services.serialize import zone_staffing_status
    attraction_ids = {a["id"] for a in attraction_by_ticket.values()}
    for aid in attraction_ids:
        for zone in db.scare_zones.values():
            if zone["attraction_id"] == aid and zone_staffing_status(zone) != "STAFFED":
                raise ApiError(errors.ERR_ZONE_UNDERSTAFFED, 409,
                               "A required scare zone is understaffed.")

    # Entry window (priority 10): clock within [earliest start, latest end).
    starts = [db.parse_iso(slot_by_ticket[t["id"]]["window_start"]) for t in tickets]
    ends = [db.parse_iso(slot_by_ticket[t["id"]]["window_end"]) for t in tickets]
    earliest_start = min(starts)
    latest_end = max(ends)
    now = db.now()
    if not (earliest_start <= now < latest_end):
        raise ApiError(errors.ERR_OUTSIDE_ENTRY_WINDOW, 409,
                       "Admission attempted outside the reservation's entry window.")

    # Commit: per ticket move one from reserved_count to admitted_count.
    for t in tickets:
        slot = slot_by_ticket[t["id"]]
        slot["reserved_count"] -= 1
        slot["admitted_count"] += 1
        touch(slot)

    res["entry_status"] = "ADMITTED"
    touch(res)
    return response.success(serialize_reservation(res), 200)


def _has_sufficient_waiver(guest_id, scare_level):
    for w in db.waivers.values():
        if w["guest_id"] != guest_id:
            continue
        if waiver_effective_status(w) != "SIGNED":
            continue
        if w["max_scare_level"] >= scare_level:
            return True
    return False


# ---------------------------------------------------------------------------
# Mark no-show (RESERVED -> NO_SHOW)
# ---------------------------------------------------------------------------
@bp.route("/reservations/<reservation_id>/mark_no_show", methods=["POST"])
def mark_no_show(reservation_id):
    _, role = get_identity()
    require_role(role, {"BoxOffice"})
    res = lookup.reservation(reservation_id)

    if res["entry_status"] != "RESERVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a RESERVED reservation can be marked NO_SHOW.")

    tickets = resvc.tickets_of(reservation_id)
    # Temporal: clock at or after the latest ticketed slot's window_end.
    ends = []
    for t in tickets:
        slot = db.time_slots.get(t["time_slot_id"])
        if slot is not None:
            ends.append(db.parse_iso(slot["window_end"]))
    if ends:
        latest_end = max(ends)
        if db.now() < latest_end:
            # No-show is only legal once the clock is at or after the latest
            # ticketed slot's window_end (PRD §3.7). No dedicated error id exists
            # for this temporal precondition, so it surfaces as ERR_INVALID_STATE.
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Cannot mark NO_SHOW before the entry window has passed.")

    for t in tickets:
        slot = db.time_slots.get(t["time_slot_id"])
        if slot is not None:
            slot["reserved_count"] -= 1
            touch(slot)

    res["entry_status"] = "NO_SHOW"
    touch(res)
    return response.success(serialize_reservation(res), 200)


# ---------------------------------------------------------------------------
# Cancel (HELD/RESERVED -> CANCELLED)
# ---------------------------------------------------------------------------
@bp.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    user_id, role = get_identity()
    require_role(role, {"Guest", "BoxOffice"})
    res = lookup.reservation(reservation_id)
    require_owner(role, user_id, res["guest_id"])

    if res["entry_status"] not in ("HELD", "RESERVED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a HELD or RESERVED reservation can be cancelled.")

    was_reserved = res["entry_status"] == "RESERVED"

    # If RESERVED: release reserved_count on each ticket's slot.
    if was_reserved:
        tickets = resvc.tickets_of(reservation_id)
        for t in tickets:
            slot = db.time_slots.get(t["time_slot_id"])
            if slot is not None:
                slot["reserved_count"] -= 1
                touch(slot)

    # If PAID: refund full total_cents to wallet (calc refund_credit).
    if res["payment_status"] == "PAID":
        res["payment_status"] = "REFUNDED"
        guest = db.guests.get(res["guest_id"])
        if guest is not None:
            guest["wallet_credit_cents"] += res["total_cents"]
            touch(guest)

    # If a pass had been applied and the reservation was RESERVED: return the
    # redemption; a pass that had become EXHAUSTED returns to ACTIVE.
    if res["pass_id"] is not None and was_reserved:
        applied_pass = db.passes.get(res["pass_id"])
        if applied_pass is not None:
            applied_pass["redemptions_used"] = max(0, applied_pass["redemptions_used"] - 1)
            if applied_pass["status"] == "EXHAUSTED":
                applied_pass["status"] = "ACTIVE"
            touch(applied_pass)

    res["entry_status"] = "CANCELLED"
    touch(res)
    return response.success(serialize_reservation(res), 200)
