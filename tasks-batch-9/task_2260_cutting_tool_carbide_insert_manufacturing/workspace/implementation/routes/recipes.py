"""Coating recipes and their layer stacks (PRD section 3.3)."""

from decimal import Decimal

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("recipes", __name__)

READ_ROLES = [
    "CoatingEngineer",
    "MetallurgyEngineer",
    "GeometryEngineer",
    "ApplicationEngineer",
    "QualityApprover",
    "ProductionPlanner",
]
OWNER = ["CoatingEngineer"]

MIN_LAYERS = 1
MAX_LAYERS = 5


def _parse_layers(payload):
    """Priority 4 (per-entry domain) then priority 6 (stack well-formedness)."""
    layers = payload.get("layers")
    if not isinstance(layers, list):
        v.bad("Field 'layers' must be an array of layer objects.")

    parsed = []
    for index, entry in enumerate(layers):
        if not isinstance(entry, dict):
            v.bad("Layer %d must be an object with 'material' and 'thickness_um'." % index)
        unknown = [k for k in entry.keys() if k not in ("material", "thickness_um")]
        if unknown:
            v.bad("Layer %d carries unknown field(s): %s." % (index, ", ".join(sorted(unknown))))
        for name in ("material", "thickness_um"):
            if name not in entry:
                v.bad("Layer %d is missing %r." % (index, name))
        material = v.as_enum(entry, "material", c.LAYER_MATERIALS)
        thickness = v.as_number(entry, "thickness_um", minimum=0.10, maximum=8.00)
        parsed.append({"material": material, "thickness_um": thickness})

    if len(parsed) < MIN_LAYERS or len(parsed) > MAX_LAYERS:
        raise ApiError(
            "ERR_INVALID_LAYER_STACK",
            "A layer stack must hold between %d and %d entries." % (MIN_LAYERS, MAX_LAYERS),
        )
    for i in range(1, len(parsed)):
        if parsed[i]["material"] == parsed[i - 1]["material"]:
            raise ApiError(
                "ERR_INVALID_LAYER_STACK",
                "Adjacent layers may not name the same material (%s)." % parsed[i]["material"],
            )
    return parsed


def _total_thickness(layers):
    total = Decimal("0")
    for layer in layers:
        total += calc.D(layer["thickness_um"])
    return float(calc.round_half_up(total, 2))


@bp.route("/tooling/coating-recipes", methods=["POST"])
def create():
    authenticate(OWNER)
    payload = v.body(required=("recipe_code", "deposition_type", "layers"))
    recipe_code = v.as_string(payload, "recipe_code")
    deposition = v.as_enum(payload, "deposition_type", c.DEPOSITION_TYPES)
    layers = _parse_layers(payload)

    derive.require_unique("recipes", "recipe_code", recipe_code)

    row = db.new_row(
        {
            "recipe_code": recipe_code,
            "deposition_type": deposition,
            "layers": layers,
            "total_thickness_um": _total_thickness(layers),
            "revision": 1,
        }
    )
    db.recipes[row["id"]] = row
    return object_response(serialize.recipe(row), 201)


@bp.route("/tooling/coating-recipes", methods=["GET"])
def index():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    filters = {}
    deposition = v.query_enum("deposition_type", c.DEPOSITION_TYPES)
    if deposition is not None:
        filters["deposition_type"] = deposition
    validated = v.query_bool("is_validated")
    rows = derive.where("recipes", **filters)
    if validated is not None:
        rows = [r for r in rows if derive.recipe_is_validated(r) == validated]
    return c.list_response("recipes", rows, limit, offset)


@bp.route("/tooling/coating-recipes/<recipe_id>", methods=["GET"])
def read(recipe_id):
    return c.read_one("recipes", recipe_id, READ_ROLES)


@bp.route("/tooling/coating-recipes/<recipe_id>/revise", methods=["POST"])
def revise(recipe_id):
    authenticate(OWNER)
    payload = v.body(required=("layers", "revision_note"))
    layers = _parse_layers(payload)
    v.as_string(payload, "revision_note")

    recipe = derive.must_exist("recipes", recipe_id)

    recipe["layers"] = layers
    recipe["total_thickness_um"] = _total_thickness(layers)
    recipe["revision"] = recipe["revision"] + 1
    db.touch(recipe)

    derive.revision_cascade(
        [p for p in db.products.values() if p["coating_recipe_id"] == recipe["id"]],
        "pinned_coating_revision",
        recipe["revision"],
    )
    return object_response(serialize.recipe(recipe))
