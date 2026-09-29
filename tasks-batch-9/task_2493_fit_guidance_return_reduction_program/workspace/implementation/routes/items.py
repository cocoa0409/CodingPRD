"""Catalog items: the two independent state axes (PRD 3.1, 3.4, 3.6)."""

from flask import Blueprint, request

import constants as C
import validate as V
from db import db, new_row, touch
from errors import ApiError
from lookup import ensure_not_delisted, filtered, get_item, get_vendor
from middleware import authenticate, require_owner
from response import array_response, object_response
from services.derive import (active_mapping_of_item, deployments_of_item,
                             terminate_deployment, verified_specs_of_item)
from services.recommend import fit_recommendation

bp = Blueprint("catalog_items", __name__)


def _new_item(vendor_id, sku, category_code, brand_size_system, unit_price_cents):
    return new_row({
        "vendor_id": vendor_id,
        "sku": sku,
        "category_code": category_code,
        "brand_size_system": brand_size_system,
        "unit_price_cents": unit_price_cents,
        "listing_status": "DRAFT",
        "fit_readiness": "UNVERIFIED",
        "fit_watch_state": "NORMAL",
        "model_measurements_published": False,
        "model_height_cm": None,
        "model_worn_size_label": None,
        "detail_image_count": 0,
        "pdp_review_required": False,
        "units_sold_count": 0,
        "fit_return_count": 0,
        "expectation_return_count": 0,
        "total_return_count": 0,
        "fit_return_rate_bp": 0,
        "expectation_return_rate_bp": 0,
        "chronic_return_score_bp": 0,
        "return_cost_accrued_cents": 0,
        "fit_signal_weight_total": 0,
        "active_fit_feedback_count": 0,
        "delist_reason_code": None,
    })


@bp.post("/fit-program/catalog-items")
def create_item():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()

    vendor_id = V.req_str(body, "vendor_id", min_len=1)
    sku = V.req_str(body, "sku", min_len=1)
    category_code = V.req_enum(body, "category_code", C.CATEGORY_CODES)
    brand_size_system = V.req_enum(body, "brand_size_system", C.SIZE_SYSTEMS)
    unit_price_cents = V.req_int(body, "unit_price_cents", minimum=1)

    get_vendor(vendor_id)

    for existing in db.items.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY",
                           "sku '%s' already exists." % sku)

    item = _new_item(vendor_id, sku, category_code, brand_size_system,
                     unit_price_cents)
    db.items[item["id"]] = item
    return object_response(item, 201)


@bp.get("/fit-program/catalog-items/<item_id>")
def read_item(item_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_FIT_ANALYST, C.ROLE_VENDOR_USER,
                 C.ROLE_RETURNS_AUDITOR, C.ROLE_CUSTOMER)
    return object_response(get_item(item_id))


@bp.get("/fit-program/catalog-items")
def list_items():
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_FIT_ANALYST, C.ROLE_RETURNS_AUDITOR)
    limit, offset = V.pagination_params()
    rows = filtered(db.items.values(), {
        "vendor_id": "vendor_id",
        "listing_status": "listing_status",
        "fit_readiness": "fit_readiness",
        "fit_watch_state": "fit_watch_state",
    })
    page, meta = V.paginate(rows, limit, offset)
    return array_response(page, meta)


