"""Reservation CRUD + lifecycle transitions (PRD §3.3–§3.7)."""
from flask import Blueprint, request

from db import db, new_common, touch
from errors import err
from middleware import get_identity, require_role
from response import success, array
from services import serialize, pricing
from services import reservation_sm as sm
from services.util import (
    get_body, parse_pagination, paginate, lookup,
    as_int, as_str, as_enum, parse_datetime,
)

bp = Blueprint("reservations", __name__)


def _owner_guard(role, user_id, res):
    """A Customer may act only on a reservation they own (PRD §2.1)."""
    if role == "Customer" and res["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this reservation")


# ----------------------------------------------------------------- create
@bp.post("/reservations")
def create_reservation():
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    body = get_body()

    customer_id = as_str(body, "customer_id")
    rate_card_id = as_str(body, "rate_card_id")
    resource_kind = as_enum(body, "resource_kind", {"LANE", "BAY"})
    lane_id = body.get("lane_id")
    bay_id = body.get("bay_id")
    party_package_id = body.get("party_package_id")
    origin = as_enum(body, "origin", {"RESERVATION", "WALK_IN"}, required=False, default="RESERVATION")
    pricing_mode = as_enum(body, "pricing_mode", {"PER_GAME", "PER_HOUR"})
    bowler_count = as_int(body, "bowler_count", minimum=1)
    game_count = as_int(body, "game_count", required=False, default=0, minimum=0)
    guest_count = as_int(body, "guest_count", required=False, default=0, minimum=0)

    # Customer creating a reservation must own it (X-User-ID == customer_id).
    if role == "Customer" and customer_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer may only create own reservations")

    # Existence checks (PRD §2.6).
    lookup(db.customers, customer_id, "customer")
    lookup(db.rate_cards, rate_card_id, "rate card")
    if resource_kind == "LANE":
        if not lane_id or not isinstance(lane_id, str):
            raise err("ERR_INVALID_REQUEST", "lane_id required when resource_kind=LANE")
        lookup(db.lanes, lane_id, "lane")
        bay_id = None
    else:
        if not bay_id or not isinstance(bay_id, str):
            raise err("ERR_INVALID_REQUEST", "bay_id required when resource_kind=BAY")
        lookup(db.bays, bay_id, "bay")
        lane_id = None
    if party_package_id:
        if not isinstance(party_package_id, str):
            raise err("ERR_INVALID_REQUEST", "party_package_id must be a string")
        lookup(db.party_packages, party_package_id, "party package")
    else:
        party_package_id = None

    start = parse_datetime(body["start_at"], "start_at") if body.get("start_at") else None
    end = parse_datetime(body["end_at"], "end_at") if body.get("end_at") else None
    if start is None or end is None:
        raise err("ERR_INVALID_REQUEST", "start_at and end_at are required")
    if not (start < end):
        raise err("ERR_INVALID_REQUEST", "start_at must be strictly before end_at")

    e = new_common()
    e.update({
        "customer_id": customer_id,
        "rate_card_id": rate_card_id,
        "resource_kind": resource_kind,
        "lane_id": lane_id,
        "bay_id": bay_id,
        "party_package_id": party_package_id,
        "origin": origin,
        "pricing_mode": pricing_mode,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "bowler_count": bowler_count,
        "game_count": game_count,
        "guest_count": guest_count,
        "lane_subtotal_cents": 0,
        "package_subtotal_cents": 0,
        "food_subtotal_cents": 0,
        "rental_subtotal_cents": 0,
        "quoted_total_cents": 0,
        "held_deposit_cents": 0,
        "refund_cents": 0,
        "status": "DRAFT",
        "cancelled_at": None,
    })
    db.reservations[e["id"]] = e
    return success(serialize.reservation(e), status=201)


