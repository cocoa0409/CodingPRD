"""Tool products, lead time, supply posture and the cutting envelope (PRD 3.5)."""

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("products", __name__)

ANY = c.ANY_ROLE
CREATORS = ["GeometryEngineer", "ApplicationEngineer"]
PINNERS = ["ApplicationEngineer", "GeometryEngineer"]
QUALITY = ["QualityApprover"]
PLANNER = ["ProductionPlanner"]
ADVISORS = [
    "ApplicationEngineer",
    "GeometryEngineer",
    "MetallurgyEngineer",
    "CoatingEngineer",
    "QualityApprover",
    "Customer",
]


def _reference_conditions(product):
    """The three referenced-entity gates of enter-qualification and repin."""
    grade, geometry, recipe = derive.product_refs(product)
    if grade is None or grade["status"] not in ("PILOT", "QUALIFIED"):
        raise ApiError(
            "ERR_INVALID_GRADE_STATE",
            "The referenced grade must be PILOT or QUALIFIED.",
        )
    if geometry is None or geometry["status"] != "RELEASED":
        raise ApiError(
            "ERR_INVALID_GEOMETRY_STATE", "The referenced geometry must be RELEASED."
        )
    if recipe is not None and not derive.recipe_is_validated(recipe):
        raise ApiError(
            "ERR_COATING_NOT_VALIDATED", "The referenced coating recipe is not validated."
        )
    return grade, geometry, recipe


def _repin(product, grade, geometry, recipe):
    product["pinned_grade_revision"] = grade["revision"]
    product["pinned_geometry_revision"] = geometry["revision"]
    product["pinned_coating_revision"] = recipe["revision"] if recipe is not None else None


@bp.route("/tooling/tool-products", methods=["POST"])
def create():
    authenticate(CREATORS)
    payload = v.body(
        required=(
            "sku",
            "order_class",
            "grade_id",
            "geometry_id",
            "tool_type",
            "list_price_cents",
            "min_order_qty",
            "nominal_length_mm",
            "min_regrind_length_mm",
            "regrind_step_mm",
            "grind_units_per_tool",
        ),
        optional=("coating_recipe_id", "base_catalog_product_id"),
    )
    sku = v.as_string(payload, "sku")
    order_class = v.as_enum(payload, "order_class", c.ORDER_CLASSES)
    grade_id = v.as_id(payload, "grade_id")
    geometry_id = v.as_id(payload, "geometry_id")
    recipe_id = v.as_id(payload, "coating_recipe_id", nullable=True)
    base_id = v.as_id(payload, "base_catalog_product_id", nullable=True)
    tool_type = v.as_enum(payload, "tool_type", c.TOOL_TYPES)
    list_price = v.as_int(payload, "list_price_cents", minimum=1)
    min_qty = v.as_int(payload, "min_order_qty", minimum=1)
    nominal = v.as_number(payload, "nominal_length_mm", exclusive_min=0)
    min_regrind = v.as_number(payload, "min_regrind_length_mm", exclusive_min=0)
    step = v.as_number(payload, "regrind_step_mm", exclusive_min=0)
    units_per_tool = v.as_int(payload, "grind_units_per_tool", minimum=1)
    if calc.D(min_regrind) >= calc.D(nominal):
        v.bad("Field 'min_regrind_length_mm' must be strictly less than 'nominal_length_mm'.")

    grade = derive.must_exist("grades", grade_id)
    geometry = derive.must_exist("geometries", geometry_id)
    recipe = derive.must_exist("recipes", recipe_id) if recipe_id else None
    base = derive.must_exist("products", base_id) if base_id else None

    derive.require_unique("products", "sku", sku)

    if order_class == "SPECIAL":
        if base is None:
            raise ApiError(
                "ERR_INVALID_PRODUCT_DERIVATION",
                "A SPECIAL product must name a base_catalog_product_id.",
            )
        if base["order_class"] != "CATALOG":
            raise ApiError(
                "ERR_INVALID_PRODUCT_DERIVATION",
                "The derivation is exactly one hop deep: the base product must be CATALOG.",
            )
    elif base is not None:
        raise ApiError(
            "ERR_INVALID_PRODUCT_DERIVATION",
            "A CATALOG product must not name a base_catalog_product_id.",
        )

    row = db.new_row(
        {
            "sku": sku,
            "order_class": order_class,
            "base_catalog_product_id": base["id"] if base else None,
            "grade_id": grade["id"],
            "geometry_id": geometry["id"],
            "coating_recipe_id": recipe["id"] if recipe else None,
            "tool_type": tool_type,
            "list_price_cents": list_price,
            "min_order_qty": min_qty,
            "nominal_length_mm": nominal,
            "min_regrind_length_mm": min_regrind,
            "regrind_step_mm": step,
            "grind_units_per_tool": units_per_tool,
            "release_status": "DEVELOPMENT",
            "supply_status": "UNAVAILABLE",
            "pinned_grade_revision": grade["revision"],
            "pinned_geometry_revision": geometry["revision"],
            "pinned_coating_revision": recipe["revision"] if recipe else None,
            "engineering_lead_time_days": None,
            "expedite_eligible": False,
            "tool_life_index": None,
            "qualified_workpiece_groups": [],
        }
    )
    derive.recompute_lead_time(row)
    db.products[row["id"]] = row
    return object_response(serialize.product(row), 201)


