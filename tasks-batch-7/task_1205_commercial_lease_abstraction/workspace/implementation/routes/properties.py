"""Property endpoints + logical clock."""

from flask import Blueprint, request

from db import db, new_resource, clock
from errors import err
from response import success_object
from services import calc
from services.core import process_clock_transitions
from services.validate import (
    body, req_string, req_int, req_present, filter_arg_int,
)
from routes.helpers import get_property_or_404, list_response

bp = Blueprint("properties", __name__)


@bp.post("/lease-admin/_clock/set_current_utc")
def set_clock():
    data = body()
    to_iso8601 = req_present(data, "to_iso8601")
    if not isinstance(to_iso8601, str):
        err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 string")
    try:
        dt = clock_parse_flex(to_iso8601)
    except ValueError:
        err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    clock.set(dt)
    process_clock_transitions()
    return success_object({"current_utc": clock.current_iso()})


def clock_parse_flex(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@bp.post("/lease-admin/properties")
def create_property():
    data = body()
    name = req_string(data, "name")
    address = req_string(data, "address")
    total_rentable_sf = req_int(data, "total_rentable_sf", min_v=1)
    fiscal_year_end_month = req_int(data, "fiscal_year_end_month",
                                    min_v=1, max_v=12)
    pid, common = new_resource()
    prop = {
        **common,
        "name": name,
        "address": address,
        "total_rentable_sf": total_rentable_sf,
        "fiscal_year_end_month": fiscal_year_end_month,
        "posture": "OPERATING",
    }
    db["properties"][pid] = prop
    return success_object(prop, status=201)


@bp.get("/lease-admin/properties/<property_id>")
def get_property(property_id):
    return success_object(get_property_or_404(property_id))


@bp.get("/lease-admin/properties")
def list_properties():
    return list_response(db["properties"].values())


@bp.get("/lease-admin/properties/<property_id>/occupancy-report")
def occupancy_report(property_id):
    prop = get_property_or_404(property_id)
    fy = filter_arg_int("fiscal_year", min_v=2000, max_v=2100)
    if fy is None:
        err("ERR_INVALID_REQUEST", "Query parameter fiscal_year is required")
    occupied_sf, rate = calc.occupancy_rate_bps(property_id, fy)
    return success_object({
        "occupied_sf": occupied_sf,
        "total_rentable_sf": prop["total_rentable_sf"],
        "occupancy_rate_bps": rate,
    })
