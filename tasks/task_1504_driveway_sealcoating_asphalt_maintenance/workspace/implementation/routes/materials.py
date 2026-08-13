"""Material endpoints."""

from flask import Blueprint

from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_enum, require_number, base_fields, paginate, err,
)
from response import success_object, success_list
from errors import ERR_MATERIAL_NOT_FOUND

bp = Blueprint("materials", __name__)


def serialize_material(m):
    return {
        "id": m["id"],
        "product_name": m["product_name"],
        "grade": m["grade"],
        "coverage_sqft_per_gallon": m["coverage_sqft_per_gallon"],
        "min_apply_temp_f": m["min_apply_temp_f"],
        "max_precip_probability_pct": m["max_precip_probability_pct"],
        "cure_hours_vehicle": m["cure_hours_vehicle"],
        "reapplication_months": m["reapplication_months"],
        "warranty_months": m["warranty_months"],
        "price_per_gallon_cents": m["price_per_gallon_cents"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.post("/api/materials")
def create_material():
    require_role("OfficeAdmin")
    body = get_json_body()
    check_unknown_fields(body, {"product_name", "grade", "coverage_sqft_per_gallon",
                                 "min_apply_temp_f", "max_precip_probability_pct",
                                 "cure_hours_vehicle", "reapplication_months",
                                 "warranty_months", "price_per_gallon_cents"})
    require_fields(body, ["product_name", "grade", "coverage_sqft_per_gallon",
                          "min_apply_temp_f", "max_precip_probability_pct",
                          "cure_hours_vehicle", "reapplication_months",
                          "warranty_months", "price_per_gallon_cents"])
    grade = require_enum(body, "grade", {"STANDARD", "PREMIUM", "ECO"})
    coverage = require_number(body, "coverage_sqft_per_gallon", gt=0)
    min_temp = require_number(body, "min_apply_temp_f")
    max_precip = require_number(body, "max_precip_probability_pct", ge=0, integer=True)
    if max_precip > 100:
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, 400, "max_precip_probability_pct must be 0-100")
    cure = require_number(body, "cure_hours_vehicle", gt=0, integer=True)
    reapp = require_number(body, "reapplication_months", gt=0, integer=True)
    warranty = require_number(body, "warranty_months", gt=0, integer=True)
    ppg = require_number(body, "price_per_gallon_cents", gt=0, integer=True)
    m = base_fields()
    m.update({
        "product_name": body["product_name"],
        "grade": grade,
        "coverage_sqft_per_gallon": coverage,
        "min_apply_temp_f": min_temp,
        "max_precip_probability_pct": max_precip,
        "cure_hours_vehicle": cure,
        "reapplication_months": reapp,
        "warranty_months": warranty,
        "price_per_gallon_cents": ppg,
    })
    DB.materials[m["id"]] = m
    return success_object(serialize_material(m), status=201)


@bp.get("/api/materials")
def list_materials():
    require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead")
    items = sorted(DB.materials.values(), key=lambda m: m["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_material(m) for m in page], limit, offset, total)


@bp.get("/api/materials/<materialId>")
def get_material(materialId):
    require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead")
    m = DB.materials.get(materialId)
    if m is None:
        raise err(ERR_MATERIAL_NOT_FOUND, 404, "Material id does not exist")
    return success_object(serialize_material(m))