@bp.route("/tooling/tool-products", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "products",
        ANY,
        {
            "grade_id": None,
            "geometry_id": None,
            "coating_recipe_id": None,
            "base_catalog_product_id": None,
            "release_status": c.RELEASE_STATUSES,
            "order_class": c.ORDER_CLASSES,
        },
    )
    return c.list_response("products", rows, limit, offset)


@bp.route("/tooling/tool-products/<product_id>", methods=["GET"])
def read(product_id):
    return c.read_one("products", product_id, ANY)


@bp.route("/tooling/tool-products/<product_id>/enter-qualification", methods=["POST"])
def enter_qualification(product_id):
    authenticate(PINNERS)
    v.no_body()
    product = derive.must_exist("products", product_id)
    if product["release_status"] != "DEVELOPMENT":
        raise ApiError(
            "ERR_INVALID_PRODUCT_STATE",
            "Qualification is entered from DEVELOPMENT (currently %s)."
            % product["release_status"],
        )
    grade, geometry, recipe = _reference_conditions(product)

    product["release_status"] = "QUALIFICATION"
    _repin(product, grade, geometry, recipe)
    derive.recompute_lead_time(product)
    db.touch(product)
    return object_response(serialize.product(product))


@bp.route("/tooling/tool-products/<product_id>/release", methods=["POST"])
def release(product_id):
    authenticate(QUALITY)
    v.no_body()
    product = derive.must_exist("products", product_id)
    if product["release_status"] != "QUALIFICATION":
        raise ApiError(
            "ERR_INVALID_PRODUCT_STATE",
            "A product is released from QUALIFICATION (currently %s)."
            % product["release_status"],
        )

    grade, geometry, recipe = derive.product_refs(product)
    stale = (
        grade is None
        or geometry is None
        or product["pinned_grade_revision"] != grade["revision"]
        or product["pinned_geometry_revision"] != geometry["revision"]
        or (recipe is not None and product["pinned_coating_revision"] != recipe["revision"])
    )
    if stale:
        raise ApiError(
            "ERR_PINNED_REVISION_STALE",
            "The product's pinned revisions no longer match the referenced definitions.",
        )

    approved = [
        d
        for d in db.dossiers.values()
        if d["product_id"] == product["id"] and d["status"] == "APPROVED"
    ]
    if not approved or product["tool_life_index"] is None:
        raise ApiError(
            "ERR_NO_APPROVED_DOSSIER",
            "Release requires an APPROVED dossier and a non-null tool_life_index.",
        )

    product["release_status"] = "RELEASED"
    product["supply_status"] = "STOCKED" if product["order_class"] == "CATALOG" else "MAKE_TO_ORDER"
    derive.recompute_lead_time(product)
    db.touch(product)
    db.touch(grade)
    return object_response(serialize.product(product))


