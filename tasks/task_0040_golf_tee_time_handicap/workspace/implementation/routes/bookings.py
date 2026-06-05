from flask import Blueprint, request
import errors
from db import db
from middleware import require_auth
from response import success_object, success_array
from pagination import parse_pagination, paginate
from serializers import booking_out
from util import new_uuid, now_iso, parse_iso
from services.booking import (
    pricing_tier_for, green_fee_cents, standby_bookings,
    rerank_standby, select_promotion,
)
import validate as V

bp = Blueprint("bookings", __name__)

SLOT_MINUTES = 12


def _golfer_confirmed_conflict(golfer_id, new_slot, exclude_booking_id=None):
    """True if golfer holds a CONFIRMED booking on another slot whose
    [start, start+SLOT_MINUTES) half-open window overlaps new_slot's."""
    new_start = parse_iso(new_slot["start_utc"])
    new_end_min = SLOT_MINUTES
    for b in db.bookings.values():
        if b["golfer_id"] != golfer_id:
            continue
        if b["status"] != "CONFIRMED":
            continue
        if b["id"] == exclude_booking_id:
            continue
        other_slot = db.tee_times.get(b["tee_time_id"])
        if not other_slot:
            continue
        if other_slot["id"] == new_slot["id"]:
            continue
        other_start = parse_iso(other_slot["start_utc"])
        # half-open overlap of [s, s+12)
        # overlap iff new_start < other_start+12 and other_start < new_start+12
        new_end = new_start.timestamp() + new_end_min * 60
        other_end = other_start.timestamp() + SLOT_MINUTES * 60
        if new_start.timestamp() < other_end and other_start.timestamp() < new_end:
            return True
    return False


