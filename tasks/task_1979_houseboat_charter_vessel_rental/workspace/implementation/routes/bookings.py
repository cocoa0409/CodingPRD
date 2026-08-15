"""Booking creation, retrieval, confirm, modify, cancel (PRD §3.4, §3.5, §3.9)."""

from datetime import timedelta

from flask import Blueprint

import common
import db
import errors
import response
from middleware import check_renter_owner, require_roles
from services import booking_ops, pricing, risk

bp = Blueprint("bookings", __name__)

ALL_ROLES = ("Renter", "DockStaff", "FleetManager", "Mechanic")
HOLD_TTL_HOURS = 48
CANCEL_REASONS = ("RENTER_REQUEST", "WEATHER")
BOOKING_STATUSES = (
    "HELD", "CONFIRMED", "CHECKED_OUT", "INTERRUPTED",
    "RETURNED", "CLOSED", "CANCELLED", "EXPIRED",
)


def load_booking(booking_id):
    booking = db.get("bookings", booking_id)
    if booking is None:
        errors.err(errors.ERR_NOT_FOUND, f"Booking {booking_id} does not exist")
    return booking


def check_booking_owner(booking, user_id, role):
    check_renter_owner(booking["renter_id"], user_id, role)


def check_renter_qualified(renter, end_date):
    """Renter QUALIFIED and holding >= 1 VERIFIED certificate with
    expires_on >= booking.end_date (inclusive)."""
    if renter["qualification_status"] != "QUALIFIED":
        errors.err(errors.ERR_RENTER_NOT_QUALIFIED, "Renter is not QUALIFIED")
    for c in db.all_of("certificates"):
        if (
            c["renter_id"] == renter["id"]
            and c["status"] == "VERIFIED"
            and c["expires_on"] >= end_date
        ):
            return
    errors.err(
        errors.ERR_RENTER_NOT_QUALIFIED,
        "No VERIFIED certificate covers the booking end_date",
    )


def check_booking_dates(start_date, end_date):
    """end > start, total_nights <= 21, start_date >= current_date."""
    if end_date <= start_date:
        errors.err(errors.ERR_BOOKING_DATES_INVALID, "end_date must follow start_date")
    if (end_date - start_date).days > pricing.MAX_BOOKING_NIGHTS:
        errors.err(
            errors.ERR_BOOKING_DATES_INVALID,
            f"Stay exceeds {pricing.MAX_BOOKING_NIGHTS} nights",
        )
    if start_date < db.current_date():
        errors.err(errors.ERR_BOOKING_DATES_INVALID, "start_date lies in the past")


def check_stay_collisions(vessel_id, start_date, end_date, exclude_booking_id=None):
    """Half-open vessel overlap, then closed-interval maintenance conflict."""
    if booking_ops.booking_overlap_exists(vessel_id, start_date, end_date, exclude_booking_id):
        errors.err(
            errors.ERR_VESSEL_DATE_CONFLICT,
            "Stay overlaps another booking of the vessel",
        )
    if booking_ops.maintenance_conflict_exists(vessel_id, start_date, end_date):
        errors.err(
            errors.ERR_MAINTENANCE_DATE_CONFLICT,
            "Stay intersects a maintenance window of the vessel",
        )


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------

