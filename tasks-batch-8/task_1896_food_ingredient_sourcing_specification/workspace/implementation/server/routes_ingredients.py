"""Ingredients, spec versions, spec parameters (PRD §3.1, §3.2)."""
from flask import Blueprint, g, request

from .envelope import (
    ALL_ROLES,
    ERR_ACTIVE_SOURCES_EXIST,
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_DUPLICATE,
    ERR_INVALID_STATE,
    ERR_NO_EFFECTIVE_SPEC,
    ERR_NO_SPEC_PARAMETERS,
    ERR_OPEN_SUBSTITUTIONS_EXIST,
    ERR_PARAMETER_BOUNDS_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SPEC_IN_USE,
    ERR_SPEC_NOT_YET_EFFECTIVE,
    ERR_STALE_VERSION,
    ERR_SUPERSEDES_NOT_EFFECTIVE,
    body,
    err,
    invalid,
    is_number,
    list_page,
    not_found,
    pagination_params,
    parse_bool_query,
    require_bool,
    require_roles,
    require_str,
    respond_object,
)
from .services import (
    ALLERGEN_TAGS,
    CRITICALITIES,
    params_of_spec,
    recompute_dual_source,
    sources_of_ingredient,
    specs_of_ingredient,
)
from .store import STORE, new_record, parse_dt, ser_ingredient, ser_parameter, ser_spec, set_dt, touch

bp = Blueprint("ingredients", __name__)

READERS_ALL = ALL_ROLES


def get_ingredient_or_404(ingredient_id):
    ing = STORE.ingredients.get(ingredient_id)
    if ing is None:
        not_found("ingredient not found")
    return ing


def get_spec_or_404(ingredient_id, spec_id):
    spec = STORE.specs.get(spec_id)
    if spec is None or spec["ingredient_id"] != ingredient_id:
        not_found("spec not found")
    return spec


# ---------------------------------------------------------------------------
# Ingredients
# ---------------------------------------------------------------------------

@bp.post("/sourcing/ingredients")
@require_roles("ProcurementManager")
def create_ingredient():
    data = body()
    # Uniqueness (priority 12) precedes basic shape (priority 23).
    code = data.get("ingredient_code")
    if isinstance(code, str):
        for other in STORE.ingredients.values():
            if other["ingredient_code"] == code:
                err(ERR_DUPLICATE, 409, "ingredient_code already exists")

    code = require_str(data, "ingredient_code")
    name = require_str(data, "name")
    profile = data.get("allergen_profile")
    if not isinstance(profile, list):
        invalid("allergen_profile is required and must be an array")
    for tag in profile:
        if tag not in ALLERGEN_TAGS:
            invalid("allergen_profile contains an invalid allergen tag")
    dual = require_bool(data, "requires_dual_source")

    rec = new_record()
    rec.update(
        {
            "ingredient_code": code,
            "name": name,
            "allergen_profile": profile,
            "requires_dual_source": dual,
            "status": "DRAFT",
            "active_spec_id": None,
            "current_dual_source_breach": False,
        }
    )
    STORE.ingredients[rec["id"]] = rec
    return respond_object(ser_ingredient(rec), 201)


