"""Show endpoints (PRD §3.1, §2.5)."""
from flask import Blueprint

import errors
import middleware as mw
from constants import (
    BILLING_MODELS,
    SHOW_FORMATS,
    TARGET_LOUDNESS_DEFAULT,
    TARGET_LOUDNESS_MAX,
    TARGET_LOUDNESS_MIN,
)
from db import db
from response import array_response, object_response
from routes.common import get_or_404
from serialize import serialize, serialize_list

bp = Blueprint("shows", __name__)


@bp.post("/shows")
def create_show():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner"})
    body = mw.get_json_body()
    title = mw.require_string(body, "title")
    fmt = mw.require_enum(body, "format", SHOW_FORMATS)
    billing_model = mw.require_enum(body, "billing_model", BILLING_MODELS)
    target = mw.optional_number(body, "target_loudness_lufs", TARGET_LOUDNESS_DEFAULT)
    if target < TARGET_LOUDNESS_MIN or target > TARGET_LOUDNESS_MAX:
        raise errors.err(errors.ERR_INVALID_REQUEST, "target_loudness_lufs out of range")
    rec = db.shows.create({
        "title": title,
        "format": fmt,
        "target_loudness_lufs": target,
        "billing_model": billing_model,
        "lifetime_billed_cents": 0,
        "production_posture": "SUSPENDED",
        "open_episode_count": 0,
    })
    return object_response(serialize(rec), status=201)


@bp.get("/shows")
def list_shows():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner", "ProducerEng", "AdOps"})
    limit, offset = mw.parse_pagination()
    from flask import request
    posture = request.args.get("production_posture")
    status_filter = request.args.get("status")
    records = db.shows.all()
    if posture is not None:
        records = [r for r in records if r["production_posture"] == posture]
    if status_filter is not None:
        records = [r for r in records if r.get("status") == status_filter]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/shows/<rid>")
def get_show(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner", "ProducerEng", "AdOps"})
    rec = get_or_404(db.shows, rid)
    if auth.role == "ShowOwner" and auth.user_id != rec["id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owner of this show")
    return object_response(serialize(rec))
