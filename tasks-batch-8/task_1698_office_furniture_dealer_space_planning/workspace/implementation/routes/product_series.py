"""ProductSeries routes: catalog management, discontinue, quality-hold clear."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_DUPLICATE_REFERENCE
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import get_or_404, new_entity, touch
from validate import body_dict, req_str, req_enum, req_int, req_list, is_int

bp = Blueprint("product_series", __name__)

MANUFACTURERS = {"STEELCASE", "MILLERKNOLL"}
CATEGORIES = {"SEATING", "SYSTEMS", "CASEGOODS", "TABLES", "STORAGE"}


def validate_option_catalog(catalog):
    for o in catalog:
        if not isinstance(o, dict):
            raise_error(ERR_INVALID_REQUEST, "each option_catalog entry must be an object")
        code = o.get("option_code")
        if not isinstance(code, str) or not code.strip():
            raise_error(ERR_INVALID_REQUEST, "option_catalog option_code must be a non-empty string")
        if not is_int(o.get("price_uplift_pct")) or o["price_uplift_pct"] < 0:
            raise_error(ERR_INVALID_REQUEST, "option_catalog price_uplift_pct must be an integer >= 0")
        if not is_int(o.get("extra_lead_days")) or o["extra_lead_days"] < 0:
            raise_error(ERR_INVALID_REQUEST, "option_catalog extra_lead_days must be an integer >= 0")
    return catalog


@bp.route("/api/product-series", methods=["POST"])
def create_series():
    authorize(["DealerAdmin"])
    body = body_dict()
    dealership_id = req_str(body, "dealership_id")
    manufacturer = req_enum(body, "manufacturer", MANUFACTURERS)
    category = req_enum(body, "category", CATEGORIES)
    series_code = req_str(body, "series_code")
    base_list_price_cents = req_int(body, "base_list_price_cents", minv=0)
    base_lead_time_days = req_int(body, "base_lead_time_days", minv=0)
    option_catalog = validate_option_catalog(req_list(body, "option_catalog"))
    get_or_404("dealerships", dealership_id)
    for other in db["product_series"].values():
        if other["dealership_id"] == dealership_id and other["series_code"] == series_code:
            raise_error(ERR_DUPLICATE_REFERENCE,
                        f"series_code '{series_code}' already exists in dealership {dealership_id}")
    series = new_entity("product_series", {
        "dealership_id": dealership_id,
        "manufacturer": manufacturer,
        "category": category,
        "series_code": series_code,
        "base_list_price_cents": base_list_price_cents,
        "base_lead_time_days": base_lead_time_days,
        "option_catalog": option_catalog,
        "quality_hold": False,
        "status": "ACTIVE",
    })
    return success_object(public(series), status=201)


@bp.route("/api/product-series", methods=["GET"])
def list_series():
    authorize(ALL_ROLES)
    return list_response("product_series", ["dealership_id", "manufacturer", "category", "status"])


@bp.route("/api/product-series/<series_id>", methods=["GET"])
def get_series(series_id):
    authorize(ALL_ROLES)
    return get_response("product_series", series_id)


@bp.route("/api/product-series/<series_id>/discontinue", methods=["POST"])
def discontinue_series(series_id):
    authorize(["DealerAdmin"])
    series = get_or_404("product_series", series_id)
    if series["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"cannot discontinue a series in status {series['status']}")
    series["status"] = "DISCONTINUED"
    touch(series)
    return success_object(public(series))


@bp.route("/api/product-series/<series_id>/clear_quality_hold", methods=["POST"])
def clear_quality_hold(series_id):
    authorize(["DealerAdmin"])
    series = get_or_404("product_series", series_id)
    # the flag is orthogonal to status: clearing never changes status
    series["quality_hold"] = False
    touch(series)
    return success_object(public(series))
