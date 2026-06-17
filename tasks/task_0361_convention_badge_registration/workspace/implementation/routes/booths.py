"""Booth and BoothBooking endpoints (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import common
import db
import errors
import util
from middleware import authenticate, authorize
from services import calc, lookup
import response

bp = Blueprint("booths", __name__)

READ_ROLES = {"ConventionAdmin", "RegistrationAgent", "Exhibitor"}
ZONES = {"STANDARD", "PREMIUM", "ENDCAP"}


# --------------------------------------------------------------------------- #
# Booth
# --------------------------------------------------------------------------- #
@bp.route("/conventions/<cid>/booths", methods=["POST"])
def create_booth(cid):
    _, role = authenticate()
    authorize(role, {"ConventionAdmin"})
    conv = lookup.convention(cid)
    body = common.get_body()

    booth_code = common.require_str(body, "booth_code")
    zone = common.require_enum(body, "zone", ZONES)
    setup_buffer = common.optional_int(body, "setup_buffer_hours", 12, minimum=0)

    # booth_code unique within the convention (PRD §3.7).
    for b in db.booths.values():
        if b["convention_id"] == conv["id"] and b["booth_code"] == booth_code:
            raise errors.err(errors.ERR_DUPLICATE_BOOTH_CODE, "Booth code already exists in this convention")

    row = common.common_fields()
    row.update({
        "convention_id": conv["id"],
        "booth_code": booth_code,
        "zone": zone,
        "setup_buffer_hours": setup_buffer,
    })
    db.booths[row["id"]] = row
    return response.success(common.serialize(row), 201)


@bp.route("/conventions/<cid>/booths", methods=["GET"])
def list_booths(cid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    conv = lookup.convention(cid)
    rows = [b for b in db.booths.values() if b["convention_id"] == conv["id"]]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/booths/<bid>", methods=["GET"])
def get_booth(bid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    b = lookup.booth(bid)
    return response.success(common.serialize(b), 200)


# --------------------------------------------------------------------------- #
# Exhibitor booth-charge recompute (PRD §3.7)
# --------------------------------------------------------------------------- #
def recompute_estimated(exhibitor):
    """estimated_booth_cents over bookings in {RESERVED, CHECKED_IN}, billing requested_days."""
    total = 0
    for bk in db.booth_bookings.values():
        if bk["exhibitor_id"] == exhibitor["id"] and bk["status"] in {"RESERVED", "CHECKED_IN"}:
            booth = db.booths.get(bk["booth_id"])
            if booth is None:
                continue
            total += calc.ZONE_DAILY_RATE[booth["zone"]] * bk["requested_days"]
    exhibitor["estimated_booth_cents"] = total
    common.touch(exhibitor)


def recompute_actual(exhibitor):
    """actual_booth_cents over CHECKED_IN bookings, billing occupied_days."""
    total = 0
    for bk in db.booth_bookings.values():
        if bk["exhibitor_id"] == exhibitor["id"] and bk["status"] == "CHECKED_IN":
            booth = db.booths.get(bk["booth_id"])
            if booth is None:
                continue
            total += calc.ZONE_DAILY_RATE[booth["zone"]] * bk["occupied_days"]
    exhibitor["actual_booth_cents"] = total
    common.touch(exhibitor)


# --------------------------------------------------------------------------- #
# BoothBooking
# --------------------------------------------------------------------------- #
@bp.route("/booth-bookings", methods=["POST"])
def create_booth_booking():
    user_id, role = authenticate()
    authorize(role, {"Exhibitor", "ConventionAdmin"})
    body = common.get_body()

    # Existence: body FKs resolved left-to-right (PRD §2.8).
    booth_id = common.require_str(body, "booth_id")
    exhibitor_id = common.require_str(body, "exhibitor_id")
    booth = lookup.booth(booth_id)
    exhibitor = lookup.exhibitor(exhibitor_id)

    # Ownership: Exhibitor may only book for itself (PRD §2.1).
    lookup.require_exhibitor_owns(role, user_id, exhibitor_id)

    occupy_start = common.require_datetime(body, "occupy_start_utc")
    occupy_end = common.require_datetime(body, "occupy_end_utc")
    if occupy_end <= occupy_start:
        raise errors.err(errors.ERR_INVALID_REQUEST, "occupy_end_utc must be strictly after occupy_start_utc")
    requested_days = common.require_int(body, "requested_days", minimum=1)

    # Buffer-expanded closed-interval overlap on the same booth against other
    # RESERVED/CHECKED_IN bookings (PRD §3.7). Buffer comes from the booth.
    buffer = timedelta(hours=booth["setup_buffer_hours"])
    new_lo = occupy_start - buffer
    new_hi = occupy_end + buffer
    for bk in db.booth_bookings.values():
        if bk["booth_id"] != booth_id or bk["status"] not in {"RESERVED", "CHECKED_IN"}:
            continue
        ex_start = util.parse_iso(bk["occupy_start_utc"])
        ex_end = util.parse_iso(bk["occupy_end_utc"])
        ex_buffer = timedelta(hours=booth["setup_buffer_hours"])
        ex_lo = ex_start - ex_buffer
        ex_hi = ex_end + ex_buffer
        # Closed-interval overlap: any shared instant counts (PRD §3.7).
        if new_lo <= ex_hi and ex_lo <= new_hi:
            raise errors.err(errors.ERR_BOOTH_TIME_CONFLICT, "Booth interval conflicts with an existing booking")

    row = common.common_fields()
    row.update({
        "booth_id": booth_id,
        "exhibitor_id": exhibitor_id,
        "occupy_start_utc": body["occupy_start_utc"],
        "occupy_end_utc": body["occupy_end_utc"],
        "requested_days": requested_days,
        "occupied_days": 0,
        "status": "RESERVED",
    })
    db.booth_bookings[row["id"]] = row
    # Creating a booking recomputes estimated_booth_cents (PRD §3.7).
    recompute_estimated(exhibitor)
    return response.success(common.serialize(row), 201)


@bp.route("/booth-bookings/<bid>", methods=["GET"])
def get_booth_booking(bid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    bk = lookup.booth_booking(bid)
    return response.success(common.serialize(bk), 200)


@bp.route("/booth-bookings", methods=["GET"])
def list_booth_bookings():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    rows = list(db.booth_bookings.values())
    booth_filter = request.args.get("booth_id")
    ex_filter = request.args.get("exhibitor_id")
    if booth_filter is not None:
        rows = [r for r in rows if r["booth_id"] == booth_filter]
    if ex_filter is not None:
        rows = [r for r in rows if r["exhibitor_id"] == ex_filter]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/booth-bookings/<bid>/check-in", methods=["POST"])
def check_in_booking(bid):
    user_id, role = authenticate()
    authorize(role, {"Exhibitor", "RegistrationAgent"})
    bk = lookup.booth_booking(bid)
    lookup.require_exhibitor_owns(role, user_id, bk["exhibitor_id"])

    if bk["status"] != "RESERVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Booking is not RESERVED")

    booth = db.booths[bk["booth_id"]]
    conv = db.conventions[booth["convention_id"]]
    # On-site window gate (PRD §3.7, §3.5).
    event_start = util.parse_iso(conv["event_start_utc"])
    window_open = event_start - timedelta(hours=calc.PICKUP_WINDOW_HOURS)
    if clock.now() < window_open:
        raise errors.err(errors.ERR_PICKUP_WINDOW_CLOSED, "On-site window not open")

    bk["status"] = "CHECKED_IN"
    bk["occupied_days"] = bk["requested_days"]
    common.touch(bk)
    exhibitor = db.exhibitors[bk["exhibitor_id"]]
    recompute_actual(exhibitor)
    return response.success(common.serialize(bk), 200)


@bp.route("/booth-bookings/<bid>/release", methods=["POST"])
def release_booking(bid):
    user_id, role = authenticate()
    authorize(role, {"Exhibitor", "RegistrationAgent"})
    bk = lookup.booth_booking(bid)
    lookup.require_exhibitor_owns(role, user_id, bk["exhibitor_id"])

    if bk["status"] not in {"RESERVED", "CHECKED_IN"}:
        raise errors.err(errors.ERR_INVALID_STATE, "Booking cannot be released from its current state")

    bk["status"] = "RELEASED"
    common.touch(bk)
    # Recompute estimated excluding this booking; actual retains billed occupied_days.
    exhibitor = db.exhibitors[bk["exhibitor_id"]]
    recompute_estimated(exhibitor)
    return response.success(common.serialize(bk), 200)