@bp.route("/tooling/tool-products/<product_id>/repin", methods=["POST"])
def repin(product_id):
    authenticate(PINNERS)
    v.no_body()
    product = derive.must_exist("products", product_id)
    if product["release_status"] != "RESTRICTED":
        raise ApiError(
            "ERR_INVALID_PRODUCT_STATE",
            "Only a RESTRICTED product may be repinned (currently %s)."
            % product["release_status"],
        )
    grade, geometry, recipe = _reference_conditions(product)

    product["release_status"] = "QUALIFICATION"
    _repin(product, grade, geometry, recipe)
    derive.recompute_lead_time(product)
    db.touch(product)
    return object_response(serialize.product(product))


@bp.route("/tooling/tool-products/<product_id>/set-supply-status", methods=["POST"])
def set_supply_status(product_id):
    authenticate(PLANNER)
    payload = v.body(required=("supply_status",))
    target = v.as_enum(payload, "supply_status", c.SUPPLY_STATUSES)

    product = derive.must_exist("products", product_id)
    current = product["supply_status"]
    release_status = product["release_status"]

    admissible = False
    if target == "MAKE_TO_ORDER":
        if current == "UNAVAILABLE":
            admissible = release_status in ("RELEASED", "RESTRICTED")
        elif current == "STOCKED":
            admissible = True
    elif target == "STOCKED":
        if current == "UNAVAILABLE":
            admissible = release_status == "RELEASED" and product["order_class"] == "CATALOG"
        elif current == "MAKE_TO_ORDER":
            admissible = release_status == "RELEASED"
    elif target == "UNAVAILABLE":
        admissible = current in ("MAKE_TO_ORDER", "STOCKED")

    if not admissible:
        raise ApiError(
            "ERR_INVALID_PRODUCT_STATE",
            "supply_status %s -> %s is not admissible for a %s %s product."
            % (current, target, release_status, product["order_class"]),
        )

    cascade = current == "STOCKED" and target == "MAKE_TO_ORDER"
    product["supply_status"] = target
    db.touch(product)
    if cascade:
        derive.supply_stocked_to_mto_cascade(product)
    return object_response(serialize.product(product))


@bp.route("/tooling/tool-products/<product_id>/withdraw", methods=["POST"])
def withdraw(product_id):
    authenticate(QUALITY)
    payload = v.body(required=("withdraw_reason",))
    v.as_string(payload, "withdraw_reason")

    product = derive.must_exist("products", product_id)
    if product["release_status"] not in (
        "DEVELOPMENT",
        "QUALIFICATION",
        "RELEASED",
        "RESTRICTED",
    ):
        raise ApiError(
            "ERR_INVALID_PRODUCT_STATE",
            "A WITHDRAWN product cannot be withdrawn again.",
        )
    if derive.product_has_open_demand(product):
        raise ApiError("ERR_OPEN_DEMAND_EXISTS", "Open demand exists on this product.")

    product["release_status"] = "WITHDRAWN"
    product["supply_status"] = "UNAVAILABLE"
    db.touch(product)
    for order in db.ordered(
        [o for o in db.orders.values() if o["product_id"] == product["id"]]
    ):
        if order["status"] == "DRAFT":
            order["status"] = "CANCELLED"
            db.touch(order)
    return object_response(serialize.product(product))


@bp.route("/tooling/tool-products/<product_id>/speeds-feeds", methods=["GET"])
def speeds_feeds(product_id):
    authenticate(ADVISORS)
    v.pagination()
    group = v.required_query_enum("workpiece_group", c.WORKPIECE_GROUPS)
    rigidity = v.required_query_enum("machine_rigidity", c.RIGIDITIES)
    coolant = v.required_query_enum("coolant", c.COOLANTS)

    product = derive.must_exist("products", product_id)
    grade, geometry, recipe = derive.product_refs(product)

    vc, fz, ap, confidence = calc.speeds_feeds_envelope(
        group,
        rigidity,
        coolant,
        grade["co_binder_pct"],
        recipe,
        geometry["application_class"],
        geometry["nose_radius_mm"],
        geometry["max_depth_of_cut_mm"],
        product["qualified_workpiece_groups"],
        product["release_status"],
    )
    return object_response(
        {
            "recommended_vc": vc,
            "recommended_fz": fz,
            "recommended_ap": ap,
            "confidence_class": confidence,
        }
    )
