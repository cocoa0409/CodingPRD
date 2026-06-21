"""Config resources: TaxJurisdiction, ProductCategory, Seller,
MarketplaceFacilitator, and the test clock. PlatformAdmin-owned writes; reads
shared across roles.
"""
from decimal import Decimal

from flask import Blueprint

import db
from errors import APIError, ERR_DUPLICATE_RESOURCE, ERR_INVALID_REQUEST
from middleware import require
from response import object_response, array_response
from services import common, serializers

bp = Blueprint("config", __name__)

ALL_ROLES = ["PlatformAdmin", "Seller", "TaxPreparer", "TaxApprover", "Auditor"]


# ---------------------------------------------------------------------------
# TaxJurisdiction
# ---------------------------------------------------------------------------
@bp.post("/tax-jurisdictions")
@require("PlatformAdmin")
def create_jurisdiction():
    body = common.get_body()
    state_code = common.require_str(body, "state_code")
    common.require_state_code(state_code)
    sourcing_rule = common.require_enum(body, "sourcing_rule", {"ORIGIN", "DESTINATION"})
    state_rate = common.require_number(body, "state_rate", minimum=0, maximum=0.25)
    local_rate = common.require_number(body, "local_rate", allow_missing=True, default=0,
                                       minimum=0, maximum=0.10)
    reduced_rate = common.require_number(body, "reduced_rate", allow_missing=True, default=0,
                                         minimum=0, maximum=0.25)
    sales_threshold = common.require_number(body, "economic_nexus_sales_threshold",
                                            minimum=0, exclusive_min=True)
    txn_threshold = common.require_int(body, "economic_nexus_txn_threshold",
                                       allow_missing=True, default=0, minimum=0)

    # Uniqueness on state_code (priority 6).
    for j in db.tax_jurisdictions.values():
        if j["state_code"] == state_code:
            raise APIError(ERR_DUPLICATE_RESOURCE, "duplicate state_code")

    combined = float(Decimal(str(state_rate)) + Decimal(str(local_rate)))
    rec = {
        "state_code": state_code,
        "sourcing_rule": sourcing_rule,
        "state_rate": state_rate,
        "local_rate": local_rate,
        "reduced_rate": reduced_rate,
        "economic_nexus_sales_threshold": sales_threshold,
        "economic_nexus_txn_threshold": txn_threshold,
        "combined_rate": combined,
    }
    common.stamp_create(rec)
    db.tax_jurisdictions[rec["id"]] = rec
    return object_response(serializers.jurisdiction(rec), 201)


@bp.get("/tax-jurisdictions/<rec_id>")
@require(*ALL_ROLES)
def get_jurisdiction(rec_id):
    rec = common.get_or_404(db.tax_jurisdictions, rec_id, "tax jurisdiction")
    return object_response(serializers.jurisdiction(rec))


@bp.get("/tax-jurisdictions")
@require(*ALL_ROLES)
def list_jurisdictions():
    from flask import request
    records = list(db.tax_jurisdictions.values())
    sc = request.args.get("state_code")
    if sc is not None:
        records = [r for r in records if r["state_code"] == sc]
    items, limit, offset, total = common.paginate(records, serializers.jurisdiction)
    return array_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# ProductCategory
# ---------------------------------------------------------------------------
@bp.post("/product-categories")
@require("PlatformAdmin")
def create_category():
    body = common.get_body()
    jurisdiction_id = common.require_str(body, "jurisdiction_id")
    category_code = common.require_str(body, "category_code")
    taxability = common.require_enum(body, "taxability", {"FULL", "REDUCED", "EXEMPT"})

    common.resolve_fk(db.tax_jurisdictions, jurisdiction_id, "jurisdiction_id")

    for c in db.product_categories.values():
        if c["jurisdiction_id"] == jurisdiction_id and c["category_code"] == category_code:
            raise APIError(ERR_DUPLICATE_RESOURCE, "duplicate (jurisdiction_id, category_code)")

    rec = {
        "jurisdiction_id": jurisdiction_id,
        "category_code": category_code,
        "taxability": taxability,
    }
    common.stamp_create(rec)
    db.product_categories[rec["id"]] = rec
    return object_response(serializers.product_category(rec), 201)


