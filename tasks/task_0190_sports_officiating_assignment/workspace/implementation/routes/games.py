"""Game + CrewSlot endpoints (PRD §3.3, §3.4, §3.9, §3.10).

POST   /games
GET    /games
GET    /games/{id}
POST   /games/{id}/crew-slots
GET    /games/{id}/crew-slots
POST   /games/{id}/open       DRAFT -> OPEN
POST   /games/{id}/lock       STAFFED -> LOCKED   (OCC)
POST   /games/{id}/settle     LOCKED -> COMPLETED (OCC, settlement pay)
POST   /games/{id}/cancel     -> CANCELLED (cascade release slots + cancel assignments)
"""
from flask import Blueprint, request

import db
import lookup
import serialize
from errors import (
    err, ERR_INVALID_STATE, ERR_LEAGUE_NOT_OPEN, ERR_CREW_NOT_PROVISIONED,
    ERR_CREW_INCOMPLETE, ERR_GAME_NOT_STARTED, ERR_STALE_GAME_VERSION,
    ERR_INVALID_REQUEST,
)
from middleware import get_user_context, require_role
from pagination import get_pagination, paginate
from response import object_response, array_response
from services import validate, calc, derive
from services.intervals import game_interval
from clock import now
from timeutil import parse_iso

bp = Blueprint("games", __name__)

POSITIONS = {"REFEREE", "ASSISTANT", "OBSERVER"}
READ_ROLES = {"LeagueAdmin", "Assignor", "Official", "Evaluator"}


@bp.route("/games", methods=["POST"])
def create_game():
    _, role = get_user_context()
    require_role(role, {"Assignor"})
    data = validate.body()
    league_id = validate.require_str(data, "league_id")
    home_team = validate.require_str(data, "home_team")
    away_team = validate.require_str(data, "away_team")
    venue_lat = validate.number(data, "venue_lat")
    venue_lon = validate.number(data, "venue_lon")
    start_raw = validate.require_str(data, "start_utc")
    required_crew = validate.integer(data, "required_crew_size", minimum=1)
    duration = validate.integer(data, "duration_minutes", required=False,
                                default=120)
    if duration <= 0:
        err(ERR_INVALID_REQUEST, "duration_minutes must be > 0")
    is_post = validate.boolean(data, "is_postseason", required=False, default=False)
    with db.lock:
        lookup.league(league_id)
        try:
            parse_iso(start_raw)
        except ValueError:
            err(ERR_INVALID_REQUEST, "start_utc must be ISO 8601")
        rec = {
            "league_id": league_id,
            "home_team": home_team,
            "away_team": away_team,
            "venue_lat": venue_lat,
            "venue_lon": venue_lon,
            "start_utc": start_raw,
            "duration_minutes": duration,
            "required_crew_size": required_crew,
            "is_postseason": is_post,
            "status": "DRAFT",
            "crew_filled_count": 0,
            "settlement_total_cents": 0,
        }
        db.stamp_create(rec)
        db.games[rec["id"]] = rec
    return object_response(serialize.game(rec), 201)


@bp.route("/games", methods=["GET"])
def list_games():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    league_id = request.args.get("league_id")
    with db.lock:
        rows = list(db.games.values())
        if league_id is not None:
            rows = [g for g in rows if g["league_id"] == league_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.game(r) for r in page]
    return array_response(items, limit, offset, total)


