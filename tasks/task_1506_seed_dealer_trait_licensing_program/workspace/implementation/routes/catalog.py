"""Catalog endpoints: TraitPackage, Variety, TreatmentOption."""

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_VARIETY_HAS_OPEN_ORDERS
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk

bp = make_blueprint("catalog")

ALL_ROLES = ["DealerAdmin", "SalesRep", "Agronomist", "Grower", "ClaimsAdjuster"]
SOILS = ["CLAY", "LOAM", "SAND", "SILT"]
DRAINAGES = ["POOR", "MODERATE", "WELL"]
CROPS = ["CORN", "SOYBEAN"]


def _check_unique(collection, field, value):
    for ent in db.all_of(collection):
        if ent.get(field) == value:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be unique")


# --- TraitPackage -----------------------------------------------------------

@bp.post("/trait-packages")
def create_trait_package():
    authenticate(["DealerAdmin"])
    body = body_json()
    check_shape(body, {
        "code": {"type": "string", "required": True},
        "description": {"type": "string", "required": True},
        "requires_stewardship_agreement": {"type": "boolean", "required": True},
        "refuge_required_bps": {"type": "integer", "required": True},
    })
    _check_unique("trait_packages", "code", body["code"])
    pkg = db.new_entity("trait_packages", {
        "code": body["code"],
        "description": body["description"],
        "requires_stewardship_agreement": body["requires_stewardship_agreement"],
        "refuge_required_bps": body["refuge_required_bps"],
        "status": "LISTED",
    })
    return success_obj(db.public(pkg), 201)


@bp.get("/trait-packages/<pid>")
def get_trait_package(pid):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_fk("trait_packages", pid, "trait package")), 200)


@bp.get("/trait-packages")
def list_trait_packages():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("trait_packages"), ["status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(p) for p in page], limit, offset, total, has_more)


@bp.post("/trait-packages/<pid>/retire")
def retire_trait_package(pid):
    authenticate(["DealerAdmin"])
    pkg = require_fk("trait_packages", pid, "trait package")
    if pkg["status"] != "LISTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a LISTED trait package can be retired")
    pkg["status"] = "RETIRED"
    db.touch(pkg)
    return success_obj(db.public(pkg), 200)


# --- Variety ----------------------------------------------------------------

@bp.post("/varieties")
def create_variety():
    authenticate(["DealerAdmin"])
    body = body_json()
    if body.get("trait_package_id") is not None:
        require_fk("trait_packages", body["trait_package_id"], "trait package")
    check_shape(body, {
        "sku": {"type": "string", "required": True},
        "crop": {"type": "enum", "required": True, "values": CROPS},
        "relative_maturity_days": {"type": "integer", "required": True, "min": 1},
        "trait_package_id": {"type": "string"},
        "base_price_cents_per_unit": {"type": "integer", "required": True, "min": 0},
        "seeds_per_unit": {"type": "integer", "required": True, "min": 1},
        "preferred_soils": {"type": "array", "required": True},
        "min_drainage": {"type": "enum", "required": True, "values": DRAINAGES},
    })
    for soil in body["preferred_soils"]:
        if soil not in SOILS:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"preferred_soils entries must be in {SOILS}")
    _check_unique("varieties", "sku", body["sku"])
    variety = db.new_entity("varieties", {
        "sku": body["sku"],
        "crop": body["crop"],
        "relative_maturity_days": body["relative_maturity_days"],
        "trait_package_id": body.get("trait_package_id"),
        "base_price_cents_per_unit": body["base_price_cents_per_unit"],
        "seeds_per_unit": body["seeds_per_unit"],
        "preferred_soils": body["preferred_soils"],
        "min_drainage": body["min_drainage"],
        "status": "LISTED",
    })
    return success_obj(db.public(variety), 201)


@bp.get("/varieties/<vid>")
def get_variety(vid):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_fk("varieties", vid, "variety")), 200)


@bp.get("/varieties")
def list_varieties():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("varieties"), ["trait_package_id", "status", "crop"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(v) for v in page], limit, offset, total, has_more)


@bp.post("/varieties/<vid>/delist")
def delist_variety(vid):
    authenticate(["DealerAdmin"])
    variety = require_fk("varieties", vid, "variety")
    if variety["status"] != "LISTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a LISTED variety can be delisted")
    open_statuses = ("DRAFT", "CONFIRMED", "COMPLIANCE_HOLD")
    for line in db.all_of("order_lines"):
        if line["variety_id"] != variety["id"]:
            continue
        order = db.get("orders", line["order_id"])
        if order and order["status"] in open_statuses:
            raise ApiError(ERR_VARIETY_HAS_OPEN_ORDERS, 409, "variety is referenced by open orders")
    variety["status"] = "DELISTED"
    db.touch(variety)
    return success_obj(db.public(variety), 200)


# --- TreatmentOption --------------------------------------------------------

@bp.post("/treatment-options")
def create_treatment_option():
    authenticate(["DealerAdmin"])
    body = body_json()
    check_shape(body, {
        "code": {"type": "string", "required": True},
        "crop": {"type": "enum", "required": True, "values": CROPS},
        "adder_cents_per_unit": {"type": "integer", "required": True, "min": 0},
    })
    _check_unique("treatment_options", "code", body["code"])
    topt = db.new_entity("treatment_options", {
        "code": body["code"],
        "crop": body["crop"],
        "adder_cents_per_unit": body["adder_cents_per_unit"],
        "status": "AVAILABLE",
    })
    return success_obj(db.public(topt), 201)


@bp.get("/treatment-options/<tid>")
def get_treatment_option(tid):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_fk("treatment_options", tid, "treatment option")), 200)


@bp.get("/treatment-options")
def list_treatment_options():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("treatment_options"), ["status", "crop"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(t) for t in page], limit, offset, total, has_more)


@bp.post("/treatment-options/<tid>/discontinue")
def discontinue_treatment_option(tid):
    authenticate(["DealerAdmin"])
    topt = require_fk("treatment_options", tid, "treatment option")
    if topt["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an AVAILABLE treatment option can be discontinued")
    topt["status"] = "DISCONTINUED"
    db.touch(topt)
    return success_obj(db.public(topt), 200)
