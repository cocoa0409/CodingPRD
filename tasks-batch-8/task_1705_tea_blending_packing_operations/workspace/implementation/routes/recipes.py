"""Blend recipe composition, lifecycle, and retirement cascade (PRD 3.3)."""
from decimal import Decimal

from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_FLAVORING_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RECIPE_COMPOSITION_INVALID,
    ERR_STALE_VERSION,
    raise_err,
)
from services import (
    CERT_TARGETS,
    LEAF_TYPES,
    MIN_GRADES,
    PACK_FORMATS,
    recipe_out,
    release_batch_allocations,
)
from util import (
    body_json, bump, get_or_404, list_response, new_record, req_enum,
    req_str, success_object, to_decimal,
)

bp = Blueprint("recipes", __name__)


def _recipe_or_404(rid):
    return get_or_404(store.recipes, rid, "BlendRecipe")


def _parse_components(raw):
    """Composition check (PRD 3.3): non-empty array of well-formed entries.
    Violations surface as ERR_RECIPE_COMPOSITION_INVALID."""
    if not isinstance(raw, list) or len(raw) == 0:
        raise_err(
            ERR_RECIPE_COMPOSITION_INVALID,
            "components must be a non-empty array",
        )
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise_err(ERR_RECIPE_COMPOSITION_INVALID, "component entries must be objects")
        leaf_type = entry.get("leaf_type")
        min_grade = entry.get("min_grade")
        pct = to_decimal(entry.get("pct"))
        if not isinstance(leaf_type, str) or leaf_type not in LEAF_TYPES:
            raise_err(
                ERR_RECIPE_COMPOSITION_INVALID,
                "component leaf_type must be one of %s" % ", ".join(LEAF_TYPES),
            )
        if not isinstance(min_grade, str) or min_grade not in MIN_GRADES:
            raise_err(
                ERR_RECIPE_COMPOSITION_INVALID,
                "component min_grade must be one of A, B, C",
            )
        if pct is None or pct <= 0:
            raise_err(
                ERR_RECIPE_COMPOSITION_INVALID,
                "component pct must be a positive number",
            )
        parsed.append({"leaf_type": leaf_type, "min_grade": min_grade, "pct": pct})
    return parsed


def _check_composition(components, flavoring_pct):
    """Exact composition: component pct values plus flavoring_pct sum to
    exactly 100.00."""
    total = sum((c["pct"] for c in components), Decimal("0")) + flavoring_pct
    if total != Decimal("100"):
        raise_err(
            ERR_RECIPE_COMPOSITION_INVALID,
            "component pct values plus flavoring_pct must sum to exactly 100.00",
        )


def _parse_recipe_fields(body, partial=False):
    """Field-shape validation for recipe payloads. With partial=True (PUT),
    only provided fields are validated. Returns dict of parsed values."""
    out = {}
    if not partial or "name" in body:
        out["name"] = req_str(body, "name")
    if not partial or "certification_target" in body:
        out["certification_target"] = req_enum(
            body, "certification_target", CERT_TARGETS
        )
    if not partial or "pack_format" in body:
        out["pack_format"] = req_enum(body, "pack_format", PACK_FORMATS)
    if "flavoring_pct" in body:
        fp = to_decimal(body.get("flavoring_pct"))
        if fp is None:
            raise_err(ERR_INVALID_REQUEST, "flavoring_pct must be a number")
        out["flavoring_pct"] = fp
    elif not partial:
        out["flavoring_pct"] = Decimal("0")
    if "components" in body:
        out["components"] = body["components"]  # composition-checked later
    elif not partial:
        out["components"] = None
    return out


@bp.route("/tea-ops/recipes", methods=["POST"])
def create_recipe():
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    body = body_json()
    # Priority 3: body FK resolution (flavoring_id) when present and non-null.
    flavoring_id = body.get("flavoring_id")
    flavoring = None
    if flavoring_id is not None:
        flavoring = get_or_404(store.flavorings, flavoring_id, "Flavoring")

    # Priority 13: scalar field shape.
    fields = _parse_recipe_fields(body, partial=False)

    # Priority 10: composition (component shape + exact 100.00 sum).
    components = _parse_components(fields["components"])
    flavoring_pct = fields["flavoring_pct"]
    if flavoring_pct < 0:
        raise_err(ERR_RECIPE_COMPOSITION_INVALID, "flavoring_pct must be >= 0")
    _check_composition(components, flavoring_pct)

    rec = new_record()
    rec.update({
        "name": fields["name"],
        "certification_target": fields["certification_target"],
        "pack_format": fields["pack_format"],
        "components": components,
        "flavoring_id": flavoring["id"] if flavoring else None,
        "flavoring_pct": flavoring_pct,
        "status": "DRAFT",
    })
    store.recipes[rec["id"]] = rec
    return success_object(recipe_out(rec), 201)


