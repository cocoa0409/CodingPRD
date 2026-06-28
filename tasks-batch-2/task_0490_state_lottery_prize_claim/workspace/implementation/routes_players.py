"""Player endpoints + self-exclusion (PRD 3.6)."""
from flask import Blueprint, request

from clock import clock
from db import db
from errors import err
from middleware import get_auth, require_roles
from models import _stamp_create, serialize, touch, get_or_404
from response import success
from util import add_days
from validate import require_body, req_str, req_int

players_bp = Blueprint("players", __name__)


def _serialize_player(p):
    return serialize(p)


def is_excluded_now(player):
    """Active self-exclusion guard: status==EXCLUDED and clock < exclusion_until."""
    if player["self_exclusion_status"] != "EXCLUDED":
        return False
    until = player.get("exclusion_until")
    if until is None:
        return False
    return clock.now < until


@players_bp.route("/players", methods=["POST"])
def create_player():
    _, role = get_auth()
    require_roles(role, {"ClaimsClerk"})
    body = require_body(request.get_json(silent=True))

    full_name = req_str(body, "full_name")
    gov_id = req_str(body, "government_id_number")

    for p in db.players.values():
        if p["government_id_number"] == gov_id:
            raise err("ERR_DUPLICATE_RESOURCE", "government_id_number already exists")

    player = {
        "full_name": full_name,
        "government_id_number": gov_id,
        "self_exclusion_status": "NONE",
        "exclusion_until": None,
    }
    _stamp_create(player)
    db.players[player["id"]] = player
    return success(_serialize_player(player), 201)


@players_bp.route("/players/<pid>", methods=["GET"])
def get_player(pid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "ClaimsClerk"})
    player = get_or_404(db.players, pid, "player")
    return success(_serialize_player(player), 200)


@players_bp.route("/players/<pid>/self-exclude", methods=["POST"])
def self_exclude(pid):
    _, role = get_auth()
    require_roles(role, {"ClaimsClerk", "LotteryOfficer"})
    player = get_or_404(db.players, pid, "player")
    body = require_body(request.get_json(silent=True))
    exclusion_days = req_int(body, "exclusion_days", minimum=1)

    player["self_exclusion_status"] = "EXCLUDED"
    player["exclusion_until"] = add_days(clock.now, exclusion_days)
    touch(player)
    return success(_serialize_player(player), 200)


@players_bp.route("/players/<pid>/reinstate", methods=["POST"])
def reinstate(pid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    player = get_or_404(db.players, pid, "player")
    if player["self_exclusion_status"] != "EXCLUDED":
        raise err("ERR_INVALID_STATE", "player not EXCLUDED")
    # Reinstate only after the exclusion has lapsed (clock >= exclusion_until).
    until = player.get("exclusion_until")
    if until is not None and clock.now < until:
        raise err("ERR_REINSTATE_TOO_EARLY", "self-exclusion still active")
    player["self_exclusion_status"] = "REINSTATED"
    player["exclusion_until"] = None
    touch(player)
    return success(_serialize_player(player), 200)