@bp.post("/bookings")
@require_roles("Renter")
def create_booking(user_id, role):
    body = common.json_body()
    # Priority 3: renter ownership on the payload renter_id.
    renter_id = body.get("renter_id")
    if renter_id is not None and renter_id != user_id:
        errors.err(
            errors.ERR_NOT_RESOURCE_OWNER,
            "Renter may only create bookings for themselves",
        )
    # Priority 4: payload-referenced ids must exist.
    vessel_id = body.get("vessel_id")
    vessel = db.get("vessels", vessel_id) if isinstance(vessel_id, str) else None
    if vessel_id is not None and vessel is None:
        errors.err(errors.ERR_NOT_FOUND, f"Vessel {vessel_id} does not exist")
    renter = db.get("renters", renter_id) if isinstance(renter_id, str) else None
    if renter_id is not None and renter is None:
        errors.err(errors.ERR_NOT_FOUND, f"Renter {renter_id} does not exist")

    # Priority 5: body well-formedness.
    vessel_id = common.as_str(common.req_field(body, "vessel_id"), "vessel_id")
    renter_id = common.as_str(common.req_field(body, "renter_id"), "renter_id")
    start_date = common.parse_date(common.req_field(body, "start_date"), "start_date")
    end_date = common.parse_date(common.req_field(body, "end_date"), "end_date")
    party_size = common.as_int(common.req_field(body, "party_size"), "party_size")

    # Business rules in the fixed family order (PRD §2.11).
    check_renter_qualified(renter, end_date)                        # p9
    check_booking_dates(start_date, end_date)                       # p11
    check_stay_collisions(vessel["id"], start_date, end_date)       # p12, p13
    quoted = pricing.rental_quote(vessel, start_date, end_date)     # p15
    if party_size < 1 or party_size > vessel["berth_count"]:        # p16
        errors.err(
            errors.ERR_PARTY_EXCEEDS_BERTH,
            "party_size must satisfy 1 <= party_size <= berth_count",
        )

    total_nights = (end_date - start_date).days
    deposit_required = pricing.deposit_requirement(
        vessel["size_class"], renter["risk_score_rolling_24m"]
    )

    rec = db.base_record()
    hold_expires = db.get_clock() + timedelta(hours=HOLD_TTL_HOURS)
    rec.update({
        "vessel_id": vessel["id"],
        "renter_id": renter["id"],
        "start_date": start_date,
        "end_date": end_date,
        "party_size": party_size,
        "status": "HELD",
        "settlement_status": "NONE",
        "deposit_status": "PENDING",
        "orientation_status": "NOT_STARTED",
        "orientation_items": [],
        "total_nights": total_nights,
        "quoted_total_cents": quoted,
        "deposit_required_cents": deposit_required,
        "deposit_held_cents": 0,
        "deposit_applied_cents": 0,
        "deposit_released_cents": 0,
        "refund_issued_cents": 0,
        "provisional_estimate_cents": None,
        "final_settlement_cents": None,
        "checkout_fuel_gauge_percent": None,
        "checkout_pump_out_done": None,
        "return_fuel_gauge_percent": None,
        "return_pump_out_done": None,
        "actual_return_at": None,
        "hold_expires_at": hold_expires,
        "cancellation_reason": None,
    })
    db.insert("bookings", rec)
    return response.ok(common.booking_out(rec), status=201)


