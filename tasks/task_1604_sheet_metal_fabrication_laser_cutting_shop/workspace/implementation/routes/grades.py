"""Material grade catalog endpoints."""
from flask import Blueprint

from db import store, new_id, new_common
from response import ok, created, paginate
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services.audit import audit

bp = Blueprint("grades", __name__)

READ_ROLES = ["ShopManager", "Estimator", "ProductionPlanner", "InventoryClerk",
              "MachineOperator", "CustomerRep"]


@bp.post("/fab/material-grades")
def create_grade():
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    body = parse_body({
        "code": ("string", True, None),
        "alloy_family": ("enum", True, ["ALUMINUM", "CARBON_STEEL", "STAINLESS"]),
        "density_g_per_cm3": ("number", True, None),
        "hardness_factor": ("number", True, None),
        "base_cut_rate_cents_per_sec": ("number", True, None),
        "material_cost_cents_per_cm2": ("number", True, None),
        "scrap_rate_cents_per_cm2": ("number", True, None),
        "thickness_tiers": ("tiers", True, None),
        "weld_compatible": ("boolean", True, None),
        "powder_compatible": ("boolean", True, None),
    }, allow_empty=False)
    grade = {
        "id": new_id(),
        "code": body["code"],
        "alloy_family": body["alloy_family"],
        "density_g_per_cm3": body["density_g_per_cm3"],
        "hardness_factor": body["hardness_factor"],
        "base_cut_rate_cents_per_sec": body["base_cut_rate_cents_per_sec"],
        "material_cost_cents_per_cm2": body["material_cost_cents_per_cm2"],
        "scrap_rate_cents_per_cm2": body["scrap_rate_cents_per_cm2"],
        "thickness_tiers": body["thickness_tiers"],
        "weld_compatible": body["weld_compatible"],
        "powder_compatible": body["powder_compatible"],
    }
    new_common(grade)
    store.material_grades[grade["id"]] = grade
    audit("MaterialGrade", grade["id"], "GRADE_CREATED", role, uid,
          {"after": {"code": grade["code"]}})
    return created(grade)


@bp.get("/fab/material-grades")
def list_grades():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    return ok(paginate(list(store.material_grades.values())), rtype="array", pagination=paginate)


@bp.get("/fab/material-grades/<grade_id>")
def get_grade(grade_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.material_grades, grade_id))
