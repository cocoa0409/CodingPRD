"""Venue + Bay routes, the walk-in seat_next OCC write, and the system sweep
(PRD §3.1, §3.5, §2.9; SCAFFOLD §1.5)."""

from flask import Blueprint

from db import db, stamp_common, touch, new_id
from clock import clock, parse_iso
from response import success, list_success, parse_pagination, paginate
from middleware import get_caller, require_roles
from errors import (
    raise_err, ERR_VALIDATION_RANGE, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_NO_BAY_AVAILABLE, ERR_NOT_QUEUE_HEAD, ERR_CARD_DEPLETED, ERR_STALE_VERSION,
)
from services import validate as V
from services import calc
from services.lookup import get_or_404, add_minutes
from services.serialize import venue_out, bay_out, queue_ticket_out

bp = Blueprint("venues", __name__)


# ---- Venue create / read / list ---------------------------------------------
@bp.post("/golf/venues")
def create_venue():
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    data = V.body()

    name = V.as_str(V.require(data, "name"), "name")
    bay_count = V.int_min(V.require(data, "bay_count"), "bay_count", 1)

    open_min = data.get("open_minute_of_day", 540)
    close_min = data.get("close_minute_of_day", 1380)
    base_rate = data.get("base_rate_cents_per_half_hour", 2500)
    peak = data.get("peak_demand_factor", 1.0)

    open_min = V.as_int(open_min, "open_minute_of_day")
    close_min = V.as_int(close_min, "close_minute_of_day")
    if not (0 <= open_min <= 1439):
        raise_err(ERR_INVALID_REQUEST, "open_minute_of_day out of range")
    if not (0 <= close_min <= 1440):
        raise_err(ERR_INVALID_REQUEST, "close_minute_of_day out of range")
    if close_min <= open_min:
        raise_err(ERR_INVALID_REQUEST, "close_minute_of_day must be > open_minute_of_day")

    base_rate = V.as_int(base_rate, "base_rate_cents_per_half_hour")
    if base_rate < 0:
        raise_err(ERR_INVALID_REQUEST, "base_rate_cents_per_half_hour must be >= 0")

    peak = V.as_number(peak, "peak_demand_factor")
    if peak < 0.5 or peak > 1.5:
        raise_err(ERR_VALIDATION_RANGE, "peak_demand_factor must be in [0.5, 1.5]")

    venue = stamp_common({
        "name": name,
        "bay_count": bay_count,
        "open_minute_of_day": open_min,
        "close_minute_of_day": close_min,
        "base_rate_cents_per_half_hour": base_rate,
        "peak_demand_factor": peak,
    })
    db.venues[venue["id"]] = venue
    return success(venue_out(venue), status=201)


