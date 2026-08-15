"""Product endpoints (PRD 3.1)."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import ALL_READ_ROLES, get_one, list_response, public
from services import new_record
from validate import get_body, opt_bool, opt_enum, opt_int, req_enum, req_int, req_str

bp = Blueprint("products", __name__)

PRODUCT_FAMILIES = {"CHEMICAL", "EQUIPMENT", "PARTS"}
HAZMAT_CLASSES = {"NONE", "OXIDIZER_5_1", "CORROSIVE_8"}


@bp.post("/pool-supply/products")
def create_product():
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    body = get_body()
    family = req_enum(body, "product_family", PRODUCT_FAMILIES)
    hazmat_class = opt_enum(body, "hazmat_class", HAZMAT_CLASSES, "NONE")
    if hazmat_class != "NONE" and family != "CHEMICAL":
        raise_error(ERR_INVALID_REQUEST, "only CHEMICAL products may carry a non-NONE hazmat_class")
    rec = new_record("products", {
        "sku": req_str(body, "sku"),
        "product_family": family,
        "hazmat_class": hazmat_class,
        "base_price_cents": req_int(body, "base_price_cents", minimum=0),
        "expiry_tracked": opt_bool(body, "expiry_tracked", False),
        "low_stock_floor": opt_int(body, "low_stock_floor", 0, minimum=0),
        "shortage_freeze_threshold": opt_int(body, "shortage_freeze_threshold", 100, minimum=0),
    })
    return success_object(public(rec), status=201)


@bp.get("/pool-supply/products")
def list_products():
    filters = {
        "product_family": request.args.get("product_family"),
        "hazmat_class": request.args.get("hazmat_class"),
    }
    return list_response("products", ALL_READ_ROLES, filters)


@bp.get("/pool-supply/products/<rid>")
def get_product(rid):
    return get_one("products", rid, ALL_READ_ROLES)
