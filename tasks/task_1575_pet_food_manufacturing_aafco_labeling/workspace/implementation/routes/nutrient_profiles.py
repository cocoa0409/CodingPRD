"""NutrientProfile endpoints."""

from flask import Blueprint

import errors
from db import store
from middleware import (require_roles, get_json_body, require_enum,
                        require_number, optional_number,
                        parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import (stamp_new, serialize, serialize_list,
                                   compute_me, compute_aafco_compliance)

bp = Blueprint("nutrient_profiles", __name__)

PROFILE_BASES = {"FORMULATION_CALC", "LAB_ANALYSIS"}


@bp.route("/formulas/<id>/nutrient-profiles", methods=["POST"])
def create_nutrient_profile(id):
    require_roles("FormulationScientist")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    body = get_json_body()
    profile_basis = require_enum(body, "profile_basis", PROFILE_BASES)

    if formula["adequacy_basis"] != "FORMULATION":
        raise errors.profile_basis_mismatch(
            "NutrientProfile allowed only for FORMULATION-basis formulas")

    crude_protein_min_pct = require_number(body, "crude_protein_min_pct")
    crude_fat_min_pct = require_number(body, "crude_fat_min_pct")
    crude_fiber_max_pct = require_number(body, "crude_fiber_max_pct")
    moisture_max_pct = require_number(body, "moisture_max_pct")
    calcium_min_pct = optional_number(body, "calcium_min_pct", 0)
    phosphorus_min_pct = optional_number(body, "phosphorus_min_pct", 0)

    me = compute_me(crude_protein_min_pct, crude_fat_min_pct,
                    crude_fiber_max_pct, moisture_max_pct, profile_basis)
    compliance = compute_aafco_compliance(
        formula["species"], formula["life_stage"], me,
        crude_protein_min_pct, crude_fat_min_pct,
        calcium_min_pct, phosphorus_min_pct)

    profile = {
        "formula_id": id,
        "profile_basis": profile_basis,
        "crude_protein_min_pct": crude_protein_min_pct,
        "crude_fat_min_pct": crude_fat_min_pct,
        "crude_fiber_max_pct": crude_fiber_max_pct,
        "moisture_max_pct": moisture_max_pct,
        "calcium_min_pct": calcium_min_pct,
        "phosphorus_min_pct": phosphorus_min_pct,
        "metabolizable_energy_kcal_per_kg": me,
        "aafco_compliance": compliance,
    }
    stamp_new(profile)
    # Create-or-replace: remove any existing profile for this basis
    for pid, p in list(store.nutrient_profiles.items()):
        if p["formula_id"] == id and p["profile_basis"] == profile_basis:
            del store.nutrient_profiles[pid]
    store.nutrient_profiles[profile["id"]] = profile
    return success_object(serialize(profile), 201)


@bp.route("/formulas/<id>/nutrient-profiles", methods=["GET"])
def list_nutrient_profiles(id):
    require_roles("PlatformAdmin", "FormulationScientist", "QualityAnalyst",
                  "QAApprover")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    limit, offset = parse_pagination()
    # Latest profile per basis
    by_basis = {}
    for p in store.nutrient_profiles.values():
        if p["formula_id"] != id:
            continue
        cur = by_basis.get(p["profile_basis"])
        if cur is None or (p["_created_at_dt"], p["id"]) > (cur["_created_at_dt"], cur["id"]):
            by_basis[p["profile_basis"]] = p
    items = sorted(by_basis.values(), key=lambda e: (e["_created_at_dt"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)
