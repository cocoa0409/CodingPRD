"""SiteAssessment endpoints."""

from flask import Blueprint, request

from clock import now_iso_ms, format_iso_ms, now
from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_enum, require_number, base_fields, paginate, err, touch,
)
from response import success_object, success_list
from errors import (
    ERR_ASSESSMENT_NOT_FOUND, ERR_PROPERTY_NOT_FOUND, ERR_ASSESSMENT_NOT_SUBMITTABLE,
    ERR_NOT_RESOURCE_OWNER,
)
from services import pavement_condition_index

bp = Blueprint("assessments", __name__)


def serialize_assessment(a):
    return {
        "id": a["id"],
        "property_id": a["property_id"],
        "measured_area_sqft": a["measured_area_sqft"],
        "crack_linear_ft": a["crack_linear_ft"],
        "pothole_count": a["pothole_count"],
        "pothole_area_sqft": a["pothole_area_sqft"],
        "oil_spot_area_sqft": a["oil_spot_area_sqft"],
        "slope_severity": a["slope_severity"],
        "pavement_condition_index": a["pavement_condition_index"],
        "submitted_at": a["submitted_at"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/api/assessments")
def create_assessment():
    require_role("Estimator")
    body = get_json_body()
    check_unknown_fields(body, {"property_id", "measured_area_sqft", "crack_linear_ft",
                                 "pothole_count", "pothole_area_sqft", "oil_spot_area_sqft",
                                 "slope_severity"})
    require_fields(body, ["property_id", "measured_area_sqft", "crack_linear_ft",
                          "pothole_count", "pothole_area_sqft", "oil_spot_area_sqft",
                          "slope_severity"])
    prop = DB.properties.get(body["property_id"])
    if prop is None:
        raise err(ERR_PROPERTY_NOT_FOUND, 404, "Property id does not exist")
    area = require_number(body, "measured_area_sqft", gt=0)
    crack = require_number(body, "crack_linear_ft", ge=0)
    pothole_count = require_number(body, "pothole_count", ge=0, integer=True)
    pothole_area = require_number(body, "pothole_area_sqft", ge=0)
    oil = require_number(body, "oil_spot_area_sqft", ge=0)
    slope = require_enum(body, "slope_severity", {"NONE", "MODERATE", "STEEP"})
    pci = pavement_condition_index(area, crack, pothole_area, oil, slope)
    a = base_fields()
    a.update({
        "property_id": body["property_id"],
        "measured_area_sqft": area,
        "crack_linear_ft": crack,
        "pothole_count": pothole_count,
        "pothole_area_sqft": pothole_area,
        "oil_spot_area_sqft": oil,
        "slope_severity": slope,
        "pavement_condition_index": pci,
        "submitted_at": None,
        "status": "DRAFT",
    })
    DB.assessments[a["id"]] = a
    return success_object(serialize_assessment(a), status=201)


@bp.get("/api/assessments")
def list_assessments():
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead", "Customer")
    property_filter = request.args.get("property_id")
    status_filter = request.args.get("status")
    items = list(DB.assessments.values())
    if role == "Customer":
        # Only assessments for customer's own properties
        own_props = {p["id"] for p in DB.properties.values() if p["customer_id"] == user_id}
        items = [a for a in items if a["property_id"] in own_props]
    if property_filter:
        items = [a for a in items if a["property_id"] == property_filter]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: a["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_assessment(a) for a in page], limit, offset, total)


@bp.get("/api/assessments/<assessmentId>")
def get_assessment(assessmentId):
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead", "Customer")
    a = DB.assessments.get(assessmentId)
    if a is None:
        raise err(ERR_ASSESSMENT_NOT_FOUND, 404, "Assessment id does not exist")
    if role == "Customer":
        prop = DB.properties.get(a["property_id"])
        if prop is None or prop["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403, "Customer acting on a resource owned by a different customer")
    return success_object(serialize_assessment(a))


@bp.post("/api/assessments/<assessmentId>/submit")
def submit_assessment(assessmentId):
    require_role("Estimator")
    a = DB.assessments.get(assessmentId)
    if a is None:
        raise err(ERR_ASSESSMENT_NOT_FOUND, 404, "Assessment id does not exist")
    if a["status"] != "DRAFT":
        raise err(ERR_ASSESSMENT_NOT_SUBMITTABLE, 409, "submit requires a DRAFT assessment")
    a["status"] = "SUBMITTED"
    a["submitted_at"] = now_iso_ms()
    touch(a)
    # Cascade: supersede other SUBMITTED assessments for same property
    for other in DB.assessments.values():
        if other["id"] != a["id"] and other["property_id"] == a["property_id"] and other["status"] == "SUBMITTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    # Cascade: refresh property area + version
    prop = DB.properties.get(a["property_id"])
    if prop is not None:
        prop["current_area_sqft"] = a["measured_area_sqft"]
        touch(prop)
    return success_object(serialize_assessment(a))
