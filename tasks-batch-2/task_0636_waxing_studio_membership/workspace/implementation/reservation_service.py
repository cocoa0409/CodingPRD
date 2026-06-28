"""Reservation booking and lifecycle (PRD 2.6, 2.7, 3.4, 3.5, 3.6)."""
from db import db
from errors import err
from clock import clock
from mutate import touch
from util import new_id, add_minutes, minute_of_day
from credits import membership_credit_balance, write_ledger_entry
from strikes import member_active_strike_count

NO_SHOW_DEPOSIT_THRESHOLD = 2

NON_TERMINAL_BOOKING = ("BOOKED", "CHECKED_IN")


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
def create_reservation(principal, body):
    from helpers import require_fields, require_str, require_int, require_enum

    # ERR_INVALID_REQUEST: required fields present, enum values valid.
    require_fields(body, ["member_id", "location_id", "room_id", "technician_id",
                          "service_type_id", "start_utc", "payment_method",
                          "expected_room_version"])
    member_id = require_str(body, "member_id")
    location_id = require_str(body, "location_id")
    room_id = require_str(body, "room_id")
    technician_id = require_str(body, "technician_id")
    service_type_id = require_str(body, "service_type_id")
    payment_method = require_enum(body, "payment_method",
                                  ("CREDIT", "DEPOSIT", "INTRO_FREE", "WALK_IN"))
    expected_room_version = require_int(body, "expected_room_version")
    expected_membership_version = None
    if body.get("expected_membership_version") is not None:
        expected_membership_version = require_int(body, "expected_membership_version")
    membership_id = body.get("membership_id")
    if membership_id is not None and not isinstance(membership_id, str):
        raise err("ERR_INVALID_REQUEST", "membership_id must be a string")

    from util import parse_dt
    start_utc = parse_dt(body.get("start_utc"))

    # --- Priority 3: existence, left-to-right:
    # Location, Room, Technician, ServiceType, Member, Membership, Product, Reservation.
    location = db.locations.get(location_id)
    if location is None:
        raise err("ERR_NOT_FOUND", "location not found")
    room = db.rooms.get(room_id)
    if room is None:
        raise err("ERR_NOT_FOUND", "room not found")
    technician = db.technicians.get(technician_id)
    if technician is None:
        raise err("ERR_NOT_FOUND", "technician not found")
    service = db.service_types.get(service_type_id)
    if service is None:
        raise err("ERR_NOT_FOUND", "service type not found")
    member = db.members.get(member_id)
    if member is None:
        raise err("ERR_NOT_FOUND", "member not found")
    membership = None
    if membership_id is not None:
        membership = db.memberships.get(membership_id)
        if membership is None:
            raise err("ERR_NOT_FOUND", "membership not found")

    # --- Priority 2 ownership: a Member may only book for themselves.
    if principal.role == "Member" and member_id != principal.user_id:
        raise err("ERR_UNAUTHORIZED", "member may only book for themselves")

    # --- Priority 6: OCC. Room version always checked; membership only when CREDIT.
    if expected_room_version != room["version"]:
        raise err("ERR_STALE_VERSION", "stale room version")
    if payment_method == "CREDIT":
        # expected_membership_version required precisely when a credit booking
        # is being made (PRD 2.6). Existence of membership for CREDIT is part of
        # the cross-entity coherence check below (priority 7), but the version
        # field must be present and well-formed first.
        if membership is not None and expected_membership_version is not None:
            if expected_membership_version != membership["version"]:
                raise err("ERR_STALE_VERSION", "stale membership version")

    # --- Priority 7: cross-entity coherence (ERR_RESOURCE_MISMATCH).
    if room["location_id"] != location_id:
        raise err("ERR_RESOURCE_MISMATCH", "room not at reservation location")
    if technician["location_id"] != location_id:
        raise err("ERR_RESOURCE_MISMATCH", "technician not at reservation location")
    if service_type_id not in technician["certified_service_ids"]:
        raise err("ERR_RESOURCE_MISMATCH", "technician not certified for service")
    if not service["active"]:
        raise err("ERR_RESOURCE_MISMATCH", "service inactive")
    if not room["active"]:
        raise err("ERR_RESOURCE_MISMATCH", "room inactive")
    if not technician["active"]:
        raise err("ERR_RESOURCE_MISMATCH", "technician inactive")
    if payment_method == "CREDIT":
        if membership is None:
            raise err("ERR_RESOURCE_MISMATCH", "membership_id required for CREDIT")
        if membership["member_id"] != member_id:
            raise err("ERR_RESOURCE_MISMATCH", "membership owner mismatch")
    else:
        if membership is not None:
            raise err("ERR_RESOURCE_MISMATCH", "membership_id only for CREDIT")

    # --- Priority 8: CREDIT booking requires ACTIVE membership.
    if payment_method == "CREDIT" and membership["status"] != "ACTIVE":
        raise err("ERR_MEMBERSHIP_NOT_ACTIVE", "membership not ACTIVE")

    # --- Priority 9: operating hours + not-in-the-past (ERR_OUTSIDE_HOURS).
    end_utc = add_minutes(start_utc, service["duration_minutes"])
    start_mod = minute_of_day(start_utc)
    # slot end time-of-day = start time-of-day + duration (do not wrap to next day).
    end_mod = start_mod + service["duration_minutes"]
    if start_mod < location["open_minute_of_day"]:
        raise err("ERR_OUTSIDE_HOURS", "start before open")
    if end_mod > location["close_minute_of_day"]:
        raise err("ERR_OUTSIDE_HOURS", "end after close")
    if start_utc < clock.get():
        raise err("ERR_OUTSIDE_HOURS", "start in the past")

    # --- Priority 10: intro eligibility (ERR_INTRO_NOT_ELIGIBLE).
    if payment_method == "INTRO_FREE":
        if member["intro_used"] or not service["intro_eligible"]:
            raise err("ERR_INTRO_NOT_ELIGIBLE", "intro not eligible")

    # --- Priority 11: deposit gating (ERR_DEPOSIT_REQUIRED).
    if payment_method == "CREDIT":
        strikes = member_active_strike_count(member_id)
        if strikes >= NO_SHOW_DEPOSIT_THRESHOLD and membership["tier"] != "UNLIMITED":
            raise err("ERR_DEPOSIT_REQUIRED", "deposit required for this member")

    # --- Priority 12: technician overlap (no buffer, closed-open).
    _check_technician_overlap(technician_id, start_utc, end_utc)
    # --- Priority 13: room overlap (buffer-inclusive, closed-open).
    buffered_end = add_minutes(end_utc, service["buffer_minutes"])
    _check_room_overlap(room_id, start_utc, buffered_end)

    # --- Priority 14: credit sufficiency (ERR_INSUFFICIENT_CREDITS).
    if payment_method == "CREDIT":
        if membership["tier"] != "UNLIMITED":
            if membership_credit_balance(membership_id) < service["credit_cost"]:
                raise err("ERR_INSUFFICIENT_CREDITS", "insufficient credits")

    # === All checks passed: create the reservation and apply side effects. ===
    rid = new_id()
    now = clock.get()
    credits_held = 0
    deposit_held_cents = 0
    settlement_status = "UNSETTLED"

    if payment_method == "CREDIT":
        settlement_status = "CREDIT_HELD"
        # PRD 3.2: "The balance must never drop below zero — a debit that would
        # drive it negative is refused before it is written." PRD 3.3: "An
        # UNLIMITED tier never accumulates a numeric balance." An UNLIMITED pass
        # carries a 0 balance, so debiting it would drive the balance negative;
        # no DEBIT is written and no credits are held against the ledger.
        if membership["tier"] != "UNLIMITED":
            credits_held = service["credit_cost"]
    elif payment_method == "DEPOSIT":
        settlement_status = "DEPOSIT_HELD"
        deposit_held_cents = location["deposit_required_cents"]
    # INTRO_FREE / WALK_IN leave settlement UNSETTLED.

    # Provisional charged_amount_cents (calc reservation_charge, provisional_quote).
    if payment_method == "INTRO_FREE":
        charged = 0
    elif payment_method == "CREDIT":
        charged = 0
    elif payment_method == "DEPOSIT":
        charged = location["deposit_required_cents"]
    else:  # WALK_IN
        charged = service["list_price_cents"]

    res = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "member_id": member_id,
        "location_id": location_id,
        "room_id": room_id,
        "technician_id": technician_id,
        "service_type_id": service_type_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "booking_status": "BOOKED",
        "settlement_status": settlement_status,
        "payment_method": payment_method,
        "membership_id": membership_id if payment_method == "CREDIT" else None,
        "credits_held": credits_held,
        "deposit_held_cents": deposit_held_cents,
        "charged_amount_cents": charged,
    }
    db.reservations[rid] = res

    if payment_method == "CREDIT":
        # PRD 3.4: a CREDIT booking advances the membership's version by 1.
        # For an UNLIMITED tier no DEBIT is written (it never accumulates a
        # numeric balance and the balance must never drop below zero, PRD 3.2/3.3);
        # for every other tier write the DEBIT of -credit_cost.
        if membership["tier"] != "UNLIMITED":
            write_ledger_entry(membership, "DEBIT", -service["credit_cost"],
                               "RESERVATION", rid)
        touch(membership)

    # Holding the slot mutates the room — advance its version by 1.
    touch(room)
    return res


