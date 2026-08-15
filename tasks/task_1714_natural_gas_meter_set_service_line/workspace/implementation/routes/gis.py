"""GISAsBuilt endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_GIS,
    ERR_GIS_DEPTH_VIOLATION,
    ERR_INVALID_STATE,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    require_enum,
    require_fields,
    require_number,
    require_roles,
    require_str,
)
from response import success_list, success_object
from services.domain import gis_for_application, get_application, get_gis, touch

bp = Blueprint("gis", __name__)

PIPE_MATERIALS = ("STEEL", "PE", "CSST")
MIN_COVER_DEPTH_IN = 18


@bp.route("/gis-as-builts", methods=["POST"])
def create_gis():
    user_id, _ = require_roles("FieldSupervisor")
    body = get_body()
    require_fields(body, "service_application_id", "geometry_geojson", "pipe_material", "depth_inches")
    app = get_application(body["service_application_id"])
    geometry = require_str(body, "geometry_geojson")
    material = require_enum(body, "pipe_material", PIPE_MATERIALS)
    depth = require_number(body, "depth_inches")
    check_app_mutable(app)
    if app["status"] not in ("ENERGIZED", "GIS_REVIEW"):
        raise_error(ERR_INVALID_STATE, "Application must be ENERGIZED or in GIS_REVIEW")
    existing = gis_for_application(app["id"])
    if existing is not None:
        raise_error(ERR_DUPLICATE_GIS, "A non-CANCELLED GIS as-built already exists")
    now = db.now_iso()
    record = {
        "id": new_id(),
        "service_application_id": app["id"],
        "geometry_geojson": geometry,
        "pipe_material": material,
        "depth_inches": depth,
        "submitted_by_user_id": user_id,
        "validated_by_user_id": None,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.gis_as_builts[record["id"]] = record
    # Application ENERGIZED → GIS_REVIEW
    if app["status"] == "ENERGIZED":
        app["status"] = "GIS_REVIEW"
        touch(app)
    return success_object(record, 201)


@bp.route("/gis-as-builts/<gid>", methods=["GET"])
def get_one_gis(gid):
    require_roles(*ANY_ROLE)
    return success_object(get_gis(gid))


@bp.route("/gis-as-builts", methods=["GET"])
def list_gis():
    require_roles(*ANY_ROLE)
    records = list(db.gis_as_builts.values())
    app_id = request.args.get("service_application_id")
    if app_id is not None:
        records = [g for g in records if g["service_application_id"] == app_id]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/gis-as-builts/<gid>/validate", methods=["POST"])
def validate_gis(gid):
    user_id, _ = require_roles("GISAnalyst")
    record = get_gis(gid)
    app = get_application(record["service_application_id"])
    check_app_mutable(app)
    if record["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Only SUBMITTED records can be validated")
    if record["depth_inches"] < MIN_COVER_DEPTH_IN:
        raise_error(ERR_GIS_DEPTH_VIOLATION, "Cover depth below the 18-inch code minimum")
    record["validated_by_user_id"] = user_id
    record["status"] = "VALIDATED"
    touch(record)
    return success_object(record)


@bp.route("/gis-as-builts/<gid>/reject", methods=["POST"])
def reject_gis(gid):
    require_roles("GISAnalyst")
    record = get_gis(gid)
    app = get_application(record["service_application_id"])
    body = get_body()
    require_fields(body, "rejection_reason")
    reason = require_str(body, "rejection_reason")
    check_app_mutable(app)
    if record["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Only SUBMITTED records can be rejected")
    record["rejection_reason"] = reason
    record["status"] = "REJECTED"
    touch(record)
    return success_object(record)


@bp.route("/gis-as-builts/<gid>/resubmit", methods=["POST"])
def resubmit_gis(gid):
    require_roles("FieldSupervisor")
    record = get_gis(gid)
    app = get_application(record["service_application_id"])
    body = get_body()
    check_app_mutable(app)
    if record["status"] != "REJECTED":
        raise_error(ERR_INVALID_STATE, "Only REJECTED records can be resubmitted")
    if "geometry_geojson" in body and body["geometry_geojson"] is not None:
        record["geometry_geojson"] = require_str(body, "geometry_geojson")
    if "pipe_material" in body and body["pipe_material"] is not None:
        record["pipe_material"] = require_enum(body, "pipe_material", PIPE_MATERIALS)
    if "depth_inches" in body and body["depth_inches"] is not None:
        record["depth_inches"] = require_number(body, "depth_inches")
    record["rejection_reason"] = None
    record["status"] = "SUBMITTED"
    touch(record)
    return success_object(record)
