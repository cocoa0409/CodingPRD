"""The logical plant clock (PRD 2.4)."""

from flask import Blueprint

import store
import validation as v
from auth import endpoint
from response import object_response
from store import db

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["PlantAdmin"])
def set_current_utc():
    payload = v.body()
    instant = v.datetime_field(payload, "to_iso8601")
    db.clock = instant
    return object_response({"current_utc": store.iso_clock(instant)}, 200)
