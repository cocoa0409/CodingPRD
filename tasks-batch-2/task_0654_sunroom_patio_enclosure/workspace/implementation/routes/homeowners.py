"""Homeowner endpoints (PRD §3.1)."""
from flask import Blueprint, g

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize

bp = Blueprint("homeowners", __name__)


@bp.route("/homeowners", methods=["POST"])
def create_homeowner():
    require_roles({"SalesDesigner"})
    body = common.get_json()

    email = common.require_field(body, "email", expected_types=["string"],
                                 validator=lambda v: v != "")
    full_name = common.require_field(body, "full_name", expected_types=["string"])
    hoa_governed = common.optional_field(body, "hoa_governed", False,
                                         expected_types=["boolean"])
    ground_snow = common.require_field(body, "ground_snow_load_psf",
                                       expected_types=["number"],
                                       validator=lambda v: v >= 0)
    design_wind = common.require_field(body, "design_wind_speed_mph",
                                       expected_types=["integer"],
                                       validator=lambda v: v >= 0)

    # unique email among homeowners (PRD §3.1)
    for h in db.homeowners.values():
        if h["email"] == email:
            raise errors.invalid_request("email must be unique among homeowners.")

    entity = {
        "email": email,
        "full_name": full_name,
        "hoa_governed": hoa_governed,
        "ground_snow_load_psf": ground_snow,
        "design_wind_speed_mph": design_wind,
    }
    common.stamp_create(entity)
    db.homeowners[entity["id"]] = entity
    return response.success(serialize.homeowner(entity), status=201)
