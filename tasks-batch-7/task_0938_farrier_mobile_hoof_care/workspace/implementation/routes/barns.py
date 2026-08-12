"""Barns (PRD 3.1)."""

from flask import Blueprint

from core.auth import authenticate
from core.constants import MINUTES_PER_DAY, WEEKDAYS, ZONES
from core.store import db
from core.timeutil import parse_iso_date
from core.validate import (
    body,
    enum,
    no_duplicates,
    opt_list,
    req_int,
    req_list,
    req_str,
    bad,
    out_of_range,
)
from domain.lookup import must

from ._common import ALL_ROLES, listing, single

bp = Blueprint("barns", __name__)


@bp.post("/barns")
def create_barn():
    authenticate(("PlatformAdmin",))
    data = body()
    name = req_str(data, "name")
    zone_value = data.get("zone")
    if not isinstance(zone_value, str) or not zone_value:
        bad("Field zone is required.")
    weekdays = req_list(data, "served_weekdays")
    for token in weekdays:
        if not isinstance(token, str):
            bad("served_weekdays must contain weekday tokens.")
    open_minute = req_int(data, "access_open_minute")
    close_minute = req_int(data, "access_close_minute")
    blackouts = opt_list(data, "blackout_dates", default=[])
    for value in blackouts:
        if not isinstance(value, str) or parse_iso_date(value) is None:
            bad("blackout_dates must contain ISO calendar dates.")
    no_duplicates(weekdays, "served_weekdays")

    # rung 22
    enum(zone_value, ZONES, "zone")
    for token in weekdays:
        enum(token, WEEKDAYS, "served_weekdays")

    # rung 23
    if open_minute < 0:
        out_of_range("access_open_minute may not be negative.")
    if close_minute > MINUTES_PER_DAY:
        out_of_range("access_close_minute may not exceed %d." % MINUTES_PER_DAY)
    if open_minute >= close_minute:
        out_of_range("access_open_minute must be strictly below access_close_minute.")

    row = db.mint(
        "barns",
        {
            "name": name,
            "zone": zone_value,
            "served_weekdays": list(weekdays),
            "access_open_minute": open_minute,
            "access_close_minute": close_minute,
            "blackout_dates": list(blackouts),
        },
    )
    return single(row, 201)


@bp.get("/barns")
def list_barns():
    return listing("barns", {"zone": "zone"}, ALL_ROLES)


@bp.get("/barns/<barn_id>")
def read_barn(barn_id):
    authenticate(ALL_ROLES)
    return single(must("barns", barn_id))