@bp.route("/golf/tee-times/<tid>/bookings", methods=["POST"])
def create_booking(tid):
    require_auth({"ProShop", "Golfer"})
    data = V.require_body(request.get_json(silent=True))

    golfer_id = V.require_present(data, "golfer_id")

    # existence: slot then golfer (path then body FK order)
    slot = db.tee_times.get(tid)
    if not slot:
        raise errors.not_found("Tee time not found.")
    golfer = db.golfers.get(golfer_id)
    if not golfer:
        raise errors.not_found("Golfer not found.")

    course = db.courses.get(slot["course_id"])

    # state admissibility: CLOSED slot rejects with the more specific code
    if slot["status"] == "CLOSED":
        raise errors.ApiError(errors.ERR_TEE_TIME_CLOSED, 409, "Tee time is closed.")

    # duplicate booking: golfer already holds a non-CANCELLED booking on this slot
    for b in db.bookings.values():
        if b["tee_time_id"] == tid and b["golfer_id"] == golfer_id and b["status"] != "CANCELLED":
            raise errors.ApiError(
                errors.ERR_DUPLICATE_BOOKING, 409,
                "Golfer already holds a booking on this tee time.")

    # golfer time conflict (CONFIRMED overlap on another slot)
    if _golfer_confirmed_conflict(golfer_id, slot):
        raise errors.ApiError(
            errors.ERR_GOLFER_TIME_CONFLICT, 409,
            "Golfer has a conflicting confirmed booking.")

    # slot start passed: start_utc must be strictly after current clock
    start_dt = parse_iso(slot["start_utc"])
    if start_dt <= db.current_utc:
        raise errors.ApiError(
            errors.ERR_SLOT_START_PASSED, 409,
            "Tee time start instant has passed.")

    # OCC: expected_tee_time_version required, must equal slot.version
    expected = V.require_present(data, "expected_tee_time_version")
    expected = V.as_int(expected, "expected_tee_time_version")
    if expected != slot["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_TEE_TIME_VERSION, 412,
            "expected_tee_time_version does not match current version.")

    join_standby = data.get("join_standby", False)
    if join_standby is None:
        join_standby = False
    if not isinstance(join_standby, bool):
        raise errors.validation("join_standby must be a boolean.")

    tier = pricing_tier_for(course, slot["local_hour"])
    ts = now_iso()

    full = slot["confirmed_count"] >= slot["capacity"]

    if full:
        if not join_standby:
            raise errors.ApiError(
                errors.ERR_SLOT_FULL_NO_STANDBY, 409,
                "Slot is full; opt into standby to join the waitlist.")
        # create STANDBY
        b = {
            "id": new_uuid(),
            "_seq": db.next_seq(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "tee_time_id": tid,
            "golfer_id": golfer_id,
            "status": "STANDBY",
            "pricing_tier": tier,
            "green_fee_cents": 0,
            "standby_rank": 0,
        }
        db.bookings[b["id"]] = b
        rerank_standby(tid, db)
        # standby creation does not change confirmed_count or version of slot
        return success_object(booking_out(b), 201)

    # CONFIRMED
    fee = green_fee_cents(course, golfer, tier)
    b = {
        "id": new_uuid(),
        "_seq": db.next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "tee_time_id": tid,
        "golfer_id": golfer_id,
        "status": "CONFIRMED",
        "pricing_tier": tier,
        "green_fee_cents": fee,
        "standby_rank": 0,
    }
    db.bookings[b["id"]] = b
    slot["confirmed_count"] += 1
    if slot["confirmed_count"] >= slot["capacity"]:
        slot["status"] = "FULL"
    slot["version"] += 1
    slot["updated_at"] = ts
    return success_object(booking_out(b), 201)


@bp.route("/golf/tee-times/<tid>/bookings", methods=["GET"])
def list_slot_bookings(tid):
    require_auth({"ProShop", "Golfer", "Anonymous"})
    limit, offset = parse_pagination()
    if tid not in db.tee_times:
        raise errors.not_found("Tee time not found.")
    status = request.args.get("status")
    items = [b for b in db.bookings.values() if b["tee_time_id"] == tid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([booking_out(b) for b in page], limit, offset, total, 200)


@bp.route("/golf/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    require_auth({"ProShop", "Golfer", "Anonymous"})
    b = db.bookings.get(bid)
    if not b:
        raise errors.not_found("Booking not found.")
    return success_object(booking_out(b), 200)


@bp.route("/golf/bookings", methods=["GET"])
def list_bookings():
    require_auth({"ProShop", "Golfer", "Anonymous"})
    limit, offset = parse_pagination()
    golfer_id = request.args.get("golfer_id")
    status = request.args.get("status")
    items = list(db.bookings.values())
    if golfer_id is not None:
        items = [b for b in items if b["golfer_id"] == golfer_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([booking_out(b) for b in page], limit, offset, total, 200)


@bp.route("/golf/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    role, user_id = require_auth({"ProShop", "Golfer"})
    b = db.bookings.get(bid)
    if not b:
        raise errors.not_found("Booking not found.")

    # ownership (priority 4) before state (priority 5)
    if role == "Golfer" and b["golfer_id"] != user_id:
        raise errors.not_booking_owner()

    if b["status"] not in ("CONFIRMED", "STANDBY"):
        raise errors.invalid_state("Booking is not cancellable.")

    slot = db.tee_times.get(b["tee_time_id"])
    ts = now_iso()
    was_confirmed = b["status"] == "CONFIRMED"

    if was_confirmed:
        b["status"] = "CANCELLED"
        b["green_fee_cents"] = 0
        b["standby_rank"] = 0
        b["updated_at"] = ts
        b["version"] += 1

        slot["confirmed_count"] -= 1

        promote = select_promotion(b["tee_time_id"], db)
        if promote is not None:
            course = db.courses.get(slot["course_id"])
            golfer = db.golfers.get(promote["golfer_id"])
            promote["status"] = "CONFIRMED"
            promote["standby_rank"] = 0
            promote["green_fee_cents"] = green_fee_cents(
                course, golfer, promote["pricing_tier"])
            promote["updated_at"] = ts
            promote["version"] += 1
            slot["confirmed_count"] += 1
            # slot remains FULL
            rerank_standby(b["tee_time_id"], db)
        else:
            # no standby: reopen
            slot["status"] = "OPEN"

        slot["version"] += 1
        slot["updated_at"] = ts
    else:
        # STANDBY cancel: no promotion, just re-rank
        b["status"] = "CANCELLED"
        b["green_fee_cents"] = 0
        b["standby_rank"] = 0
        b["updated_at"] = ts
        b["version"] += 1
        rerank_standby(b["tee_time_id"], db)

    return success_object(booking_out(b), 200)
