"""Logical clock capability (PRD Section 2.5)."""
from flask import Blueprint

import auth
import common
import config
import envelope
import store
import validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require(*config.ALL_ROLES)
    body = validate.json_body()
    target = validate.datetime_field(body, "to_iso8601")
    store.set_clock(target)
    # Every clock-dependent derivation is re-evaluated for the new instant.
    common.commit()
    return envelope.object_response({"current_utc": store.now_iso()})
