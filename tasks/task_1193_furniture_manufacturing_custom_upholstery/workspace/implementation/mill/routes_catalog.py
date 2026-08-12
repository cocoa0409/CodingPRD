"""Routes: product models, fabric specs, dealer accounts."""
from flask import Blueprint

from mill.common import (
    ALL_ROLES,
    ApiError,
    endpoint,
    get_body,
    list_response,
    new_rec,
    ok,
    opt_bool,
    opt_enum,
    opt_int,
    opt_num,
    pub,
    req_enum,
    req_field,
    req_int,
    req_pos_num,
    touch,
)
from mill.store import store

bp = Blueprint("catalog", __name__)

MODEL_CATEGORIES = ["SOFA", "CHAIR", "SECTIONAL", "OTTOMAN"]
FLAM_STANDARDS = ["TB117_2013", "UFAC", "TB133"]
SPEC_ORIGINS = ["PLANT", "CUSTOMER"]
SPEC_GRADES = ["A", "B", "C", "D", "COM"]
MATCH_METHODS = ["NONE", "STRAIGHT", "DROP_HALF"]

WRITE_PLANNER = ["ProductionPlanner"]
WRITE_SALES = ["SalesRep"]


# ---------------------------------------------------------------------------
# ProductModel
# ---------------------------------------------------------------------------


