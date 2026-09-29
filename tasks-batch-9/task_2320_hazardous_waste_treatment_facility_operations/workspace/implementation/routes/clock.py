"""Logical clock control (PRD 2.5). Exempt from authentication."""

from flask import Blueprint

import schema
from db import db
from middleware import endpoint
from response import ok
from util import iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(authenticated=False)
def set_current_utc():
    body = schema.body({"current_utc": {"type": "datetime", "required": True}})
    db.current_utc = body["current_utc"]
    return ok({"current_utc": iso(db.current_utc)})
