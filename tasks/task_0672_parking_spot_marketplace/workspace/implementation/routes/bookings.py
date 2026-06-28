"""Booking lifecycle: create (quote + charge + OCC), reads, and state transitions
(check-in, check-out, cancel, mark-no-show, reverse-payout)."""
from flask import Blueprint, request

from clock import clock
from db import db, make_versioned, make_lightweight, new_id, touch
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE,
    ERR_STALE_SPOT_VERSION,
    ERR_STALE_BOOKING_VERSION,
    ERR_NO_REVERSIBLE_PAYOUT,
    ERR_INVALID_WINDOW,
    ERR_CHECKIN_WINDOW_CLOSED,
    ERR_SPOT_TIME_CONFLICT,
    ERR_SPOT_UNLISTED,
    ERR_DRIVER_SUSPENDED,
    ERR_INSUFFICIENT_WALLET,
)
from middleware import require_auth, require_role
from response import success, success_list
from serialize import (
    booking_view,
    transfer_offer_view,
    violation_view,
    access_pass_view,
    ledger_entry_view,
)
from util import (
    require_body,
    require_str,
    require_int,
    require_enum,
    require_datetime,
    parse_pagination,
    paginate,
)
from services import calculations as calc
from services import domain

bp = Blueprint("bookings", __name__)

RATE_KINDS = {"HOURLY", "DAILY", "MONTHLY"}
THIRTY_DAYS_S = 30 * 86400


def _find_matching_event(spot, start_at):
    """Among ACTIVE pricing events for the spot's zone whose [window_start, window_end)
    contains start_at, pick the highest surge_multiplier_bps, tie-break earliest created."""
    candidates = []
    for ev in db.pricing_events.values():
        if ev["status"] != "ACTIVE" or ev["zone_code"] != spot["zone_code"]:
            continue
        if ev["_window_start_dt"] <= start_at < ev["_window_end_dt"]:
            candidates.append(ev)
    if not candidates:
        return None
    # Highest surge first; tie-break earliest creation (_seq ascending).
    candidates.sort(key=lambda e: (-e["surge_multiplier_bps"], e["_seq"]))
    return candidates[0]


@bp.post("/bookings")
def create_booking():
    caller = require_auth()
    require_role(caller, "Driver")
    data = require_body(request.get_json(silent=True))

    # Extract referenced IDs for existence checks (these are structurally required).
    spot_id = require_str(data, "spot_id")
    driver_id = require_str(data, "driver_id")

    # Existence (priority 3), validated left-to-right: spot then driver.
    spot = db.spots.get(spot_id)
    if spot is None:
        raise err(ERR_NOT_FOUND, "Spot not found.")
    driver = db.drivers.get(driver_id)
    if driver is None:
        raise err(ERR_NOT_FOUND, "Driver not found.")

    # Ownership (priority 4): acting Driver must hold the booking (driver_id == caller).
    if driver_id != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "driver_id must match the acting driver.")

    # OCC (priority 11): expected_spot_version must match spot.version.
    expected_spot_version = require_int(data, "expected_spot_version")
    if expected_spot_version != spot["version"]:
        raise err(ERR_STALE_SPOT_VERSION, "expected_spot_version does not match spot.")

    # Remaining body shape for window computation.
    rate_kind = require_enum(data, "rate_kind", RATE_KINDS)
    start_at = require_datetime(data, "start_at")
    end_at = require_datetime(data, "end_at")

    # Temporal window (priority 20): end>start, inside availability, MONTHLY==30d.
    if end_at <= start_at:
        raise err(ERR_INVALID_WINDOW, "end_at must be after start_at.")
    if not (spot["_availability_start_dt"] <= start_at
            and end_at <= spot["_availability_end_dt"]):
        raise err(ERR_INVALID_WINDOW, "Window must lie within spot availability.")
    if rate_kind == "MONTHLY":
        if (end_at - start_at).total_seconds() != THIRTY_DAYS_S:
            raise err(ERR_INVALID_WINDOW, "MONTHLY window must be exactly 30 days.")

    # Spot time conflict (priority 30): half-open overlap with RESERVED/CHECKED_IN/CHECKED_OUT.
    for b in db.bookings.values():
        if b["spot_id"] != spot_id:
            continue
        if b["occupancy_status"] not in ("RESERVED", "CHECKED_IN", "CHECKED_OUT"):
            continue
        if start_at < b["_end_at_dt"] and b["_start_at_dt"] < end_at:
            raise err(ERR_SPOT_TIME_CONFLICT, "Window overlaps an existing booking on this spot.")

    # Spot listed (priority 40).
    if spot["listing_status"] != "LISTED":
        raise err(ERR_SPOT_UNLISTED, "Spot is not LISTED.")

    # Driver not suspended (priority 41).
    if driver["standing_tier"] == "SUSPENDED":
        raise err(ERR_DRIVER_SUSPENDED, "Driver is suspended.")

    # Quote (frozen).
    matched_event = _find_matching_event(spot, start_at)
    quoted = calc.booking_quote_amount(rate_kind, start_at, end_at, spot, matched_event)

    # Wallet funding (priority 50): must cover the charge; reject before any mutation.
    if driver["wallet_balance_cents"] < quoted:
        raise err(ERR_INSUFFICIENT_WALLET, "Insufficient wallet balance for booking charge.")

    # Commit.
    booking = make_versioned(
        {
            "spot_id": spot_id,
            "driver_id": driver_id,
            "rate_kind": rate_kind,
            "start_at": data["start_at"],
            "end_at": data["end_at"],
            "quoted_amount_cents": quoted,
            "final_amount_cents": None,
            "occupancy_status": "RESERVED",
            "settlement_status": "SETTLED",
            "actual_checkin_at": None,
            "actual_checkout_at": None,
            "transfer_count": 0,
            "_start_at_dt": start_at,
            "_end_at_dt": end_at,
        }
    )
    db.bookings[booking["id"]] = booking
    # Debit driver wallet; mutation -> touch driver.
    driver["wallet_balance_cents"] -= quoted
    touch(driver)
    # Spot version bump (availability footprint changed).
    touch(spot)
    return success(booking_view(booking), status=201)


