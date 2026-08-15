"""Logical clock endpoint (PRD §2.5)."""

from flask import Blueprint
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object
from util import body, req_str, parse_datetime, iso_z

bp = Blueprint("clock", __name__)


@bp.route("/backline/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    data = body()
    to_iso8601 = req_str(data, "to_iso8601")
    dt = parse_datetime(to_iso8601, "to_iso8601")
    store.current_utc = dt
    return success_object({"current_utc": iso_z(store.current_utc)}, status=200)
