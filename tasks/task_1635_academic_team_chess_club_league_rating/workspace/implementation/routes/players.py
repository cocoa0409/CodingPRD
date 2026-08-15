from flask import Blueprint, g, request

from db import store, new_id, next_seq, now_iso
from errors import (invalid_request, state_error, integrity_error,
                    forbidden_ownership)
from middleware import require_roles, ALL_ROLES, acting_coach
from response import success_object, success_array, paginate
from services.common import get_or_404, touch, performance_points
from services.serializers import player_json
from validate import Body, get_body

bp = Blueprint("players", __name__)

READ = ALL_ROLES


def _coach_owns_club(club_id):
    coach = acting_coach()
    if coach is None or coach["club_id"] != club_id:
        raise forbidden_ownership()


@bp.route("/api/players", methods=["POST"])
@require_roles("ClubCoach", "FederationAdmin")
def create_player():
    data = get_body()
    club_id = data.get("club_id")
    if isinstance(club_id, str):
        get_or_404(store.clubs, club_id, "club")
    # ownership (rung 5) before shape (rung 7) beyond FK presence
    if g.user_role == "ClubCoach":
        if not isinstance(club_id, str):
            raise invalid_request("club_id is required")
        _coach_owns_club(club_id)
    body = Body(data, {"club_id", "full_name", "grade_level", "initial_rating",
                       "initial_rated_games"})
    cid = body.req_str("club_id")
    club = get_or_404(store.clubs, cid, "club")
    name = body.req_str("full_name")
    grade = body.req_int("grade_level")
    if grade < 1 or grade > 12:
        raise invalid_request("grade_level must be between 1 and 12")
    season = store.seasons[club["season_id"]]
    init_rating = body.opt_int("initial_rating")
    if init_rating is None:
        init_rating = season["base_rating"]
    init_games = body.opt_int("initial_rated_games")
    if init_games is None:
        init_games = 0
    if init_games < 0:
        raise invalid_request("initial_rated_games must be >= 0")
    if club["status"] == "SUSPENDED":
        raise integrity_error("ERR_CLUB_SUSPENDED", "Club is SUSPENDED")
    now = now_iso()
    p = {"id": new_id(), "_seq": next_seq(), "created_at": now, "updated_at": now,
         "version": 1, "club_id": cid, "full_name": name, "grade_level": grade,
         "initial_rating": init_rating, "initial_rated_games": init_games,
         "rating": init_rating, "peak_rating": init_rating,
         "rated_games_played": init_games,
         "is_provisional": init_games < season["provisional_game_threshold"],
         "status": "ACTIVE"}
    store.players[p["id"]] = p
    return success_object(player_json(p), 201)


@bp.route("/api/players", methods=["GET"])
@require_roles(*READ)
def list_players():
    items = list(store.players.values())
    cid = request.args.get("club_id")
    if cid is not None:
        items = [p for p in items if p["club_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    prov = request.args.get("is_provisional")
    if prov is not None:
        want = prov.strip().lower() in ("true", "1", "yes")
        items = [p for p in items if p["is_provisional"] == want]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([player_json(p) for p in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/players/<playerId>", methods=["GET"])
@require_roles(*READ)
def get_player(playerId):
    p = get_or_404(store.players, playerId, "player")
    return success_object(player_json(p), 200)


def _player_transition(playerId, from_states, to_state, coach_scoped):
    get_body()
    p = get_or_404(store.players, playerId, "player")
    if coach_scoped and g.user_role == "ClubCoach":
        _coach_owns_club(p["club_id"])
    if p["status"] not in from_states:
        raise state_error("ERR_PLAYER_INVALID_STATE",
                          "Player cannot transition from %s" % p["status"])
    p["status"] = to_state
    touch(p)
    return p


@bp.route("/api/players/<playerId>/deactivate", methods=["POST"])
@require_roles("ClubCoach", "FederationAdmin")
def deactivate_player(playerId):
    p = _player_transition(playerId, ("ACTIVE",), "INACTIVE", coach_scoped=True)
    return success_object(player_json(p), 200)


@bp.route("/api/players/<playerId>/reactivate", methods=["POST"])
@require_roles("ClubCoach", "FederationAdmin")
def reactivate_player(playerId):
    p = _player_transition(playerId, ("INACTIVE",), "ACTIVE", coach_scoped=True)
    return success_object(player_json(p), 200)


@bp.route("/api/players/<playerId>/suspend", methods=["POST"])
@require_roles("FederationAdmin")
def suspend_player(playerId):
    p = _player_transition(playerId, ("ACTIVE", "INACTIVE"), "SUSPENDED",
                           coach_scoped=False)
    return success_object(player_json(p), 200)
