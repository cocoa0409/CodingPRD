"""Theme routes."""
from flask import Blueprint, request

from db import store, make_common, bump
from middleware import require_role
from response import success_object, success_array
from validators import (
    get_json_body, require_string, require_int, optional_int, require_field,
    require_enum, require_list, optional_list, parse_pagination,
    paginate_list, sort_by_created_at,
)
from errors import (
    raise_error,
    ERR_THEME_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_THEME_NO_COMPATIBLE_ROOM, ERR_THEME_HAS_FUTURE_SESSIONS,
    ERR_INSUFFICIENT_PERMISSIONS,
)


themes_bp = Blueprint("themes", __name__)


GENRES = ["MYSTERY", "HORROR", "EMOTIONAL", "SCIFI", "COMEDY", "PUZZLE"]
DIFFICULTIES = ["EASY", "MEDIUM", "HARD", "EXPERT"]


def _theme_view(t: dict) -> dict:
    out = {
        "id": t["id"],
        "chain_id": t["chain_id"],
        "title": t["title"],
        "genre": t["genre"],
        "difficulty": t["difficulty"],
        "duration_minutes": t["duration_minutes"],
        "min_players": t["min_players"],
        "max_players": t["max_players"],
        "required_host_qualifications": t.get("required_host_qualifications") or [],
        "required_npc_count": t.get("required_npc_count", 0),
        "compatible_room_ids": t.get("compatible_room_ids") or [],
        "base_price_cents": t["base_price_cents"],
        "author_royalty_bps_override": t.get("author_royalty_bps_override"),
        "current_version": t["current_version"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }
    if "aggregated_theme_score" in t:
        out["aggregated_theme_score"] = t.get("aggregated_theme_score")
        out["aggregated_host_score"] = t.get("aggregated_host_score")
        out["aggregated_venue_score"] = t.get("aggregated_venue_score")
    return out


def _verify_script_author(user_id: str, theme: dict):
    """ScriptAuthor identity: X-User-ID equals StaffMember.id whose chain_id matches theme.chain_id."""
    sm = store.staff_members.get(user_id)
    if not sm or sm.get("chain_id") != theme.get("chain_id"):
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "script author chain mismatch")


@themes_bp.route("/themes", methods=["POST"])
def create_theme():
    user_id, role = require_role("ScriptAuthor")
    body = get_json_body()
    chain_id = require_string(body, "chain_id")
    # ScriptAuthor must belong to the chain
    sm = store.staff_members.get(user_id)
    if not sm or sm.get("chain_id") != chain_id:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "script author chain mismatch")

    title = require_string(body, "title", 1, 200)
    genre = require_enum(body, "genre", GENRES)
    difficulty = require_enum(body, "difficulty", DIFFICULTIES)
    duration_minutes = require_int(body, "duration_minutes", 30, 360)
    min_players = require_int(body, "min_players", 1, 20)
    max_players = require_int(body, "max_players", min_players, 20)
    required_host_qualifications = optional_list(body, "required_host_qualifications", default=[])
    required_npc_count = optional_int(body, "required_npc_count", 0, 10, default=0)
    compatible_room_ids = require_list(body, "compatible_room_ids")
    if len(compatible_room_ids) == 0:
        raise_error(ERR_INVALID_REQUEST, "compatible_room_ids must be non-empty")
    # All compatible rooms must exist and be in same chain
    for rid in compatible_room_ids:
        r = store.rooms.get(rid)
        if not r:
            raise_error(ERR_INVALID_REQUEST, f"room {rid} not found")
        venue = store.venues.get(r["venue_id"])
        if not venue or venue["chain_id"] != chain_id:
            raise_error(ERR_INVALID_REQUEST, "compatible_room_id not in same chain")
    base_price_cents = require_int(body, "base_price_cents", 0, 100_000_000)
    author_royalty_bps_override = optional_int(body, "author_royalty_bps_override", 0, 10000, default=None)

    # Title uniqueness in chain
    for t in store.themes.values():
        if t["chain_id"] == chain_id and t["title"] == title:
            raise_error(ERR_INVALID_REQUEST, "theme title not unique in chain")

    t = make_common({
        "chain_id": chain_id,
        "title": title,
        "genre": genre,
        "difficulty": difficulty,
        "duration_minutes": duration_minutes,
        "min_players": min_players,
        "max_players": max_players,
        "required_host_qualifications": required_host_qualifications,
        "required_npc_count": required_npc_count,
        "compatible_room_ids": compatible_room_ids,
        "base_price_cents": base_price_cents,
        "author_royalty_bps_override": author_royalty_bps_override,
        "current_version": 1,
        "status": "DRAFT",
        "aggregated_theme_score": None,
        "aggregated_host_score": None,
        "aggregated_venue_score": None,
    })
    store.themes[t["id"]] = t
    return success_object(_theme_view(t), 201)


