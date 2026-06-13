"""CustomDesignRequest endpoints and the quote/revision/approve/decline
state machine (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import ApiError
from helpers import (get_json_body, require_str, require_int, optional_int,
                     paginate)
from lookups import get_custom_request, get_artist, get_client
from middleware import require_auth
from response import success
from serializers import serialize_custom_request

bp = Blueprint("custom_requests", __name__)


@bp.route("/studio/custom-requests", methods=["POST"])
@require_auth(["Client"])
def create_custom_request():
    body = get_json_body()
    artist_id = require_str(body, "artist_id")
    client_id = require_str(body, "client_id")
    brief = require_str(body, "brief")

    get_artist(artist_id)   # FK existence (left-to-right body FKs)
    get_client(client_id)

    req = {
        "artist_id": artist_id,
        "client_id": client_id,
        "brief": brief,
        "quoted_price_cents": None,
        "quoted_hourly_rate_cents": None,
        "estimated_minutes": None,
        "status": "PENDING",
    }
    db.stamp_create(req)
    db.custom_requests[req["id"]] = req
    return success(serialize_custom_request(req), 201)


@bp.route("/studio/custom-requests/<request_id>", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def fetch_custom_request(request_id):
    req = get_custom_request(request_id)
    return success(serialize_custom_request(req), 200)


@bp.route("/studio/custom-requests", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_custom_requests():
    client_id = request.args.get("client_id")
    artist_id = request.args.get("artist_id")
    status = request.args.get("status")
    items = list(db.custom_requests.values())
    if client_id is not None:
        items = [r for r in items if r["client_id"] == client_id]
    if artist_id is not None:
        items = [r for r in items if r["artist_id"] == artist_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return success([serialize_custom_request(r) for r in page], 200,
                   response_type="array", pagination=meta)


@bp.route("/studio/custom-requests/<request_id>/quote", methods=["POST"])
@require_auth(["Artist"])
def quote_custom_request(request_id):
    req = get_custom_request(request_id)
    body = get_json_body()
    # State: quote allowed only from PENDING or REVISION_REQUESTED.
    if req["status"] not in ("PENDING", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "quote not allowed from %s" % req["status"])

    quoted_price = optional_int(body, "quoted_price_cents")
    quoted_hourly = optional_int(body, "quoted_hourly_rate_cents")
    estimated_minutes = body.get("estimated_minutes")

    # estimated_minutes required and >= 15
    if estimated_minutes is None:
        raise ApiError("ERR_INVALID_REQUEST", "estimated_minutes is required")
    if isinstance(estimated_minutes, bool) or not isinstance(estimated_minutes, int):
        raise ApiError("ERR_INVALID_REQUEST", "estimated_minutes must be an integer")
    if estimated_minutes < 15:
        raise ApiError("ERR_INVALID_REQUEST", "estimated_minutes must be >= 15")

    # Must supply at least one of price / hourly rate; neither -> ERR_VALIDATION.
    if quoted_price is None and quoted_hourly is None:
        raise ApiError("ERR_VALIDATION",
                       "quote must supply quoted_price_cents or quoted_hourly_rate_cents")
    if quoted_price is not None and quoted_price < 1000:
        raise ApiError("ERR_INVALID_REQUEST", "quoted_price_cents must be >= 1000")
    if quoted_hourly is not None and quoted_hourly < 1000:
        raise ApiError("ERR_INVALID_REQUEST", "quoted_hourly_rate_cents must be >= 1000")

    req["quoted_price_cents"] = quoted_price
    req["quoted_hourly_rate_cents"] = quoted_hourly
    req["estimated_minutes"] = estimated_minutes
    req["status"] = "QUOTED"
    db.touch(req)
    return success(serialize_custom_request(req), 200)


@bp.route("/studio/custom-requests/<request_id>/request-revision", methods=["POST"])
@require_auth(["Client"])
def request_revision(request_id):
    req = get_custom_request(request_id)
    get_json_body()
    if req["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE",
                       "request-revision not allowed from %s" % req["status"])
    req["status"] = "REVISION_REQUESTED"
    db.touch(req)
    return success(serialize_custom_request(req), 200)


@bp.route("/studio/custom-requests/<request_id>/approve", methods=["POST"])
@require_auth(["Client"])
def approve_custom_request(request_id):
    req = get_custom_request(request_id)
    get_json_body()
    if req["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE",
                       "approve not allowed from %s" % req["status"])
    req["status"] = "APPROVED"
    db.touch(req)
    return success(serialize_custom_request(req), 200)


@bp.route("/studio/custom-requests/<request_id>/decline", methods=["POST"])
@require_auth(["Artist"])
def decline_custom_request(request_id):
    req = get_custom_request(request_id)
    get_json_body()
    if req["status"] not in ("PENDING", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "decline not allowed from %s" % req["status"])
    req["status"] = "DECLINED"
    db.touch(req)
    return success(serialize_custom_request(req), 200)
