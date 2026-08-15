"""Routes: vendors, products (catalog administration), logical clock."""

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err,
    ERR_VENDOR_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_DUPLICATE_VENDOR_CODE,
)
from middleware import require_role, INTERNAL_ROLES
from response import success_object, success_list, paginate
from validation import (
    body, req_string, req_int, req_positive_int, req_number, req_bool,
    req_enum, req_datetime,
)

bp = Blueprint("catalog", __name__)

LICENSE_METRICS = ("PER_INSTALL", "PER_USER", "PER_CORE")


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@bp.post("/sam/vendors")
def create_vendor():
    require_role(["SAMPlatformAdmin"])
    data = body()
    name = req_string(data, "name")
    vendor_code = req_string(data, "vendor_code")
    metric = req_enum(data, "default_license_metric", LICENSE_METRICS)
    days = req_int(data, "notice_response_deadline_days", required=False,
                   minimum=1, default=30)
    for v in db.vendors.values():
        if v["vendor_code"] == vendor_code:
            raise_err(ERR_DUPLICATE_VENDOR_CODE,
                      "vendor_code is already registered")
    rec = svc.stamp_new({
        "name": name,
        "vendor_code": vendor_code,
        "default_license_metric": metric,
        "notice_response_deadline_days": days,
    })
    db.vendors[rec["id"]] = rec
    return success_object(rec, 201)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@bp.post("/sam/products")
def create_product():
    require_role(["SAMPlatformAdmin"])
    data = body()
    vendor_id = req_string(data, "vendor_id")
    name = req_string(data, "name")
    metric = req_enum(data, "license_metric", LICENSE_METRICS)
    price = req_positive_int(data, "unit_list_price_cents")
    rate = req_number(data, "support_rate_pct", minimum=0, maximum=1)
    mission_critical = req_bool(data, "mission_critical", default=False)
    counts_np = req_bool(data, "counts_non_production", default=False)
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise_err(ERR_VENDOR_NOT_FOUND, "vendor_id does not exist")
    rec = svc.stamp_new({
        "vendor_id": vendor_id,
        "name": name,
        "license_metric": metric,
        "unit_list_price_cents": price,
        "support_rate_pct": rate,
        "mission_critical": mission_critical,
        "counts_non_production": counts_np,
    })
    db.products[rec["id"]] = rec
    # Exactly one LicensePosition per product, auto-created (PRD §3.1).
    pos = svc.stamp_new({
        "product_id": rec["id"],
        "entitled_quantity": 0,
        "deployed_quantity": 0,
        "gap_quantity": 0,
        "gap_severity": "COMPLIANT",
        "self_audit_exposure_cents": 0,
        "vendor_list_exposure_cents": 0,
        "position_basis": "SELF_AUDIT",
    })
    db.positions[pos["id"]] = pos
    return success_object(rec, 201)


@bp.get("/sam/products")
def list_products():
    require_role(INTERNAL_ROLES)
    records = list(db.products.values())
    v = request.args.get("vendor_id")
    if v is not None:
        if v not in db.vendors:
            raise_err(ERR_VENDOR_NOT_FOUND, "vendor_id does not exist")
        records = [p for p in records if p["vendor_id"] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.get("/sam/products/<pid>")
def get_product(pid):
    require_role(INTERNAL_ROLES)
    rec = db.products.get(pid)
    if rec is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    return success_object(rec)


@bp.patch("/sam/products/<pid>")
def update_product(pid):
    require_role(["SAMPlatformAdmin"])
    data = body()
    # Request shape first (validation priority 3), then existence (4).
    name = req_string(data, "name", required=False)
    price = req_positive_int(data, "unit_list_price_cents", required=False)
    rate = req_number(data, "support_rate_pct", required=False,
                      minimum=0, maximum=1)
    mission_critical = req_bool(data, "mission_critical")
    counts_np = req_bool(data, "counts_non_production")
    rec = db.products.get(pid)
    if rec is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    if name is not None:
        rec["name"] = name
    if price is not None:
        rec["unit_list_price_cents"] = price
    if rate is not None:
        rec["support_rate_pct"] = rate
    if mission_critical is not None:
        rec["mission_critical"] = mission_critical
    if counts_np is not None:
        rec["counts_non_production"] = counts_np
    svc.touch(rec)
    # Pricing/flags feed exposures and severity: recompute the position, the
    # rollups of every non-terminal case scoping the product, and alerts.
    svc.cascade_product(pid)
    return success_object(rec)


# ---------------------------------------------------------------------------
# Test-driving logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role(["SAMPlatformAdmin"])
    data = body()
    to_iso8601 = req_datetime(data, "to_iso8601")
    db.clock.set(db.parse_iso(to_iso8601))
    svc.clock_sweep()
    return success_object({"current_utc": db.now_iso()})