@bp.get("/bookings/<bid>")
@require_roles(*ALL_ROLES)
def get_booking(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    return response.ok(common.booking_out(booking))


@bp.get("/bookings")
@require_roles(*ALL_ROLES)
def list_bookings(user_id, role):
    vessel_id = None
    renter_id = None
    status = None
    from flask import request
    if "vessel_id" in request.args:
        vessel_id = request.args.get("vessel_id")
    if "renter_id" in request.args:
        renter_id = request.args.get("renter_id")
    if "status" in request.args:
        status = request.args.get("status")
        if status not in BOOKING_STATUSES:
            errors.err(errors.ERR_INVALID_REQUEST, f"Unknown booking status {status}")

    bookings = db.all_of("bookings")
    if role == "Renter":
        # Renter callers only ever see their own bookings.
        bookings = [b for b in bookings if b["renter_id"] == user_id]
    if vessel_id is not None:
        bookings = [b for b in bookings if b["vessel_id"] == vessel_id]
    if renter_id is not None:
        bookings = [b for b in bookings if b["renter_id"] == renter_id]
    if status is not None:
        bookings = [b for b in bookings if b["status"] == status]

    page, total, limit, offset = common.paginate(bookings)
    return response.list_ok(
        [common.booking_out(b) for b in page], total, limit, offset
    )


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

@bp.post("/bookings/<bid>/confirm")
@require_roles("Renter")
def confirm_booking(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    if booking["status"] != "HELD":
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Booking in state {booking['status']} cannot be confirmed",
        )

    vessel = db.get("vessels", booking["vessel_id"])
    renter = db.get("renters", booking["renter_id"])
    # Creation-time safety net re-run in the fixed family order.
    check_renter_qualified(renter, booking["end_date"])             # p9
    if booking["start_date"] < db.current_date():                   # p11
        errors.err(errors.ERR_BOOKING_DATES_INVALID, "start_date lies in the past")
    check_stay_collisions(                                          # p12, p13
        vessel["id"], booking["start_date"], booking["end_date"],
        exclude_booking_id=booking["id"],
    )
    quoted = pricing.rental_quote(                                  # p15
        vessel, booking["start_date"], booking["end_date"]
    )

    booking["quoted_total_cents"] = quoted
    booking_ops.post_charge(booking["id"], "RENTAL", quoted, "PAID", note="rental prepayment")
    booking["deposit_status"] = "HELD"
    booking["deposit_held_cents"] = booking["deposit_required_cents"]
    booking["orientation_status"] = "IN_PROGRESS"
    booking["orientation_items"] = [
        {"item_code": code, "signed": False}
        for code in pricing.orientation_item_set(vessel["size_class"])
    ]
    booking["status"] = "CONFIRMED"
    db.touch(booking)

    turn = db.base_record()
    turn.update({
        "booking_id": booking["id"],
        "scheduled_date": booking["end_date"],
        "status": "SCHEDULED",
        "re_clean_count": 0,
    })
    db.insert("cleaning_turns", turn)
    return response.ok(common.booking_out(booking))


# ---------------------------------------------------------------------------
# Modify (OCC-guarded)
# ---------------------------------------------------------------------------

@bp.post("/bookings/<bid>/modify")
@require_roles("Renter")
def modify_booking(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    body = common.json_body()
    expected = common.as_int(
        common.req_field(body, "expected_booking_version"), "expected_booking_version"
    )
    start_date = common.parse_date(common.req_field(body, "start_date"), "start_date")
    end_date = common.parse_date(common.req_field(body, "end_date"), "end_date")

    # OCC is evaluated before any other state precondition.
    if expected != booking["version"]:
        errors.err(
            errors.ERR_STALE_VERSION,
            f"expected_booking_version {expected} does not match current version {booking['version']}",
        )
    if booking["status"] not in ("HELD", "CONFIRMED"):
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Booking in state {booking['status']} cannot be modified",
        )

    vessel = db.get("vessels", booking["vessel_id"])
    check_booking_dates(start_date, end_date)                       # p11
    check_stay_collisions(                                          # p12, p13
        vessel["id"], start_date, end_date, exclude_booking_id=booking["id"]
    )
    new_quote = pricing.rental_quote(vessel, start_date, end_date)  # p15

    old_quote = booking["quoted_total_cents"]
    booking["start_date"] = start_date
    booking["end_date"] = end_date
    booking["total_nights"] = (end_date - start_date).days
    booking["quoted_total_cents"] = new_quote

    if booking["status"] == "CONFIRMED" and new_quote != old_quote:
        delta = new_quote - old_quote
        if delta > 0:
            booking_ops.post_charge(
                booking["id"], "RENTAL_ADJUSTMENT", delta, "PAID",
                note="date modification repricing",
            )
        else:
            booking_ops.post_charge(
                booking["id"], "RENTAL_ADJUSTMENT", delta, "REFUNDED",
                note="date modification repricing",
            )
            booking["refund_issued_cents"] += -delta

    for t in db.all_of("cleaning_turns"):
        if t["booking_id"] == booking["id"] and t["status"] == "SCHEDULED":
            t["scheduled_date"] = end_date
            db.touch(t)

    db.touch(booking)
    return response.ok(common.booking_out(booking))


# ---------------------------------------------------------------------------
# Cancel (OCC-guarded)
# ---------------------------------------------------------------------------

@bp.post("/bookings/<bid>/cancel")
@require_roles("Renter")
def cancel_booking(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    body = common.json_body()
    expected = common.as_int(
        common.req_field(body, "expected_booking_version"), "expected_booking_version"
    )
    reason = common.opt_field(body, "reason")
    if reason is not None:
        common.as_enum(reason, "reason", CANCEL_REASONS)

    # OCC is evaluated before any other check of the operation.
    if expected != booking["version"]:
        errors.err(
            errors.ERR_STALE_VERSION,
            f"expected_booking_version {expected} does not match current version {booking['version']}",
        )
    if booking["status"] not in ("HELD", "CONFIRMED"):
        errors.err(
            errors.ERR_BOOKING_NOT_CANCELLABLE,
            f"Booking in state {booking['status']} cannot be cancelled",
        )

    booking_ops.cancel_booking(booking, reason, system=False)
    return response.ok(common.booking_out(booking))
