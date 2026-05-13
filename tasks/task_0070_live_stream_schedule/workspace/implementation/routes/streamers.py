"""Streamer endpoints — create/read/list."""

from flask import Blueprint, request

import db
from errors import (
    ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_VALIDATION_FAILED, raise_err)
from middleware import require_auth, require_role, parse_pagination, paginate
from response import success
from services import audit


bp = Blueprint("streamers", __name__, url_prefix="/live-schedule/streamers")


@bp.post("")
def create_streamer():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = request.get_json(silent=True) or {}

    required = [
        "legal_name", "id_card_number", "real_name_verified",
        "health_cert_expires_at", "professional_cert_categories",
        "content_category_tags",
    ]
    for key in required:
        if key not in body:
            raise_err(ERR_VALIDATION_FAILED, f"Missing field: {key}")

    # id_card_number uniqueness across ACTIVE streamers
    new_card = body["id_card_number"]
    for s in db.raw_all("streamers"):
        if s.get("status") == "ACTIVE" and s.get("id_card_number") == new_card:
            raise_err(ERR_VALIDATION_FAILED, "id_card_number already in use")

    payload = {
        "legal_name": body["legal_name"],
        "id_card_number": new_card,
        "real_name_verified": bool(body["real_name_verified"]),
        "health_cert_expires_at": body["health_cert_expires_at"],
        "professional_cert_categories": list(body["professional_cert_categories"]),
        "content_category_tags": list(body["content_category_tags"]),
        "tier": "BRONZE",
        "lifetime_gmv_cents": 0,
        "completed_broadcast_count": 0,
        "violation_score": 0,
        "status": "ACTIVE",
        "suspension_until": None,
    }
    streamer = db.create_entity("streamers", payload)
    audit.log(
        subject_kind="STREAMER",
        subject_id=streamer["id"],
        action="CREATE",
        actor_role=role,
        actor_id=user_id,
        from_state=None,
        to_state="ACTIVE",
        payload_snapshot={"legal_name": streamer["legal_name"]},
    )
    return success(streamer, http_status=201)


@bp.get("/<sid>")
def read_streamer(sid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer",
                        "ComplianceReviewer", "Streamer"])
    entity = db.get_entity("streamers", sid)
    if entity is None:
        raise_err(ERR_NOT_FOUND, "Streamer not found")
    if role == "Streamer" and user_id != sid:
        raise_err(ERR_FORBIDDEN, "Streamers may only read their own profile")
    return success(entity)


@bp.get("")
def list_streamers():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer", "ComplianceReviewer"])
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    tier_filter = request.args.get("tier")

    def predicate(s):
        if status_filter and s.get("status") != status_filter:
            return False
        if tier_filter and s.get("tier") != tier_filter:
            return False
        return True

    items = db.list_entities("streamers", predicate=predicate)
    window, pagination = paginate(items, limit, offset)
    return success(window, pagination=pagination, response_type="array")
