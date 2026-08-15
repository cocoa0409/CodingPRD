"""Branch network and product catalog (PRD 3.1)."""
from flask import Blueprint

from errors import ERR_BRANCH_NOT_FOUND, ERR_PRODUCT_NOT_FOUND
from middleware import authorized
from routes.helpers import body, render_list, render_one
from services.core import create_record, get_or_404

bp = Blueprint("branches", __name__)

READ_ALL = ["PlatformAdmin", "BranchManager", "SalesRep", "Dispatcher",
            "Contractor", "CreditAnalyst", "ClaimsAdjuster", "WarehouseClerk"]


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------

@bp.post("/roofing/branches")
def create_branch():
    authorized(["PlatformAdmin"])
    data = body()
    rec = create_record("branches", {
        "branch_code": data.get("branch_code"),
        "name": data.get("name"),
        "rooftop_delivery_capacity_per_day": data.get("rooftop_delivery_capacity_per_day"),
        "conveyor_fleet_size": data.get("conveyor_fleet_size"),
        "crane_available": bool(data.get("crane_available", False)),
        "surge_mode": "NORMAL",
        "status": "ACTIVE",
    })
    return render_one("branches", rec, status=201)


@bp.get("/roofing/branches")
def list_branches():
    caller = authorized(READ_ALL)
    return render_list(caller, "branches")


@bp.get("/roofing/branches/<rid>")
def get_branch(rid):
    caller = authorized(READ_ALL)
    rec = get_or_404("branches", rid, ERR_BRANCH_NOT_FOUND)
    return render_one("branches", rec)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@bp.post("/roofing/products")
def create_product():
    authorized(["PlatformAdmin"])
    data = body()
    rec = create_record("products", {
        "sku": data.get("sku"),
        "manufacturer_name": data.get("manufacturer_name"),
        "color_code": data.get("color_code"),
        "bundles_per_square": data.get("bundles_per_square"),
        "base_price_per_bundle_cents": data.get("base_price_per_bundle_cents"),
        "requires_certified_installer": bool(data.get("requires_certified_installer", False)),
        "status": "ACTIVE",
    })
    return render_one("products", rec, status=201)


@bp.get("/roofing/products")
def list_products():
    caller = authorized(READ_ALL)
    return render_list(caller, "products")


@bp.get("/roofing/products/<rid>")
def get_product(rid):
    caller = authorized(READ_ALL)
    rec = get_or_404("products", rid, ERR_PRODUCT_NOT_FOUND)
    return render_one("products", rec)
