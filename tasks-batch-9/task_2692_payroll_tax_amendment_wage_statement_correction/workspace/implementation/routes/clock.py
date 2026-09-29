"""The server-owned logical UTC clock (PRD 2.5).

This is the one endpoint that requires no identity headers at all.
"""

from flask import Blueprint

from common import F, db, get_body, iso, ok, validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    data = validate(body, {"to_iso8601": F("datetime", True)})
    db.now = data["to_iso8601"]
    return ok({"current_utc": iso(db.now)})
