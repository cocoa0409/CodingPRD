"""The test-driving logical clock (PRD 2.4).

The clock starts at the fixed default 2026-08-01T00:00:00Z and never falls back
to real wall-clock time.
"""

from flask import Blueprint

import db
import response
import validation as v
from auth import endpoint
from util import iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("GovernanceAdmin")
def set_current_utc():
    body = v.body()
    instant = v.req_dt(body, "to_iso8601")
    db.store.clock = instant
    return response.ok({"current_utc": iso(db.store.clock)})