@bp.get("/bookings/<booking_id>")
def get_booking(booking_id):
    caller = require_auth()
    require_role(caller, "Driver", "Host", "PlatformAdmin")
    rec = db.bookings.get(booking_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    return success(booking_view(rec))


@bp.get("/bookings")
def list_bookings():
    caller = require_auth()
    require_role(caller, "Driver", "Host", "PlatformAdmin")
    limit, offset = parse_pagination(request.args)
    driver_id = request.args.get("driver_id")
    spot_id = request.args.get("spot_id")
    items = list(db.bookings.values())
    if driver_id is not None:
        items = [b for b in items if b["driver_id"] == driver_id]
    if spot_id is not None:
        items = [b for b in items if b["spot_id"] == spot_id]
    items.sort(key=lambda b: b["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([booking_view(b) for b in page], limit, offset, total)


@bp.get("/bookings/<booking_id>/transfer-offers")
def list_booking_transfer_offers(booking_id):
    caller = require_auth()
    require_role(caller, "Driver", "PlatformAdmin")
    if booking_id not in db.bookings:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    limit, offset = parse_pagination(request.args)
    items = [t for t in db.transfer_offers.values() if t["booking_id"] == booking_id]
    items.sort(key=lambda t: t["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([transfer_offer_view(t) for t in page], limit, offset, total)


@bp.get("/bookings/<booking_id>/violations")
def list_booking_violations(booking_id):
    caller = require_auth()
    require_role(caller, "Driver", "Host", "PlatformAdmin")
    if booking_id not in db.bookings:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    limit, offset = parse_pagination(request.args)
    items = [v for v in db.violations.values() if v["booking_id"] == booking_id]
    items.sort(key=lambda v: v["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([violation_view(v) for v in page], limit, offset, total)


@bp.get("/bookings/<booking_id>/access-pass")
def get_booking_access_pass(booking_id):
    caller = require_auth()
    require_role(caller, "Driver", "PlatformAdmin")
    if booking_id not in db.bookings:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    items = [p for p in db.access_passes.values() if p["booking_id"] == booking_id]
    items.sort(key=lambda p: p["_seq"])
    # Array of 0-1.
    return success_list([access_pass_view(p) for p in items], 10, 0, len(items))


@bp.get("/bookings/<booking_id>/ledger-entries")
def list_booking_ledger_entries(booking_id):
    caller = require_auth()
    require_role(caller, "Host", "PlatformAdmin")
    if booking_id not in db.bookings:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.ledger_entries.values() if e["booking_id"] == booking_id]
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([ledger_entry_view(e) for e in page], limit, offset, total)


@bp.post("/bookings/<booking_id>/check-in")
def check_in(booking_id):
    caller = require_auth()
    require_role(caller, "Driver")
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if booking["driver_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Driver does not hold this booking.")
    if booking["occupancy_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Booking is not RESERVED.")
    if booking["settlement_status"] != "SETTLED":
        raise err(ERR_INVALID_STATE, "Booking is not SETTLED.")

    spot = db.spots[booking["spot_id"]]
    now = clock.now()
    grace_seconds = spot["overstay_grace_minutes"] * 60
    window_close = booking["_end_at_dt"].timestamp() + grace_seconds
    # Check-in window: [start_at, end_at + grace).
    if now < booking["_start_at_dt"] or now.timestamp() >= window_close:
        raise err(ERR_CHECKIN_WINDOW_CLOSED, "Outside the check-in window.")

    booking["occupancy_status"] = "CHECKED_IN"
    booking["actual_checkin_at"] = _iso(now)
    # Mint AccessPass with gate_opens_remaining = 2.
    ap = make_lightweight(
        {
            "booking_id": booking["id"],
            "qr_token": "qr_" + new_id().replace("-", ""),
            "gate_opens_remaining": 2,
        }
    )
    db.access_passes[ap["id"]] = ap
    touch(booking)
    return success(booking_view(booking))


@bp.post("/bookings/<booking_id>/check-out")
def check_out(booking_id):
    caller = require_auth()
    require_role(caller, "Driver")
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if booking["driver_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Driver does not hold this booking.")
    if booking["occupancy_status"] != "CHECKED_IN":
        raise err(ERR_INVALID_STATE, "Booking is not CHECKED_IN.")

    spot = db.spots[booking["spot_id"]]
    driver = db.drivers[booking["driver_id"]]
    now = clock.now()
    booking["actual_checkout_at"] = _iso(now)
    final_amount = calc.final_settlement_amount(booking, spot, now)
    booking["final_amount_cents"] = final_amount

    # Overstay top-up: debit wallet by delta, floored at 0 (never negative).
    if final_amount > booking["quoted_amount_cents"]:
        delta = final_amount - booking["quoted_amount_cents"]
        debit = min(delta, driver["wallet_balance_cents"])
        if debit > 0:
            driver["wallet_balance_cents"] -= debit
            touch(driver)

    # Overstay violation cascade: actual_checkout_at > end_at + grace.
    grace_seconds = spot["overstay_grace_minutes"] * 60
    overstay_threshold = booking["_end_at_dt"].timestamp() + grace_seconds
    if now.timestamp() > overstay_threshold:
        domain.create_violation(booking, "OVERSTAY", 1)

    booking["occupancy_status"] = "CHECKED_OUT"
    # Post host EARNING on the final amount.
    domain.post_earning(booking, final_amount)
    # Invalidate access pass.
    for p in db.access_passes.values():
        if p["booking_id"] == booking["id"]:
            p["gate_opens_remaining"] = 0
    touch(booking)
    return success(booking_view(booking))


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    caller = require_auth()
    require_role(caller, "Driver")
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if booking["driver_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Driver does not hold this booking.")
    if booking["occupancy_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Booking is not RESERVED.")

    driver = db.drivers[booking["driver_id"]]
    now = clock.now()
    booking["occupancy_status"] = "CANCELLED"
    domain.refund_to_wallet(booking, driver, now)
    touch(driver)
    booking["settlement_status"] = "REFUNDED"
    # Cascade: auto-withdraw any PENDING transfer offer for this booking.
    for t in db.transfer_offers.values():
        if t["booking_id"] == booking["id"] and t["status"] == "PENDING":
            t["status"] = "WITHDRAWN"
            touch(t)
    touch(booking)
    return success(booking_view(booking))


@bp.post("/bookings/<booking_id>/mark-no-show")
def mark_no_show(booking_id):
    caller = require_auth()
    require_role(caller, "PlatformAdmin")
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if booking["occupancy_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Booking is not RESERVED.")
    spot = db.spots[booking["spot_id"]]
    now = clock.now()
    grace_seconds = spot["overstay_grace_minutes"] * 60
    threshold = booking["_end_at_dt"].timestamp() + grace_seconds
    if now.timestamp() < threshold:
        raise err(ERR_INVALID_STATE, "Booking window + grace has not elapsed.")

    booking["occupancy_status"] = "NO_SHOW"
    booking["settlement_status"] = "SETTLED"
    # Host EARNING on quoted amount.
    domain.post_earning(booking, booking["quoted_amount_cents"])
    # Cascade: auto-log NO_SHOW violation (base_points 3).
    domain.create_violation(booking, "NO_SHOW", 3)
    touch(booking)
    return success(booking_view(booking))


@bp.post("/bookings/<booking_id>/reverse-payout")
def reverse_payout(booking_id):
    caller = require_auth()
    require_role(caller, "PlatformAdmin")
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    data = require_body(request.get_json(silent=True))

    # OCC (priority 11): expected_booking_version. Per PRD §2.7 the reverse-payout
    # version mismatch is rejected with ERR_STALE_SPOT_VERSION semantics for stale
    # parents (the reversal request carries expected_booking_version).
    expected_booking_version = require_int(data, "expected_booking_version")
    if expected_booking_version != booking["version"]:
        raise err(ERR_STALE_SPOT_VERSION, "expected_booking_version does not match booking.")

    # Reverse-payout eligibility (priority 12): the reversal targets a finalized
    # booking with exactly one posted EARNING and no prior REVERSAL. A booking with
    # no posted earning (e.g. still RESERVED) falls here per PRD §3.6 and is rejected
    # with ERR_NO_REVERSIBLE_PAYOUT — reverse-payout has no separate state-machine
    # transition, so there is no ERR_INVALID_STATE gate for it.
    earning = domain.earning_for_booking(booking["id"])
    if earning is None or domain.reversal_for_booking(booking["id"]) is not None:
        raise err(ERR_NO_REVERSIBLE_PAYOUT, "No reversible payout for this booking.")

    entry = domain.post_reversal(booking, earning)
    touch(booking)
    return success(ledger_entry_view(entry))


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
