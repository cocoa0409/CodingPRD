"""Formula endpoints: create/read/list, lifecycle actions, revisions,
regulatory review creation, and stability study creation."""
from decimal import Decimal

from flask import Blueprint, g, request

from core import (body, check_bool, check_enum, check_int, check_number,
                  check_string, err, get_required, list_page, new_entity,
                  require_roles, success, touch)
from services import (D, REQUIRED_INTERVALS, cancel_order_cascade,
                      latest_review, must_get, serialize_formula,
                      serialize_review, serialize_study)
from store import db

bp = Blueprint("formulas", __name__)

OWNERSHIPS = {"CUSTOMER_OWNED", "MANUFACTURER_OWNED"}
CONFIDENTIALITIES = {"STANDARD", "EXCLUSIVE"}
PRODUCT_CLASSES = {"SKIN", "HAIR", "BABY", "SUN"}
REVIEW_SCOPES = {"INCI_LIST", "LABEL_ARTWORK"}
STUDY_TYPES = {"PRESERVATIVE_EFFICACY", "ACCELERATED", "REAL_TIME"}

FORMULA_READ_ROLES = ("FormulationChemist", "RegulatoryAffairs", "QAManager",
                      "ProductionPlanner", "PlantDirector", "CustomerRep")


def check_formula_confidentiality(formula):
    if g.user_role == "CustomerRep" and formula["customer_id"] != g.user_id:
        err("ERR_CONFIDENTIALITY_VIOLATION", 403,
            "CustomerRep may only access their own customer's formulas")


def validate_ingredients(value):
    if not isinstance(value, list):
        err("ERR_VALIDATION", 400, "ingredients must be an array")
    total = Decimal("0")
    for ing in value:
        if not isinstance(ing, dict):
            err("ERR_VALIDATION", 400, "Each ingredient must be an object")
        check_string(get_required(ing, "inci_name"), "ingredients[].inci_name")
        pct = check_number(get_required(ing, "percentage"), "ingredients[].percentage")
        total += D(pct)
        cid = ing.get("component_id")
        if cid is not None:
            must_get(db.components, cid, "Component")
    if abs(total - Decimal("100")) > Decimal("0.01"):
        err("ERR_VALIDATION", 400,
            "Ingredient percentages must sum to 100 within +/-0.01")
    return value


def validate_required_components(value):
    if not isinstance(value, list):
        err("ERR_VALIDATION", 400, "required_components must be an array")
    for entry in value:
        if not isinstance(entry, dict):
            err("ERR_VALIDATION", 400, "Each required component must be an object")
        must_get(db.components, get_required(entry, "component_id"), "Component")
        check_number(get_required(entry, "units_per_product"),
                     "required_components[].units_per_product", minimum=0,
                     exclusive_min=True)
    return value


def validate_formula_fields(b, base=None):
    """Validate formula payload fields. When base is given (revision), fields
    absent from the payload are inherited from the parent."""
    out = {}

    def pick(field):
        if field in b and b[field] is not None:
            return b[field]
        if base is not None:
            return base[field]
        return get_required(b, field)

    out["name"] = check_string(pick("name"), "name")
    if base is None:
        out["ownership"] = check_enum(pick("ownership"), OWNERSHIPS, "ownership")
        out["confidentiality"] = check_enum(pick("confidentiality"), CONFIDENTIALITIES,
                                            "confidentiality")
        out["bulk_mass_per_unit_kg"] = check_number(
            pick("bulk_mass_per_unit_kg"), "bulk_mass_per_unit_kg",
            minimum=0, exclusive_min=True)
    else:
        out["ownership"] = base["ownership"]
        out["confidentiality"] = base["confidentiality"]
        out["bulk_mass_per_unit_kg"] = base["bulk_mass_per_unit_kg"]
    out["product_class"] = check_enum(pick("product_class"), PRODUCT_CLASSES,
                                      "product_class")
    out["allergen_flag"] = check_bool(pick("allergen_flag"), "allergen_flag")
    out["viscosity_target_cps"] = check_int(pick("viscosity_target_cps"),
                                            "viscosity_target_cps", minimum=1)
    out["viscosity_tolerance_pct"] = check_number(
        pick("viscosity_tolerance_pct"), "viscosity_tolerance_pct",
        minimum=0, maximum=50, exclusive_min=True)
    out["ph_target"] = check_number(pick("ph_target"), "ph_target",
                                    minimum=0, maximum=14)
    out["ph_tolerance"] = check_number(pick("ph_tolerance"), "ph_tolerance",
                                       minimum=0, exclusive_min=True)
    if "ingredients" in b and b["ingredients"] is not None:
        out["ingredients"] = validate_ingredients(b["ingredients"])
    elif base is not None:
        out["ingredients"] = base["ingredients"]
    else:
        out["ingredients"] = validate_ingredients(get_required(b, "ingredients"))
    if "required_components" in b and b["required_components"] is not None:
        out["required_components"] = validate_required_components(b["required_components"])
    elif base is not None:
        out["required_components"] = base["required_components"]
    else:
        out["required_components"] = []
    return out


