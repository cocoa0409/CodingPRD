"""Test-driving logical clock (PRD 2.8)."""
from flask import Blueprint

import db
from db import store
from middleware import get_context, require_roles
from response import ok
from validation import parse_body, schema_field

bp = Blueprint("misc", __name__)


@bp.post("/reman/_clock/set_current_utc")
def set_current_utc():
    uid, role, _ = get_context()
    require_roles(["ServiceManager"])
    body = parse_body({"to_iso8601": schema_field("datetime")}, allow_empty=False)
    store.clock = db.parse_iso_dt(body["to_iso8601"])
    return ok({"current_utc": db.clock_iso()})
