"""BomLine endpoints (nested under models)."""
from flask import Blueprint

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_enum, as_int, as_number, as_string, body, check_occ, optional, require
from routes.models import get_model
from services import calc, cascade

bp = Blueprint("bom_lines", __name__)

COMPONENT_TYPES = {
    "FOAM_CORE",
    "MEMORY_LAYER",
    "FIRE_BARRIER",
    "TICKING",
    "QUILT_PANEL",
    "FOUNDATION",
    "THREAD",
}
FILLING_TYPES = {"FOAM_CORE", "MEMORY_LAYER", "FIRE_BARRIER", "TICKING"}


def bom_line_view(l):
    return {
        "id": l["id"],
        "model_id": l["model_id"],
        "component_type": l["component_type"],
        "material_code": l["material_code"],
        "quantity_per_unit": l["quantity_per_unit"],
        "unit_cost_cents": l["unit_cost_cents"],
        "filling_content_code": l["filling_content_code"],
        "line_cost_cents": l["line_cost_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def get_bom_line(model, line_id):
    line = db.bom_lines.get(line_id)
    if line is None or line["model_id"] != model["id"]:
        errors.raise_err(errors.ERR_BOM_LINE_NOT_FOUND, "bom line not found within the model")
    return line


@bp.route("/models/<mid>/bom-lines", methods=["POST"])
def create_bom_line(mid):
    middleware.require_roles(["PlantManager"])
    model = get_model(mid)
    data = body()
    component_type = as_enum(require(data, "component_type"), "component_type", COMPONENT_TYPES)
    material_code = as_string(require(data, "material_code"), "material_code")
    qty = as_number(require(data, "quantity_per_unit"), "quantity_per_unit")
    if calc.dec(qty) <= 0:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "quantity_per_unit must be > 0")
    unit_cost = as_int(require(data, "unit_cost_cents"), "unit_cost_cents")
    if unit_cost < 0:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "unit_cost_cents must be >= 0")
    filling = optional(data, "filling_content_code", None)
    if component_type in FILLING_TYPES:
        if filling is None or not isinstance(filling, str) or filling == "":
            errors.raise_err(
                errors.ERR_VALIDATION_FAILED,
                "filling_content_code is required for filling component types",
            )
    else:
        filling = None
    # tier 5: model must be DRAFT
    if model["status"] != "DRAFT":
        errors.raise_err(errors.ERR_MODEL_NOT_DRAFT, "model must be DRAFT")
    line = {
        "id": db.new_id(),
        "model_id": model["id"],
        "component_type": component_type,
        "material_code": material_code,
        "quantity_per_unit": qty,
        "unit_cost_cents": unit_cost,
        "filling_content_code": filling,
        "line_cost_cents": calc.bom_line_cost(qty, unit_cost),
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.bom_lines, line)
    calc.recompute_bom_cost(model)
    cascade.bump(model)
    return response.success_object(bom_line_view(line), 201)


@bp.route("/models/<mid>/bom-lines", methods=["GET"])
def list_bom_lines(mid):
    middleware.require_roles(middleware.ALL_ROLES)
    model = get_model(mid)
    items = [l for l in db.bom_lines.values() if l["model_id"] == model["id"]]
    items.sort(key=lambda l: l["_seq"])
    return response.success_list([bom_line_view(l) for l in items])


@bp.route("/models/<mid>/bom-lines/<lineId>", methods=["PATCH"])
def patch_bom_line(mid, lineId):
    middleware.require_roles(["PlantManager"])
    model = get_model(mid)
    line = get_bom_line(model, lineId)
    data = body()
    qty = line["quantity_per_unit"]
    unit_cost = line["unit_cost_cents"]
    if "quantity_per_unit" in data and data["quantity_per_unit"] is not None:
        qty = as_number(data["quantity_per_unit"], "quantity_per_unit")
        if calc.dec(qty) <= 0:
            errors.raise_err(errors.ERR_VALIDATION_FAILED, "quantity_per_unit must be > 0")
    if "unit_cost_cents" in data and data["unit_cost_cents"] is not None:
        unit_cost = as_int(data["unit_cost_cents"], "unit_cost_cents")
        if unit_cost < 0:
            errors.raise_err(errors.ERR_VALIDATION_FAILED, "unit_cost_cents must be >= 0")
    # tier 5: model must be DRAFT
    if model["status"] != "DRAFT":
        errors.raise_err(errors.ERR_MODEL_NOT_DRAFT, "model must be DRAFT")
    # tier 12: OCC
    check_occ(require(data, "expected_model_version"), model["version"])
    line["quantity_per_unit"] = qty
    line["unit_cost_cents"] = unit_cost
    line["line_cost_cents"] = calc.bom_line_cost(qty, unit_cost)
    cascade.bump(line)
    calc.recompute_bom_cost(model)
    cascade.bump(model)
    return response.success_object(bom_line_view(line))
