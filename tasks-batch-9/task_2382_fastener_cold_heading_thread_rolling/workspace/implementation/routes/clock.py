"""The logical clock control endpoint (PRD 2.4)."""

from flask import Blueprint, g

from db import db
from middleware import ANY_ROLE, endpoint
from response import ok
from util import iso
from validate import field_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ANY_ROLE)
def set_current_utc():
    moment = field_dt(g.body, "current_utc", required=True)
    db.clock = moment
    return ok({"current_utc": iso(moment)})