@bp.post("/mill/product-models")
@endpoint(WRITE_PLANNER)
def create_product_model():
    b = get_body()
    model_code = req_field(b, "model_code")
    category = req_enum(b, "category", MODEL_CATEGORIES)
    base_fabric_yards = req_pos_num(b, "base_fabric_yards")
    base_price_cents = req_int(b, "base_price_cents", minimum=0)
    requires_pattern_match = opt_bool(b, "requires_pattern_match", False)
    flammability_standard = req_enum(b, "flammability_standard", FLAM_STANDARDS)
    required_component_codes = b.get("required_component_codes") or []
    if not isinstance(required_component_codes, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "required_component_codes must be an array")
    option_rules = b.get("option_rules") or []
    if not isinstance(option_rules, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "option_rules must be an array")
    if any(m["model_code"] == model_code for m in store.product_models.values()):
        raise ApiError("ERR_DUPLICATE_NATURAL_KEY", 409, f"model_code {model_code} already exists")
    rec = new_rec()
    rec.update(
        {
            "model_code": model_code,
            "category": category,
            "base_fabric_yards": base_fabric_yards,
            "base_price_cents": base_price_cents,
            "requires_pattern_match": requires_pattern_match,
            "flammability_standard": flammability_standard,
            "required_component_codes": required_component_codes,
            "option_rules": option_rules,
            "status": "ACTIVE",
        }
    )
    store.product_models[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/product-models")
@endpoint(ALL_ROLES)
def list_product_models():
    return list_response(list(store.product_models.values()))


@bp.get("/mill/product-models/<mid>")
@endpoint(ALL_ROLES)
def get_product_model(mid):
    rec = store.product_models.get(mid)
    if not rec:
        raise ApiError("ERR_PRODUCT_MODEL_NOT_FOUND", 404, "ProductModel not found")
    return ok(pub(rec))


@bp.post("/mill/product-models/<mid>/discontinue")
@endpoint(WRITE_PLANNER)
def discontinue_product_model(mid):
    rec = store.product_models.get(mid)
    if not rec:
        raise ApiError("ERR_PRODUCT_MODEL_NOT_FOUND", 404, "ProductModel not found")
    rec["status"] = "DISCONTINUED"
    touch(rec)
    return ok(pub(rec))


# ---------------------------------------------------------------------------
# FabricSpec
# ---------------------------------------------------------------------------


@bp.post("/mill/fabric-specs")
@endpoint(WRITE_PLANNER)
def create_fabric_spec():
    b = get_body()
    fabric_code = req_field(b, "fabric_code")
    origin = req_enum(b, "origin", SPEC_ORIGINS)
    grade = req_enum(b, "grade", SPEC_GRADES)
    nominal_width_inches = req_pos_num(b, "nominal_width_inches")
    pattern_repeat_v_inches = opt_num(b, "pattern_repeat_v_inches", 0)
    pattern_repeat_h_inches = opt_num(b, "pattern_repeat_h_inches", 0)
    match_method = opt_enum(b, "match_method", MATCH_METHODS, "NONE")
    price_per_yard_cents = opt_int(b, "price_per_yard_cents", 0, minimum=0)
    com_credit_per_yard_cents = opt_int(b, "com_credit_per_yard_cents", 0, minimum=0)
    if any(s["fabric_code"] == fabric_code for s in store.fabric_specs.values()):
        raise ApiError("ERR_DUPLICATE_NATURAL_KEY", 409, f"fabric_code {fabric_code} already exists")
    rec = new_rec()
    rec.update(
        {
            "fabric_code": fabric_code,
            "origin": origin,
            "grade": grade,
            "nominal_width_inches": nominal_width_inches,
            "pattern_repeat_v_inches": pattern_repeat_v_inches,
            "pattern_repeat_h_inches": pattern_repeat_h_inches,
            "match_method": match_method,
            "price_per_yard_cents": price_per_yard_cents,
            "com_credit_per_yard_cents": com_credit_per_yard_cents,
        }
    )
    store.fabric_specs[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/fabric-specs")
@endpoint(ALL_ROLES)
def list_fabric_specs():
    return list_response(list(store.fabric_specs.values()))


@bp.get("/mill/fabric-specs/<sid>")
@endpoint(ALL_ROLES)
def get_fabric_spec(sid):
    rec = store.fabric_specs.get(sid)
    if not rec:
        raise ApiError("ERR_FABRIC_SPEC_NOT_FOUND", 404, "FabricSpec not found")
    return ok(pub(rec))


# ---------------------------------------------------------------------------
# DealerAccount
# ---------------------------------------------------------------------------


@bp.post("/mill/dealer-accounts")
@endpoint(WRITE_SALES)
def create_dealer():
    b = get_body()
    dealer_code = req_field(b, "dealer_code")
    name = req_field(b, "name")
    credit_limit_cents = req_int(b, "credit_limit_cents", minimum=0)
    sample_allowance_cents = req_int(b, "sample_allowance_cents", minimum=0)
    if any(d["dealer_code"] == dealer_code for d in store.dealers.values()):
        raise ApiError("ERR_DUPLICATE_NATURAL_KEY", 409, f"dealer_code {dealer_code} already exists")
    rec = new_rec()
    rec.update(
        {
            "dealer_code": dealer_code,
            "name": name,
            "credit_limit_cents": credit_limit_cents,
            "sample_allowance_cents": sample_allowance_cents,
            "outstanding_sample_value_cents": 0,
            "status": "ACTIVE",
        }
    )
    store.dealers[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/dealer-accounts")
@endpoint(ALL_ROLES)
def list_dealers():
    return list_response(list(store.dealers.values()))


@bp.get("/mill/dealer-accounts/<did>")
@endpoint(ALL_ROLES)
def get_dealer(did):
    rec = store.dealers.get(did)
    if not rec:
        raise ApiError("ERR_DEALER_NOT_FOUND", 404, "DealerAccount not found")
    return ok(pub(rec))


@bp.post("/mill/dealer-accounts/<did>/set-status")
@endpoint(WRITE_SALES)
def set_dealer_status(did):
    b = get_body()
    status = req_enum(b, "status", ["ACTIVE", "SUSPENDED"])
    rec = store.dealers.get(did)
    if not rec:
        raise ApiError("ERR_DEALER_NOT_FOUND", 404, "DealerAccount not found")
    rec["status"] = status
    touch(rec)
    return ok(pub(rec))