@bp.post("/fit-program/catalog-items/<item_id>/list")
def list_item_on_storefront(item_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    item = get_item(item_id)
    if item["listing_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ITEM_STATE",
                       "Only a DRAFT item can be listed; this item is %s."
                       % item["listing_status"])
    # the readiness axis is deliberately untouched
    item["listing_status"] = "LISTED"
    touch(item)
    return object_response(item)


@bp.post("/fit-program/catalog-items/<item_id>/delist")
def delist_item(item_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    item = get_item(item_id)
    body = V.get_body()
    delist_reason_code = V.req_enum(body, "delist_reason_code",
                                    C.DELIST_REASON_CODES)
    if item["listing_status"] not in ("DRAFT", "LISTED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_ITEM_STATE",
                       "A %s item cannot be delisted." % item["listing_status"])

    item["listing_status"] = "DELISTED"
    item["delist_reason_code"] = delist_reason_code
    touch(item)

    # closing out the program's running measurement work on this item
    for deployment in deployments_of_item(item["id"]):
        if deployment["status"] in ("SCHEDULED", "ACTIVE"):
            terminate_deployment(deployment, "ITEM_DELISTED")

    return object_response(item)


@bp.post("/fit-program/catalog-items/<item_id>/pdp-enhancement")
def enhance_product_page(item_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    item = get_item(item_id)
    body = V.get_body()

    model_measurements_published = V.req_bool(body, "model_measurements_published")
    detail_image_count = V.req_int(body, "detail_image_count", minimum=0)
    has_height = "model_height_cm" in body and body["model_height_cm"] is not None
    model_height_cm = V.opt_int(body, "model_height_cm", minimum=0)
    has_label = ("model_worn_size_label" in body
                 and body["model_worn_size_label"] is not None)
    model_worn_size_label = V.opt_str(body, "model_worn_size_label", min_len=1)

    ensure_not_delisted(item)

    item["model_measurements_published"] = model_measurements_published
    item["detail_image_count"] = detail_image_count
    if has_height:
        item["model_height_cm"] = model_height_cm
    if has_label:
        item["model_worn_size_label"] = model_worn_size_label
    item["pdp_review_required"] = False
    touch(item)
    return object_response(item)


@bp.post("/fit-program/catalog-items/<item_id>/publish-guidance")
def publish_guidance(item_id):
    authenticate(C.ROLE_FIT_ANALYST)
    item = get_item(item_id)
    ensure_not_delisted(item)

    if item["fit_readiness"] != "CHART_MAPPED":
        raise ApiError("ERR_INVALID_ITEM_STATE",
                       "Guidance can only be published from CHART_MAPPED; this "
                       "item is %s." % item["fit_readiness"])

    verified = verified_specs_of_item(item["id"])
    if len(verified) != 1:
        raise ApiError("ERR_SPEC_NOT_VERIFIED",
                       "The item must have exactly one VERIFIED measurement "
                       "specification.")

    mapping = active_mapping_of_item(item["id"])
    chart = db.charts.get(mapping["chart_id"]) if mapping is not None else None
    if (mapping is None or chart is None or chart["status"] != "STANDARDIZED"
            or chart["category_code"] != item["category_code"]):
        raise ApiError("ERR_CHART_NOT_STANDARDIZED",
                       "The item's active mapping must point at a STANDARDIZED "
                       "chart of the item's category.")

    if mapping["coverage_bp"] < C.MIN_COVERAGE_BP:
        raise ApiError("ERR_MAPPING_COVERAGE_INSUFFICIENT",
                       "Mapping coverage %d bp is below the required %d bp."
                       % (mapping["coverage_bp"], C.MIN_COVERAGE_BP))

    if (not item["model_measurements_published"]
            or item["detail_image_count"] < C.MIN_DETAIL_IMAGE_COUNT):
        raise ApiError("ERR_PDP_ENHANCEMENT_INCOMPLETE",
                       "The product page needs published model measurements and "
                       "at least %d detail images." % C.MIN_DETAIL_IMAGE_COUNT)

    item["fit_readiness"] = "GUIDANCE_READY"
    if item["listing_status"] == "SUSPENDED" and item["fit_watch_state"] != "CHRONIC":
        item["listing_status"] = "LISTED"
    touch(item)
    return object_response(item)


@bp.get("/fit-program/catalog-items/<item_id>/fit-recommendation")
def read_fit_recommendation(item_id):
    actor = authenticate(C.ROLE_CUSTOMER, C.ROLE_FIT_ANALYST, C.ROLE_MERCH_OPS_ADMIN)
    item = get_item(item_id)

    customer_profile_id = request.args.get("customer_profile_id")
    if actor.role == C.ROLE_CUSTOMER and customer_profile_id is not None:
        require_owner(actor.user_id == customer_profile_id,
                      "A Customer may only read fit guidance for their own profile.")

    if item["fit_readiness"] != "GUIDANCE_READY":
        raise ApiError("ERR_GUIDANCE_NOT_READY",
                       "Fit guidance is not servable until the item reaches "
                       "GUIDANCE_READY.")

    mapping = active_mapping_of_item(item["id"])
    chart = db.charts.get(mapping["chart_id"]) if mapping is not None else None
    if mapping is None or chart is None:
        raise ApiError("ERR_GUIDANCE_NOT_READY",
                       "The item has no active mapping to recommend from.")

    return object_response(fit_recommendation(item, customer_profile_id))
