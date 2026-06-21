"""ElevationCertificate endpoints (immutable evidence records, PRD §3.3).

A certificate carries only id + created_at (no updated_at/version). On filing,
freeboard_ft = lowest_floor_elevation_ft - Property.base_flood_elevation_ft.
"""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts
from middleware import require_roles
from response import success
from serializers import serialize_elevation_certificate
from helpers import get_body, require_str, require_number, opt_bool

bp = Blueprint("elevation_certificates", __name__)


@bp.route("/elevation-certificates", methods=["POST"])
@require_roles("PolicyHolder", "Underwriter")
def create_certificate():
    body = get_body()
    property_id = require_str(body, "property_id")
    surveyor_license = require_str(body, "surveyor_license")
    lowest_floor_elevation_ft = require_number(body, "lowest_floor_elevation_ft")
    superseded = opt_bool(body, "superseded", False)

    # Existence (priority 3): property_id FK must resolve.
    prop = db.properties.get(property_id)
    if prop is None:
        raise errors.not_found("Property not found")

    # Ownership (priority 4): a PolicyHolder may only file on a property they own.
    if g.user_role == "PolicyHolder" and prop["owner_id"] != g.user_id:
        raise errors.not_resource_owner("Not the owner of this property")

    freeboard_ft = lowest_floor_elevation_ft - prop["base_flood_elevation_ft"]

    ts = now_ts()
    eid = new_id()
    record = {
        "id": eid,
        "created_at": ts,
        "property_id": property_id,
        "surveyor_license": surveyor_license,
        "lowest_floor_elevation_ft": lowest_floor_elevation_ft,
        "freeboard_ft": freeboard_ft,
        "superseded": superseded,
    }
    db.elevation_certificates[eid] = record
    return success(serialize_elevation_certificate(record), status=201)


@bp.route("/elevation-certificates/<eid>", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def get_certificate(eid):
    record = db.elevation_certificates.get(eid)
    if record is None:
        raise errors.not_found("Elevation certificate not found")
    if g.user_role == "PolicyHolder":
        prop = db.properties.get(record["property_id"])
        if prop is not None and prop["owner_id"] != g.user_id:
            raise errors.not_resource_owner("Not the owner of this certificate's property")
    return success(serialize_elevation_certificate(record), status=200)
