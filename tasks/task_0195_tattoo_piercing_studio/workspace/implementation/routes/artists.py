"""Artist endpoints (PRD §3.1) plus FK reverse-reachability list endpoints."""
from flask import Blueprint

import db
from errors import ApiError
from helpers import (get_json_body, require_str, require_int, optional_int,
                     require_enum, paginate)
from lookups import get_artist
from middleware import require_auth
from response import success
from serializers import (serialize_artist, serialize_flash,
                         serialize_custom_request, serialize_portfolio_item)
from services import strict_reliability_score
from flask import request

bp = Blueprint("artists", __name__)

DISCIPLINES = {"TATTOO", "PIERCING", "BOTH"}


@bp.route("/studio/artists", methods=["POST"])
@require_auth(["StudioManager"])
def create_artist():
    body = get_json_body()
    display_name = require_str(body, "display_name")
    discipline = require_enum(body, "discipline", DISCIPLINES)
    hourly_rate_cents = require_int(body, "hourly_rate_cents")
    if hourly_rate_cents < 1000:
        raise ApiError("ERR_INVALID_REQUEST", "hourly_rate_cents must be >= 1000")

    commission_pct = body.get("commission_pct", 0.70)
    if commission_pct is None:
        commission_pct = 0.70
    if isinstance(commission_pct, bool) or not isinstance(commission_pct, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "commission_pct must be a number")
    if not (0 < commission_pct <= 1):
        raise ApiError("ERR_INVALID_REQUEST", "commission_pct must be in (0, 1]")

    accepting_custom = body.get("accepting_custom", True)
    if accepting_custom is None:
        accepting_custom = True
    if not isinstance(accepting_custom, bool):
        raise ApiError("ERR_INVALID_REQUEST", "accepting_custom must be a boolean")

    artist = {
        "display_name": display_name,
        "discipline": discipline,
        "hourly_rate_cents": hourly_rate_cents,
        "commission_pct": commission_pct,
        "accepting_custom": accepting_custom,
        "completed_session_count": 0,
        "artist_cancel_count": 0,
        "late_reschedule_count": 0,
        "reliability_score": 100,
    }
    db.stamp_create(artist)
    db.artists[artist["id"]] = artist
    return success(serialize_artist(artist), 201)


@bp.route("/studio/artists/<artist_id>", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def fetch_artist(artist_id):
    artist = get_artist(artist_id)
    return success(serialize_artist(artist), 200)


@bp.route("/studio/artists", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_artists():
    discipline = request.args.get("discipline")
    items = list(db.artists.values())
    if discipline is not None:
        items = [a for a in items if a["discipline"] == discipline]
    page, meta = paginate(items)
    return success([serialize_artist(a) for a in page], 200,
                   response_type="array", pagination=meta)


@bp.route("/studio/artists/<artist_id>/flash-designs", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_artist_flash(artist_id):
    get_artist(artist_id)
    status = request.args.get("status")
    items = [f for f in db.flash_designs.values() if f["artist_id"] == artist_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, meta = paginate(items)
    return success([serialize_flash(f) for f in page], 200,
                   response_type="array", pagination=meta)


@bp.route("/studio/artists/<artist_id>/custom-requests", methods=["GET"])
@require_auth(["StudioManager", "Artist"])
def list_artist_custom_requests(artist_id):
    get_artist(artist_id)
    status = request.args.get("status")
    items = [r for r in db.custom_requests.values() if r["artist_id"] == artist_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return success([serialize_custom_request(r) for r in page], 200,
                   response_type="array", pagination=meta)


@bp.route("/studio/artists/<artist_id>/portfolio-items", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_artist_portfolio(artist_id):
    get_artist(artist_id)
    visibility = request.args.get("visibility")
    items = [p for p in db.portfolio_items.values() if p["artist_id"] == artist_id]
    if visibility is not None:
        items = [p for p in items if p["visibility"] == visibility]
    page, meta = paginate(items)
    return success([serialize_portfolio_item(p) for p in page], 200,
                   response_type="array", pagination=meta)