@bp.get("/sourcing/ingredients")
@require_roles(*ALL_ROLES)
def list_ingredients():
    limit, offset = pagination_params()
    status = request.args.get("status")
    dual = parse_bool_query(request.args.get("requires_dual_source"), "requires_dual_source")
    active_spec_id = request.args.get("active_spec_id")
    rows = list(STORE.ingredients.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if dual is not None:
        rows = [r for r in rows if r["requires_dual_source"] == dual]
    if active_spec_id is not None:
        rows = [r for r in rows if r["active_spec_id"] == active_spec_id]
    return list_page(rows, ser_ingredient, limit, offset)


@bp.get("/sourcing/ingredients/<ingredient_id>")
@require_roles(*ALL_ROLES)
def get_ingredient(ingredient_id):
    return respond_object(ser_ingredient(get_ingredient_or_404(ingredient_id)))


@bp.post("/sourcing/ingredients/<ingredient_id>/activate")
@require_roles("ProcurementManager")
def activate_ingredient(ingredient_id):
    ing = get_ingredient_or_404(ingredient_id)
    if ing["status"] != "DRAFT":
        err(ERR_INVALID_STATE, 409, "ingredient is not DRAFT")
    effective = [s for s in specs_of_ingredient(ing["id"]) if s["status"] == "EFFECTIVE"]
    if not effective:
        err(ERR_NO_EFFECTIVE_SPEC, 409, "ingredient has no EFFECTIVE spec")
    ing["status"] = "ACTIVE"
    touch(ing)
    return respond_object(ser_ingredient(ing))


@bp.post("/sourcing/ingredients/<ingredient_id>/discontinue")
@require_roles("ProcurementManager")
def discontinue_ingredient(ingredient_id):
    ing = get_ingredient_or_404(ingredient_id)
    if ing["status"] != "ACTIVE":
        err(ERR_INVALID_STATE, 409, "ingredient is not ACTIVE")
    live_sources = [
        s for s in sources_of_ingredient(ing["id"]) if s["status"] in ("PROVISIONAL", "ACTIVE")
    ]
    if live_sources:
        err(ERR_ACTIVE_SOURCES_EXIST, 409, "ingredient has PROVISIONAL or ACTIVE sources")
    open_subs = [
        r
        for r in STORE.substitutions.values()
        if r["ingredient_id"] == ing["id"]
        and r["status"] in ("REQUESTED", "IMPACT_ASSESSED", "PENDING_REGULATORY", "APPROVED")
    ]
    if open_subs:
        err(ERR_OPEN_SUBSTITUTIONS_EXIST, 409, "ingredient has open substitution requests")
    if ing["active_spec_id"] is not None:
        spec = STORE.specs.get(ing["active_spec_id"])
        if spec is not None and spec["status"] == "EFFECTIVE":
            spec["status"] = "RETIRED"
            touch(spec)
    ing["active_spec_id"] = None
    ing["status"] = "DISCONTINUED"
    touch(ing)
    return respond_object(ser_ingredient(ing))


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------

@bp.post("/sourcing/ingredients/<ingredient_id>/specs")
@require_roles("SpecAuthor")
def create_spec(ingredient_id):
    ing = get_ingredient_or_404(ingredient_id)
    data = body()

    # Body-FK existence (priority 4) then cross-reference coherence (5).
    supersedes_id = data.get("supersedes_spec_id")
    supersedes = None
    if supersedes_id is not None:
        supersedes = STORE.specs.get(supersedes_id)
        if supersedes is None:
            not_found("supersedes_spec_id does not reference an existing spec")
        if supersedes["ingredient_id"] != ing["id"]:
            err(
                ERR_CROSS_REFERENCE_MISMATCH,
                422,
                "supersedes_spec_id must reference a spec of the same ingredient",
            )

    # Uniqueness (12): spec_version_label unique within the ingredient.
    label = data.get("spec_version_label")
    if isinstance(label, str):
        for other in specs_of_ingredient(ing["id"]):
            if other["spec_version_label"] == label:
                err(ERR_DUPLICATE, 409, "spec_version_label already exists for ingredient")

    # Basic request shape (23).
    label = require_str(data, "spec_version_label")
    effective_raw = data.get("effective_date")
    if not isinstance(effective_raw, str):
        invalid("effective_date is required and must be an ISO8601 string")
    try:
        parse_dt(effective_raw)
    except ValueError:
        invalid("effective_date must be a valid ISO8601 timestamp")
    note = data.get("version_note")
    if not isinstance(note, str):
        invalid("version_note is required and must be a string")

    # OCC (24): expected_ingredient_version.
    expected = data.get("expected_ingredient_version")
    if expected is None:
        invalid("expected_ingredient_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        invalid("expected_ingredient_version must be an integer")
    if expected != ing["version"]:
        err(ERR_STALE_VERSION, 412, "ingredient version has advanced")

    rec = new_record()
    rec.update(
        {
            "ingredient_id": ing["id"],
            "spec_version_label": label,
            "supersedes_spec_id": supersedes_id,
            "author_user_id": g.user_id,
            "reviewed_by_user_id": None,
            "status": "DRAFT",
            "version_note": note,
        }
    )
    set_dt(rec, "effective_date", effective_raw)
    STORE.specs[rec["id"]] = rec
    touch(ing)  # creating a spec version increments Ingredient.version by 1
    return respond_object(ser_spec(rec), 201)


@bp.get("/sourcing/ingredients/<ingredient_id>/specs")
@require_roles(*ALL_ROLES)
def list_specs(ingredient_id):
    get_ingredient_or_404(ingredient_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = specs_of_ingredient(ingredient_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_spec, limit, offset)


@bp.get("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>")
@require_roles(*ALL_ROLES)
def get_spec(ingredient_id, spec_id):
    get_ingredient_or_404(ingredient_id)
    return respond_object(ser_spec(get_spec_or_404(ingredient_id, spec_id)))


# --- Parameters ------------------------------------------------------------

@bp.post("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>/parameters")
@require_roles("SpecAuthor")
def add_parameter(ingredient_id, spec_id):
    get_ingredient_or_404(ingredient_id)
    spec = get_spec_or_404(ingredient_id, spec_id)
    if spec["status"] != "DRAFT":
        err(ERR_INVALID_STATE, 409, "parameters can only be added to a DRAFT spec")
    data = body()

    name = data.get("parameter_name")
    if isinstance(name, str):
        for other in params_of_spec(spec["id"]):
            if other["parameter_name"] == name:
                err(ERR_DUPLICATE, 409, "parameter_name already exists in spec")

    name = require_str(data, "parameter_name")
    criticality = data.get("criticality")
    if criticality not in CRITICALITIES:
        invalid("criticality must be one of CRITICAL, MAJOR, MINOR")
    uom = require_str(data, "uom")
    target = data.get("target_value")
    minv = data.get("min_value")
    maxv = data.get("max_value")
    for field, value in (("target_value", target), ("min_value", minv), ("max_value", maxv)):
        if not is_number(value):
            invalid(f"{field} is required and must be a number")

    rec = new_record()
    rec.update(
        {
            "spec_id": spec["id"],
            "parameter_name": name,
            "criticality": criticality,
            "uom": uom,
            "target_value": target,
            "min_value": minv,
            "max_value": maxv,
        }
    )
    STORE.parameters[rec["id"]] = rec
    return respond_object(ser_parameter(rec), 201)


@bp.get("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>/parameters")
@require_roles(*ALL_ROLES)
def list_parameters(ingredient_id, spec_id):
    get_ingredient_or_404(ingredient_id)
    spec = get_spec_or_404(ingredient_id, spec_id)
    limit, offset = pagination_params()
    return list_page(params_of_spec(spec["id"]), ser_parameter, limit, offset)


# --- Spec lifecycle actions -------------------------------------------------

@bp.post("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>/submit")
@require_roles("SpecAuthor")
def submit_spec(ingredient_id, spec_id):
    get_ingredient_or_404(ingredient_id)
    spec = get_spec_or_404(ingredient_id, spec_id)
    if spec["status"] != "DRAFT":
        err(ERR_INVALID_STATE, 409, "spec is not DRAFT")
    if g.user_id != spec["author_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "only the author may submit the spec")
    if not params_of_spec(spec["id"]):
        err(ERR_NO_SPEC_PARAMETERS, 409, "spec has no parameters")
    if len(spec["version_note"]) < 10:
        invalid("version_note must be at least 10 characters when submitting")
    spec["status"] = "PENDING_REVIEW"
    touch(spec)
    return respond_object(ser_spec(spec))


@bp.post("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>/approve")
@require_roles("QualityManager")
def approve_spec(ingredient_id, spec_id):
    get_ingredient_or_404(ingredient_id)
    spec = get_spec_or_404(ingredient_id, spec_id)
    if spec["status"] != "PENDING_REVIEW":
        err(ERR_INVALID_STATE, 409, "spec is not PENDING_REVIEW")
    if g.user_id == spec["author_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "author cannot approve own spec")
    for p in params_of_spec(spec["id"]):
        if not (p["min_value"] < p["max_value"] and p["min_value"] <= p["target_value"] <= p["max_value"]):
            err(ERR_PARAMETER_BOUNDS_INVALID, 422, "parameter bounds violated")
    spec["status"] = "APPROVED"
    spec["reviewed_by_user_id"] = g.user_id
    touch(spec)
    return respond_object(ser_spec(spec))


@bp.post("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>/reject")
@require_roles("QualityManager")
def reject_spec(ingredient_id, spec_id):
    get_ingredient_or_404(ingredient_id)
    spec = get_spec_or_404(ingredient_id, spec_id)
    if spec["status"] != "PENDING_REVIEW":
        err(ERR_INVALID_STATE, 409, "spec is not PENDING_REVIEW")
    if g.user_id == spec["author_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "author cannot reject own spec")
    spec["status"] = "REJECTED"
    touch(spec)
    return respond_object(ser_spec(spec))


@bp.post("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>/revise")
@require_roles("SpecAuthor")
def revise_spec(ingredient_id, spec_id):
    get_ingredient_or_404(ingredient_id)
    spec = get_spec_or_404(ingredient_id, spec_id)
    if spec["status"] != "REJECTED":
        err(ERR_INVALID_STATE, 409, "spec is not REJECTED")
    if g.user_id != spec["author_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "only the author may revise the spec")
    spec["status"] = "DRAFT"
    touch(spec)
    return respond_object(ser_spec(spec))


@bp.post("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>/make-effective")
@require_roles("QualityManager")
def make_effective_spec(ingredient_id, spec_id):
    ing = get_ingredient_or_404(ingredient_id)
    spec = get_spec_or_404(ingredient_id, spec_id)
    if spec["status"] != "APPROVED":
        err(ERR_INVALID_STATE, 409, "spec is not APPROVED")
    if STORE.clock < spec["effective_date__dt"]:
        err(ERR_SPEC_NOT_YET_EFFECTIVE, 422, "spec effective_date is in the future")
    superseded = None
    if spec["supersedes_spec_id"] is not None:
        superseded = STORE.specs.get(spec["supersedes_spec_id"])
        if superseded is None or superseded["status"] != "EFFECTIVE":
            err(ERR_SUPERSEDES_NOT_EFFECTIVE, 409, "superseded spec is not EFFECTIVE")

    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
    spec["status"] = "EFFECTIVE"
    touch(spec)
    ing["active_spec_id"] = spec["id"]
    touch(ing)
    if superseded is not None:
        # Stale-pin sweep: ACTIVE sources pinned to the superseded spec.
        for src in sources_of_ingredient(ing["id"]):
            if src["pinned_spec_id"] == superseded["id"] and src["status"] == "ACTIVE":
                src["status"] = "SUSPENDED"
                src["suspension_reason"] = "MANUAL"
                touch(src)
    recompute_dual_source(ing)
    return respond_object(ser_spec(spec))


@bp.post("/sourcing/ingredients/<ingredient_id>/specs/<spec_id>/retire")
@require_roles("QualityManager")
def retire_spec(ingredient_id, spec_id):
    get_ingredient_or_404(ingredient_id)
    spec = get_spec_or_404(ingredient_id, spec_id)
    if spec["status"] not in ("DRAFT", "REJECTED"):
        err(ERR_INVALID_STATE, 409, "spec is not DRAFT or REJECTED")
    in_use = [
        s
        for s in STORE.sources.values()
        if s["pinned_spec_id"] == spec["id"] and s["status"] in ("PROVISIONAL", "ACTIVE")
    ]
    if in_use:
        err(ERR_SPEC_IN_USE, 409, "spec is referenced by live approved sources")
    spec["status"] = "RETIRED"
    touch(spec)
    return respond_object(ser_spec(spec))
