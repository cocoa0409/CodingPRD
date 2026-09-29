"""Venue and VenueZone endpoints (PRD 3.1)."""

from flask import Blueprint

import calc
import serial
import valid
from auth import authenticate
from calc import num
from db import db, make_record
from errors import ApiError
from response import object_response
from routes._common import ALL_ROLES, get_venue, match_filters, paginated

bp = Blueprint("venues", __name__)

ZONE_TYPES = ("PERIMETER", "CONCOURSE", "FLOOR", "SEATED", "EXIT_CORRIDOR", "BACKSTAGE")


@bp.post("/venues")
def create_venue():
    authenticate({"SecurityDirector"})
    payload = valid.body()
    name = valid.req_string(payload, "name", max_length=120)
    gross_capacity = valid.req_int(payload, "gross_capacity", minimum=1)
    door_count = valid.req_int(payload, "door_count", minimum=1)
    egress = valid.req_int(payload, "egress_capacity_per_minute", minimum=1)
    perimeter = valid.req_int(payload, "perimeter_length_m", minimum=1)
    alcohol_licensed = valid.opt_bool(payload, "alcohol_licensed", default=False)
    prior_rate = valid.opt_number(payload, "prior_incident_rate", minimum=0, maximum=25, places=2)

    record = make_record(
        {
            "name": name,
            "gross_capacity": gross_capacity,
            "door_count": door_count,
            "egress_capacity_per_minute": egress,
            "perimeter_length_m": perimeter,
            "alcohol_licensed": alcohol_licensed,
            "prior_incident_rate": num(prior_rate) if prior_rate is not None else 0,
            "status": "ACTIVE",
        }
    )
    db.venues[record["id"]] = record
    return object_response(serial.venue(record), 201)


@bp.get("/venues/<venue_id>")
def read_venue(venue_id):
    authenticate(set(ALL_ROLES))
    venue = get_venue(venue_id)
    return object_response(serial.venue(venue))


@bp.post("/venues/<venue_id>/zones")
def create_zone(venue_id):
    authenticate({"SecurityDirector", "RiskAnalyst"})
    payload = valid.body()
    zone_code = valid.req_string(payload, "zone_code")
    zone_type = valid.req_enum(payload, "zone_type", ZONE_TYPES)
    floor_area = valid.req_number(payload, "floor_area_sqm", places=2)
    if floor_area <= 0:
        valid.bad("Field 'floor_area_sqm' must be greater than zero.")
    posted_capacity = valid.req_int(payload, "posted_capacity", minimum=1)
    exit_units = valid.req_int(payload, "exit_units", minimum=1)
    post_slot_capacity = valid.req_int(payload, "post_slot_capacity", minimum=1)
    is_ingress_zone = valid.opt_bool(payload, "is_ingress_zone", default=False)

    venue = get_venue(venue_id)

    for existing in db.zones.values():
        if existing.get("venue_id") == venue["id"] and existing.get("zone_code") == zone_code:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field 'zone_code' must be unique within the venue.",
            )

    record = make_record(
        {
            "venue_id": venue["id"],
            "zone_code": zone_code,
            "zone_type": zone_type,
            "floor_area_sqm": num(floor_area),
            "posted_capacity": posted_capacity,
            "exit_units": exit_units,
            "post_slot_capacity": post_slot_capacity,
            "is_ingress_zone": is_ingress_zone,
            "max_safe_occupancy": calc.zone_max_safe_occupancy(
                posted_capacity, floor_area, exit_units
            ),
        }
    )
    db.zones[record["id"]] = record
    return object_response(serial.zone(record), 201)


@bp.get("/venues/<venue_id>/zones")
def list_zones(venue_id):
    authenticate(
        {
            "SecurityDirector",
            "RiskAnalyst",
            "StaffingCoordinator",
            "IncidentCommander",
            "PostSupervisor",
        }
    )
    filters = {"zone_type": valid.query_enum("zone_type", ZONE_TYPES)}
    venue = get_venue(venue_id)
    records = [
        z
        for z in db.zones.values()
        if z.get("venue_id") == venue["id"] and match_filters(z, filters)
    ]
    return paginated(records, serial.zone)