@bp.route("/tea-ops/recipes/<rid>", methods=["GET"])
def get_recipe(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(recipe_out(_recipe_or_404(rid)))


@bp.route("/tea-ops/recipes", methods=["GET"])
def list_recipes():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.recipes.values())
    flavoring_id = request.args.get("flavoring_id")
    status = request.args.get("status")
    if flavoring_id is not None:
        records = [r for r in records if r["flavoring_id"] == flavoring_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, recipe_out)


@bp.route("/tea-ops/recipes/<rid>", methods=["PUT"])
def update_recipe(rid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    recipe = _recipe_or_404(rid)
    body = body_json()
    # Priority 3: body FK resolution.
    if "flavoring_id" in body and body["flavoring_id"] is not None:
        get_or_404(store.flavorings, body["flavoring_id"], "Flavoring")
    # Priority 4: OCC on the recipe version (PRD 2.7).
    expected = body.get("expected_recipe_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != recipe["version"]:
            raise_err(
                ERR_STALE_VERSION,
                "expected_recipe_version does not match the current version",
            )
    # Priority 5: terminal guard.
    if recipe["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "BlendRecipe is RETIRED")
    # Priority 6: revisions require DRAFT.
    if recipe["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT recipe can be revised")
    # Priority 13: field shape — expected_recipe_version is not optional.
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(
            ERR_INVALID_REQUEST, "expected_recipe_version is required and must be an integer"
        )
    fields = _parse_recipe_fields(body, partial=True)

    if "name" in fields:
        recipe["name"] = fields["name"]
    if "certification_target" in fields:
        recipe["certification_target"] = fields["certification_target"]
    if "pack_format" in fields:
        recipe["pack_format"] = fields["pack_format"]
    if "components" in fields:
        recipe["components"] = _parse_components(fields["components"])
    if "flavoring_id" in body:
        recipe["flavoring_id"] = body["flavoring_id"]
    if "flavoring_pct" in fields:
        recipe["flavoring_pct"] = fields["flavoring_pct"]
    bump(recipe)
    return success_object(recipe_out(recipe))


@bp.route("/tea-ops/recipes/<rid>/activate", methods=["POST"])
def activate_recipe(rid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    recipe = _recipe_or_404(rid)
    if recipe["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "BlendRecipe is RETIRED")
    if recipe["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT recipe can be activated")
    # Priority 10: composition re-checked at activation (PRD 3.3).
    components = _parse_components(recipe["components"])
    flavoring_pct = recipe["flavoring_pct"]
    if flavoring_pct < 0:
        raise_err(ERR_RECIPE_COMPOSITION_INVALID, "flavoring_pct must be >= 0")
    _check_composition(components, flavoring_pct)
    # Priority 11: flavoring liveness.
    if recipe["flavoring_id"] is not None:
        flavoring = store.flavorings.get(recipe["flavoring_id"])
        if flavoring is None or flavoring["status"] != "ACTIVE":
            raise_err(
                ERR_FLAVORING_NOT_ACTIVE,
                "Referenced flavoring is not ACTIVE",
            )
    recipe["status"] = "ACTIVE"
    bump(recipe)
    return success_object(recipe_out(recipe))


@bp.route("/tea-ops/recipes/<rid>/retire", methods=["POST"])
def retire_recipe(rid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    recipe = _recipe_or_404(rid)
    if recipe["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "BlendRecipe is RETIRED")
    if recipe["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE recipe can be retired")
    recipe["status"] = "RETIRED"
    bump(recipe)
    # Cascade link 1: DRAFT / RECIPE_LOCKED batches of this recipe -> CANCELLED;
    # link 2: their allocations release back to the lots.
    for batch in sorted(
        (b for b in store.batches.values() if b["recipe_id"] == recipe["id"]),
        key=lambda b: b["_seq"],
    ):
        if batch["status"] in ("DRAFT", "RECIPE_LOCKED"):
            batch["status"] = "CANCELLED"
            bump(batch)
            release_batch_allocations(batch)
    return success_object(recipe_out(recipe))
