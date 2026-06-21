"""Leagues and league nights (PRD §3.8)."""
from flask import Blueprint, request

from db import db, new_common, touch
from errors import err
from middleware import get_identity, require_role
from response import success, array
from services import serialize, pricing
from services.util import (
    get_body, parse_pagination, paginate, lookup,
    as_str, as_int, parse_datetime,
)

bp = Blueprint("leagues", __name__)


# --------------------------------------------------------------------- League
@bp.post("/leagues")
def create_league():
    _, role = get_identity()
    require_role(role, {"LeagueAdmin"})
    body = get_body()
    name = as_str(body, "name")
    rate_card_id = as_str(body, "rate_card_id")
    season_night_count = as_int(body, "season_night_count", minimum=1)
    lanes_per_night = as_int(body, "lanes_per_night", minimum=1)
    weekly_fee_cents = as_int(body, "weekly_fee_cents", minimum=0)

    lookup(db.rate_cards, rate_card_id, "rate card")

    e = new_common()
    e.update({
        "name": name,
        "rate_card_id": rate_card_id,
        "season_night_count": season_night_count,
        "lanes_per_night": lanes_per_night,
        "weekly_fee_cents": weekly_fee_cents,
        "season_fee_quote_cents": 0,
        "season_fee_accrued_cents": 0,
        "status": "DRAFT",
    })
    db.leagues[e["id"]] = e
    return success(serialize.league(e), status=201)


@bp.get("/leagues/<id>")
def get_league(id):
    _, role = get_identity()
    require_role(role, {"LeagueAdmin", "CenterManager"})
    e = lookup(db.leagues, id, "league")
    return success(serialize.league(e))


@bp.get("/leagues")
def list_leagues():
    _, role = get_identity()
    require_role(role, {"LeagueAdmin", "CenterManager"})
    limit, offset = parse_pagination()
    items = list(db.leagues.values())
    for field in ("rate_card_id", "status"):
        val = request.args.get(field)
        if val:
            items = [l for l in items if l.get(field) == val]
    page, meta = paginate(items, limit, offset)
    return array([serialize.league(e) for e in page], pagination=meta)


