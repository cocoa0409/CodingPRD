"""Formula, ProcessValidation, ProductionBatch, and LabelSubmission endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, now, new_id
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_INVALID_RANGE, ERR_DUPLICATE_CODE, ERR_STALE_VERSION,
                    ERR_PROFILE_NOT_APPROVED, ERR_PERCENTAGE_SUM_INVALID,
                    ERR_SEGREGATION_OF_DUTIES, ERR_VALIDATION_REQUIRED,
                    ERR_FORMULA_NOT_ACTIVE, ERR_LABEL_NOT_APPROVED,
                    ERR_ACTIVE_BATCHES_EXIST, ERR_LOT_NOT_QC_PASSED,
                    ERR_SUPPLIER_NOT_QUALIFIED, ERR_LOT_EXPIRED,
                    ERR_INSUFFICIENT_INGREDIENT_QUANTITY,
                    ERR_INCOMPLETE_TEST_RESULTS, ERR_BATCH_TESTS_FAILED)
from middleware import authorized
from response import ok, paginate
from services import (ser_formula, ser_validation, ser_batch, ser_label,
                      get_or_404, stamp_new, touch, refresh_validation,
                      evaluate_nutrient_results, batch_shelf_life_months,
                      PROCESS_TYPES, VALIDATION_TYPES, SUBMISSION_TYPES)
from util import (get_body, require_fields, check_enum, parse_datetime,
                  to_decimal, add_months)

bp = Blueprint("formulas", __name__)

FORMULA_READ = ("REGULATORY_AFFAIRS", "QA_MANAGER", "QUALITY_ANALYST",
                "PRODUCTION_SUPERVISOR", "SUPPLY_CHAIN_PLANNER")
VALIDATION_READ = ("QA_MANAGER", "QUALITY_ANALYST", "PRODUCTION_SUPERVISOR")
BATCH_READ = ("QA_MANAGER", "QUALITY_ANALYST", "PRODUCTION_SUPERVISOR", "SUPPLY_CHAIN_PLANNER")
LABEL_ROLES = ("REGULATORY_AFFAIRS", "QA_MANAGER")

# validation_type matching a formula process_type
TYPE_FOR_PROCESS = {"DRY_BLEND": "DRY_BLEND_HOMOGENEITY",
                    "WET_PROCESS": "WET_PROCESS_THERMAL",
                    "COMBINATION": "COMBINATION_FULL"}


def _passed_validations(formula_id):
    out = []
    for v in store.validations.values():
        if v["formula_id"] == formula_id:
            refresh_validation(v)
            if v["status"] == "PASSED":
                out.append(v)
    return out


def _approve_validation_satisfied(formula):
    passed = _passed_validations(formula["id"])
    types = {v["validation_type"] for v in passed}
    pt = formula["process_type"]
    if pt == "COMBINATION":
        return "COMBINATION_FULL" in types or \
            ("DRY_BLEND_HOMOGENEITY" in types and "WET_PROCESS_THERMAL" in types)
    return TYPE_FOR_PROCESS[pt] in types


def _activation_validation_satisfied(formula_id):
    ts = now()
    for v in _passed_validations(formula_id):
        if v.get("valid_until") is not None and v["valid_until"] > ts:
            return True
    return False


def _start_production_validation_satisfied(formula):
    ts = now()
    needed = []
    if formula["process_type"] in ("DRY_BLEND", "COMBINATION"):
        needed.append("DRY_BLEND_HOMOGENEITY")
    if formula["process_type"] in ("WET_PROCESS", "COMBINATION"):
        needed.append("WET_PROCESS_THERMAL")
    passed = _passed_validations(formula["id"])
    for vtype in needed:
        ok_found = any(v["validation_type"] == vtype and v.get("valid_until") is not None
                       and v["valid_until"] > ts for v in passed)
        if not ok_found:
            return False
    return True


# ------------------------------------------------------------------ formulas
@bp.post("/formulas")
@authorized("REGULATORY_AFFAIRS")
def create_formula(_user_id=None, _role=None):
    body = get_body()
    code = body.get("formula_code")
    if isinstance(code, str) and code:
        if any(f["formula_code"] == code for f in store.formulas.values()):
            raise err(ERR_DUPLICATE_CODE, "formula_code '%s' already exists" % code)
    profile = None
    if body.get("nutrient_profile_id") is not None:
        profile = get_or_404(store.profiles, body["nutrient_profile_id"], "NutrientProfile")
    require_fields(body, ["formula_code", "product_name", "nutrient_profile_id",
                          "ingredients", "process_type"])
    process_type = check_enum(body["process_type"], PROCESS_TYPES, "process_type")
    ingredients = body["ingredients"]
    if not isinstance(ingredients, list) or len(ingredients) < 2:
        raise err(ERR_INVALID_REQUEST, "ingredients must contain at least 2 entries")
    norm_ingredients = []
    for entry in ingredients:
        if not isinstance(entry, dict) or not entry.get("ingredient_id"):
            raise err(ERR_INVALID_REQUEST,
                      "Each ingredient entry requires an ingredient_id")
        if "percentage_by_weight" not in entry:
            raise err(ERR_INVALID_REQUEST,
                      "Each ingredient entry requires a percentage_by_weight")
        pct = to_decimal(entry["percentage_by_weight"], "percentage_by_weight")
        if pct <= 0:
            raise err(ERR_INVALID_RANGE, "percentage_by_weight must be greater than 0")
        is_critical = entry.get("is_critical", False)
        if not isinstance(is_critical, bool):
            raise err(ERR_INVALID_REQUEST, "is_critical must be a boolean")
        norm_ingredients.append({
            "ingredient_id": entry["ingredient_id"],
            "percentage_by_weight": float(pct),
            "is_critical": is_critical,
        })
    rec = stamp_new({
        "id": new_id(),
        "formula_code": body["formula_code"],
        "product_name": body["product_name"],
        "nutrient_profile_id": profile["id"],
        "ingredients": norm_ingredients,
        "process_type": process_type,
        "status": "DRAFT",
        "_submitted_by": None,
    })
    store.formulas[rec["id"]] = rec
    return ok(ser_formula(rec), 201)


@bp.get("/formulas")
@authorized(*FORMULA_READ)
def list_formulas(_user_id=None, _role=None):
    records = list(store.formulas.values())
    for param, field in (("status", "status"), ("process_type", "process_type"),
                         ("nutrient_profile_id", "nutrient_profile_id")):
        v = request.args.get(param)
        if v is not None:
            records = [f for f in records if f[field] == v]
    return paginate(records, ser_formula)


@bp.get("/formulas/<fid>")
@authorized(*FORMULA_READ)
def get_formula(fid, _user_id=None, _role=None):
    return ok(ser_formula(get_or_404(store.formulas, fid, "Formula")))


@bp.post("/formulas/<fid>/submit-for-review")
@authorized("REGULATORY_AFFAIRS")
def submit_formula(fid, _user_id=None, _role=None):
    rec = get_or_404(store.formulas, fid, "Formula")
    # FK existence: every referenced ingredient must exist
    for entry in rec["ingredients"]:
        if entry["ingredient_id"] not in store.ingredients:
            raise err(ERR_NOT_FOUND,
                      "Ingredient '%s' does not exist" % entry["ingredient_id"])
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  "Formula in status %s cannot be submitted for review" % rec["status"])
    total = sum(Decimal(str(e["percentage_by_weight"])) for e in rec["ingredients"])
    if abs(total - Decimal("100")) > Decimal("0.001"):
        raise err(ERR_PERCENTAGE_SUM_INVALID,
                  "Ingredient percentages must sum to 100.000 within 0.001")
    profile = store.profiles.get(rec["nutrient_profile_id"])
    if profile is None or profile["status"] != "APPROVED":
        raise err(ERR_PROFILE_NOT_APPROVED,
                  "Referenced NutrientProfile is not APPROVED")
    rec["status"] = "IN_REVIEW"
    rec["_submitted_by"] = _user_id
    touch(rec)
    return ok(ser_formula(rec))


@bp.post("/formulas/<fid>/approve")
@authorized("QA_MANAGER")
def approve_formula(fid, _user_id=None, _role=None):
    rec = get_or_404(store.formulas, fid, "Formula")
    if rec["status"] != "IN_REVIEW":
        raise err(ERR_INVALID_STATE,
                  "Formula in status %s cannot be approved" % rec["status"])
    if rec.get("_submitted_by") is not None and rec["_submitted_by"] == _user_id:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Approver must differ from the user who submitted the formula")
    if not _approve_validation_satisfied(rec):
        raise err(ERR_INVALID_STATE,
                  "Formula lacks a PASSED process validation matching its process_type")
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(ser_formula(rec))


@bp.post("/formulas/<fid>/return-for-revision")
@authorized("QA_MANAGER")
def return_formula(fid, _user_id=None, _role=None):
    rec = get_or_404(store.formulas, fid, "Formula")
    if rec["status"] != "IN_REVIEW":
        raise err(ERR_INVALID_STATE,
                  "Formula in status %s cannot be returned for revision" % rec["status"])
    rec["status"] = "DRAFT"
    touch(rec)
    return ok(ser_formula(rec))


@bp.post("/formulas/<fid>/activate")
@authorized("QA_MANAGER")
def activate_formula(fid, _user_id=None, _role=None):
    rec = get_or_404(store.formulas, fid, "Formula")
    if rec["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE,
                  "Formula in status %s cannot be activated" % rec["status"])
    if not any(l["formula_id"] == rec["id"] and l["status"] == "APPROVED"
               for l in store.labels.values()):
        raise err(ERR_LABEL_NOT_APPROVED,
                  "Formula has no APPROVED LabelSubmission")
    if not _activation_validation_satisfied(rec["id"]):
        raise err(ERR_VALIDATION_REQUIRED,
                  "Formula has no PASSED, non-expired ProcessValidation")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(ser_formula(rec))


@bp.post("/formulas/<fid>/discontinue")
@authorized("QA_MANAGER")
def discontinue_formula(fid, _user_id=None, _role=None):
    rec = get_or_404(store.formulas, fid, "Formula")
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE,
                  "Formula in status %s cannot be discontinued" % rec["status"])
    for b in store.batches.values():
        if b["formula_id"] == rec["id"] and b["status"] in (
                "IN_PRODUCTION", "TESTING", "POSITIVE_RELEASE_HOLD"):
            raise err(ERR_ACTIVE_BATCHES_EXIST,
                      "Formula has production batches in non-terminal states")
    rec["status"] = "DISCONTINUED"
    touch(rec)
    return ok(ser_formula(rec))


# ------------------------------------------------------------------ process validations
@bp.post("/process-validations")
@authorized("QA_MANAGER")
def create_validation(_user_id=None, _role=None):
    body = get_body()
    formula = None
    if body.get("formula_id") is not None:
        formula = get_or_404(store.formulas, body["formula_id"], "Formula")
    require_fields(body, ["formula_id", "validation_type", "protocol_version",
                          "validation_validity_days"])
    vtype = check_enum(body["validation_type"], VALIDATION_TYPES, "validation_type")
    days = body["validation_validity_days"]
    if isinstance(days, bool) or not isinstance(days, int) or days < 30 or days > 1095:
        raise err(ERR_INVALID_RANGE,
                  "validation_validity_days must be an integer between 30 and 1095")
    rec = stamp_new({
        "id": new_id(),
        "formula_id": formula["id"],
        "validation_type": vtype,
        "status": "PLANNED",
        "protocol_version": body["protocol_version"],
        "started_at": None,
        "completed_at": None,
        "test_results": None,
        "valid_until": None,
        "validation_validity_days": days,
    })
    store.validations[rec["id"]] = rec
    return ok(ser_validation(rec), 201)


@bp.get("/process-validations")
@authorized(*VALIDATION_READ)
def list_validations(_user_id=None, _role=None):
    records = list(store.validations.values())
    for param, field in (("formula_id", "formula_id"), ("status", "status"),
                         ("validation_type", "validation_type")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate(records, ser_validation)


@bp.get("/process-validations/<vid>")
@authorized(*VALIDATION_READ)
def get_validation(vid, _user_id=None, _role=None):
    return ok(ser_validation(get_or_404(store.validations, vid, "ProcessValidation")))


@bp.get("/formulas/<fid>/process-validations")
@authorized(*VALIDATION_READ)
def list_formula_validations(fid, _user_id=None, _role=None):
    get_or_404(store.formulas, fid, "Formula")
    records = [v for v in store.validations.values() if v["formula_id"] == fid]
    return paginate(records, ser_validation)


@bp.post("/process-validations/<vid>/start")
@authorized("PRODUCTION_SUPERVISOR")
def start_validation(vid, _user_id=None, _role=None):
    rec = get_or_404(store.validations, vid, "ProcessValidation")
    if rec["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE,
                  "ProcessValidation in status %s cannot be started" % rec["status"])
    rec["status"] = "IN_PROGRESS"
    rec["started_at"] = now()
    touch(rec)
    return ok(ser_validation(rec))


@bp.post("/process-validations/<vid>/complete")
@authorized("QUALITY_ANALYST")
def complete_validation(vid, _user_id=None, _role=None):
    rec = get_or_404(store.validations, vid, "ProcessValidation")
    if rec["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE,
                  "ProcessValidation in status %s cannot be completed" % rec["status"])
    body = get_body()
    require_fields(body, ["test_results"])
    results = body["test_results"]
    if not isinstance(results, list):
        raise err(ERR_INVALID_REQUEST, "test_results must be an array")
    if not all(isinstance(t, dict) and t.get("pass") is True for t in results):
        raise err(ERR_INVALID_STATE,
                  "All test_results entries must have pass == true to complete")
    rec["status"] = "PASSED"
    rec["test_results"] = results
    rec["completed_at"] = now()
    from datetime import timedelta as _td
    rec["valid_until"] = rec["completed_at"] + _td(days=rec["validation_validity_days"])
    touch(rec)
    return ok(ser_validation(rec))


@bp.post("/process-validations/<vid>/fail")
@authorized("QUALITY_ANALYST")
def fail_validation(vid, _user_id=None, _role=None):
    rec = get_or_404(store.validations, vid, "ProcessValidation")
    if rec["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE,
                  "ProcessValidation in status %s cannot be failed" % rec["status"])
    body = get_body()
    results = body.get("test_results")
    if isinstance(results, list) and len(results) > 0 and \
            not any(isinstance(t, dict) and t.get("pass") is False for t in results):
        raise err(ERR_INVALID_STATE,
                  "At least one test_results entry must have pass == false to fail")
    require_fields(body, ["test_results", "failure_summary"])
    rec["status"] = "FAILED"
    rec["test_results"] = results
    rec["completed_at"] = now()
    touch(rec)
    return ok(ser_validation(rec))