@bp.get("/product-categories/<rec_id>")
@require(*ALL_ROLES)
def get_category(rec_id):
    rec = common.get_or_404(db.product_categories, rec_id, "product category")
    return object_response(serializers.product_category(rec))


@bp.get("/product-categories")
@require(*ALL_ROLES)
def list_categories():
    from flask import request
    records = list(db.product_categories.values())
    jid = request.args.get("jurisdiction_id")
    cc = request.args.get("category_code")
    if jid is not None:
        records = [r for r in records if r["jurisdiction_id"] == jid]
    if cc is not None:
        records = [r for r in records if r["category_code"] == cc]
    items, limit, offset, total = common.paginate(records, serializers.product_category)
    return array_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Seller
# ---------------------------------------------------------------------------
@bp.post("/sellers")
@require("PlatformAdmin")
def create_seller():
    body = common.get_body()
    legal_name = common.require_str(body, "legal_name")
    origin_state_code = common.require_str(body, "origin_state_code")
    common.require_state_code(origin_state_code, "origin_state_code")

    rec = {
        "legal_name": legal_name,
        "origin_state_code": origin_state_code,
        "status": "ACTIVE",
    }
    common.stamp_create(rec)
    db.sellers[rec["id"]] = rec
    return object_response(serializers.seller(rec), 201)


@bp.get("/sellers/<rec_id>")
@require(*ALL_ROLES)
def get_seller(rec_id):
    rec = common.get_or_404(db.sellers, rec_id, "seller")
    return object_response(serializers.seller(rec))


@bp.get("/sellers")
@require("PlatformAdmin", "TaxPreparer", "TaxApprover", "Auditor")
def list_sellers():
    records = list(db.sellers.values())
    items, limit, offset, total = common.paginate(records, serializers.seller)
    return array_response(items, limit, offset, total)


@bp.post("/sellers/<rec_id>/suspend")
@require("PlatformAdmin")
def suspend_seller(rec_id):
    rec = common.get_or_404(db.sellers, rec_id, "seller")
    rec["status"] = "SUSPENDED"
    common.touch(rec)
    return object_response(serializers.seller(rec))


# ---------------------------------------------------------------------------
# MarketplaceFacilitator
# ---------------------------------------------------------------------------
@bp.post("/marketplace-facilitators")
@require("PlatformAdmin")
def create_facilitator():
    body = common.get_body()
    name = common.require_str(body, "name")
    codes = body.get("collecting_state_codes")
    if not isinstance(codes, list) or len(codes) == 0:
        raise APIError(ERR_INVALID_REQUEST, "collecting_state_codes must be a non-empty array")
    for c in codes:
        common.require_state_code(c, "collecting_state_codes[]")

    rec = {"name": name, "collecting_state_codes": list(codes)}
    common.stamp_create(rec)
    db.marketplace_facilitators[rec["id"]] = rec
    return object_response(serializers.marketplace_facilitator(rec), 201)


@bp.get("/marketplace-facilitators/<rec_id>")
@require(*ALL_ROLES)
def get_facilitator(rec_id):
    rec = common.get_or_404(db.marketplace_facilitators, rec_id, "marketplace facilitator")
    return object_response(serializers.marketplace_facilitator(rec))


@bp.get("/marketplace-facilitators")
@require(*ALL_ROLES)
def list_facilitators():
    records = list(db.marketplace_facilitators.values())
    items, limit, offset, total = common.paginate(records, serializers.marketplace_facilitator)
    return array_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Test clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@require("PlatformAdmin")
def set_clock():
    body = common.get_body()
    dt = common.parse_dt(body, "to_iso8601")
    db.set_clock(dt)
    return object_response({})
