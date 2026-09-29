"""Products, the component inventory and design review (PRD 3.1, 3.2)."""
from decimal import Decimal

from flask import Blueprint

from db import db, new_row, now_iso, sort_key, touch
from derive import recompute_product
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import list_response, obj_response
from serialize import component_out, product_out
from validate import (
    ASSESSMENT_SCOPES,
    ASSESSMENT_STATES,
    COMPONENT_TYPES,
    LEVELS,
    LEVEL_RANK,
    POSTURES,
    READINESS,
    REVIEW_DECISIONS,
    SURFACES,
    body,
    fk_standard,
    pagination,
    paginate,
    path_component,
    path_product,
    q_bool,
    q_enum,
    q_str,
    v_bool,
    v_enum,
    v_int,
    v_str,
)

bp = Blueprint("products", __name__)


@bp.post("/products")
@endpoint(["AccessibilityLead"])
def create_product():
    data = body()
    standard = fk_standard(data.get("standard_id"))          # step 5
    name = v_str(data, "name", required=True, min_len=1, max_len=160)
    version_label = v_str(data, "version_label", required=True, min_len=1, max_len=40)
    v_str(data, "standard_id", required=True, min_len=1)
    target_level = v_enum(data, "target_level", LEVELS, required=True)
    surface_type = v_enum(data, "surface_type", ["WEB", "SOFTWARE", "BOTH"],
                          required=True)

    # step 37: level and surface compatibility
    if LEVEL_RANK[target_level] > LEVEL_RANK[standard["max_target_level"]]:
        raise ApiError("ERR_LEVEL_OR_SURFACE_UNSUPPORTED",
                       "Target level %s exceeds the standard's maximum %s"
                       % (target_level, standard["max_target_level"]))
    scope = standard["surface_scope"]
    if scope != "BOTH" and surface_type != scope:
        raise ApiError("ERR_LEVEL_OR_SURFACE_UNSUPPORTED",
                       "Surface type %s is incompatible with the standard's scope %s"
                       % (surface_type, scope))

    row = new_row({
        "name": name,
        "version_label": version_label,
        "standard_id": standard["id"],
        "target_level": target_level,
        "surface_type": surface_type,
        "components_in_scope_count": 0,
        "components_complete_count": 0,
        "assessment_readiness": "NOT_READY",
        "assessed_criteria_count": 0,
        "conformance_index_provisional": Decimal("0.00"),
        "stale_questionnaire_count": 0,
        "correction_required_questionnaire_count": 0,
        "overdue_committed_blocker_count": 0,
        "publication_posture": "OPEN",
        "accommodations_fulfilled_count": 0,
    })
    db.products[row["id"]] = row
    return obj_response(product_out(row), 201)


@bp.get("/products/<product_id>")
@endpoint(ALL_ROLES)
def get_product(product_id):
    return obj_response(product_out(path_product(product_id)))


@bp.get("/products")
@endpoint(ALL_ROLES)
def list_products():
    standard_id = q_str("standard_id")
    posture = q_enum("publication_posture", POSTURES)
    readiness = q_enum("assessment_readiness", READINESS)
    limit, offset = pagination()
    rows = list(db.products.values())
    if standard_id is not None:
        rows = [r for r in rows if r["standard_id"] == standard_id]
    if posture is not None:
        rows = [r for r in rows if r["publication_posture"] == posture]
    if readiness is not None:
        rows = [r for r in rows if r["assessment_readiness"] == readiness]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([product_out(r) for r in page], limit, offset, total)


@bp.post("/products/<product_id>/recompute-posture")
@endpoint(["AccessibilityLead"])
def recompute_posture(product_id):
    product = path_product(product_id)
    data = body()
    v_str(data, "reason", required=True, min_len=1, max_len=2000)
    recompute_product(product, lapse_accuracy=True)
    touch(product)
    return obj_response(product_out(product))


@bp.post("/products/<product_id>/components")
@endpoint(["AccessibilityLead"])
def create_component(product_id):
    product = path_product(product_id)
    data = body()
    name = v_str(data, "name", required=True, min_len=1, max_len=160)
    component_type = v_enum(data, "component_type", COMPONENT_TYPES, required=True)
    in_scope = v_bool(data, "in_scope", required=True)
    assessment_scope = v_enum(data, "assessment_scope", ASSESSMENT_SCOPES, required=True)
    applicable = v_int(data, "applicable_criteria_count", required=True,
                       min_value=1, max_value=500)
    reach = v_int(data, "user_reach_pct", required=True, min_value=0, max_value=100)

    # step 35: name unique within the product
    for existing in db.components.values():
        if existing["product_id"] == product["id"] and existing["name"] == name:
            raise ApiError("ERR_DUPLICATE_COMPONENT_NAME",
                           "Component name %s already exists on this product" % name)

    row = new_row({
        "product_id": product["id"],
        "name": name,
        "component_type": component_type,
        "in_scope": in_scope,
        "assessment_scope": assessment_scope,
        "applicable_criteria_count": applicable,
        "user_reach_pct": reach,
        "evidence_units_total": 0,
        "coverage_pct": Decimal("0.00"),
        "validated_disability_categories": [],
        "assessment_state": "PLANNED",
        "design_review_state": "NOT_REVIEWED",
        "design_review_note": None,
        "_design_reviewed_at": None,
    })
    db.components[row["id"]] = row

    recompute_product(product)
    touch(product)
    return obj_response(component_out(row), 201)


@bp.get("/products/<product_id>/components")
@endpoint(ALL_ROLES)
def list_components(product_id):
    product = path_product(product_id)
    in_scope = q_bool("in_scope")
    state = q_enum("assessment_state", ASSESSMENT_STATES)
    limit, offset = pagination()
    rows = [c for c in db.components.values() if c["product_id"] == product["id"]]
    if in_scope is not None:
        rows = [c for c in rows if c["in_scope"] is in_scope]
    if state is not None:
        rows = [c for c in rows if c["assessment_state"] == state]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([component_out(r) for r in page], limit, offset, total)


@bp.get("/components/<component_id>")
@endpoint(ALL_ROLES)
def get_component(component_id):
    return obj_response(component_out(path_component(component_id)))


@bp.post("/components/<component_id>/design-review")
@endpoint(["ConformanceReviewer"])
def design_review(component_id):
    component = path_component(component_id)
    data = body()
    decision = v_enum(data, "review_decision", REVIEW_DECISIONS, required=True)
    note = v_str(data, "review_note", required=True, min_len=1, max_len=2000)

    product = db.products[component["product_id"]]
    # step 15: posture gate
    if product["publication_posture"] == "FROZEN":
        raise ApiError("ERR_PRODUCT_POSTURE_FROZEN",
                       "Product %s is FROZEN" % product["id"])

    component["design_review_state"] = (
        "REVIEWED_PASS" if decision == "PASS" else "REVIEWED_BLOCKED")
    component["design_review_note"] = note
    component["_design_reviewed_at"] = now_iso()
    touch(component)
    # the testing dimension is untouched (PRD 2.11)
    touch(product)
    return obj_response(component_out(component))