@bp.get("/reservations/<id>")
def get_reservation(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    e = lookup(db.reservations, id, "reservation")
    _owner_guard(role, user_id, e)
    return success(serialize.reservation(e))


@bp.get("/reservations")
def list_reservations():
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    limit, offset = parse_pagination()
    items = list(db.reservations.values())
    # Customers see only their own reservations.
    if role == "Customer":
        items = [r for r in items if r["customer_id"] == user_id]
    for field in ("customer_id", "lane_id", "bay_id", "rate_card_id", "party_package_id", "status"):
        val = request.args.get(field)
        if val:
            items = [r for r in items if r.get(field) == val]
    page, meta = paginate(items, limit, offset)
    return array([serialize.reservation(e) for e in page], pagination=meta)


# ------------------------------------------------------------- transitions
@bp.post("/reservations/<id>/hold")
def hold_reservation(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    e = lookup(db.reservations, id, "reservation")
    _owner_guard(role, user_id, e)
    sm.hold(e)
    return success(serialize.reservation(e))


@bp.post("/reservations/<id>/confirm")
def confirm_reservation(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    e = lookup(db.reservations, id, "reservation")
    _owner_guard(role, user_id, e)
    body = get_body()
    expected = as_int(body, "expected_reservation_version", minimum=0)
    sm.confirm(e, expected)
    return success(serialize.reservation(e))


@bp.post("/reservations/<id>/revise")
def revise_reservation(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    e = lookup(db.reservations, id, "reservation")
    _owner_guard(role, user_id, e)
    body = get_body()
    expected = as_int(body, "expected_reservation_version", minimum=0)

    updates = {}
    if "start_at" in body and body["start_at"] is not None:
        parse_datetime(body["start_at"], "start_at")
        updates["start_at"] = body["start_at"]
    if "end_at" in body and body["end_at"] is not None:
        parse_datetime(body["end_at"], "end_at")
        updates["end_at"] = body["end_at"]
    # Determine effective window for the start<end check.
    eff_start = updates.get("start_at", e["start_at"])
    eff_end = updates.get("end_at", e["end_at"])
    if not (parse_datetime(eff_start) < parse_datetime(eff_end)):
        raise err("ERR_INVALID_REQUEST", "start_at must be strictly before end_at")
    if "pricing_mode" in body and body["pricing_mode"] is not None:
        updates["pricing_mode"] = as_enum(body, "pricing_mode", {"PER_GAME", "PER_HOUR"})
    if "bowler_count" in body and body["bowler_count"] is not None:
        updates["bowler_count"] = as_int(body, "bowler_count", minimum=1)
    if "game_count" in body and body["game_count"] is not None:
        updates["game_count"] = as_int(body, "game_count", minimum=0)
    if "guest_count" in body and body["guest_count"] is not None:
        updates["guest_count"] = as_int(body, "guest_count", minimum=0)

    sm.revise(e, expected, updates)
    return success(serialize.reservation(e))


@bp.post("/reservations/<id>/check-in")
def check_in_reservation(id):
    _, role = get_identity()
    require_role(role, {"FrontDesk"})
    e = lookup(db.reservations, id, "reservation")
    sm.check_in(e)
    return success(serialize.reservation(e))


@bp.post("/reservations/<id>/complete")
def complete_reservation(id):
    _, role = get_identity()
    require_role(role, {"FrontDesk"})
    e = lookup(db.reservations, id, "reservation")
    sm.complete(e)
    return success(serialize.reservation(e))


@bp.post("/reservations/<id>/cancel")
def cancel_reservation(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    e = lookup(db.reservations, id, "reservation")
    _owner_guard(role, user_id, e)
    sm.cancel(e)
    return success(serialize.reservation(e))


@bp.post("/reservations/<id>/no-show")
def no_show_reservation(id):
    _, role = get_identity()
    require_role(role, {"FrontDesk"})
    e = lookup(db.reservations, id, "reservation")
    sm.no_show(e)
    return success(serialize.reservation(e))


@bp.post("/reservations/<id>/waitlist")
def waitlist_reservation(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    e = lookup(db.reservations, id, "reservation")
    _owner_guard(role, user_id, e)
    if e["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT reservation may join the waitlist")
    # Meaningful only on a genuinely contended window (PRD §3.7).
    if not pricing.has_conflict(e):
        raise err("ERR_NOT_WAITLISTED", "Window has no active overlap; hold directly")
    e["status"] = "WAITLISTED"
    touch(e)
    return success(serialize.reservation(e), status=201)
