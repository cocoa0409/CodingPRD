"""SalvageVendor and SalvageBale endpoints (PRD §3.5)."""
from flask import Blueprint

from db import db, new_record, touch, iso_now
from errors import (
    ApiError, not_found, invalid_request,
    ERR_BALE_INVALID_STATE, ERR_BALE_UNDERWEIGHT, ERR_VENDOR_RATE_MISSING,
    ERR_NO_OPEN_CYCLE,
)
from middleware import require_roles, get_body, ALL_ROLES, paginate, query_filters, apply_filters
from response import success_object, success_list
from services import calc
from services.helpers import get_open_cycle

bp = Blueprint("salvage", __name__)

SALVAGE_CATEGORIES = ["TEXTILES", "PAPER", "EWASTE", "BULK"]


def vendor_view(v):
    return dict(v)


def bale_view(b):
    return dict(b)


def _get_bale(bale_id):
    b = db.bales.get(bale_id)
    if b is None:
        raise not_found("salvage bale")
    return b


def _validate_rates(rates):
    if not isinstance(rates, list):
        raise invalid_request("rates must be an array")
    for sheet in rates:
        if not isinstance(sheet, dict):
            raise invalid_request("rates entries must be objects")
        for key in sheet:
            if key not in ("category", "brackets"):
                raise invalid_request("Unknown rates field: %s" % key)
        if sheet.get("category") not in SALVAGE_CATEGORIES:
            raise invalid_request("rates.category must be a salvage category")
        brackets = sheet.get("brackets")
        if not isinstance(brackets, list) or len(brackets) == 0:
            raise invalid_request("brackets must be a non-empty array")
        prev_up_to = None
        for idx, br in enumerate(brackets):
            if not isinstance(br, dict):
                raise invalid_request("bracket entries must be objects")
            for key in br:
                if key not in ("up_to_lbs", "rate_cents_per_lb"):
                    raise invalid_request("Unknown bracket field: %s" % key)
            up_to = br.get("up_to_lbs")
            rate = br.get("rate_cents_per_lb")
            if up_to is not None and (not isinstance(up_to, (int, float))
                                      or isinstance(up_to, bool)):
                raise invalid_request("up_to_lbs must be a number or null")
            if not isinstance(rate, (int, float)) or isinstance(rate, bool):
                raise invalid_request("rate_cents_per_lb must be a number")
            if rate < 0:
                raise invalid_request("rate_cents_per_lb must be non-negative")
            if up_to is not None and up_to <= 0:
                raise invalid_request("up_to_lbs must be positive")
            # ascending order; only the final bracket may be unbounded (null)
            if idx < len(brackets) - 1 and up_to is None:
                raise invalid_request("only the final bracket may have up_to_lbs null")
            if prev_up_to is not None and up_to is not None and up_to <= prev_up_to:
                raise invalid_request("brackets must be in ascending order")
            if up_to is not None:
                prev_up_to = up_to


@bp.route("/api/salvage-vendors", methods=["POST"])
def create_vendor():
    require_roles(["StoreManager"])
    payload = get_body(
        required=[("name", "string"), ("rates", "array")],
    )
    _validate_rates(payload["rates"])
    rec = new_record()
    rec.update({"name": payload["name"], "rates": payload["rates"]})
    db.vendors[rec["id"]] = rec
    return success_object(vendor_view(rec), status=201)


@bp.route("/api/salvage-vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    require_roles(ALL_ROLES)
    v = db.vendors.get(vendor_id)
    if v is None:
        raise not_found("salvage vendor")
    return success_object(vendor_view(v))


@bp.route("/api/salvage-bales/<bale_id>", methods=["GET"])
def get_bale(bale_id):
    require_roles(ALL_ROLES)
    return success_object(bale_view(_get_bale(bale_id)))


@bp.route("/api/salvage-bales", methods=["GET"])
def list_bales():
    require_roles(ALL_ROLES)
    filters = query_filters(["category", "status", "vendor_id", "settled_cycle_id"])
    records = apply_filters(list(db.bales.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([bale_view(b) for b in page], limit, offset, total)


def _vendor_has_category(vendor, category):
    for sheet in vendor.get("rates", []):
        if sheet.get("category") == category:
            return True
    return False


@bp.route("/api/salvage-bales/<bale_id>/seal", methods=["POST"])
def seal_bale(bale_id):
    require_roles(["StoreManager"])
    payload = get_body(required=[("vendor_id", "string")])
    bale = _get_bale(bale_id)
    if bale["status"] != "ACCUMULATING":
        raise ApiError(ERR_BALE_INVALID_STATE, 409,
                       "seal requires a bale in ACCUMULATING")
    vendor = db.vendors.get(payload["vendor_id"])
    if vendor is None:
        raise not_found("salvage vendor")
    # weight check BEFORE vendor checks (PRD §2.9 / §3.5)
    if float(bale["weight_lbs"]) < calc.BALE_MIN_SEAL_LBS:
        raise ApiError(ERR_BALE_UNDERWEIGHT, 422,
                       "Seal requires weight_lbs >= 100.0")
    if not _vendor_has_category(vendor, bale["category"]):
        raise ApiError(ERR_VENDOR_RATE_MISSING, 422,
                       "Seal vendor declares no rates for the bale's category")
    bale["vendor_id"] = vendor["id"]
    bale["status"] = "SEALED"
    bale["sealed_at"] = iso_now()
    bale["estimated_revenue_cents"] = calc.bale_estimate_post_seal(
        vendor, bale["category"], bale["weight_lbs"])
    touch(bale)
    # cascade: assigned items in RECYCLE | PULLED_TO_SALVAGE -> BALED
    for item in db.items.values():
        if item.get("bale_id") == bale["id"] and item["status"] in ("RECYCLE", "PULLED_TO_SALVAGE"):
            item["status"] = "BALED"
            touch(item)
    return success_object(bale_view(bale))


@bp.route("/api/salvage-bales/<bale_id>/ship", methods=["POST"])
def ship_bale(bale_id):
    require_roles(["StoreManager"])
    get_body()
    bale = _get_bale(bale_id)
    if bale["status"] != "SEALED":
        raise ApiError(ERR_BALE_INVALID_STATE, 409,
                       "ship requires a bale in SEALED")
    bale["status"] = "SHIPPED"
    bale["shipped_at"] = iso_now()
    touch(bale)
    return success_object(bale_view(bale))


@bp.route("/api/salvage-bales/<bale_id>/settle", methods=["POST"])
def settle_bale(bale_id):
    require_roles(["FinanceClerk"])
    payload = get_body(required=[("actual_weight_lbs", "number")])
    if float(payload["actual_weight_lbs"]) < 0:
        raise invalid_request("actual_weight_lbs must be non-negative")
    bale = _get_bale(bale_id)
    if bale["status"] != "SHIPPED":
        raise ApiError(ERR_BALE_INVALID_STATE, 409,
                       "settle requires a bale in SHIPPED")
    open_cycle = get_open_cycle()
    if open_cycle is None:
        raise ApiError(ERR_NO_OPEN_CYCLE, 409,
                       "settle requires an OPEN weekly cycle")
    vendor = db.vendors.get(bale["vendor_id"])
    bale["actual_weight_lbs"] = payload["actual_weight_lbs"]
    bale["settled_revenue_cents"] = calc.bale_settlement(
        vendor, bale["category"], payload["actual_weight_lbs"])
    bale["status"] = "SETTLED"
    bale["settled_at"] = iso_now()
    bale["settled_cycle_id"] = open_cycle["id"]
    touch(bale)
    return success_object(bale_view(bale))
