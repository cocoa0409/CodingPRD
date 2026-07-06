"""Engineer endpoints (PRD §3.3)."""
from flask import Blueprint, request

import errors
import middleware as mw
from constants import REMOTE_BUFFER_DEFAULT
from db import db
from response import array_response, object_response
from routes.common import get_or_404
from serialize import serialize, serialize_list

bp = Blueprint("engineers", __name__)


@bp.post("/engineers")
def create_engineer():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    body = mw.get_json_body()
    name = mw.require_string(body, "name")
    buffer_minutes = mw.optional_int(body, "remote_buffer_minutes", REMOTE_BUFFER_DEFAULT)
    if buffer_minutes < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "remote_buffer_minutes must be >= 0")
    active = mw.optional_bool(body, "active", True)
    rec = db.engineers.create({
        "name": name,
        "remote_buffer_minutes": buffer_minutes,
        "active": active,
    })
    return object_response(serialize(rec), status=201)


@bp.get("/engineers")
def list_engineers():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ProducerEng"})
    limit, offset = mw.parse_pagination()
    records = db.engineers.all()
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        records = [r for r in records if r["active"] == want]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/engineers/<rid>")
def get_engineer(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ProducerEng"})
    rec = get_or_404(db.engineers, rid)
    return object_response(serialize(rec))
