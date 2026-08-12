"""Catalog governance: jurisdictions, VOC rules, products, tint formulas,
and discontinuation bulletins."""
from flask import Blueprint, request

import db
import services as svc
from authz import require_roles
from envelope import ok_object, ok_list
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_VALIDATION,
    ERR_INVALID_STATE, ERR_SKU_EXISTS, ERR_JURISDICTION_CODE_EXISTS,
    ERR_VOC_RULE_OVERLAP, ERR_BULLETIN_NOT_YET_EFFECTIVE, ERR_BULLETIN_REPLACEMENT_INVALID,
)
from serializers import (
    ser_jurisdiction, ser_voc_rule, ser_product, ser_formula, ser_bulletin, sorted_rows,
)
from validate import (
    body_json, req_str, req_int, req_bool, req_enum, req_dt, opt_dt, opt_str, opt_int,
    opt_bool, valid_shots, pagination_params, query_enum_filter,
)

bp = Blueprint("catalog", __name__)

ADMIN = ["CorporateAdmin"]
ALL_READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "SpecWriter", "Contractor"]
CATEGORIES = {"FLAT", "NON_FLAT", "INDUSTRIAL_MAINTENANCE"}
PRODUCT_STATUS = {"ACTIVE", "DISCONTINUED"}
FORMULA_STATUS = {"ACTIVE", "RETIRED"}
BULLETIN_STATUS = {"DRAFT", "PUBLISHED", "EFFECTIVE"}


# --- jurisdictions ---------------------------------------------------------------
@bp.post("/jurisdictions")
def create_jurisdiction():
    require_roles(ADMIN)
    data = body_json()
    code = req_str(data, "code")
    name = req_str(data, "name")
    for j in db.jurisdictions.values():
        if j["code"] == code:
            raise_err(ERR_JURISDICTION_CODE_EXISTS, "jurisdiction code %s already exists" % code)
    j = svc.stamp_new({"code": code, "name": name})
    db.jurisdictions[j["id"]] = j
    return ok_object(ser_jurisdiction(j), 201)


