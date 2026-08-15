"""Formula and FormulaIngredient endpoints."""

from flask import Blueprint

import errors
from db import store
from middleware import (require_roles, get_json_body, require_string,
                        require_enum, optional_field, require_number,
                        parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import (stamp_new, touch, serialize, serialize_list,
                                   compute_me)

bp = Blueprint("formulas", __name__)

SPECIES = {"DOG", "CAT"}
LIFE_STAGES = {"GROWTH", "ADULT_MAINTENANCE", "ALL_LIFE_STAGES", "GESTATION_LACTATION"}
ADEQUACY_BASIS = {"FORMULATION", "FEEDING_TRIAL"}
FORMULA_TERMINAL = {"SUPERSEDED", "WITHDRAWN"}


@bp.route("/brand-owners/<id>/formulas", methods=["POST"])
def create_formula(id):
    require_roles("FormulationScientist")
    bo = store.brand_owners.get(id)
    if bo is None:
        raise errors.not_found("BrandOwner not found")
    body = get_json_body()
    formula_code = require_string(body, "formula_code")
    product_name = require_string(body, "product_name")
    species = require_enum(body, "species", SPECIES)
    life_stage = require_enum(body, "life_stage", LIFE_STAGES)
    adequacy_basis = require_enum(body, "adequacy_basis", ADEQUACY_BASIS)
    parent_formula_id = optional_field(body, "parent_formula_id")

    for f in store.formulas.values():
        if f["brand_owner_id"] == id and f["formula_code"] == formula_code:
            raise errors.duplicate_key("formula_code already exists within brand")

    parent = None
    if parent_formula_id is not None:
        parent = store.formulas.get(parent_formula_id)
        if parent is None:
            raise errors.not_found("parent_formula_id does not resolve")

    formula = {
        "brand_owner_id": id,
        "formula_code": formula_code,
        "product_name": product_name,
        "species": species,
        "life_stage": life_stage,
        "adequacy_basis": adequacy_basis,
        "status": "DRAFT",
        "revision_number": 1,
        "parent_formula_id": parent_formula_id,
        "substantiation_locked_version": None,
        "total_batch_count": 0,
        "open_recall_flag": False,
    }
    stamp_new(formula)
    store.formulas[formula["id"]] = formula

    # Supersede the LOCKED parent with cascades
    if parent is not None and parent["status"] == "LOCKED":
        parent["status"] = "SUPERSEDED"
        touch(parent, status_changed=True)
        # Cascade: SUBMITTED or UNDER_REVIEW registrations -> REVOKED
        for reg in store.state_registrations.values():
            if reg["formula_id"] == parent["id"] and reg["status"] in ("SUBMITTED", "UNDER_REVIEW"):
                reg["status"] = "REVOKED"
                touch(reg, status_changed=True)
        # Cascade: SCHEDULED or RELEASED_FOR_PRODUCTION batches -> REJECTED
        for batch in store.production_batches.values():
            if batch["formula_id"] == parent["id"] and batch["status"] in ("SCHEDULED", "RELEASED_FOR_PRODUCTION"):
                batch["status"] = "REJECTED"
                touch(batch, status_changed=True)

    return success_object(serialize(formula), 201)


def _get_formula(id):
    f = store.formulas.get(id)
    if f is None:
        raise errors.not_found("Formula not found")
    return f


def _check_formula_not_terminal(f):
    if f["status"] in FORMULA_TERMINAL:
        raise errors.already_terminal("Formula is in a terminal state")


@bp.route("/formulas/<id>", methods=["GET"])
def get_formula(id):
    require_roles("PlatformAdmin", "FormulationScientist", "QualityAnalyst",
                  "QAApprover", "RegulatoryAffairs", "ProductionPlanner",
                  "StateRegulator")
    formula = _get_formula(id)
    return success_object(serialize(formula), 200)


@bp.route("/formulas/<id>/ingredients", methods=["GET"])
def list_formula_ingredients(id):
    require_roles("PlatformAdmin", "FormulationScientist", "QualityAnalyst",
                  "QAApprover", "ProductionPlanner")
    _get_formula(id)
    limit, offset = parse_pagination()
    items = [fi for fi in store.formula_ingredients.values() if fi["formula_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


@bp.route("/formulas/<id>/ingredients", methods=["POST"])
def add_formula_ingredient(id):
    require_roles("FormulationScientist")
    formula = _get_formula(id)
    _check_formula_not_terminal(formula)
    if formula["status"] != "DRAFT":
        raise errors.invalid_state("Ingredient lines may only be added to a DRAFT formula")
    body = get_json_body()
    ingredient_id = require_string(body, "ingredient_id")
    ingredient = store.ingredients.get(ingredient_id)
    if ingredient is None:
        raise errors.not_found("Ingredient not found")
    inclusion_pct = require_number(body, "inclusion_pct")
    if inclusion_pct <= 0 or inclusion_pct > 100:
        raise errors.invalid_request("inclusion_pct must satisfy 0 < pct <= 100")
    processing_note = optional_field(body, "processing_note", "")
    if not isinstance(processing_note, str):
        raise errors.invalid_request("processing_note must be a string")

    fi = {
        "formula_id": id,
        "ingredient_id": ingredient_id,
        "inclusion_pct": inclusion_pct,
        "processing_note": processing_note,
    }
    stamp_new(fi)
    store.formula_ingredients[fi["id"]] = fi
    touch(formula)
    return success_object(serialize(fi), 201)


def _formula_ingredient_lines(formula_id):
    return [fi for fi in store.formula_ingredients.values() if fi["formula_id"] == formula_id]


def _latest_nutrient_profile(formula_id):
    """The current profile: latest created per formula (create-or-replace semantics)."""
    profiles = [p for p in store.nutrient_profiles.values() if p["formula_id"] == formula_id]
    if not profiles:
        return None
    profiles.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    return profiles[-1]


@bp.route("/formulas/<id>/submit-nutrient-review", methods=["POST"])
def submit_nutrient_review(id):
    require_roles("FormulationScientist")
    formula = _get_formula(id)
    _check_formula_not_terminal(formula)
    if formula["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT formulas can be submitted for nutrient review")

    lines = _formula_ingredient_lines(id)
    if not lines:
        raise errors.invalid_state("Formula has no ingredient lines")

    # Guard order: ingredient-active check, then inclusion-sum check.
    for fi in lines:
        ing = store.ingredients.get(fi["ingredient_id"])
        if ing is None or ing["status"] != "ACTIVE":
            raise errors.ingredient_inactive()

    total = sum(float(fi["inclusion_pct"]) for fi in lines)
    if abs(total - 100.0) > 0.01 + 1e-9:
        raise errors.inclusion_sum_invalid()

    formula["status"] = "NUTRIENT_REVIEW"
    touch(formula, status_changed=True)

    # Recompute ME on existing profile
    profile = _latest_nutrient_profile(id)
    if profile is not None:
        profile["metabolizable_energy_kcal_per_kg"] = compute_me(
            profile["crude_protein_min_pct"], profile["crude_fat_min_pct"],
            profile["crude_fiber_max_pct"], profile["moisture_max_pct"],
            profile["profile_basis"])
        touch(profile)

    return success_object(serialize(formula), 200)


@bp.route("/formulas/<id>/request-revision", methods=["POST"])
def request_revision(id):
    require_roles("QAApprover")
    formula = _get_formula(id)
    _check_formula_not_terminal(formula)
    if formula["status"] != "NUTRIENT_REVIEW":
        raise errors.invalid_state("Only NUTRIENT_REVIEW formulas can be sent back for revision")
    formula["status"] = "DRAFT"
    formula["revision_number"] = int(formula["revision_number"]) + 1
    touch(formula, status_changed=True)
    return success_object(serialize(formula), 200)


def _has_approved_pairing_covering(ingredient_id):
    return any(
        a["ingredient_id"] == ingredient_id and a["approval_state"] == "APPROVED"
        for a in store.supplier_ingredient_approvals.values()
    )


@bp.route("/formulas/<id>/substantiate", methods=["POST"])
def substantiate(id):
    require_roles("QAApprover")
    formula = _get_formula(id)
    _check_formula_not_terminal(formula)
    if formula["status"] != "NUTRIENT_REVIEW":
        raise errors.invalid_state("Only NUTRIENT_REVIEW formulas can be substantiated")

    # Guard order: sourcing coverage first, then adequacy-basis gate.
    lines = _formula_ingredient_lines(id)
    for fi in lines:
        if not _has_approved_pairing_covering(fi["ingredient_id"]):
            raise errors.unapproved_ingredient_source()

    if formula["adequacy_basis"] == "FORMULATION":
        profile = _latest_nutrient_profile(id)
        if profile is None or profile.get("aafco_compliance") != "COMPLIANT":
            raise errors.substantiation_unmet(
                "FORMULATION basis requires a COMPLIANT NutrientProfile")
        locked_version = profile["version"]
    else:  # FEEDING_TRIAL
        protocols = [p for p in store.feeding_trial_protocols.values()
                     if p["formula_id"] == id]
        passed = [p for p in protocols if p["status"] == "PASSED"]
        if not passed:
            raise errors.substantiation_unmet(
                "FEEDING_TRIAL basis requires a PASSED FeedingTrialProtocol")
        locked_version = passed[-1]["version"]

    formula["status"] = "SUBSTANTIATED"
    formula["substantiation_locked_version"] = locked_version
    touch(formula, status_changed=True)
    return success_object(serialize(formula), 200)


@bp.route("/formulas/<id>/lock", methods=["POST"])
def lock_formula(id):
    require_roles("QAApprover")
    formula = _get_formula(id)
    _check_formula_not_terminal(formula)
    if formula["status"] != "SUBSTANTIATED":
        raise errors.invalid_state("Only SUBSTANTIATED formulas can be locked")
    if formula.get("open_recall_flag"):
        raise errors.open_recall()
    formula["status"] = "LOCKED"
    touch(formula, status_changed=True)
    return success_object(serialize(formula), 200)


@bp.route("/formulas/<id>/withdraw", methods=["POST"])
def withdraw_formula(id):
    require_roles("QAApprover")
    formula = _get_formula(id)
    _check_formula_not_terminal(formula)
    if formula["status"] != "LOCKED":
        raise errors.invalid_state("Only LOCKED formulas can be withdrawn")
    terminal_batch_states = {"COMPLETED", "REJECTED", "RECALLED"}
    for batch in store.production_batches.values():
        if batch["formula_id"] == id and batch["status"] not in terminal_batch_states:
            raise errors.invalid_state(
                "All production batches must be terminal before withdrawal")
    formula["status"] = "WITHDRAWN"
    touch(formula, status_changed=True)
    # Cascade: APPROVED registrations -> REVOKED
    for reg in store.state_registrations.values():
        if reg["formula_id"] == id and reg["status"] == "APPROVED":
            reg["status"] = "REVOKED"
            touch(reg, status_changed=True)
    return success_object(serialize(formula), 200)
