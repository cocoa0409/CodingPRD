"""Tract and Field endpoints (PRD §3.1)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import ApiError, ERR_CROPLAND_EXCEEDED
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.helpers import (
    get_farm_or_404, get_tract_or_404, get_field_or_404,
    recompute_farm_base_acres,
)
from validation import body, require_string, require_decimal

bp = Blueprint("tracts", __name__)


@bp.post("/fsa/farms/<farm_id>/tracts")
def create_tract(farm_id):
    require_roles(["CountySpecialist"])
    farm = get_farm_or_404(farm_id)
    data = body()
    tract_number = require_string(data, "tract_number")
    base_acres = require_decimal(data, "base_acres")
    cropland_acres = require_decimal(data, "cropland_acres")

    tract = db.common_fields()
    tract.update({
        "farm_id": farm_id,
        "tract_number": tract_number,
        "base_acres": float(base_acres),
        "cropland_acres": float(cropland_acres),
        "tract_status": "ACTIVE",
        "reconstituted_from_tract_id": None,
    })
    db.tracts[tract["id"]] = tract
    # Side effect: farm.total_base_acres recomputed.
    recompute_farm_base_acres(farm)
    db.touch(farm)
    return success_object(tract, 201)


@bp.get("/fsa/farms/<farm_id>/tracts")
def list_farm_tracts(farm_id):
    require_roles(ALL_ROLES)
    get_farm_or_404(farm_id)
    items = [t for t in db.tracts.values() if t["farm_id"] == farm_id]
    items.sort(key=lambda t: t["created_at"])
    return paginate(items, request.args)


@bp.get("/fsa/tracts/<tract_id>")
def get_tract(tract_id):
    require_roles(ALL_ROLES)
    return success_object(get_tract_or_404(tract_id))


@bp.get("/fsa/tracts")
def list_tracts():
    require_roles(ALL_ROLES)
    farm_id = request.args.get("farm_id")
    recon_from = request.args.get("reconstituted_from_tract_id")
    items = list(db.tracts.values())
    if farm_id is not None:
        items = [t for t in items if t["farm_id"] == farm_id]
    if recon_from is not None:
        items = [t for t in items if t.get("reconstituted_from_tract_id") == recon_from]
    items.sort(key=lambda t: t["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/tracts/<tract_id>/fields")
def create_field(tract_id):
    require_roles(["CountySpecialist"])
    tract = get_tract_or_404(tract_id)
    data = body()
    field_number = require_string(data, "field_number")
    acres = require_decimal(data, "acres")

    # Sum of field acres on the tract must not exceed cropland_acres
    # (PRD §3.1; validation priority 13).
    existing_total = sum(
        Decimal(str(f["acres"])) for f in db.fields.values()
        if f["tract_id"] == tract_id
    )
    if existing_total + acres > Decimal(str(tract["cropland_acres"])):
        raise ApiError(
            ERR_CROPLAND_EXCEEDED,
            "Sum of Field.acres would exceed tract.cropland_acres",
            422,
        )

    field = db.common_fields()
    field.update({
        "tract_id": tract_id,
        "field_number": field_number,
        "acres": float(acres),
    })
    db.fields[field["id"]] = field
    return success_object(field, 201)


@bp.get("/fsa/tracts/<tract_id>/fields")
def list_tract_fields(tract_id):
    require_roles(ALL_ROLES)
    get_tract_or_404(tract_id)
    items = [f for f in db.fields.values() if f["tract_id"] == tract_id]
    items.sort(key=lambda f: f["created_at"])
    return paginate(items, request.args)


@bp.get("/fsa/fields/<field_id>")
def get_field(field_id):
    require_roles(ALL_ROLES)
    return success_object(get_field_or_404(field_id))


@bp.get("/fsa/fields/<field_id>/acreage-report-lines")
def list_field_report_lines(field_id):
    require_roles(ALL_ROLES)
    get_field_or_404(field_id)
    items = [
        l for l in db.acreage_report_lines.values() if l["field_id"] == field_id
    ]
    items.sort(key=lambda l: l["created_at"])
    return paginate(items, request.args)