def _terminal_excluded_reservations(field, value, exclude_id=None):
    out = []
    for r in db.reservations.values():
        if r[field] != value:
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if r["booking_status"] in NON_TERMINAL_BOOKING:
            out.append(r)
    return out


def _overlaps(a_start, a_end, b_start, b_end):
    # Closed-open intervals: [a_start, a_end) overlaps [b_start, b_end).
    return a_start < b_end and b_start < a_end


def _check_technician_overlap(technician_id, start_utc, end_utc):
    for r in _terminal_excluded_reservations("technician_id", technician_id):
        svc = db.service_types[r["service_type_id"]]
        other_end = add_minutes(r["start_utc"], svc["duration_minutes"])
        if _overlaps(start_utc, end_utc, r["start_utc"], other_end):
            raise err("ERR_TECH_DOUBLE_BOOKED", "technician double booked")


def _check_room_overlap(room_id, start_utc, buffered_end):
    for r in _terminal_excluded_reservations("room_id", room_id):
        svc = db.service_types[r["service_type_id"]]
        other_end = add_minutes(r["start_utc"], svc["duration_minutes"])
        other_buffered_end = add_minutes(other_end, svc["buffer_minutes"])
        if _overlaps(start_utc, buffered_end, r["start_utc"], other_buffered_end):
            raise err("ERR_ROOM_DOUBLE_BOOKED", "room double booked")


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
def check_in(res):
    # PRD 3.6: permitted only while BOOKED.
    if res["booking_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "reservation not BOOKED")
    # Only once the clock has reached at least 30 minutes before start_utc.
    earliest = add_minutes(res["start_utc"], -30)
    if clock.get() < earliest:
        raise err("ERR_CHECKIN_TOO_EARLY", "check-in too early")
    res["booking_status"] = "CHECKED_IN"
    touch(res)
    return res


def complete(res):
    # PRD 3.6: moves a CHECKED_IN reservation to COMPLETED; settlement -> PAID.
    if res["booking_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "reservation not CHECKED_IN")
    service = db.service_types[res["service_type_id"]]
    pm = res["payment_method"]
    # Final charge (calc reservation_charge, final_charge variant).
    if pm == "INTRO_FREE":
        res["charged_amount_cents"] = 0
        member = db.members[res["member_id"]]
        member["intro_used"] = True
        touch(member)
    elif pm == "CREDIT":
        res["charged_amount_cents"] = 0  # credits already consumed at hold
    elif pm == "DEPOSIT":
        res["charged_amount_cents"] = max(0, service["list_price_cents"]
                                          - res["deposit_held_cents"])
    else:  # WALK_IN
        res["charged_amount_cents"] = service["list_price_cents"]
    res["booking_status"] = "COMPLETED"
    res["settlement_status"] = "PAID"
    touch(res)
    return res


def cancel(res):
    # PRD 3.6: cancellable while BOOKED or CHECKED_IN; branches on timing.
    if res["booking_status"] not in ("BOOKED", "CHECKED_IN"):
        raise err("ERR_INVALID_STATE", "reservation not cancellable")
    timely = clock.get() <= add_minutes(res["start_utc"], -24 * 60)
    if timely:
        _settle_refund(res)
        res["settlement_status"] = "REFUNDED"
    else:
        _mint_strike(res, "LATE_CANCEL")
        _settle_forfeit(res)
        res["settlement_status"] = "FORFEITED"
    _void_pending_retail(res)
    res["booking_status"] = "CANCELLED"
    touch(res)
    return res


def mark_no_show(res):
    # PRD 3.6: mark a BOOKED reservation as no-show; clock >= start + 15m.
    if res["booking_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "reservation not BOOKED")
    if clock.get() < add_minutes(res["start_utc"], 15):
        raise err("ERR_INVALID_STATE", "not yet eligible for no-show")
    _do_no_show(res)
    return res


def _do_no_show(res):
    """No-show cascade shared by the endpoint and the no-show sweep."""
    _mint_strike(res, "NO_SHOW")
    _settle_forfeit(res)
    res["settlement_status"] = "FORFEITED"
    _void_pending_retail(res)
    res["booking_status"] = "NO_SHOW"
    touch(res)


def _settle_refund(res):
    # Timely cancel: CREDIT writes REFUND restoring credits_held; DEPOSIT returns
    # deposit_held_cents to the member's wallet.
    if res["payment_method"] == "CREDIT" and res["credits_held"] > 0:
        membership = db.memberships.get(res["membership_id"])
        if membership is not None:
            write_ledger_entry(membership, "REFUND", res["credits_held"],
                               "RESERVATION", res["id"])
            touch(membership)
    elif res["payment_method"] == "DEPOSIT" and res["deposit_held_cents"] > 0:
        member = db.members[res["member_id"]]
        member["wallet_credit_cents"] += res["deposit_held_cents"]
        touch(member)


def _settle_forfeit(res):
    # Late cancel / no-show: deposit forfeited, credits forfeited (no REFUND).
    # Nothing is written back; the fee is recorded on the NoShowStrike.
    pass


def _mint_strike(res, kind):
    location = db.locations[res["location_id"]]
    if res["payment_method"] == "DEPOSIT" and res["deposit_held_cents"] > 0:
        fee = res["deposit_held_cents"]
    else:
        fee = location["no_show_fee_cents"]
    sid = new_id()
    db.no_show_strikes[sid] = {
        "id": sid,
        "created_at": clock.get(),
        "_seq": db.next_seq(),
        "member_id": res["member_id"],
        "reservation_id": res["id"],
        "strike_kind": kind,
        "fee_charged_cents": fee,
        "status": "ACTIVE",
    }
    # Member.no_show_strike_count is computed; refresh updated_at to reflect the
    # cross-entity change.
    member = db.members[res["member_id"]]
    touch(member)


def _void_pending_retail(res):
    # PRD 3.6 / 3.7: any PENDING retail sale attached to this reservation is
    # voided (no stock change — stock was never decremented while PENDING).
    for rs in db.retail_sales.values():
        if rs["reservation_id"] == res["id"] and rs["status"] == "PENDING":
            rs["status"] = "VOIDED"
            touch(rs)


def release_credits_for_membership_cancel(res, membership):
    """Membership cancel cascade: cancel an open CREDIT reservation, refunding
    its held credits via a REFUND ledger entry (PRD 3.3)."""
    if res["payment_method"] == "CREDIT" and res["credits_held"] > 0:
        write_ledger_entry(membership, "REFUND", res["credits_held"],
                           "RESERVATION", res["id"])
    res["settlement_status"] = "REFUNDED"
    _void_pending_retail(res)
    res["booking_status"] = "CANCELLED"
    touch(res)