@bp.post("/cosmfg/formulas")
@require_roles("FormulationChemist")
def create_formula():
    b = body()
    customer_id = get_required(b, "customer_id")
    must_get(db.customers, customer_id, "Customer")
    base_id = b.get("base_formula_id")
    base = None
    if base_id is not None:
        base = must_get(db.formulas, base_id, "Formula")
        # Confidentiality: base must be a non-EXCLUSIVE formula of the same
        # customer, or any MANUFACTURER_OWNED STANDARD formula (PRD 2.10/3.2).
        same_customer_ok = (base["customer_id"] == customer_id
                            and base["confidentiality"] != "EXCLUSIVE")
        mfr_ok = (base["ownership"] == "MANUFACTURER_OWNED"
                  and base["confidentiality"] == "STANDARD")
        if not (same_customer_ok or mfr_ok):
            err("ERR_CONFIDENTIALITY_VIOLATION", 403,
                "base_formula_id may not reference another customer's EXCLUSIVE formula")
    fields = validate_formula_fields(b)
    f = new_entity()
    f.update({
        "customer_id": customer_id,
        "base_formula_id": base_id,
        "version_seq": 1,  # derivation is not a revision (PRD 3.2)
        "status": "DRAFT",
    })
    f.update(fields)
    db.formulas[f["id"]] = f
    return success(serialize_formula(f), status=201)


@bp.get("/cosmfg/formulas/<fid>")
@require_roles(*FORMULA_READ_ROLES)
def get_formula(fid):
    f = must_get(db.formulas, fid, "Formula")
    check_formula_confidentiality(f)
    return success(serialize_formula(f))


@bp.get("/cosmfg/formulas")
@require_roles(*FORMULA_READ_ROLES)
def list_formulas():
    items = list(db.formulas.values())
    if g.user_role == "CustomerRep":
        items = [f for f in items if f["customer_id"] == g.user_id]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [f for f in items if f["customer_id"] == customer_id]
    base_formula_id = request.args.get("base_formula_id")
    if base_formula_id is not None:
        items = [f for f in items if f["base_formula_id"] == base_formula_id]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return list_page(items, serialize_formula)


@bp.post("/cosmfg/formulas/<fid>/submit")
@require_roles("FormulationChemist")
def submit_formula(fid):
    f = must_get(db.formulas, fid, "Formula")
    if f["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        err("ERR_INVALID_STATE", 409,
            "Only a DRAFT or CHANGES_REQUESTED formula may be submitted")
    f["status"] = "IN_REVIEW"
    touch(f)
    return success(serialize_formula(f))


@bp.post("/cosmfg/formulas/<fid>/activate")
@require_roles("FormulationChemist")
def activate_formula(fid):
    f = must_get(db.formulas, fid, "Formula")
    if f["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Only an APPROVED formula may be activated")
    latest_inci = latest_review(f["id"], "INCI_LIST")
    if latest_inci is None or latest_inci["status"] != "APPROVED":
        err("ERR_INCI_REVIEW_NOT_APPROVED", 409,
            "Latest INCI_LIST review is not APPROVED")
    f["status"] = "ACTIVE"
    touch(f)
    return success(serialize_formula(f))


@bp.post("/cosmfg/formulas/<fid>/retire")
@require_roles("PlantDirector")
def retire_formula(fid):
    f = must_get(db.formulas, fid, "Formula")
    if f["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE formula may be retired")
    f["status"] = "RETIRED"
    touch(f)
    for o in db.orders.values():
        if o["formula_id"] == f["id"] and o["status"] == "DRAFT":
            cancel_order_cascade(o)
    return success(serialize_formula(f))


