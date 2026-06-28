"""Artist (instructor) endpoints (PRD §3.1, §3.2)."""
from flask import Blueprint

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response

bp = Blueprint("artists", __name__)


@bp.post("/studio-ops/artists")
def create_artist():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()
    full_name = helpers.as_str(body, "full_name")
    hourly = helpers.as_int(body, "hourly_rate_cents", min_value=0)
    rec = models.make_artist(full_name, hourly)
    db.artists[rec["id"]] = rec
    return object_response(models.serialize_artist(rec), 201)


@bp.get("/studio-ops/artists/<aid>")
def get_artist(aid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "PlatformAdmin")
    rec = db.artists.get(aid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Artist not found")
    return object_response(models.serialize_artist(rec), 200)


@bp.post("/studio-ops/artists/<aid>/deactivate")
def deactivate_artist(aid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    rec = db.artists.get(aid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Artist not found")
    if rec["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Artist is not ACTIVE")
    rec["status"] = "INACTIVE"
    models.touch(rec)
    return object_response(models.serialize_artist(rec), 200)
