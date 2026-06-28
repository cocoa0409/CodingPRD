"""Artist roster & portfolio routes (PRD §3.1)."""
from flask import Blueprint

import errors
from db import store, LOCK
from middleware import get_identity, require_role, parse_pagination, get_json_body
from response import object_response, array_response
from services.common import base_fields, touch, public, paginate
from services.domain import recompute_portfolio_published
from services.validate import (
    require_str, require_enum, require_int_min, optional_bool, optional_int_min,
)

bp = Blueprint("artists", __name__)

SKILL_TIERS = {"LEAD", "SENIOR", "JUNIOR"}
ARTIST_STATUSES = {"ACTIVE", "SUSPENDED", "RETIRED"}
PORTFOLIO_CATEGORIES = {"HAIR", "MAKEUP", "BOTH"}


def serialize_artist(a):
    return {
        "id": a["id"],
        "display_name": a["display_name"],
        "skill_tier": a["skill_tier"],
        "hair_rate_per_face_cents": a["hair_rate_per_face_cents"],
        "makeup_rate_per_face_cents": a["makeup_rate_per_face_cents"],
        "travel_rate_per_km_cents": a["travel_rate_per_km_cents"],
        "max_faces_per_hour": a["max_faces_per_hour"],
        "can_assist": a["can_assist"],
        "status": a["status"],
        "portfolio_published": a["portfolio_published"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_portfolio(p):
    return {
        "id": p["id"],
        "artist_id": p["artist_id"],
        "look_name": p["look_name"],
        "category": p["category"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/bridal-beauty/artists", methods=["POST"])
def create_artist():
    user_id, role = get_identity()
    require_role(role, {"Coordinator"})
    body = get_json_body()

    display_name = require_str(body, "display_name")
    skill_tier = require_enum(body, "skill_tier", SKILL_TIERS)
    hair = require_int_min(body, "hair_rate_per_face_cents", 0)
    makeup = require_int_min(body, "makeup_rate_per_face_cents", 0)
    travel = require_int_min(body, "travel_rate_per_km_cents", 0)
    max_fph = require_int_min(body, "max_faces_per_hour", 1)
    can_assist = optional_bool(body, "can_assist", False)

    with LOCK:
        rec = base_fields()
        rec.update({
            "display_name": display_name,
            "skill_tier": skill_tier,
            "hair_rate_per_face_cents": hair,
            "makeup_rate_per_face_cents": makeup,
            "travel_rate_per_km_cents": travel,
            "max_faces_per_hour": max_fph,
            "can_assist": can_assist,
            "status": "ACTIVE",
            "portfolio_published": False,
        })
        store.artists[rec["id"]] = rec
        return object_response(serialize_artist(rec), 201)


@bp.route("/bridal-beauty/artists/<artist_id>", methods=["GET"])
def get_artist(artist_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist", "Client"})
    a = store.artists.get(artist_id)
    if a is None:
        raise errors.not_found()
    return object_response(serialize_artist(a), 200)


@bp.route("/bridal-beauty/artists", methods=["GET"])
def list_artists():
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist", "Client"})
    limit, offset = parse_pagination()
    from flask import request
    status_f = request.args.get("status")
    tier_f = request.args.get("skill_tier")

    items = list(store.artists.values())
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if tier_f is not None:
        items = [a for a in items if a["skill_tier"] == tier_f]

    page, total = paginate(items, limit, offset)
    return array_response([serialize_artist(a) for a in page], limit, offset, total)


@bp.route("/bridal-beauty/artists/<artist_id>", methods=["PATCH"])
def edit_artist(artist_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator"})
    body = get_json_body()

    with LOCK:
        a = store.artists.get(artist_id)
        if a is None:
            raise errors.not_found()

        # OCC on the artist row (PRD §2.7): expected_artist_version required.
        if "expected_artist_version" not in body:
            raise errors.invalid_request("expected_artist_version is required")
        ev = body["expected_artist_version"]
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise errors.invalid_request("expected_artist_version must be an integer")
        if ev != a["version"]:
            raise errors.stale_event_version("expected_artist_version does not match")

        # Optional editable fields.
        if "hair_rate_per_face_cents" in body:
            a["hair_rate_per_face_cents"] = require_int_min(body, "hair_rate_per_face_cents", 0)
        if "makeup_rate_per_face_cents" in body:
            a["makeup_rate_per_face_cents"] = require_int_min(body, "makeup_rate_per_face_cents", 0)
        if "travel_rate_per_km_cents" in body:
            a["travel_rate_per_km_cents"] = require_int_min(body, "travel_rate_per_km_cents", 0)
        if "max_faces_per_hour" in body:
            a["max_faces_per_hour"] = require_int_min(body, "max_faces_per_hour", 1)
        if "status" in body:
            a["status"] = require_enum(body, "status", ARTIST_STATUSES)
        if "can_assist" in body:
            ca = body["can_assist"]
            if not isinstance(ca, bool):
                raise errors.invalid_request("can_assist must be a boolean")
            a["can_assist"] = ca

        touch(a)
        return object_response(serialize_artist(a), 200)


@bp.route("/bridal-beauty/artists/<artist_id>/portfolio", methods=["POST"])
def add_portfolio(artist_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist"})
    body = get_json_body()

    with LOCK:
        a = store.artists.get(artist_id)
        if a is None:
            raise errors.not_found()
        look_name = require_str(body, "look_name")
        category = require_enum(body, "category", PORTFOLIO_CATEGORIES)
        rec = base_fields()
        rec.update({
            "artist_id": artist_id,
            "look_name": look_name,
            "category": category,
            "status": "DRAFT",
        })
        store.portfolio_items[rec["id"]] = rec
        return object_response(serialize_portfolio(rec), 201)


@bp.route("/bridal-beauty/portfolio/<item_id>/publish", methods=["POST"])
def publish_portfolio(item_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist"})

    with LOCK:
        p = store.portfolio_items.get(item_id)
        if p is None:
            raise errors.not_found()
        if p["status"] != "DRAFT":
            raise errors.invalid_state("Portfolio item is not DRAFT")
        p["status"] = "PUBLISHED"
        touch(p)
        artist = store.artists.get(p["artist_id"])
        if artist is not None:
            before = artist["portfolio_published"]
            recompute_portfolio_published(artist)
            if artist["portfolio_published"] != before:
                touch(artist)
        return object_response(serialize_portfolio(p), 200)


@bp.route("/bridal-beauty/artists/<artist_id>/portfolio", methods=["GET"])
def list_portfolio(artist_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist", "Client"})
    limit, offset = parse_pagination()
    from flask import request
    status_f = request.args.get("status")

    a = store.artists.get(artist_id)
    if a is None:
        raise errors.not_found()

    items = [p for p in store.portfolio_items.values() if p["artist_id"] == artist_id]
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_portfolio(p) for p in page], limit, offset, total)