@bp.post("/cosmfg/formulas/<fid>/revisions")
@require_roles("FormulationChemist")
def create_revision(fid):
    parent = must_get(db.formulas, fid, "Formula")
    b = body()
    expected = get_required(b, "expected_formula_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        err("ERR_VALIDATION", 400, "expected_formula_version must be an integer")
    # OCC (priority 6) precedes the state check (priority 7)
    if expected != parent["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_formula_version does not match the formula's current version")
    if parent["status"] not in ("CHANGES_REQUESTED", "APPROVED", "ACTIVE"):
        err("ERR_INVALID_STATE", 409,
            "Revisions require the parent in CHANGES_REQUESTED, APPROVED, or ACTIVE")
    fields = validate_formula_fields(b, base=parent)
    child = new_entity()
    child.update({
        "customer_id": parent["customer_id"],
        "base_formula_id": parent["id"],
        "version_seq": parent["version_seq"] + 1,
        "status": "DRAFT",
    })
    child.update(fields)
    db.formulas[child["id"]] = child
    touch(parent)  # creating a revision increments the parent's version by 1
    return success(serialize_formula(child), status=201)


@bp.get("/cosmfg/formulas/<fid>/reviews")
@require_roles("RegulatoryAffairs", "FormulationChemist", "PlantDirector")
def list_formula_reviews(fid):
    f = must_get(db.formulas, fid, "Formula")
    items = [r for r in db.reviews.values() if r["formula_id"] == f["id"]]
    scope = request.args.get("review_scope")
    if scope is not None:
        items = [r for r in items if r["review_scope"] == scope]
    return list_page(items, serialize_review)


@bp.post("/cosmfg/formulas/<fid>/reviews")
@require_roles("FormulationChemist")
def create_review(fid):
    f = must_get(db.formulas, fid, "Formula")
    b = body()
    scope = check_enum(get_required(b, "review_scope"), REVIEW_SCOPES, "review_scope")
    if f["status"] not in ("IN_REVIEW", "ACTIVE"):
        err("ERR_INVALID_STATE", 409,
            "Reviews may only be opened for a formula in IN_REVIEW or ACTIVE")
    for r in db.reviews.values():
        if (r["formula_id"] == f["id"] and r["review_scope"] == scope
                and r["status"] in ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED")):
            err("ERR_REVIEW_ALREADY_OPEN", 409,
                "An open review of the same scope already exists for the formula")
    r = new_entity()
    r.update({
        "formula_id": f["id"],
        "review_scope": scope,
        "status": "SUBMITTED",
        "reviewer_user_id": None,
        "comment": None,
    })
    db.reviews[r["id"]] = r
    return success(serialize_review(r), status=201)


@bp.get("/cosmfg/formulas/<fid>/stability-studies")
@require_roles("QAManager", "PlantDirector")
def list_formula_studies(fid):
    f = must_get(db.formulas, fid, "Formula")
    items = [s for s in db.studies.values() if s["formula_id"] == f["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_page(items, serialize_study)


@bp.post("/cosmfg/formulas/<fid>/stability-studies")
@require_roles("QAManager")
def create_study(fid):
    f = must_get(db.formulas, fid, "Formula")
    b = body()
    chamber_id = get_required(b, "chamber_id")
    chamber = must_get(db.chambers, chamber_id, "StabilityChamber")
    if f["status"] not in ("APPROVED", "ACTIVE"):
        err("ERR_INVALID_STATE", 409,
            "Stability studies require an APPROVED or ACTIVE formula")
    if chamber["active_study_count"] >= chamber["capacity_studies"]:
        err("ERR_CHAMBER_CAPACITY_EXCEEDED", 409,
            "Chamber already holds capacity_studies IN_PROGRESS studies")
    study_type = check_enum(get_required(b, "study_type"), STUDY_TYPES, "study_type")
    s = new_entity()
    s.update({
        "formula_id": f["id"],
        "chamber_id": chamber["id"],
        "study_type": study_type,
        "required_intervals": list(REQUIRED_INTERVALS[study_type]),
        "recorded_interval_count": 0,
        "status": "IN_PROGRESS",
    })
    db.studies[s["id"]] = s
    chamber["active_study_count"] += 1
    touch(chamber)
    return success(serialize_study(s), status=201)
