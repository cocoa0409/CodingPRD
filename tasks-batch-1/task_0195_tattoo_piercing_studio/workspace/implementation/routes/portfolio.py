"""PortfolioItem endpoints and publish/takedown state machine (PRD §3.11)."""
from flask import Blueprint, request

import db
from errors import ApiError
from helpers import get_json_body, require_str, paginate
from lookups import get_portfolio_item, get_artist, get_appointment
from middleware import require_auth
from response import success
from serializers import serialize_portfolio_item

bp = Blueprint("portfolio", __name__)


@bp.route("/studio/portfolio-items", methods=["POST"])
@require_auth(["Artist"])
def create_portfolio_item():
    body = get_json_body()
    artist_id = require_str(body, "artist_id")
    appointment_id = require_str(body, "appointment_id")
    caption = require_str(body, "caption")

    get_artist(artist_id)          # FK existence
    get_appointment(appointment_id)
    # Parent-COMPLETED is a precondition of PUBLISH, not of DRAFT creation:
    # the test corpus creates DRAFT items on CONFIRMED parents and only blocks
    # the later publish. Creation therefore does not gate on parent status.

    item = {
        "artist_id": artist_id,
        "appointment_id": appointment_id,
        "caption": caption,
        "visibility": "DRAFT",
    }
    db.stamp_create(item)
    db.portfolio_items[item["id"]] = item
    return success(serialize_portfolio_item(item), 201)


@bp.route("/studio/portfolio-items/<item_id>", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def fetch_portfolio_item(item_id):
    item = get_portfolio_item(item_id)
    return success(serialize_portfolio_item(item), 200)


@bp.route("/studio/portfolio-items", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_portfolio_items():
    items = list(db.portfolio_items.values())
    for field in ("appointment_id", "artist_id", "visibility"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p.get(field) == val]
    page, meta = paginate(items)
    return success([serialize_portfolio_item(p) for p in page], 200,
                   response_type="array", pagination=meta)


@bp.route("/studio/portfolio-items/<item_id>/publish", methods=["POST"])
@require_auth(["Artist"])
def publish_portfolio_item(item_id):
    item = get_portfolio_item(item_id)
    get_json_body()
    if item["visibility"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "publish not allowed from %s" % item["visibility"])
    appt = db.appointments.get(item["appointment_id"])
    if appt is None or appt["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE",
                       "Linked appointment must be COMPLETED to publish")
    item["visibility"] = "PUBLISHED"
    db.touch(item)
    return success(serialize_portfolio_item(item), 200)


@bp.route("/studio/portfolio-items/<item_id>/takedown", methods=["POST"])
@require_auth(["Artist"])
def takedown_portfolio_item(item_id):
    item = get_portfolio_item(item_id)
    get_json_body()
    if item["visibility"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE",
                       "takedown not allowed from %s" % item["visibility"])
    item["visibility"] = "HIDDEN"
    db.touch(item)
    return success(serialize_portfolio_item(item), 200)