@bp.get("/golf/venues/<venue_id>")
def get_venue(venue_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    v = get_or_404(db.venues, venue_id, "venue")
    return success(venue_out(v))


@bp.get("/golf/venues")
def list_venues():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    limit, offset = parse_pagination(__import__("flask").request.args)
    window, total = paginate(list(db.venues.values()), limit, offset)
    return list_success([venue_out(v) for v in window], limit, offset, total)


# ---- Bay create / read / list / out_of_service ------------------------------
@bp.post("/golf/bays")
def create_bay():
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    data = V.body()

    venue_id = V.as_str(V.require(data, "venue_id"), "venue_id")
    label = V.as_str(V.require(data, "label"), "label")
    get_or_404(db.venues, venue_id, "venue")

    floor_level = data.get("floor_level", 1)
    floor_level = V.as_int(floor_level, "floor_level")
    if floor_level < 1:
        raise_err(ERR_INVALID_REQUEST, "floor_level must be >= 1")
    has_target_tech = data.get("has_target_tech", True)
    has_target_tech = V.as_bool(has_target_tech, "has_target_tech")

    bay = stamp_common({
        "venue_id": venue_id,
        "label": label,
        "floor_level": floor_level,
        "has_target_tech": has_target_tech,
        "status": "AVAILABLE",
        "current_session_id": None,
    })
    db.bays[bay["id"]] = bay
    return success(bay_out(bay), status=201)


@bp.get("/golf/bays/<bay_id>")
def get_bay(bay_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    b = get_or_404(db.bays, bay_id, "bay")
    return success(bay_out(b))


@bp.get("/golf/bays")
def list_bays():
    from flask import request
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    limit, offset = parse_pagination(request.args)
    records = list(db.bays.values())
    venue_id = request.args.get("venue_id")
    if venue_id is not None:
        records = [b for b in records if b["venue_id"] == venue_id]
    current_session_id = request.args.get("current_session_id")
    if current_session_id is not None:
        records = [b for b in records if b["current_session_id"] == current_session_id]
    window, total = paginate(records, limit, offset)
    return list_success([bay_out(b) for b in window], limit, offset, total)


@bp.post("/golf/bays/<bay_id>/out_of_service")
def bay_out_of_service(bay_id):
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    b = get_or_404(db.bays, bay_id, "bay")
    # OCC field is present on this endpoint per scaffold (expected_bay_version),
    # but the §2.5 guarded writes are only confirm/seat_next; here we accept it
    # for completeness and do not treat it as a guarded mismatch (PRD §2.5 lists
    # exactly two guarded endpoints). We simply transition.
    V.body()
    b["status"] = "OUT_OF_SERVICE"
    touch(b)
    return success(bay_out(b))


# ---- Walk-in seating (OCC-guarded on Venue.version) -------------------------
@bp.post("/golf/venues/<venue_id>/seat_next")
def seat_next(venue_id):
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    v = get_or_404(db.venues, venue_id, "venue")
    data = V.body()
    expected = V.as_int(V.require(data, "expected_venue_version"), "expected_venue_version")

    # Determine the head WAITING ticket (position 1) by created_at ASC.
    waiting = [
        t for t in db.queue_tickets.values()
        if t["venue_id"] == venue_id and t["status"] == "WAITING"
    ]
    waiting.sort(key=lambda t: (t["created_at"], t["_seq"]))

    # State/queue-head check (priority 6 / 10): there must be a head WAITING ticket.
    if not waiting:
        raise_err(ERR_NOT_QUEUE_HEAD, "no WAITING ticket at the head of the queue")
    head = waiting[0]

    # Bay availability (priority 9).
    available = [b for b in db.bays.values()
                 if b["venue_id"] == venue_id and b["status"] == "AVAILABLE"]
    if not available:
        raise_err(ERR_NO_BAY_AVAILABLE, "no AVAILABLE bay at the venue")

    # Card credit sufficiency (priority 11).
    card = None
    if head["game_card_id"] is not None:
        card = db.game_cards.get(head["game_card_id"])
        if card is None or card["status"] != "ACTIVE" or card["credits_remaining"] < 1:
            raise_err(ERR_CARD_DEPLETED, "game card has no remaining credit")

    # OCC version match (priority 13).
    if expected != v["version"]:
        raise_err(ERR_STALE_VERSION, "venue version is stale")

    # Select AVAILABLE bay: lowest floor_level, tie-break created_at ASC.
    available.sort(key=lambda b: (b["floor_level"], b["created_at"], b["_seq"]))
    chosen = available[0]

    # Create walk-in session.
    session = stamp_common({
        "bay_id": chosen["id"],
        "member_id": head["member_id"],
        "reservation_id": None,
        "queue_ticket_id": head["id"],
        "play_status": "OPEN",
        "billing_status": "UNBILLED",
        "total_score": 0,
        "shot_count": 0,
        "shots": [],
        "charge_id": None,
    })
    db.sessions[session["id"]] = session

    # Occupy bay.
    chosen["status"] = "OCCUPIED"
    chosen["current_session_id"] = session["id"]
    touch(chosen)

    # Consume card credit.
    if card is not None:
        card["credits_remaining"] -= 1
        if card["credits_remaining"] == 0:
            card["status"] = "DEPLETED"
        touch(card)

    # Seat the ticket.
    head["status"] = "SEATED"
    head["assigned_bay_id"] = chosen["id"]
    touch(head)

    # Bump venue version (the OCC bump a competing seating observes).
    touch(v)

    return success(queue_ticket_out(head))


# ---- System sweep -----------------------------------------------------------
@bp.post("/golf/venues/<venue_id>/sweep_holds")
def sweep_holds(venue_id):
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    v = get_or_404(db.venues, venue_id, "venue")
    V.body()
    now = clock.now()

    # HOLD reservations whose hold_expires_utc <= clock -> EXPIRED (this venue).
    for r in db.reservations.values():
        if r["venue_id"] != venue_id:
            continue
        if r["status"] == "HOLD" and parse_iso(r["hold_expires_utc"]) <= now:
            r["status"] = "EXPIRED"
            touch(r)
        elif r["status"] == "CONFIRMED" and parse_iso(r["end_utc"]) <= now:
            realized = any(
                s["reservation_id"] == r["id"] for s in db.sessions.values()
            )
            if not realized:
                r["no_show_fee_cents"] = calc.no_show_fee(r["quoted_price_cents"])
                # Reverse provisional loyalty (never confirms).
                member = db.members.get(r["member_id"])
                prov = r.get("_provisional_earn", 0)
                if member is not None and prov:
                    member["pending_loyalty_points"] -= prov
                    if member["pending_loyalty_points"] < 0:
                        member["pending_loyalty_points"] = 0
                    touch(member)
                    r["_provisional_earn"] = 0
                r["status"] = "NO_SHOW"
                touch(r)

    # WAITING queue tickets older than QUEUE_TTL -> EXPIRED (this venue).
    for t in db.queue_tickets.values():
        if t["venue_id"] != venue_id:
            continue
        if t["status"] == "WAITING":
            expiry = add_minutes(parse_iso(t["created_at"]), calc.QUEUE_TTL_MINUTES)
            if expiry <= now:
                t["status"] = "EXPIRED"
                touch(t)

    return success(venue_out(v))