@themes_bp.route("/themes/<theme_id>/publish", methods=["POST"])
def publish_theme(theme_id):
    user_id, role = require_role("ScriptAuthor")
    t = store.themes.get(theme_id)
    if not t:
        raise_error(ERR_THEME_NOT_FOUND, "theme not found")
    _verify_script_author(user_id, t)
    if t["status"] != "DRAFT":
        raise_error(ERR_INVALID_REQUEST, "theme not DRAFT")
    if not t.get("compatible_room_ids"):
        raise_error(ERR_THEME_NO_COMPATIBLE_ROOM, "no compatible rooms")
    if t["min_players"] > t["max_players"]:
        raise_error(ERR_INVALID_REQUEST, "min_players > max_players")
    t["status"] = "PUBLISHED"
    bump(t)
    return success_object(_theme_view(t))


@themes_bp.route("/themes/<theme_id>/publish-revision", methods=["POST"])
def publish_revision(theme_id):
    user_id, role = require_role("ScriptAuthor")
    t = store.themes.get(theme_id)
    if not t:
        raise_error(ERR_THEME_NOT_FOUND, "theme not found")
    _verify_script_author(user_id, t)
    if t["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_REQUEST, "theme not PUBLISHED")
    body = get_json_body()
    if body.get("bumps_version") is not True:
        raise_error(ERR_INVALID_REQUEST, "bumps_version must be true")
    t["current_version"] = int(t["current_version"]) + 1
    bump(t)
    return success_object(_theme_view(t))


@themes_bp.route("/themes/<theme_id>/retire", methods=["POST"])
def retire_theme(theme_id):
    user_id, role = require_role("ScriptAuthor")
    t = store.themes.get(theme_id)
    if not t:
        raise_error(ERR_THEME_NOT_FOUND, "theme not found")
    _verify_script_author(user_id, t)
    if t["status"] not in ("DRAFT", "PUBLISHED"):
        raise_error(ERR_INVALID_REQUEST, "theme not in DRAFT or PUBLISHED")
    # No SessionSlot SCHEDULED|LIVE referencing it
    for s in store.session_slots.values():
        if s["theme_id"] == theme_id and s["schedule_status"] in ("SCHEDULED", "LIVE"):
            raise_error(ERR_THEME_HAS_FUTURE_SESSIONS, "theme has future sessions")
    t["status"] = "RETIRED"
    bump(t)
    return success_object(_theme_view(t))


@themes_bp.route("/themes/<theme_id>", methods=["GET"])
def get_theme(theme_id):
    require_role("PlatformAdmin", "VenueOperator", "ScriptAuthor", "Player")
    t = store.themes.get(theme_id)
    if not t:
        raise_error(ERR_THEME_NOT_FOUND, "theme not found")
    return success_object(_theme_view(t))


@themes_bp.route("/themes", methods=["GET"])
def list_themes():
    require_role("PlatformAdmin", "VenueOperator", "ScriptAuthor", "Player")
    limit, offset = parse_pagination()
    chain_id = request.args.get("chain_id")
    items = list(store.themes.values())
    if chain_id:
        items = [t for t in items if t["chain_id"] == chain_id]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate_list(items, limit, offset)
    return success_array([_theme_view(t) for t in page], limit, offset, total)
