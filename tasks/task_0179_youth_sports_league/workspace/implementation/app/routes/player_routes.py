"""Player endpoints: register, read, list, verify-age, record-evaluation, withdraw."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

from ..auth import require_roles
from ..calculations import tier_classification
from ..errors import raise_error
from ..response import paginated_response, success_response
from ..services.lookup import get_guardian, get_player, get_season
from ..services.serializers import serialize_player
from ..store import get_store, new_id, stamp_create, stamp_update
from ..time_utils import format_iso, parse_iso
from ..validation import (
    as_iso_datetime,
    as_number,
    as_string,
    get_json_body,
    parse_pagination,
    require_fields,
)

player_bp = Blueprint("players", __name__)


# ---------------------------------------------------------------------------
# Register player
# ---------------------------------------------------------------------------
@player_bp.route("/league/players", methods=["POST"])
@require_roles(["Guardian", "LeagueAdmin"])
def register_player():
    body = get_json_body()
    require_fields(body, ["season_id", "first_name", "last_name", "birth_date", "guardian_id"])
    store = get_store()
    # PRD §2.5: body-supplied foreign keys surface as ERR_REFERENCE_NOT_FOUND
    # when they do not resolve (HTTP 404). season_id in this body is a body FK,
    # so we use the body-FK code rather than the path-level ERR_SEASON_NOT_FOUND.
    season = store.seasons.get(body["season_id"])
    if season is None:
        raise_error("ERR_REFERENCE_NOT_FOUND")
    guardian = get_guardian(store, body["guardian_id"])
    if g.role == "Guardian" and g.user_id != guardian["id"]:
        raise_error("ERR_NOT_OWNER")

    first = as_string(body["first_name"], "first_name", min_len=1, max_len=80)
    last = as_string(body["last_name"], "last_name", min_len=1, max_len=80)
    birth = as_iso_datetime(body["birth_date"], "birth_date")

    cert_uri = None
    if "birth_certificate_uri" in body and body["birth_certificate_uri"] is not None:
        cert_uri = as_string(body["birth_certificate_uri"], "birth_certificate_uri", min_len=1, max_len=2048)

    player = {
        "id": new_id(),
        "season_id": season["id"],
        "first_name": first,
        "last_name": last,
        "birth_date": format_iso(birth),
        "guardian_id": guardian["id"],
        "birth_certificate_uri": cert_uri,
        "evaluation_score": None,
        "evaluation_tier": None,
        "status": "PENDING_VERIFICATION",
        "team_id": None,
        "draft_pick_overall": None,
    }
    stamp_create(player)
    store.players[player["id"]] = player
    store.record_audit("Player", player["id"], g.role, g.user_id, "PLAYER_REGISTERED", {})
    return success_response(serialize_player(player), status_code=201)


# ---------------------------------------------------------------------------
# Read player
# ---------------------------------------------------------------------------
@player_bp.route("/league/players/<player_id>", methods=["GET"])
@require_roles(["LeagueAdmin", "Coach", "Guardian"])
def read_player(player_id: str):
    store = get_store()
    player = get_player(store, player_id)
    if g.role == "Guardian" and player["guardian_id"] != g.user_id:
        raise_error("ERR_NOT_OWNER")
    return success_response(serialize_player(player), status_code=200)


# ---------------------------------------------------------------------------
# List players
# ---------------------------------------------------------------------------
@player_bp.route("/league/players", methods=["GET"])
@require_roles(["LeagueAdmin", "Coach"])
def list_players():
    store = get_store()
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    tier = request.args.get("evaluation_tier")

    results = []
    for p in store.players.values():
        if season_id and p["season_id"] != season_id:
            continue
        if status and p["status"] != status:
            continue
        if tier and p.get("evaluation_tier") != tier:
            continue
        results.append(p)
    results.sort(key=lambda x: x["created_at"])
    total = len(results)
    page = results[offset : offset + limit]
    return paginated_response([serialize_player(p) for p in page], total, limit, offset)


# ---------------------------------------------------------------------------
# verify-age
# ---------------------------------------------------------------------------
@player_bp.route("/league/players/<player_id>/verify-age", methods=["POST"])
@require_roles(["LeagueAdmin"])
def verify_age(player_id: str):
    store = get_store()
    player = get_player(store, player_id)
    body = get_json_body()

    # State precondition: PENDING_VERIFICATION
    if player["status"] != "PENDING_VERIFICATION":
        raise_error("ERR_INVALID_PLAYER_STATE", "Player must be PENDING_VERIFICATION.")

    season = get_season(store, player["season_id"])
    if season["status"] != "DRAFT_OPEN":
        raise_error("ERR_SEASON_NOT_DRAFT_OPEN")

    # Allow body to supply birth_certificate_uri.
    cert = player.get("birth_certificate_uri")
    if "birth_certificate_uri" in body and body["birth_certificate_uri"] is not None:
        cert = as_string(body["birth_certificate_uri"], "birth_certificate_uri", min_len=1, max_len=2048)
        player["birth_certificate_uri"] = cert
    if not cert:
        raise_error("ERR_BIRTH_CERT_REQUIRED")

    birth = parse_iso(player["birth_date"])
    min_b = parse_iso(season["min_birth_date"])
    max_b = parse_iso(season["max_birth_date"])
    if birth < min_b or birth > max_b:
        raise_error("ERR_AGE_INELIGIBLE")

    player["status"] = "AGE_VERIFIED"
    stamp_update(player)
    store.record_audit("Player", player["id"], g.role, g.user_id, "PLAYER_AGE_VERIFIED", {})
    return success_response(serialize_player(player), status_code=200)


# ---------------------------------------------------------------------------
# record-evaluation
# ---------------------------------------------------------------------------
@player_bp.route("/league/players/<player_id>/record-evaluation", methods=["POST"])
@require_roles(["LeagueAdmin"])
def record_evaluation(player_id: str):
    store = get_store()
    player = get_player(store, player_id)
    body = get_json_body()
    require_fields(body, ["evaluation_score"])

    if player["status"] != "AGE_VERIFIED":
        raise_error("ERR_INVALID_PLAYER_STATE", "Player must be AGE_VERIFIED.")

    season = get_season(store, player["season_id"])
    if season["status"] != "DRAFT_OPEN":
        raise_error("ERR_SEASON_NOT_DRAFT_OPEN")

    score = as_number(body["evaluation_score"], "evaluation_score", minimum=0, maximum=100)
    # Score is one decimal in the spec; we accept as-is and store as Decimal-like float.
    score_dec = Decimal(str(score)).quantize(Decimal("0.1"))
    tier = tier_classification(float(score_dec))

    player["evaluation_score"] = score_dec
    player["evaluation_tier"] = tier
    player["status"] = "EVALUATED"
    stamp_update(player)
    store.record_audit("Player", player["id"], g.role, g.user_id, "PLAYER_EVALUATED", {"score": str(score_dec), "tier": tier})
    return success_response(serialize_player(player), status_code=200)


# ---------------------------------------------------------------------------
# withdraw
# ---------------------------------------------------------------------------
@player_bp.route("/league/players/<player_id>/withdraw", methods=["POST"])
@require_roles(["Guardian", "LeagueAdmin"])
def withdraw_player(player_id: str):
    store = get_store()
    player = get_player(store, player_id)

    # State preconditions:
    if player["status"] == "WITHDRAWN":
        raise_error("ERR_INVALID_PLAYER_STATE", "Player already WITHDRAWN.")
    if player["status"] == "DRAFTED":
        raise_error("ERR_INVALID_PLAYER_STATE", "Cannot withdraw a DRAFTED player.")

    # Ownership for Guardian role.
    if g.role == "Guardian" and player["guardian_id"] != g.user_id:
        raise_error("ERR_NOT_OWNER")

    player["status"] = "WITHDRAWN"
    stamp_update(player)
    store.record_audit("Player", player["id"], g.role, g.user_id, "PLAYER_WITHDRAWN", {})
    return success_response(serialize_player(player), status_code=200)
