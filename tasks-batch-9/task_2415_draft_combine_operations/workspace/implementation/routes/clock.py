"""The server-controlled logical clock (PRD 2.5)."""

from flask import Blueprint

import auth
import logic
import respond
import validate
from db import db
from timeutil import fmt_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    target = validate.instant(data, "to_iso8601")
    db.now = target
    logic.share_expiry_sweep()
    return respond.payload({"current_utc": fmt_iso(db.now)})
