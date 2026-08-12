"""Test-driving logical clock endpoint."""
from flask import Blueprint

from db import store
from middleware import endpoint
from response import success
from util import check_fields, get_body, parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["ZoneOperator"])
def set_clock(user_id, role):
    body = get_body()
    check_fields(body, {"to_iso8601": ("dt", True)})
    store.clock = parse_dt(body["to_iso8601"])
    return success({"current_utc": body["to_iso8601"]})
