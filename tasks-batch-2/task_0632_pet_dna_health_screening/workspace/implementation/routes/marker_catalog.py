"""Marker catalog routes (PRD §3.9)."""
from flask import Blueprint, request

from db import db, create_light
from errors import err, ERR_INVALID_REQUEST
from helpers import (
    get_json_body, require_fields, require_enum, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_marker_catalog_entry

marker_catalog_bp = Blueprint("marker_catalog", __name__)


@marker_catalog_bp.route("/dna/marker-catalog", methods=["POST"])
def create_marker():
    require_roles({"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["marker_code", "category", "species"])
    require_enum(body["category"], {"HEALTH", "TRAIT"}, "category")
    require_enum(body["species"], {"DOG", "CAT"}, "species")

    # marker_code unique across catalog.
    for e in db.marker_catalog.values():
        if e["marker_code"] == body["marker_code"]:
            raise err(ERR_INVALID_REQUEST, "marker_code must be unique")

    rec = create_light(db.marker_catalog, {
        "marker_code": body["marker_code"],
        "category": body["category"],
        "species": body["species"],
    })
    return success(serialize_marker_catalog_entry(rec), status=201)


@marker_catalog_bp.route("/dna/marker-catalog", methods=["GET"])
def list_markers():
    require_roles({"PlatformAdmin", "LabTechnician"})
    limit, offset = parse_pagination()
    species = request.args.get("species")
    category = request.args.get("category")

    items = list(db.marker_catalog.values())
    if species is not None:
        items = [e for e in items if e["species"] == species]
    if category is not None:
        items = [e for e in items if e["category"] == category]

    window, total = paginate(items, limit, offset)
    return list_success(
        [serialize_marker_catalog_entry(e) for e in window], limit, offset, total
    )
