"""FlashDesign endpoints (PRD §3.3)."""
from flask import Blueprint

import db
from errors import ApiError
from helpers import get_json_body, require_str, require_int
from lookups import get_flash, get_artist
from middleware import require_auth
from response import success
from serializers import serialize_flash

bp = Blueprint("flash", __name__)


@bp.route("/studio/flash-designs", methods=["POST"])
@require_auth(["Artist"])
def create_flash():
    body = get_json_body()
    artist_id = require_str(body, "artist_id")
    title = require_str(body, "title")
    piece_price_cents = require_int(body, "piece_price_cents")
    estimated_minutes = require_int(body, "estimated_minutes")

    if piece_price_cents < 1000:
        raise ApiError("ERR_INVALID_REQUEST", "piece_price_cents must be >= 1000")
    if estimated_minutes < 15:
        raise ApiError("ERR_INVALID_REQUEST", "estimated_minutes must be >= 15")

    get_artist(artist_id)  # FK existence

    flash = {
        "artist_id": artist_id,
        "title": title,
        "piece_price_cents": piece_price_cents,
        "estimated_minutes": estimated_minutes,
        "status": "AVAILABLE",
    }
    db.stamp_create(flash)
    db.flash_designs[flash["id"]] = flash
    return success(serialize_flash(flash), 201)


@bp.route("/studio/flash-designs/<flash_id>", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def fetch_flash(flash_id):
    flash = get_flash(flash_id)
    return success(serialize_flash(flash), 200)


@bp.route("/studio/flash-designs/<flash_id>/retire", methods=["POST"])
@require_auth(["Artist"])
def retire_flash(flash_id):
    flash = get_flash(flash_id)
    get_json_body()
    # Retire permitted only from AVAILABLE (not when RESERVED or already RETIRED).
    if flash["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE",
                       "retire not allowed from %s" % flash["status"])
    flash["status"] = "RETIRED"
    db.touch(flash)
    return success(serialize_flash(flash), 200)
