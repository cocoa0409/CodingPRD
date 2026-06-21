"""Charter routes: create + the full lifecycle state machine with cascades."""
from flask import Blueprint, request

from db import db, base_versioned, touch
from errors import ApiError
from middleware import require_role
from helpers import (
    get_body, require_str, require_enum, require_int, require_dt, opt_str,
    opt_bool, get_pagination, paginate,
)
from response import success, list_success
from services import serializers as S
from services.lookups import get_charter, get_marina, get_boat, get_permit
from services import calculations as calc

bp = Blueprint("charters", __name__)


def _sorted(collection):
    return sorted(collection.values(), key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Create charter
# ---------------------------------------------------------------------------
@bp.route("/charters", methods=["POST"])
def create_charter():
    require_role({"FleetManager"})
    body = get_body()
    # --- body well-formedness (priority 4) collected first for the FK fields,
    # but existence (priority 3) must run before body validation per PRD 2.9.
    # We resolve required FKs in declared order: marina_id, boat_id, (permit_id).
    marina_id = require_str(body, "marina_id")
    boat_id = require_str(body, "boat_id")
    # existence: path has none; body FKs in declared order: marina_id, boat_id, permit_id
    marina = get_marina(marina_id)
    boat = get_boat(boat_id)
    permit_id = opt_str(body, "permit_id", default=None)
    permit = None
    if permit_id is not None:
        permit = get_permit(permit_id)
    # --- remaining body validation (priority 4) ---
    trip_type = require_enum(body, "trip_type", {"INSHORE", "OFFSHORE", "HALF_DAY"})
    depart_at = require_dt(body, "depart_at")
    return_at = require_dt(body, "return_at")
    if not (return_at > depart_at):
        raise ApiError("ERR_INVALID_REQUEST", "return_at must be strictly after depart_at")
    base_seat_price_cents = require_int(body, "base_seat_price_cents", minimum=0)
    seats_total = require_int(body, "seats_total", minimum=0)
    split_charter = opt_bool(body, "split_charter", default=False)

    # --- cross-entity referential wiring (priority 6) ---
    if boat["marina_id"] != marina_id:
        raise ApiError("ERR_CROSS_MARINA_MISMATCH", "Boat marina differs from charter marina")
    if permit is not None:
        # permit_kind must match trip_type (OFFSHORE needs FEDERAL_OFFSHORE)
        if trip_type == "OFFSHORE" and permit["permit_kind"] != "FEDERAL_OFFSHORE":
            raise ApiError("ERR_CROSS_MARINA_MISMATCH", "Permit kind does not match trip type")

    # --- credential/capacity safety (priority 7): offshore trip needs a rated
    # hull (PRD §3.2: "a charter or staffing operation that would place an
    # un-rated hull on offshore water is rejected with ERR_BOAT_NOT_OFFSHORE_RATED").
    if trip_type == "OFFSHORE" and not boat["offshore_rated"]:
        raise ApiError("ERR_BOAT_NOT_OFFSHORE_RATED", "Boat is not offshore rated")

    # --- capacity (priority 10): seats_total <= boat.passenger_capacity ---
    if seats_total > boat["passenger_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "seats_total exceeds boat passenger capacity")

    ch = base_versioned()
    ch.update({
        "marina_id": marina_id,
        "boat_id": boat_id,
        "permit_id": permit_id,
        "trip_type": trip_type,
        "depart_at": body["depart_at"],
        "return_at": body["return_at"],
        "base_seat_price_cents": base_seat_price_cents,
        "seats_total": seats_total,
        "seats_booked": 0,
        "split_charter": split_charter,
        "catch_total": 0,
        "weather_reschedule_count": 0,
        "status": "DRAFT",
        "_depart_dt": depart_at,
        "_return_dt": return_at,
        "_seq": db.next_seq(),
    })
    db.charters[ch["id"]] = ch
    return success(S.charter_out(ch), status=201)


@bp.route("/charters", methods=["GET"])
def list_charters():
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    limit, offset = get_pagination()
    items = _sorted(db.charters)
    for key in ("marina_id", "boat_id", "permit_id"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([S.charter_out(c) for c in page], limit, offset, total)


@bp.route("/charters/<charter_id>", methods=["GET"])
def get_charter_route(charter_id):
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    ch = get_charter(charter_id)
    return success(S.charter_out(ch), status=200)


# ---------------------------------------------------------------------------
# Helpers for crew/slot lookups by charter
# ---------------------------------------------------------------------------
def _crew_for(charter_id):
    return [a for a in db.crew_assignments.values() if a["charter_id"] == charter_id]


def _slot_res_for(charter_id):
    return [r for r in db.slot_reservations.values() if r["charter_id"] == charter_id]


def _active_slot_res(charter_id):
    """The charter's HELD/OCCUPIED slot reservation (if any)."""
    for r in _slot_res_for(charter_id):
        if r["status"] in ("HELD", "OCCUPIED"):
            return r
    return None


# ---------------------------------------------------------------------------
# Schedule (DRAFT -> SCHEDULED)
# ---------------------------------------------------------------------------
@bp.route("/charters/<charter_id>/schedule", methods=["POST"])
def schedule_charter(charter_id):
    require_role({"FleetManager"})
    ch = get_charter(charter_id)
    # The schedule transition runs only from DRAFT (state machine §1.2).
    # WEATHER_HOLD returns to SCHEDULED exclusively through /reschedule, so a
    # held charter (TENTATIVE crew, HELD slot) must NOT be re-schedulable here.
    # The catalog has no dedicated "must be DRAFT" code; the documented
    # schedule preconditions (boat/marina/crew/slot) are the gates and already
    # reject an already-SCHEDULED charter (its captain assignment is LOCKED,
    # not TENTATIVE -> ERR_NO_CAPTAIN_ASSIGNED). To close the WEATHER_HOLD
    # loophole without inventing an error, only DRAFT charters proceed; any
    # other state is treated as "no captain available to (re)assign here".
    if ch["status"] != "DRAFT":
        raise ApiError("ERR_NO_CAPTAIN_ASSIGNED", "Charter is not in DRAFT for scheduling")

    boat = db.boats.get(ch["boat_id"])
    marina = db.marinas.get(ch["marina_id"])

    # schedule preconditions (PRD 3.7), in listed order
    if boat["status"] != "IN_SERVICE":
        raise ApiError("ERR_BOAT_NOT_IN_SERVICE", "Boat is not in service")
    if marina["status"] != "OPEN":
        raise ApiError("ERR_MARINA_NOT_OPEN", "Marina is not open")

    crew = _crew_for(charter_id)
    has_captain = any(
        a["role_slot"] == "CAPTAIN" and a.get("captain_id") and a["status"] == "TENTATIVE"
        for a in crew
    )
    if not has_captain:
        raise ApiError("ERR_NO_CAPTAIN_ASSIGNED", "No tentative captain assignment")

    if ch["trip_type"] == "OFFSHORE":
        has_mate = any(
            a["role_slot"] == "MATE" and a.get("mate_id") for a in crew
        )
        if not has_mate:
            raise ApiError("ERR_NO_MATE_ASSIGNED", "Offshore charter requires a mate assignment")
        if ch["permit_id"] is None:
            raise ApiError("ERR_PERMIT_REQUIRED", "Offshore charter requires a permit")

    slot_res = _active_slot_res(charter_id)
    if slot_res is None:
        raise ApiError("ERR_NO_SLOT_RESERVED", "No HELD/OCCUPIED slot reservation")

    # side effects
    for a in crew:
        if a["status"] == "TENTATIVE":
            a["status"] = "LOCKED"
            touch(a)
    slot_res["status"] = "OCCUPIED"
    touch(slot_res)
    ch["status"] = "SCHEDULED"
    touch(ch)
    return success(S.charter_out(ch), status=200)


# ---------------------------------------------------------------------------
# Weather hold (SCHEDULED -> WEATHER_HOLD)
# ---------------------------------------------------------------------------
@bp.route("/charters/<charter_id>/weather-hold", methods=["POST"])
def weather_hold_charter(charter_id):
    require_role({"Captain"})
    ch = get_charter(charter_id)
    if ch["status"] != "SCHEDULED":
        raise ApiError("ERR_CHARTER_NOT_SCHEDULED", "Charter is not SCHEDULED")
    # side effects
    for b in db.bookings.values():
        if b["charter_id"] == charter_id and b["status"] in ("RESERVED", "CONFIRMED"):
            b["weather_waiver"] = True
            touch(b)
    for a in _crew_for(charter_id):
        if a["status"] == "LOCKED":
            a["status"] = "TENTATIVE"
            touch(a)
    slot_res = _active_slot_res(charter_id)
    if slot_res is not None and slot_res["status"] == "OCCUPIED":
        slot_res["status"] = "HELD"
        touch(slot_res)
    ch["status"] = "WEATHER_HOLD"
    touch(ch)
    return success(S.charter_out(ch), status=200)


# ---------------------------------------------------------------------------
# Reschedule (WEATHER_HOLD -> SCHEDULED)
# ---------------------------------------------------------------------------
def _window_conflict(slot_id, new_start, new_end, buffer_minutes, exclude_res_id):
    """Closed-adjacency buffered conflict: a new window conflicts if it
    overlaps, touches, or opens before prior_end + buffer on the same slot."""
    from datetime import timedelta
    buf = timedelta(minutes=buffer_minutes)
    for r in db.slot_reservations.values():
        if r["id"] == exclude_res_id:
            continue
        if r["dock_slot_id"] != slot_id:
            continue
        if r["status"] not in ("HELD", "OCCUPIED"):
            continue
        ex_start = r["_window_start_dt"]
        ex_end = r["_window_end_dt"]
        # Earliest the new window may open after this existing one is ex_end+buf.
        # Conflict unless new window is entirely before existing (new_end+buf <= ex_start)
        # or entirely after (new_start >= ex_end + buf).
        if new_start >= ex_end + buf:
            continue  # new is sufficiently after existing
        if new_end + buf <= ex_start:
            continue  # new is sufficiently before existing
        return True
    return False


@bp.route("/charters/<charter_id>/reschedule", methods=["POST"])
def reschedule_charter(charter_id):
    require_role({"FleetManager"})
    ch = get_charter(charter_id)
    body = get_body()
    new_depart = require_dt(body, "depart_at")
    new_return = require_dt(body, "return_at")
    if not (new_return > new_depart):
        raise ApiError("ERR_INVALID_REQUEST", "return_at must be strictly after depart_at")
    # state precondition
    if ch["status"] != "WEATHER_HOLD":
        raise ApiError("ERR_CHARTER_NOT_ON_HOLD", "Charter is not on weather hold")

    # credential expiry against new depart date: captain license + permit
    crew = _crew_for(charter_id)
    for a in crew:
        if a["role_slot"] == "CAPTAIN" and a.get("captain_id"):
            cap = db.captains.get(a["captain_id"])
            if cap and cap["_license_expires_dt"] <= new_depart:
                raise ApiError("ERR_CREDENTIAL_EXPIRED_FOR_DATE",
                               "Captain license lapses on/before new depart date")
    if ch["permit_id"]:
        permit = db.permits.get(ch["permit_id"])
        if permit and permit["_valid_through_dt"] <= new_depart:
            raise ApiError("ERR_CREDENTIAL_EXPIRED_FOR_DATE",
                           "Permit lapses on/before new depart date")

    # slot window conflict under buffer
    slot_res = _active_slot_res(charter_id)
    if slot_res is not None:
        slot = db.dock_slots.get(slot_res["dock_slot_id"])
        marina = db.marinas.get(slot["marina_id"]) if slot else None
        buffer_minutes = marina["turnaround_buffer_minutes"] if marina else 0
        if _window_conflict(slot_res["dock_slot_id"], new_depart, new_return,
                            buffer_minutes, slot_res["id"]):
            raise ApiError("ERR_SLOT_WINDOW_CONFLICT", "New window conflicts with another reservation")

    # side effects
    ch["depart_at"] = body["depart_at"]
    ch["return_at"] = body["return_at"]
    ch["_depart_dt"] = new_depart
    ch["_return_dt"] = new_return
    if slot_res is not None:
        slot_res["window_start"] = body["depart_at"]
        slot_res["window_end"] = body["return_at"]
        slot_res["_window_start_dt"] = new_depart
        slot_res["_window_end_dt"] = new_return
        slot_res["status"] = "OCCUPIED"
        touch(slot_res)
    for a in crew:
        if a["status"] == "TENTATIVE":
            a["status"] = "LOCKED"
            touch(a)

    count_before = ch["weather_reschedule_count"]
    ch["weather_reschedule_count"] = count_before + 1

    # per-booking reschedule fee + weather_waiver reset (non-terminal bookings).
    # Terminal bookings (CANCELLED/SETTLED/NO_SHOW) are left untouched: they
    # accrue no fee and their mutation-tracking fields do not advance.
    for b in db.bookings.values():
        if b["charter_id"] != charter_id:
            continue
        if b["status"] in ("CANCELLED", "SETTLED", "NO_SHOW"):
            continue
        b["weather_waiver"] = False
        fee = calc.reschedule_fee_cents(count_before, b["seat_subtotal_cents"])
        customer = db.customers.get(b["customer_id"])
        if customer and customer["loyalty_tier"] == "GOLD" and not b["gold_reschedule_waiver_used"]:
            fee = 0
            b["gold_reschedule_waiver_used"] = True
        b["reschedule_fee_total_cents"] = b["reschedule_fee_total_cents"] + fee
        touch(b)

    ch["status"] = "SCHEDULED"
    touch(ch)
    return success(S.charter_out(ch), status=200)


# ---------------------------------------------------------------------------
# Sail (SCHEDULED -> SAILED)
# ---------------------------------------------------------------------------
@bp.route("/charters/<charter_id>/sail", methods=["POST"])
def sail_charter(charter_id):
    require_role({"Captain"})
    ch = get_charter(charter_id)
    if ch["status"] != "SCHEDULED":
        raise ApiError("ERR_CHARTER_NOT_SCHEDULED", "Charter is not SCHEDULED")
    if db.now() < ch["_depart_dt"]:
        raise ApiError("ERR_DEPART_TIME_NOT_REACHED", "Departure time not reached")
    # seats_booked recomputed from bookings
    from services.aggregates import recompute_seats_booked
    if recompute_seats_booked(ch) < 1:
        raise ApiError("ERR_NO_BOOKINGS_TO_SAIL", "No bookings to sail")
    # Every CrewAssignment for this charter must be LOCKED (PRD §3.8).
    crew = _crew_for(charter_id)
    if any(a["status"] != "LOCKED" for a in crew):
        raise ApiError("ERR_CREW_NOT_LOCKED", "Not every crew assignment is locked")

    # side effects: resolve manifest
    for b in db.bookings.values():
        if b["charter_id"] != charter_id:
            continue
        if b["status"] == "RESERVED" and b["deposit_paid_cents"] == 0:
            _void_addons(b)
            b["status"] = "NO_SHOW"
            touch(b)
        elif b["status"] in ("RESERVED", "CONFIRMED") and b["deposit_paid_cents"] > 0:
            b["status"] = "CONFIRMED"
            touch(b)
    ch["status"] = "SAILED"
    touch(ch)
    return success(S.charter_out(ch), status=200)


# ---------------------------------------------------------------------------
# Settle (SAILED -> SETTLED)
# ---------------------------------------------------------------------------
@bp.route("/charters/<charter_id>/settle", methods=["POST"])
def settle_charter(charter_id):
    require_role({"FleetManager"})
    ch = get_charter(charter_id)
    if ch["status"] != "SAILED":
        raise ApiError("ERR_CHARTER_NOT_SAILED", "Charter is not SAILED")
    # bag limit check (when permit present)
    from services.aggregates import recompute_catch_total
    if ch["permit_id"]:
        permit = db.permits.get(ch["permit_id"])
        if permit and recompute_catch_total(ch) > permit["daily_bag_limit"]:
            raise ApiError("ERR_BAG_LIMIT_EXCEEDED", "Kept catch exceeds permit bag limit")

    # side effects
    for b in db.bookings.values():
        if b["charter_id"] != charter_id or b["status"] != "CONFIRMED":
            continue
        b["gratuity_cents"] = _compute_gratuity(b)
        # fulfil pending addons on this settled booking
        for a in db.add_on_lines.values():
            if a["booking_id"] == b["id"] and a["status"] == "PENDING":
                a["status"] = "FULFILLED"
                touch(a)
        b["status"] = "SETTLED"
        touch(b)
    for a in _crew_for(charter_id):
        if a["status"] != "RELEASED":
            a["status"] = "RELEASED"
            touch(a)
    slot_res = _active_slot_res(charter_id)
    if slot_res is not None:
        slot_res["status"] = "RELEASED"
        touch(slot_res)
    ch["status"] = "SETTLED"
    touch(ch)
    return success(S.charter_out(ch), status=200)


# ---------------------------------------------------------------------------
# Cancel (DRAFT/SCHEDULED/WEATHER_HOLD -> CANCELLED)
# ---------------------------------------------------------------------------
@bp.route("/charters/<charter_id>/cancel", methods=["POST"])
def cancel_charter(charter_id):
    require_role({"FleetManager"})
    ch = get_charter(charter_id)
    if ch["status"] not in ("DRAFT", "SCHEDULED", "WEATHER_HOLD"):
        raise ApiError("ERR_CHARTER_NOT_CANCELLABLE", "Charter is not cancellable")
    now = db.now()
    for b in db.bookings.values():
        if b["charter_id"] != charter_id:
            continue
        if b["status"] in ("CANCELLED", "SETTLED", "NO_SHOW"):
            continue
        # refund per cancellation rule
        lead_hours = (ch["_depart_dt"] - now).total_seconds() / 3600
        b["refund_cents"] = calc.cancellation_refund_cents(
            b["weather_waiver"], b["deposit_paid_cents"], lead_hours)
        _void_addons(b)
        b["status"] = "CANCELLED"
        touch(b)
    for a in _crew_for(charter_id):
        if a["status"] != "RELEASED":
            a["status"] = "RELEASED"
            touch(a)
    slot_res = _active_slot_res(charter_id)
    if slot_res is not None:
        slot_res["status"] = "RELEASED"
        touch(slot_res)
    ch["status"] = "CANCELLED"
    touch(ch)
    return success(S.charter_out(ch), status=200)


# ---------------------------------------------------------------------------
# Shared cascade helpers (also used by booking routes)
# ---------------------------------------------------------------------------
def _void_addons(booking):
    for a in db.add_on_lines.values():
        if a["booking_id"] == booking["id"] and a["status"] in ("PENDING", "FULFILLED"):
            a["status"] = "VOIDED"
            touch(a)


def _compute_gratuity(booking):
    addon_base = 0
    for a in db.add_on_lines.values():
        if a["booking_id"] == booking["id"] and a["status"] in ("PENDING", "FULFILLED"):
            addon_base += a["line_total_cents"]
    return calc.gratuity_cents(
        booking["seat_subtotal_cents"], addon_base, booking["party_size"],
        booking["gratuity_input_mode"], booking["gratuity_input_value"])
