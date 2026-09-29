"""Logical clock test hook."""

from flask import Blueprint

import db
import response
from middleware import auth
from util import body, parse_iso, require

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@auth()
def set_current_utc():
    payload = body()
    require(payload, ["to_iso8601"])
    db.store.clock = parse_iso(payload["to_iso8601"], "to_iso8601")
    return response.ok({})
