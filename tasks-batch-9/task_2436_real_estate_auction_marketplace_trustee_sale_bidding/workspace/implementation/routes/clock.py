"""The logical clock (PRD §2.5)."""

from flask import Blueprint

import db
import validate as v
from auth import authenticate
from util import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    data = v.body()
    instant = v.req_dt(data, "to_iso8601")
    # Setting the clock is inert with respect to data: nothing is mutated and no
    # deferred transition fires.  Consequences are realized lazily.
    db.set_clock(instant)
    return ok({})
