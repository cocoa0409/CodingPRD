"""The logical-clock control surface (PRD 2.4)."""
from flask import Blueprint

import validate
from core import Raw, read_endpoint
from db import store
from middleware import ALL_ROLES

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@read_endpoint(list(ALL_ROLES))
def set_current_utc(ctx):
    """No entity is mutated; subsequent clock reads return the supplied value."""
    data = validate.body()
    parsed = validate.req_dt(data, "current_utc")
    supplied = data["current_utc"]
    store.set_clock(parsed)
    return Raw({"current_utc": supplied})
