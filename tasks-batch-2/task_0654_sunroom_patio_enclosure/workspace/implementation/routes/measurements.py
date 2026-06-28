"""Measurement endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, calculations

bp = Blueprint("measurements", __name__)


@bp.route("/measurements", methods=["POST"])
def create_measurement():
    require_roles({"SalesDesigner"})
    body = common.get_json()

    project_id = common.require_field(body, "project_id", expected_types=["string"])
    width_in = common.require_field(body, "width_in", expected_types=["number"],
                                    validator=lambda v: v > 0)
    depth_in = common.require_field(body, "depth_in", expected_types=["number"],
                                    validator=lambda v: v > 0)
    wall_height_in = common.require_field(body, "wall_height_in",
                                          expected_types=["number"],
                                          validator=lambda v: v > 0)
    existing_slab = common.optional_field(body, "existing_slab", False,
                                          expected_types=["boolean"])

    common.get_project(project_id)  # FK existence (priority 4)

    entity = {
        "project_id": project_id,
        "width_in": width_in,
        "depth_in": depth_in,
        "wall_height_in": wall_height_in,
        "existing_slab": existing_slab,
        "status": "PENDING",
    }
    common.stamp_create(entity)
    db.measurements[entity["id"]] = entity
    return response.success(serialize.measurement(entity), status=201)


@bp.route("/measurements/<mid>/accept", methods=["POST"])
def accept_measurement(mid):
    require_roles({"SalesDesigner"})
    common.get_json()
    measurement = common.get_measurement(mid)
    project = common.get_project(measurement["project_id"])

    # state checks (priority 5)
    if measurement["status"] != "PENDING":
        raise errors.invalid_state("Measurement must be PENDING to accept.")
    if project["status"] in common.PROJECT_TERMINAL:
        raise errors.invalid_state("Project is terminal; cannot accept measurement.")

    if project["status"] == "DRAFT":
        # first measurement: DRAFT -> MEASURED
        measurement["status"] = "ACCEPTED"
        common.touch(measurement)
        _copy_dims(project, measurement)
        project["status"] = "MEASURED"
        common.touch(project)
    elif project["status"] in ("DESIGNED", "QUOTED"):
        # re-measure: a project that has already reached DESIGNED (DESIGNED or QUOTED,
        # the latter holding outstanding ISSUED estimates) re-measures back to MEASURED,
        # only while it holds no accepted quote (accepted_quote_id is still null).
        if project["accepted_quote_id"] is not None:
            raise errors.invalid_state(
                "Cannot re-measure a project with an accepted quote.")
        # supersede prior ACCEPTED measurement(s) on this project
        for m in db.measurements.values():
            if (m["project_id"] == project["id"] and m["status"] == "ACCEPTED"
                    and m["id"] != mid):
                m["status"] = "SUPERSEDED"
                common.touch(m)
        measurement["status"] = "ACCEPTED"
        common.touch(measurement)
        _copy_dims(project, measurement)
        # supersede every ISSUED quote on this project
        for q in db.quotes.values():
            if q["project_id"] == project["id"] and q["status"] == "ISSUED":
                q["status"] = "SUPERSEDED"
                common.touch(q)
        project["status"] = "MEASURED"
        common.touch(project)
    else:
        # MEASURED or any other non-DRAFT/non-DESIGNED state: no transition allowed
        raise errors.invalid_state(
            "Project is not in a state that accepts a measurement.")

    return response.success(serialize.measurement(measurement), status=200)


def _copy_dims(project, measurement):
    project["width_in"] = measurement["width_in"]
    project["depth_in"] = measurement["depth_in"]
    project["footprint_sqft"] = calculations.footprint_area(
        measurement["width_in"], measurement["depth_in"])
