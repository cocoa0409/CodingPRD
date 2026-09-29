"""Hazard areas: classification, commodity escalation and reclassification (PRD 3.2)."""
from flask import Blueprint

import calc_hazard
import cascades
import db
import guards
import helpers
import response
import validate
from middleware import ALL_ROLES, authenticate

bp = Blueprint("hazard_areas", __name__)


def _declared_inputs(data, required=True):
    """The classification inputs, shared by declaration and reclassification."""
    return {
        "hazard_class": validate.req_str(
            data, "hazard_class", enum=calc_hazard.HAZARD_CLASSES
        ),
        "commodity_class": validate.req_str(
            data, "commodity_class", enum=calc_hazard.COMMODITY_CLASSES
        ),
        "storage_height_ft": validate.req_num(data, "storage_height_ft", ge=0),
        "ceiling_height_ft": validate.req_num(data, "ceiling_height_ft", gt=0),
        "area_sqft": validate.req_num(data, "area_sqft", gt=0),
    }


def _optional_inputs(data):
    return {
        "ceiling_slope_pct": validate.opt_num(data, "ceiling_slope_pct", ge=0, default=0.0),
        "room_area_sqft": validate.opt_num(data, "room_area_sqft", gt=0, default=None),
        "enclosure_rating_hours": validate.opt_num(
            data, "enclosure_rating_hours", ge=0, default=None
        ),
        "room_has_unprotected_opening": validate.opt_bool(
            data, "room_has_unprotected_opening", default=False
        ),
    }


@bp.post("/hazard-areas")
def create_hazard_area():
    actor = authenticate(["DesignEngineer"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    guards.require_lead_engineer(actor, project)
    row = {"project_id": validate.req_str(data, "project_id")}
    row["label"] = validate.req_str(data, "label")
    row.update(_declared_inputs(data))
    row["sprinkler_system_type"] = validate.req_str(
        data, "sprinkler_system_type", enum=calc_hazard.SPRINKLER_SYSTEM_TYPES
    )
    row.update(_optional_inputs(data))
    guards.require_not_frozen(project)
    row.update(calc_hazard.classify(row))
    row["reclassification_count"] = 0
    db.stamp_create(row)
    db.hazard_areas[row["id"]] = row
    return response.created(response.public(row))


@bp.get("/hazard-areas/<area_id>")
def get_hazard_area(area_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("hazard_area", area_id)))


@bp.get("/hazard-areas")
def list_hazard_areas():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.hazard_areas.values()),
        ["project_id", "effective_hazard_class", "sprinkler_system_type"],
    )
    return helpers.list_response(rows)


@bp.post("/hazard-areas/<area_id>/reclassify")
def reclassify(area_id):
    actor = authenticate(["DesignEngineer"])
    area = guards.must("hazard_area", area_id)
    project = guards.must("project", area["project_id"])
    guards.require_lead_engineer(actor, project)
    data = validate.body()
    restated = _declared_inputs(data)
    restated.update(_optional_inputs(data))
    guards.require_not_frozen(project)

    before_project = db.snapshot(project)
    area.update(restated)
    area.update(calc_hazard.classify(area))
    area["reclassification_count"] = (area["reclassification_count"] or 0) + 1
    db.touch(area)
    cascades.cascade_reclassification(area, project)
    db.touch_if_changed(project, before_project)
    return response.ok(response.public(area))
