"""Community resource center registry endpoints."""

from flask import Blueprint

import db
import validation as v
from middleware import (
    COMMUNITY_LIAISON,
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import object_response

bp = Blueprint("centers", __name__)

READ_ROLES = (
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    COMMUNITY_LIAISON,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
)


@bp.post("/community-resource-centers")
@roles(COMMUNITY_LIAISON)
def create_center():
    body = v.Body()
    center_code = body.string("resource_center_code", 3, 40)
    district_code = body.string("district_code", 3, 40)
    site_capacity = body.integer("site_capacity", minimum=1)
    certified = body.boolean("accessibility_certified", default=False)

    v.unique_code(db.resource_centers, "resource_center_code", center_code)

    row = db.new_row()
    row["resource_center_code"] = center_code
    row["district_code"] = district_code
    row["site_capacity"] = site_capacity
    row["accessibility_certified"] = certified
    row["status"] = "STANDBY"
    row["psps_event_id"] = None
    db.set_dt(row, "activated_at", None)
    db.set_dt(row, "demobilized_at", None)
    db.set_dt(row, "last_served_all_clear_at", None)
    row["activation_order"] = None
    db.resource_centers[row["id"]] = row
    return object_response(db.resource_center_out(row), 201)


@bp.get("/community-resource-centers/<center_id>")
@roles(*READ_ROLES)
def get_center(center_id):
    return object_response(db.resource_center_out(v.resource_center(center_id)))
