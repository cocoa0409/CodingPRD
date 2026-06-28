"""Reference-data routes: clock, coverage-products, vendors, force-majeure-events.

(PRD §2.4, §3.1; scaffold §1.5)
"""
from flask import Blueprint

from clock import clock
from db import db, new_common, now_iso, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_success
from serializers import public
from services.lookups import get_peril, get_product, get_vendor
from timeutil import parse_iso, fmt
from validators import (
    get_body,
    get_pagination,
    opt_bool,
    query_str,
    req_enum,
    req_int,
    req_number,
    req_str,
)

bp = Blueprint("reference", __name__)

COVERAGE_TYPES = {"CANCELLATION", "LIABILITY", "LIQUOR_LIABILITY"}
TIERS = {"BASIC", "STANDARD", "PREMIER"}
VENDOR_CATEGORIES = {"VENUE", "CATERER", "FLORIST", "PHOTOGRAPHER", "ENTERTAINMENT", "OTHER"}
PERIL_TYPES = {"NAMED_STORM", "PANDEMIC", "WILDFIRE", "CIVIL_AUTHORITY"}


def _paginate_sorted(items):
    """Sort by created_at ascending (insertion order) and paginate."""
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return [public(x) for x in page], limit, offset, total


# ---- Logical clock (PRD §2.4) ----------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    target = parse_iso(req_str(body, "to_iso8601"))
    clock.set(target)
    return success({"current_utc": fmt(target)}, status=200)


# ---- CoverageProduct (PRD §3.1) --------------------------------------------
@bp.route("/coverage-products", methods=["POST"])
def create_product():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    coverage_type = req_enum(body, "coverage_type", COVERAGE_TYPES)
    tier = req_enum(body, "tier", TIERS)
    base_premium_cents = req_int(body, "base_premium_cents", minimum=0)
    per_guest_premium_cents = req_int(body, "per_guest_premium_cents", minimum=0)
    coverage_limit_cents = req_int(body, "coverage_limit_cents", minimum=1)
    deposit_sublimit_pct = req_number(body, "deposit_sublimit_pct", gt=0, le=1)
    liquor_required = opt_bool(body, "liquor_required", default=False)

    # No two ACTIVE products may share the same coverage_type (PRD §3.1).
    for p in db.coverage_products.values():
        if p["status"] == "ACTIVE" and p["coverage_type"] == coverage_type:
            raise err("ERR_INVALID_REQUEST", "an ACTIVE product already exists for this coverage_type")

    product = new_common()
    product.update({
        "coverage_type": coverage_type,
        "tier": tier,
        "base_premium_cents": base_premium_cents,
        "per_guest_premium_cents": per_guest_premium_cents,
        "coverage_limit_cents": coverage_limit_cents,
        "deposit_sublimit_pct": deposit_sublimit_pct,
        "liquor_required": liquor_required,
        "status": "ACTIVE",
    })
    db.coverage_products[product["id"]] = product
    return success(public(product), status=201)


@bp.route("/coverage-products", methods=["GET"])
def list_products():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    f_type = query_str("coverage_type")
    f_tier = query_str("tier")
    f_status = query_str("status")
    items = list(db.coverage_products.values())
    if f_type is not None:
        items = [p for p in items if p["coverage_type"] == f_type]
    if f_tier is not None:
        items = [p for p in items if p["tier"] == f_tier]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    data, limit, offset, total = _paginate_sorted(items)
    return list_success(data, limit, offset, total)