@bp.route("/games/<game_id>", methods=["GET"])
def get_game(game_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.game(game_id)
        return object_response(serialize.game(rec))


# ---- CrewSlot provisioning ----------------------------------------------

@bp.route("/games/<game_id>/crew-slots", methods=["POST"])
def create_crew_slot(game_id):
    _, role = get_user_context()
    require_role(role, {"Assignor"})
    data = validate.body()
    position = validate.enum(data, "position", POSITIONS)
    multiplier = validate.number(data, "slot_fee_multiplier", required=False,
                                 default=1.0)
    with db.lock:
        game = lookup.game(game_id)
        if game["status"] != "DRAFT":
            err(ERR_INVALID_STATE, "crew slots may only be provisioned on a DRAFT game")
        rec = {
            "game_id": game_id,
            "position": position,
            "slot_fee_multiplier": multiplier,
            "status": "VACANT",
            "current_assignment_id": None,
        }
        db.stamp_create(rec)
        db.crew_slots[rec["id"]] = rec
    return object_response(serialize.crew_slot(rec), 201)


@bp.route("/games/<game_id>/crew-slots", methods=["GET"])
def list_crew_slots(game_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        lookup.game(game_id)
        rows = [s for s in db.crew_slots.values() if s["game_id"] == game_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.crew_slot(r) for r in page]
    return array_response(items, limit, offset, total)


# ---- Game state transitions ---------------------------------------------

@bp.route("/games/<game_id>/open", methods=["POST"])
def open_game(game_id):
    _, role = get_user_context()
    require_role(role, {"Assignor"})
    with db.lock:
        game = lookup.game(game_id)
        if game["status"] != "DRAFT":
            err(ERR_INVALID_STATE, "game not in DRAFT")
        league = db.leagues.get(game["league_id"])
        if league is None or league["status"] != "OPEN":
            err(ERR_LEAGUE_NOT_OPEN, "league is not OPEN")
        slot_count = sum(1 for s in db.crew_slots.values()
                         if s["game_id"] == game_id)
        if slot_count != game["required_crew_size"]:
            err(ERR_CREW_NOT_PROVISIONED,
                "crew slot count must equal required_crew_size")
        game["status"] = "OPEN"
        db.touch(game)
        return object_response(serialize.game(game))


def _check_game_version(game, data):
    if "expected_game_version" not in data or data["expected_game_version"] is None:
        err(ERR_INVALID_REQUEST, "expected_game_version is required")
    expected = data["expected_game_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err(ERR_INVALID_REQUEST, "expected_game_version must be an integer")
    if expected != game["version"]:
        err(ERR_STALE_GAME_VERSION, "game version mismatch")


@bp.route("/games/<game_id>/lock", methods=["POST"])
def lock_game(game_id):
    _, role = get_user_context()
    require_role(role, {"Assignor"})
    data = validate.body()
    with db.lock:
        game = lookup.game(game_id)
        if game["status"] != "STAFFED":
            err(ERR_INVALID_STATE, "game not in STAFFED")
        if game["crew_filled_count"] != game["required_crew_size"]:
            err(ERR_CREW_INCOMPLETE, "crew is not complete")
        _check_game_version(game, data)
        game["status"] = "LOCKED"
        db.touch(game)
        return object_response(serialize.game(game))


@bp.route("/games/<game_id>/settle", methods=["POST"])
def settle_game(game_id):
    _, role = get_user_context()
    require_role(role, {"Assignor"})
    data = validate.body()
    with db.lock:
        game = lookup.game(game_id)
        if game["status"] != "LOCKED":
            err(ERR_INVALID_STATE, "game not in LOCKED")
        g_start, _ = game_interval(game)
        if not (g_start <= now()):
            err(ERR_GAME_NOT_STARTED, "game has not started yet")
        _check_game_version(game, data)
        league = db.leagues.get(game["league_id"])
        # Settle each FILLED slot's ACCEPTED assignment.
        touched_officials = set()
        for slot in db.crew_slots.values():
            if slot["game_id"] != game_id or slot["status"] != "FILLED":
                continue
            aid = slot.get("current_assignment_id")
            a = db.assignments.get(aid) if aid else None
            if a is None or a["status"] != "ACCEPTED":
                continue
            official = db.officials.get(a["official_id"])
            led = derive.ledger_for(a["official_id"])
            penalty_points = led["penalty_points"] if led else 0
            final_pay = calc.finalized_settlement_pay(
                official["rank"], penalty_points,
                league["base_game_fee_cents"], slot["slot_fee_multiplier"],
                bool(game.get("is_postseason")), a["distance_miles"],
                league["mileage_rate_cents_per_mile"])
            a["status"] = "COMPLETED"
            a["final_pay_cents"] = final_pay
            db.touch(a)
            # Pay-conservation accrual.
            if led is not None:
                led["total_pay_accrued_cents"] += final_pay
                led["total_mileage_accrued_cents"] += a["mileage_cents"]
                db.touch(led)
            touched_officials.add(a["official_id"])
        game["status"] = "COMPLETED"
        db.touch(game)
        derive.recompute_game_settlement_total(game)
        for oid in touched_officials:
            off = db.officials.get(oid)
            if off is not None:
                derive.recompute_official_derived(off)
        return object_response(serialize.game(game))


@bp.route("/games/<game_id>/cancel", methods=["POST"])
def cancel_game(game_id):
    _, role = get_user_context()
    require_role(role, {"Assignor"})
    with db.lock:
        game = lookup.game(game_id)
        if game["status"] not in {"DRAFT", "OPEN", "STAFFED", "LOCKED"}:
            err(ERR_INVALID_STATE, "game cannot be cancelled from its current state")
        # Cascade depth 3: game -> slots -> live assignments.
        for slot in db.crew_slots.values():
            if slot["game_id"] != game_id:
                continue
            aid = slot.get("current_assignment_id")
            a = db.assignments.get(aid) if aid else None
            if a is not None and a["status"] in {"OFFERED", "ACCEPTED"}:
                a["status"] = "CANCELLED"  # no penalty
                db.touch(a)
            slot["current_assignment_id"] = None
            slot["status"] = "RELEASED"
            db.touch(slot)
        game["status"] = "CANCELLED"
        db.touch(game)
        derive.recompute_game_filled_count(game)
        return object_response(serialize.game(game))
