"""Insert geometries and chip breakers (PRD section 3.2)."""

from flask import Blueprint

import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("geometries", __name__)

READ_ROLES = [
    "GeometryEngineer",
    "MetallurgyEngineer",
    "CoatingEngineer",
    "ApplicationEngineer",
    "QualityApprover",
    "ProductionPlanner",
]
OWNER = ["GeometryEngineer"]


def _cutting_fields(payload):
    return (
        v.as_string(payload, "chipbreaker_code"),
        v.as_number(payload, "rake_angle_deg", minimum=-10.0, maximum=25.0),
        v.as_number(payload, "nose_radius_mm", minimum=0.05, maximum=3.2),
        v.as_number(payload, "max_depth_of_cut_mm", exclusive_min=0),
        v.as_enum(payload, "edge_prep", c.EDGE_PREPS),
    )


@bp.route("/tooling/insert-geometries", methods=["POST"])
def create():
    authenticate(OWNER)
    payload = v.body(
        required=(
            "geometry_code",
            "iso_designation",
            "application_class",
            "chipbreaker_code",
            "rake_angle_deg",
            "nose_radius_mm",
            "max_depth_of_cut_mm",
            "edge_prep",
        )
    )
    geometry_code = v.as_string(payload, "geometry_code")
    iso = v.as_string(payload, "iso_designation")
    application_class = v.as_enum(payload, "application_class", c.APPLICATION_CLASSES)
    chipbreaker, rake, nose, depth, prep = _cutting_fields(payload)

    derive.require_unique("geometries", "geometry_code", geometry_code)

    row = db.new_row(
        {
            "geometry_code": geometry_code,
            "iso_designation": iso,
            "application_class": application_class,
            "chipbreaker_code": chipbreaker,
            "rake_angle_deg": rake,
            "nose_radius_mm": nose,
            "max_depth_of_cut_mm": depth,
            "edge_prep": prep,
            "status": "DRAFT",
            "revision": 1,
        }
    )
    db.geometries[row["id"]] = row
    return object_response(serialize.geometry(row), 201)


@bp.route("/tooling/insert-geometries", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "geometries",
        READ_ROLES,
        {"application_class": c.APPLICATION_CLASSES, "status": c.GEOMETRY_STATUSES},
    )
    return c.list_response("geometries", rows, limit, offset)


@bp.route("/tooling/insert-geometries/<geometry_id>", methods=["GET"])
def read(geometry_id):
    return c.read_one("geometries", geometry_id, READ_ROLES)


@bp.route("/tooling/insert-geometries/<geometry_id>/release", methods=["POST"])
def release(geometry_id):
    authenticate(OWNER)
    v.no_body()
    geometry = derive.must_exist("geometries", geometry_id)
    if geometry["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_GEOMETRY_STATE",
            "A geometry may only be released from DRAFT (currently %s)." % geometry["status"],
        )
    geometry["status"] = "RELEASED"
    db.touch(geometry)
    derive.recompute_lead_times_for(
        [p for p in db.products.values() if p["geometry_id"] == geometry["id"]]
    )
    return object_response(serialize.geometry(geometry))


@bp.route("/tooling/insert-geometries/<geometry_id>/revise", methods=["POST"])
def revise(geometry_id):
    authenticate(OWNER)
    payload = v.body(
        required=(
            "chipbreaker_code",
            "rake_angle_deg",
            "nose_radius_mm",
            "max_depth_of_cut_mm",
            "edge_prep",
            "revision_note",
        )
    )
    chipbreaker, rake, nose, depth, prep = _cutting_fields(payload)
    v.as_string(payload, "revision_note")

    geometry = derive.must_exist("geometries", geometry_id)
    if geometry["status"] != "RELEASED":
        raise ApiError(
            "ERR_INVALID_GEOMETRY_STATE",
            "A geometry may only be revised from RELEASED (currently %s)."
            % geometry["status"],
        )

    geometry["chipbreaker_code"] = chipbreaker
    geometry["rake_angle_deg"] = rake
    geometry["nose_radius_mm"] = nose
    geometry["max_depth_of_cut_mm"] = depth
    geometry["edge_prep"] = prep
    geometry["revision"] = geometry["revision"] + 1
    geometry["status"] = "DRAFT"
    db.touch(geometry)

    derive.revision_cascade(
        [p for p in db.products.values() if p["geometry_id"] == geometry["id"]],
        "pinned_geometry_revision",
        geometry["revision"],
    )
    return object_response(serialize.geometry(geometry))