@bp.route("/coverage-products/<product_id>/retire", methods=["POST"])
def retire_product(product_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    product = get_product(product_id)
    if product["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "product is not ACTIVE")
    product["status"] = "RETIRED"
    touch(product)
    return success(public(product), status=200)


# ---- Vendor (PRD §3.1) -----------------------------------------------------
@bp.route("/vendors", methods=["POST"])
def create_vendor():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent"})
    body = get_body()
    legal_name = req_str(body, "legal_name")
    category = req_enum(body, "category", VENDOR_CATEGORIES)
    deposit_paid_cents = req_int(body, "deposit_paid_cents", minimum=0)
    vendor = new_common()
    vendor.update({
        "legal_name": legal_name,
        "category": category,
        "deposit_paid_cents": deposit_paid_cents,
        "status": "SOLVENT",
    })
    db.vendors[vendor["id"]] = vendor
    return success(public(vendor), status=201)


@bp.route("/vendors", methods=["GET"])
def list_vendors():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    f_cat = query_str("category")
    f_status = query_str("status")
    items = list(db.vendors.values())
    if f_cat is not None:
        items = [v for v in items if v["category"] == f_cat]
    if f_status is not None:
        items = [v for v in items if v["status"] == f_status]
    data, limit, offset, total = _paginate_sorted(items)
    return list_success(data, limit, offset, total)


@bp.route("/vendors/<vendor_id>/flag", methods=["POST"])
def flag_vendor(vendor_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    vendor = get_vendor(vendor_id)
    if vendor["status"] != "SOLVENT":
        raise err("ERR_VENDOR_NOT_SOLVENT", "vendor is not SOLVENT")
    vendor["status"] = "FLAGGED"
    touch(vendor)
    return success(public(vendor), status=200)


@bp.route("/vendors/<vendor_id>/default", methods=["POST"])
def default_vendor(vendor_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    vendor = get_vendor(vendor_id)
    if vendor["status"] != "FLAGGED":
        raise err("ERR_VENDOR_NOT_FLAGGED", "vendor is not FLAGGED")
    vendor["status"] = "DEFAULTED"
    touch(vendor)
    return success(public(vendor), status=200)


@bp.route("/vendors/<vendor_id>/clear", methods=["POST"])
def clear_vendor(vendor_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    vendor = get_vendor(vendor_id)
    if vendor["status"] != "FLAGGED":
        raise err("ERR_VENDOR_NOT_FLAGGED", "vendor is not FLAGGED")
    vendor["status"] = "SOLVENT"
    touch(vendor)
    return success(public(vendor), status=200)


# ---- ForceMajeureEvent (PRD §3.1) ------------------------------------------
@bp.route("/force-majeure-events", methods=["POST"])
def create_peril():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    peril_name = req_str(body, "peril_name")
    peril_type = req_enum(body, "peril_type", PERIL_TYPES)
    cutoff_at = parse_iso(req_str(body, "cutoff_at"))
    landfall_at = parse_iso(req_str(body, "landfall_at"))
    peril = new_common()
    peril.update({
        "peril_name": peril_name,
        "peril_type": peril_type,
        "cutoff_at": fmt(cutoff_at),
        "landfall_at": fmt(landfall_at),
        "status": "WATCH",
        "_cutoff_at": cutoff_at,
        "_landfall_at": landfall_at,
    })
    db.force_majeure_events[peril["id"]] = peril
    return success(public(peril), status=201)


@bp.route("/force-majeure-events", methods=["GET"])
def list_perils():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    f_type = query_str("peril_type")
    f_status = query_str("status")
    items = list(db.force_majeure_events.values())
    if f_type is not None:
        items = [e for e in items if e["peril_type"] == f_type]
    if f_status is not None:
        items = [e for e in items if e["status"] == f_status]
    data, limit, offset, total = _paginate_sorted(items)
    return list_success(data, limit, offset, total)


@bp.route("/force-majeure-events/<event_id>/activate", methods=["POST"])
def activate_peril(event_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    peril = get_peril(event_id)
    if peril["status"] != "WATCH":
        raise err("ERR_PERIL_NOT_WATCH", "peril is not WATCH")
    peril["status"] = "ACTIVE"
    touch(peril)
    return success(public(peril), status=200)


@bp.route("/force-majeure-events/<event_id>/expire", methods=["POST"])
def expire_peril(event_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    peril = get_peril(event_id)
    if peril["status"] != "ACTIVE":
        raise err("ERR_PERIL_NOT_ACTIVE", "peril is not ACTIVE")
    peril["status"] = "EXPIRED"
    touch(peril)
    return success(public(peril), status=200)