# --- VOC rules ---------------------------------------------------------------------
@bp.post("/voc-rules")
def create_voc_rule():
    require_roles(ADMIN)
    data = body_json()
    jurisdiction_id = data.get("jurisdiction_id")
    if isinstance(jurisdiction_id, str) and jurisdiction_id not in db.jurisdictions:
        raise_err(ERR_REFERENCE_NOT_FOUND, "jurisdiction_id %s not found" % jurisdiction_id)
    jurisdiction_id = req_str(data, "jurisdiction_id")
    category = req_enum(data, "category", CATEGORIES)
    max_voc = req_int(data, "max_voc_gpl", minimum=1)
    effective_from = req_dt(data, "effective_from")
    effective_to = opt_dt(data, "effective_to")
    # Half-open window overlap for the same (jurisdiction, category); adjacency allowed.
    for r in db.voc_rules.values():
        if r["jurisdiction_id"] != jurisdiction_id or r["category"] != category:
            continue
        ex_from, ex_to = r["effective_from"], r["effective_to"]
        new_before_ex = effective_to is not None and effective_to <= ex_from
        new_after_ex = ex_to is not None and effective_from >= ex_to
        if not (new_before_ex or new_after_ex):
            raise_err(ERR_VOC_RULE_OVERLAP,
                      "VOC rule window overlaps an existing rule for this jurisdiction/category")
    rule = svc.stamp_new({
        "jurisdiction_id": jurisdiction_id,
        "category": category,
        "max_voc_gpl": max_voc,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    db.voc_rules[rule["id"]] = rule
    return ok_object(ser_voc_rule(rule), 201)


@bp.get("/voc-rules")
def list_voc_rules():
    require_roles(ALL_READERS)
    limit, offset = pagination_params()
    jurisdiction_filter = request.args.get("jurisdiction_id")
    category_filter = query_enum_filter("category", CATEGORIES)
    rows = list(db.voc_rules.values())
    if jurisdiction_filter is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_filter]
    if category_filter is not None:
        rows = [r for r in rows if r["category"] == category_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_voc_rule(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/voc-rules/<rule_id>")
def get_voc_rule(rule_id):
    require_roles(ALL_READERS)
    r = db.voc_rules.get(rule_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "VOC rule %s not found" % rule_id)
    return ok_object(ser_voc_rule(r))


# --- products -------------------------------------------------------------------------
@bp.post("/products")
def create_product():
    require_roles(ADMIN)
    data = body_json()
    sku = req_str(data, "sku")
    name = req_str(data, "name")
    category = req_enum(data, "category", CATEGORIES)
    voc_gpl = req_int(data, "voc_gpl", minimum=1)
    list_price = req_int(data, "list_price_cents", minimum=0)
    tintable = req_bool(data, "tintable")
    for p in db.products.values():
        if p["sku"] == sku:
            raise_err(ERR_SKU_EXISTS, "product sku %s already exists" % sku)
    p = svc.stamp_new({
        "sku": sku, "name": name, "category": category, "voc_gpl": voc_gpl,
        "list_price_cents": list_price, "tintable": tintable,
        "status": "ACTIVE", "replacement_product_id": None,
    })
    db.products[p["id"]] = p
    return ok_object(ser_product(p), 201)


@bp.get("/products/<product_id>")
def get_product(product_id):
    require_roles(ALL_READERS)
    p = db.products.get(product_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "product %s not found" % product_id)
    return ok_object(ser_product(p))


@bp.get("/products")
def list_products():
    require_roles(ALL_READERS)
    limit, offset = pagination_params()
    status_filter = query_enum_filter("status", PRODUCT_STATUS)
    category_filter = query_enum_filter("category", CATEGORIES)
    replacement_filter = request.args.get("replacement_product_id")
    rows = list(db.products.values())
    if status_filter is not None:
        rows = [p for p in rows if p["status"] == status_filter]
    if category_filter is not None:
        rows = [p for p in rows if p["category"] == category_filter]
    if replacement_filter is not None:
        rows = [p for p in rows if p["replacement_product_id"] == replacement_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_product(p) for p in rows[offset:offset + limit]], total, limit, offset)


@bp.patch("/products/<product_id>")
def patch_product(product_id):
    require_roles(ADMIN)
    p = db.products.get(product_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "product %s not found" % product_id)
    data = body_json()
    name = opt_str(data, "name")
    list_price = opt_int(data, "list_price_cents", minimum=0)
    voc_gpl = opt_int(data, "voc_gpl", minimum=1)
    tintable = opt_bool(data, "tintable")
    if name is not None:
        p["name"] = name
    if list_price is not None:
        p["list_price_cents"] = list_price
    if voc_gpl is not None:
        p["voc_gpl"] = voc_gpl
    if tintable is not None:
        p["tintable"] = tintable
    svc.bump(p)
    return ok_object(ser_product(p))


# --- tint formulas ----------------------------------------------------------------------
@bp.post("/tint-formulas")
def create_tint_formula():
    require_roles(["StoreAssociate", "CorporateAdmin"])
    data = body_json()
    product_id = data.get("product_id")
    if isinstance(product_id, str) and product_id not in db.products:
        raise_err(ERR_REFERENCE_NOT_FOUND, "product_id %s not found" % product_id)
    product_id = req_str(data, "product_id")
    color_code = req_str(data, "color_code")
    name = req_str(data, "name")
    shots = valid_shots(data)
    formula = svc.create_formula(product_id, color_code, name, shots, "LIBRARY")
    return ok_object(ser_formula(formula), 201)


@bp.get("/tint-formulas")
def list_tint_formulas():
    require_roles(ALL_READERS)
    limit, offset = pagination_params()
    product_filter = request.args.get("product_id")
    status_filter = query_enum_filter("status", FORMULA_STATUS)
    color_filter = request.args.get("color_code")
    supersedes_filter = request.args.get("supersedes_formula_id")
    rows = list(db.tint_formulas.values())
    if product_filter is not None:
        rows = [f for f in rows if f["product_id"] == product_filter]
    if status_filter is not None:
        rows = [f for f in rows if f["status"] == status_filter]
    if color_filter is not None:
        rows = [f for f in rows if f["color_code"] == color_filter]
    if supersedes_filter is not None:
        rows = [f for f in rows if f["supersedes_formula_id"] == supersedes_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_formula(f) for f in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/tint-formulas/<formula_id>")
def get_tint_formula(formula_id):
    require_roles(ALL_READERS)
    f = db.tint_formulas.get(formula_id)
    if f is None:
        raise_err(ERR_NOT_FOUND, "tint formula %s not found" % formula_id)
    return ok_object(ser_formula(f))


@bp.post("/tint-formulas/<formula_id>/retire")
def retire_tint_formula(formula_id):
    require_roles(ADMIN)
    f = db.tint_formulas.get(formula_id)
    if f is None:
        raise_err(ERR_NOT_FOUND, "tint formula %s not found" % formula_id)
    if f["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "formula is not ACTIVE")
    f["status"] = "RETIRED"
    svc.bump(f)
    return ok_object(ser_formula(f))


# --- product bulletins ---------------------------------------------------------------------
@bp.post("/product-bulletins")
def create_bulletin():
    require_roles(ADMIN)
    data = body_json()
    product_id = data.get("product_id")
    replacement_id = data.get("replacement_product_id")
    if isinstance(product_id, str) and product_id not in db.products:
        raise_err(ERR_REFERENCE_NOT_FOUND, "product_id %s not found" % product_id)
    if isinstance(replacement_id, str) and replacement_id not in db.products:
        raise_err(ERR_REFERENCE_NOT_FOUND, "replacement_product_id %s not found" % replacement_id)
    product_id = req_str(data, "product_id")
    replacement_id = req_str(data, "replacement_product_id")
    title = req_str(data, "title")
    effective_date = req_dt(data, "effective_date")
    b = svc.stamp_new({
        "product_id": product_id,
        "replacement_product_id": replacement_id,
        "title": title,
        "effective_date": effective_date,
        "status": "DRAFT",
        "published_at": None,
        "effected_at": None,
    })
    db.product_bulletins[b["id"]] = b
    return ok_object(ser_bulletin(b), 201)


@bp.get("/product-bulletins")
def list_bulletins():
    require_roles(ALL_READERS)
    limit, offset = pagination_params()
    product_filter = request.args.get("product_id")
    replacement_filter = request.args.get("replacement_product_id")
    status_filter = query_enum_filter("status", BULLETIN_STATUS)
    rows = list(db.product_bulletins.values())
    if product_filter is not None:
        rows = [b for b in rows if b["product_id"] == product_filter]
    if replacement_filter is not None:
        rows = [b for b in rows if b["replacement_product_id"] == replacement_filter]
    if status_filter is not None:
        rows = [b for b in rows if b["status"] == status_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_bulletin(b) for b in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/product-bulletins/<bulletin_id>")
def get_bulletin(bulletin_id):
    require_roles(ALL_READERS)
    b = db.product_bulletins.get(bulletin_id)
    if b is None:
        raise_err(ERR_NOT_FOUND, "product bulletin %s not found" % bulletin_id)
    return ok_object(ser_bulletin(b))


@bp.post("/product-bulletins/<bulletin_id>/publish")
def publish_bulletin(bulletin_id):
    require_roles(ADMIN)
    b = db.product_bulletins.get(bulletin_id)
    if b is None:
        raise_err(ERR_NOT_FOUND, "product bulletin %s not found" % bulletin_id)
    if b["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "bulletin is not DRAFT")
    replacement_id = b["replacement_product_id"]
    replacement = db.products.get(replacement_id) if isinstance(replacement_id, str) else None
    subject = db.products.get(b["product_id"])
    if (
        replacement_id is None
        or replacement_id == b["product_id"]
        or replacement is None
        or replacement["status"] != "ACTIVE"
        or subject is None
        or replacement["category"] != subject["category"]
    ):
        raise_err(ERR_BULLETIN_REPLACEMENT_INVALID,
                  "replacement must be an existing ACTIVE product of the same category, "
                  "different from the subject product")
    b["status"] = "PUBLISHED"
    b["published_at"] = db.now()
    svc.bump(b)
    return ok_object(ser_bulletin(b))


@bp.post("/product-bulletins/<bulletin_id>/take-effect")
def take_effect_bulletin(bulletin_id):
    require_roles(ADMIN)
    b = db.product_bulletins.get(bulletin_id)
    if b is None:
        raise_err(ERR_NOT_FOUND, "product bulletin %s not found" % bulletin_id)
    if b["status"] != "PUBLISHED":
        raise_err(ERR_INVALID_STATE, "bulletin is not PUBLISHED")
    if db.now() < b["effective_date"]:
        raise_err(ERR_BULLETIN_NOT_YET_EFFECTIVE,
                  "the logical clock has not reached the bulletin's effective_date")
    svc.bulletin_take_effect(b)
    return ok_object(ser_bulletin(b))
