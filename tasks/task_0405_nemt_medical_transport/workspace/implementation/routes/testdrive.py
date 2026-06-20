"""Test-driving capabilities: set the server clock and seed county distances
(PRD 3.10). Both are Coordinator-only and return 200 with an empty data object."""
from flask import Blueprint

from clock import clock
from db import set_county_distance
from errors import err
from helpers import get_json_body, parse_dt
from middleware import require_roles
from response import ok_object

bp = Blueprint("testdrive", __name__)


@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    require_roles("Coordinator")
    body = get_json_body()
    if "now_utc" not in body or body["now_utc"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: now_utc")
    dt = parse_dt(body["now_utc"])
    clock.set(dt)
    return ok_object({})


@bp.route("/_geo/county_distance", methods=["POST"])
def geo_county_distance():
    require_roles("Coordinator")
    body = get_json_body()
    county_a = body.get("county_a")
    county_b = body.get("county_b")
    miles = body.get("miles")
    if not isinstance(county_a, str) or county_a == "":
        raise err("ERR_INVALID_REQUEST", "county_a must be a non-empty string")
    if not isinstance(county_b, str) or county_b == "":
        raise err("ERR_INVALID_REQUEST", "county_b must be a non-empty string")
    if isinstance(miles, bool) or not isinstance(miles, (int, float)) or miles < 0:
        raise err("ERR_INVALID_REQUEST", "miles must be a non-negative number")
    set_county_distance(county_a, county_b, miles)
    return ok_object({})
