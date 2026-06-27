"""DrawingGame endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from middleware import get_auth, require_roles
from models import (_stamp_create, serialize, get_or_404, parse_pagination,
                    paginate, sort_by_created)
from response import success
from validate import (require_body, req_str, req_int, opt_int, opt_number,
                      req_enum)

games_bp = Blueprint("games", __name__)

GAME_TYPES = {"JACKPOT", "INSTANT", "DAILY"}
ALL_ROLES = {"LotteryOfficer", "LicensingAdmin", "ClaimsClerk", "TerminalOperator"}


def _serialize_game(g):
    return serialize(g)


@games_bp.route("/games", methods=["POST"])
def create_game():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    body = require_body(request.get_json(silent=True))

    name = req_str(body, "name")
    game_type = req_enum(body, "game_type", GAME_TYPES)
    claim_window_days = req_int(body, "claim_window_days", minimum=1)
    fed_threshold = opt_int(body, "federal_withholding_threshold_cents", 60000000, minimum=0)
    fed_rate = opt_number(body, "federal_withholding_rate", 0.24, minimum=0, maximum=1, max_exclusive=True)
    state_rate = opt_number(body, "state_withholding_rate", 0.05, minimum=0, maximum=1, max_exclusive=True)
    cash_factor = opt_number(body, "cash_option_factor", 0.60, minimum=0, maximum=1, min_exclusive=True)
    annuity_years = opt_int(body, "annuity_years", 30, minimum=1)

    game = {
        "name": name,
        "game_type": game_type,
        "claim_window_days": claim_window_days,
        "federal_withholding_threshold_cents": fed_threshold,
        "federal_withholding_rate": fed_rate,
        "state_withholding_rate": state_rate,
        "cash_option_factor": cash_factor,
        "annuity_years": annuity_years,
        "status": "ACTIVE",
    }
    _stamp_create(game)
    db.games[game["id"]] = game
    return success(_serialize_game(game), 201)


@games_bp.route("/games/<gid>", methods=["GET"])
def get_game(gid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    game = get_or_404(db.games, gid, "game")
    return success(_serialize_game(game), 200)


@games_bp.route("/games", methods=["GET"])
def list_games():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.games.values())
    status_f = request.args.get("status")
    if status_f is not None:
        rows = [g for g in rows if g["status"] == status_f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_game(g) for g in page], 200, pagination=meta)
