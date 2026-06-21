"""Booking core lifecycle endpoints."""
from flask import Blueprint, request

import calculations as calc
import clock as clockmod
import db
from errors import (ApiError, invalid_request, invalid_state, not_resource_owner,
                    stale_version, ERR_BACKUP_IS_PRIMARY, ERR_BALANCE_OUTSTANDING,
                    ERR_EVENT_IN_PAST, ERR_NO_ELIGIBLE_BACKUP,
                    ERR_NOT_LOWEST_RANK_BACKUP, ERR_PACKAGE_RETIRED,
                    ERR_PERFORMER_BLACKED_OUT, ERR_PERFORMER_DOUBLE_BOOKED,
                    ERR_SET_TOO_SHORT)
from middleware import authenticate, require_roles
from response import array_response, object_response
from services import (equipment_unit_fees_for_package, get_or_404,
                      get_or_ref_404, refresh_ledger)
from timeutil import parse_iso
from validate import (get_json_body, opt_int, parse_pagination, paginate,
                      require_int, require_str_field)

bp = Blueprint("bookings", __name__)

NON_TERMINAL_BOOKING_STATES = {
    "INQUIRY", "HOLD", "CONTRACT_SENT", "NEGOTIATING", "CONFIRMED", "PERFORMING",
}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.post("/bookings")
def create_booking():
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    body = get_json_body()

    # FK fields must at least be present strings before existence can be
    # checked. Body-FK existence (priority 5) precedes generic well-formedness
    # of the remaining fields (priority 6), so resolve FKs first.
    client_id = require_str_field(body, "client_id")
    performer_id = require_str_field(body, "performer_id")
    package_id = require_str_field(body, "package_id")
    event_zone_id = require_str_field(body, "event_zone_id")

    # Body FK existence (priority 5) — left to right per declared input order.
    client = get_or_ref_404(db.clients, client_id)
    performer = get_or_ref_404(db.performers, performer_id)
    package = get_or_ref_404(db.packages, package_id)
    event_zone = get_or_ref_404(db.travel_zones, event_zone_id)

    # Well-formedness of the remaining (non-FK) fields (priority 6).
    event_start_raw = body.get("event_start_utc")
    if event_start_raw is None:
        raise invalid_request("Missing required field: event_start_utc")
    miles = require_int(body, "event_miles_from_home", minimum=0)
    contracted_in = opt_int(body, "contracted_set_minutes", default=None)
    event_start = parse_iso(event_start_raw, "event_start_utc")

    # Business referential: package must be ACTIVE (priority 7).
    if package["status"] != "ACTIVE":
        raise ApiError(ERR_PACKAGE_RETIRED, 409, "Package is retired")

    # Temporal: event strictly in the future (priority 10).
    if not (event_start > clockmod.now()):
        raise ApiError(ERR_EVENT_IN_PAST, 422,
                       "event_start_utc must be strictly in the future")

    # contracted_set_minutes default + lower bound (priority 14).
    if contracted_in is None:
        contracted = package["included_set_minutes"]
    else:
        contracted = contracted_in
        if contracted < package["included_set_minutes"]:
            raise ApiError(ERR_SET_TOO_SHORT, 422,
                           "contracted_set_minutes below package included minutes")

    rec = db.make_common()
    rec.update({
        "client_id": client["id"],
        "performer_id": performer["id"],
        "package_id": package["id"],
        "event_zone_id": event_zone["id"],
        "event_start_utc": event_start_raw,
        "contracted_set_minutes": contracted,
        "event_miles_from_home": miles,
        "actual_set_minutes": None,
        "status": "INQUIRY",
        "quote_total_cents": 0,
        "final_total_cents": 0,
        "overtime_cents": 0,
        "deposit_required_cents": 0,
        "amount_paid_cents": 0,
        "balance_due_cents": 0,
        "cancellation_fee_cents": 0,
        "active_performer_id": None,
    })
    db.bookings[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/bookings/<bid>")
def get_booking(bid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    rec = get_or_404(db.bookings, bid)
    return object_response(rec)


@bp.get("/bookings")
def list_bookings():
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    limit, offset = parse_pagination()
    rows = list(db.bookings.values())
    for field in ("client_id", "performer_id", "active_performer_id",
                  "package_id", "event_zone_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_quote(booking):
    performer = db.performers[booking["performer_id"]]
    package = db.packages[booking["package_id"]]
    event_zone = db.travel_zones[booking["event_zone_id"]]
    travel = calc.travel_fee(booking["event_zone_id"], performer, event_zone,
                             booking["event_miles_from_home"])
    fees = equipment_unit_fees_for_package(package["id"])
    return calc.booking_quote_total(performer, package, fees, travel)


# ---------------------------------------------------------------------------
# INQUIRY -> HOLD
# ---------------------------------------------------------------------------
@bp.post("/bookings/<bid>/hold")
def hold_booking(bid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    booking = get_or_404(db.bookings, bid)

    if booking["status"] != "INQUIRY":
        raise invalid_state("hold is only legal from INQUIRY")

    performer = db.performers[booking["performer_id"]]
    package = db.packages[booking["package_id"]]

    # Performer must be AVAILABLE or ON_HOLD.
    if performer["availability_status"] not in ("AVAILABLE", "ON_HOLD"):
        raise invalid_state("performer is not available for a hold")

    event_start = parse_iso(booking["event_start_utc"], "event_start_utc")

    # Blackout check (priority 11): start in [w.start, w.end).
    for w in db.blackout_windows.values():
        if w["performer_id"] != performer["id"]:
            continue
        w_start = parse_iso(w["start_utc"], "start_utc")
        w_end = parse_iso(w["end_utc"], "end_utc")
        if w_start <= event_start < w_end:
            raise ApiError(ERR_PERFORMER_BLACKED_OUT, 409,
                           "event start falls inside a performer blackout window")

    # Double-booking check (priority 12): set window vs other non-terminal
    # bookings of the same performer. The set window is
    # [event_start, event_start + contracted_set_minutes). Closed-buffer
    # semantics: two windows collide when one starts before the other ends and
    # vice versa (half-open overlap).
    from datetime import timedelta
    this_start = event_start
    this_end = event_start + timedelta(minutes=booking["contracted_set_minutes"])
    for other in db.bookings.values():
        if other["id"] == booking["id"]:
            continue
        if other["status"] not in NON_TERMINAL_BOOKING_STATES:
            continue
        # Compare against the other booking's active performer (its hooked act).
        other_perf = other.get("active_performer_id") or other["performer_id"]
        if other_perf != performer["id"]:
            continue
        o_start = parse_iso(other["event_start_utc"], "event_start_utc")
        o_end = o_start + timedelta(minutes=other["contracted_set_minutes"])
        if this_start < o_end and o_start < this_end:
            raise ApiError(ERR_PERFORMER_DOUBLE_BOOKED, 409,
                           "performer is already booked in an overlapping window")

    # Side effects.
    quote = _compute_quote(booking)
    booking["quote_total_cents"] = quote
    booking["deposit_required_cents"] = calc.deposit_required(
        quote, package["deposit_pct_bps"])
    booking["active_performer_id"] = performer["id"]
    booking["status"] = "HOLD"
    refresh_ledger(booking)
    db.touch(booking)

    performer["availability_status"] = "ON_HOLD"
    db.touch(performer)

    return object_response(booking)


# ---------------------------------------------------------------------------
# issue-contract: HOLD->CONTRACT_SENT and NEGOTIATING->CONTRACT_SENT
# ---------------------------------------------------------------------------
@bp.post("/bookings/<bid>/issue-contract")
def issue_contract(bid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    booking = get_or_404(db.bookings, bid)
    body = get_json_body()
    expected = require_int(body, "expected_booking_version")

    if booking["status"] not in ("HOLD", "NEGOTIATING"):
        raise invalid_state("issue-contract is only legal from HOLD or NEGOTIATING")

    # OCC check (priority 9) runs after state legality.
    if expected != booking["version"]:
        raise stale_version()

    if booking["status"] == "HOLD":
        # No deposit may have been captured yet.
        for p in db.payments.values():
            if (p["booking_id"] == booking["id"] and p["kind"] == "DEPOSIT"
                    and p["capture_status"] == "CAPTURED"):
                raise invalid_state("deposit already captured")
        revision = 1
    else:  # NEGOTIATING
        # Supersede any still-ISSUED contract on the booking.
        max_rev = 0
        for c in db.contracts.values():
            if c["booking_id"] != booking["id"]:
                continue
            max_rev = max(max_rev, c["revision"])
            if c["status"] == "ISSUED":
                c["status"] = "SUPERSEDED"
                db.touch(c)
        revision = max_rev + 1

    contract = db.make_common()
    contract.update({
        "booking_id": booking["id"],
        "revision": revision,
        "quoted_total_cents": booking["quote_total_cents"],
        "status": "ISSUED",
    })
    db.contracts[contract["id"]] = contract

    booking["status"] = "CONTRACT_SENT"
    db.touch(booking)
    return object_response(booking)


# ---------------------------------------------------------------------------
# CONTRACT_SENT -> NEGOTIATING (request-revision)
# ---------------------------------------------------------------------------
@bp.post("/bookings/<bid>/request-revision")
def request_revision(bid):
    caller = authenticate()
    require_roles(caller, {"Client"})
    booking = get_or_404(db.bookings, bid)
    # Ownership (priority 3).
    if caller.user_id != booking["client_id"]:
        raise not_resource_owner()

    if booking["status"] != "CONTRACT_SENT":
        raise invalid_state("request-revision is only legal from CONTRACT_SENT")

    # Current contract must be ISSUED.
    current = _current_issued_contract(booking["id"])
    if current is None:
        raise invalid_state("no ISSUED contract to revise")

    current["status"] = "DECLINED"
    db.touch(current)
    booking["status"] = "NEGOTIATING"
    db.touch(booking)
    return object_response(booking)


def _current_issued_contract(booking_id):
    issued = [c for c in db.contracts.values()
              if c["booking_id"] == booking_id and c["status"] == "ISSUED"]
    if not issued:
        return None
    issued.sort(key=lambda c: c["revision"], reverse=True)
    return issued[0]


# ---------------------------------------------------------------------------
# CONFIRMED -> PERFORMING (start-set)
# ---------------------------------------------------------------------------
@bp.post("/bookings/<bid>/start-set")
def start_set(bid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    booking = get_or_404(db.bookings, bid)
    if booking["status"] != "CONFIRMED":
        raise invalid_state("start-set is only legal from CONFIRMED")
    event_start = parse_iso(booking["event_start_utc"], "event_start_utc")
    if clockmod.now() < event_start:
        raise invalid_state("clock has not reached event_start_utc")
    booking["status"] = "PERFORMING"
    db.touch(booking)
    return object_response(booking)


# ---------------------------------------------------------------------------
# PERFORMING -> PERFORMED (complete-set)
# ---------------------------------------------------------------------------
@bp.post("/bookings/<bid>/complete-set")
def complete_set(bid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    booking = get_or_404(db.bookings, bid)
    body = get_json_body()
    actual = require_int(body, "actual_set_minutes", minimum=0)

    if booking["status"] != "PERFORMING":
        raise invalid_state("complete-set is only legal from PERFORMING")

    performer = db.performers[booking["active_performer_id"]]
    overtime = calc.overtime_charge(actual, booking["contracted_set_minutes"],
                                    performer["overtime_rate_cents_per_15min"])
    booking["actual_set_minutes"] = actual
    booking["overtime_cents"] = overtime
    booking["final_total_cents"] = booking["quote_total_cents"] + overtime
    booking["status"] = "PERFORMED"
    refresh_ledger(booking)
    db.touch(booking)

    performer["availability_status"] = "AVAILABLE"
    performer["lifetime_completed_sets"] += 1
    db.touch(performer)
    return object_response(booking)


# ---------------------------------------------------------------------------
# PERFORMED -> SETTLED (settle)
# ---------------------------------------------------------------------------
@bp.post("/bookings/<bid>/settle")
def settle_booking(bid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    booking = get_or_404(db.bookings, bid)
    if booking["status"] != "PERFORMED":
        raise invalid_state("settle is only legal from PERFORMED")
    refresh_ledger(booking)
    if booking["balance_due_cents"] > 0:
        raise ApiError(ERR_BALANCE_OUTSTANDING, 409,
                       "balance still outstanding")
    for p in db.payments.values():
        if (p["booking_id"] == booking["id"]
                and p["capture_status"] == "CAPTURED"
                and p["settlement_status"] == "UNSETTLED"):
            p["settlement_status"] = "SETTLED"
            db.touch(p)
    booking["status"] = "SETTLED"
    db.touch(booking)
    return object_response(booking)


# ---------------------------------------------------------------------------
# cancel: from HOLD, CONTRACT_SENT, NEGOTIATING, CONFIRMED
# ---------------------------------------------------------------------------
@bp.post("/bookings/<bid>/cancel")
def cancel_booking(bid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent", "Client"})
    booking = get_or_404(db.bookings, bid)
    if caller.role == "Client" and caller.user_id != booking["client_id"]:
        raise not_resource_owner()

    if booking["status"] not in ("HOLD", "CONTRACT_SENT", "NEGOTIATING",
                                 "CONFIRMED"):
        raise invalid_state("cancel is not legal from current state")

    status_at_cancel = booking["status"]
    event_start = parse_iso(booking["event_start_utc"], "event_start_utc")
    fee = calc.cancellation_fee(booking["quote_total_cents"], event_start,
                                clockmod.now(), status_at_cancel)
    booking["cancellation_fee_cents"] = fee

    # Refund each CAPTURED payment. Refundable portion = amount_paid - fee.
    refresh_ledger(booking)
    refundable = booking["amount_paid_cents"] - fee
    if refundable < 0:
        refundable = 0
    for p in db.payments.values():
        if (p["booking_id"] == booking["id"]
                and p["capture_status"] == "CAPTURED"
                and p["settlement_status"] == "UNSETTLED"):
            p["settlement_status"] = "REFUNDED"
            db.touch(p)
            if p["refund_destination"] == "STORE_CREDIT":
                client = db.clients[booking["client_id"]]
                client["store_credit_cents"] += refundable
                db.touch(client)

    # Contracts: ISSUED/SIGNED -> DECLINED.
    for c in db.contracts.values():
        if c["booking_id"] == booking["id"] and c["status"] in ("ISSUED", "SIGNED"):
            c["status"] = "DECLINED"
            db.touch(c)

    # Backups: OFFERED/ACCEPTED -> EXPIRED.
    for ba in db.backup_assignments.values():
        if ba["booking_id"] == booking["id"] and ba["status"] in ("OFFERED",
                                                                   "ACCEPTED"):
            ba["status"] = "EXPIRED"
            db.touch(ba)

    # Active performer back to AVAILABLE.
    if booking["active_performer_id"]:
        perf = db.performers.get(booking["active_performer_id"])
        if perf is not None:
            perf["availability_status"] = "AVAILABLE"
            db.touch(perf)

    booking["status"] = "CANCELLED"
    refresh_ledger(booking)
    db.touch(booking)
    return object_response(booking)


# ---------------------------------------------------------------------------
# promote-backup
# ---------------------------------------------------------------------------
@bp.post("/bookings/<bid>/promote-backup")
def promote_backup(bid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    booking = get_or_404(db.bookings, bid)
    body = get_json_body()
    # FK existence (priority 5): targeted assignment must exist and belong to
    # this booking.
    target_id = require_str_field(body, "backup_assignment_id")
    target = db.backup_assignments.get(target_id)
    if target is None or target["booking_id"] != booking["id"]:
        from errors import referenced_not_found
        raise referenced_not_found()

    # Remaining well-formedness (priority 6).
    expected = require_int(body, "expected_booking_version")

    # State legality (priority 8): booking must be CONFIRMED or PERFORMING.
    if booking["status"] not in ("CONFIRMED", "PERFORMING"):
        raise invalid_state("promote-backup is only legal from CONFIRMED/PERFORMING")

    # OCC (priority 9).
    if expected != booking["version"]:
        raise stale_version()

    # Eligible ACCEPTED backups (priority 16 then 15).
    accepted = [ba for ba in db.backup_assignments.values()
                if ba["booking_id"] == booking["id"] and ba["status"] == "ACCEPTED"]
    if not accepted:
        raise ApiError(ERR_NO_ELIGIBLE_BACKUP, 409,
                       "no accepted backup for this booking")

    def sort_key(ba):
        perf = db.performers[ba["candidate_performer_id"]]
        return (ba["rank"], -perf["reliability_score"], ba["created_at"],
                ba.get("_seq", 0))

    accepted.sort(key=sort_key)
    eligible = accepted[0]

    if target["status"] != "ACCEPTED" or target["id"] != eligible["id"]:
        raise ApiError(ERR_NOT_LOWEST_RANK_BACKUP, 409,
                       "targeted backup is not the lowest-rank eligible one")

    # Promote.
    former_perf = db.performers.get(booking["active_performer_id"])
    new_perf = db.performers[eligible["candidate_performer_id"]]

    eligible["status"] = "PROMOTED"
    db.touch(eligible)

    booking["active_performer_id"] = new_perf["id"]

    if former_perf is not None and former_perf["id"] != new_perf["id"]:
        former_perf["availability_status"] = "AVAILABLE"
        former_perf["reliability_score"] = max(0, former_perf["reliability_score"] - 10)
        db.touch(former_perf)

    new_perf["availability_status"] = "BOOKED"
    db.touch(new_perf)

    # Expire all other OFFERED/ACCEPTED backups on this booking.
    for ba in db.backup_assignments.values():
        if ba["id"] == eligible["id"]:
            continue
        if ba["booking_id"] == booking["id"] and ba["status"] in ("OFFERED",
                                                                   "ACCEPTED"):
            ba["status"] = "EXPIRED"
            db.touch(ba)

    db.touch(booking)
    return object_response(booking)