@bp.post("/leagues/<id>/activate")
def activate_league(id):
    _, role = get_identity()
    require_role(role, {"LeagueAdmin"})
    e = lookup(db.leagues, id, "league")
    if e["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "League must be DRAFT to activate")
    nights = [n for n in db.league_nights.values() if n["league_id"] == id]
    if not nights:
        raise err("ERR_LEAGUE_NO_NIGHTS", "League has no scheduled nights")
    # Forward-looking quote (PRD §3.8).
    e["season_fee_quote_cents"] = e["weekly_fee_cents"] * e["season_night_count"]
    e["status"] = "ACTIVE"
    touch(e)
    return success(serialize.league(e))


@bp.post("/leagues/<id>/close")
def close_league(id):
    _, role = get_identity()
    require_role(role, {"LeagueAdmin"})
    e = lookup(db.leagues, id, "league")
    if e["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "League must be ACTIVE to close")
    scheduled = [n for n in db.league_nights.values()
                 if n["league_id"] == id and n["status"] == "SCHEDULED"]
    if scheduled:
        raise err("ERR_LEAGUE_HAS_SCHEDULED_NIGHTS", "Scheduled nights remain")
    # Finalize chronological accrual: sum night_fee over PLAYED/FORFEITED nights.
    accrued = 0
    for n in db.league_nights.values():
        if n["league_id"] == id and n["status"] in ("PLAYED", "FORFEITED"):
            accrued += n["night_fee_cents"]
    e["season_fee_accrued_cents"] = accrued
    e["status"] = "CLOSED"
    touch(e)
    return success(serialize.league(e))


# ---------------------------------------------------------------- LeagueNight
@bp.post("/league-nights")
def create_league_night():
    _, role = get_identity()
    require_role(role, {"LeagueAdmin"})
    body = get_body()
    league_id = as_str(body, "league_id")
    night_index = as_int(body, "night_index", minimum=1)

    league = lookup(db.leagues, league_id, "league")

    start = parse_datetime(body["start_at"], "start_at") if body.get("start_at") else None
    end = parse_datetime(body["end_at"], "end_at") if body.get("end_at") else None
    if start is None or end is None:
        raise err("ERR_INVALID_REQUEST", "start_at and end_at are required")
    if not (start < end):
        raise err("ERR_INVALID_REQUEST", "start_at must be strictly before end_at")

    # Unique night_index within league.
    for n in db.league_nights.values():
        if n["league_id"] == league_id and n["night_index"] == night_index:
            raise err("ERR_DUPLICATE_NIGHT_INDEX", "night_index already used in this league")

    # Reserve lanes_per_night available IN_SERVICE lanes with no overlap.
    needed = league["lanes_per_night"]
    available_lanes = sorted(
        [l for l in db.lanes.values() if l["status"] == "IN_SERVICE"],
        key=lambda l: l["number"],
    )
    reserved = []
    for lane in available_lanes:
        if len(reserved) >= needed:
            break
        if not pricing.lane_conflict(lane["id"], start, end):
            reserved.append(lane["id"])
    if len(reserved) < needed:
        raise err("ERR_LANE_TIME_CONFLICT", "Not enough free lanes for this window")

    e = new_common()
    e.update({
        "league_id": league_id,
        "night_index": night_index,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "reserved_lane_ids": reserved,
        "status": "SCHEDULED",
        "night_fee_cents": 0,
    })
    db.league_nights[e["id"]] = e
    return success(serialize.league_night(e), status=201)


@bp.get("/league-nights/<id>")
def get_league_night(id):
    _, role = get_identity()
    require_role(role, {"LeagueAdmin", "CenterManager"})
    e = lookup(db.league_nights, id, "league night")
    return success(serialize.league_night(e))


@bp.get("/league-nights")
def list_league_nights():
    _, role = get_identity()
    require_role(role, {"LeagueAdmin", "CenterManager"})
    limit, offset = parse_pagination()
    items = list(db.league_nights.values())
    for field in ("league_id", "status"):
        val = request.args.get(field)
        if val:
            items = [n for n in items if n.get(field) == val]
    page, meta = paginate(items, limit, offset)
    return array([serialize.league_night(e) for e in page], pagination=meta)


def _resolve_night(id, new_status, fee_from_weekly):
    e = lookup(db.league_nights, id, "league night")
    league = db.leagues.get(e["league_id"])
    if e["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "League night is not SCHEDULED")
    if not league or league["status"] != "ACTIVE":
        raise err("ERR_LEAGUE_NOT_ACTIVE", "Parent league is not ACTIVE")
    return e, league


@bp.post("/league-nights/<id>/mark-played")
def mark_played(id):
    _, role = get_identity()
    require_role(role, {"LeagueAdmin"})
    e, league = _resolve_night(id, "PLAYED", True)
    now = db.current_utc()
    if not (now >= parse_datetime(e["start_at"])):
        raise err("ERR_INVALID_STATE", "Cannot mark played before start_at")
    e["night_fee_cents"] = league["weekly_fee_cents"]
    e["status"] = "PLAYED"
    e["reserved_lane_ids"] = []
    touch(e)
    league["season_fee_accrued_cents"] += e["night_fee_cents"]
    touch(league)
    return success(serialize.league_night(e))


@bp.post("/league-nights/<id>/forfeit")
def forfeit(id):
    _, role = get_identity()
    require_role(role, {"LeagueAdmin"})
    e, league = _resolve_night(id, "FORFEITED", True)
    e["night_fee_cents"] = league["weekly_fee_cents"]
    e["status"] = "FORFEITED"
    e["reserved_lane_ids"] = []
    touch(e)
    league["season_fee_accrued_cents"] += e["night_fee_cents"]
    touch(league)
    return success(serialize.league_night(e))


@bp.post("/league-nights/<id>/rain-out")
def rain_out(id):
    _, role = get_identity()
    require_role(role, {"LeagueAdmin"})
    e, league = _resolve_night(id, "RAINED_OUT", False)
    e["night_fee_cents"] = 0
    e["status"] = "RAINED_OUT"
    e["reserved_lane_ids"] = []
    touch(e)
    # accrual unchanged
    return success(serialize.league_night(e))
