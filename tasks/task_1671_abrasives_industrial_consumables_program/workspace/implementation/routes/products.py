"""Product catalog endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_REPLACEMENT_INVALID,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.core import new_record, serialize, touch
from util import CLOCK
from validate import (
    get_body, opt_int, req_enum, req_int, req_str, require_fk,
    require_path_resource,
)

bp = Blueprint("products", __name__)

PRODUCT_FORMS = {"COATED", "BONDED", "NONWOVEN"}
SHELF_LIFE_POLICIES = {"EXACT_DAY", "END_OF_MONTH"}
HAZARD_CLASSES = {"NONE", "METAL_SWARF", "OIL_CONTAMINATED"}


@bp.post("/api/products")
def create_product():
    authorized(["ProgramAdmin"])
    body = get_body()
    sku = req_str(body, "sku")
    name = req_str(body, "name")
    product_form = req_enum(body, "product_form", PRODUCT_FORMS)
    rpm = req_int(body, "max_operating_speed_rpm", min_value=1)
    shelf_life_months = opt_int(body, "shelf_life_months", min_value=1, default=None)
    shelf_life_policy = req_enum(body, "shelf_life_policy", SHELF_LIFE_POLICIES, default="EXACT_DAY")
    hazard_class = req_enum(body, "used_media_hazard_class", HAZARD_CLASSES, default="NONE")
    # shelf_life_months is REQUIRED for BONDED and ignored for other forms.
    if product_form == "BONDED":
        if shelf_life_months is None:
            raise_error(ERR_INVALID_REQUEST, "shelf_life_months is required for BONDED products")
    else:
        shelf_life_months = None
    for p in db["products"].values():
        if p["sku"] == sku:
            raise_error(ERR_INVALID_REQUEST, f"sku {sku} already exists")
    rec = new_record("products", {
        "sku": sku,
        "name": name,
        "product_form": product_form,
        "max_operating_speed_rpm": rpm,
        "shelf_life_months": shelf_life_months,
        "shelf_life_policy": shelf_life_policy,
        "used_media_hazard_class": hazard_class,
        "status": "ACTIVE",
        "replacement_product_id": None,
        "discontinued_at": None,
    })
    return success_object(serialize(rec), status=201)


@bp.get("/api/products")
def list_products():
    return list_response("products", {
        "status": arg("status"),
        "product_form": arg("product_form"),
        "replacement_product_id": arg("replacement_product_id"),
    })


@bp.get("/api/products/<pid>")
def get_product(pid):
    return get_one("products", pid, "product")


@bp.post("/api/products/<pid>/discontinue")
def discontinue_product(pid):
    authorized(["ProgramAdmin"])
    # Priority 3 (shape): the discontinuation must carry replacement_product_id.
    body = get_body()
    replacement_id = req_str(body, "replacement_product_id")
    # Priority 4 (existence): path id first, then the body FK.
    product = require_path_resource("products", pid, "product")
    replacement = require_fk("products", replacement_id, "replacement product")
    # Priority 6 (state): discontinuation only on an ACTIVE product.
    if product["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only an ACTIVE product can be discontinued")
    # Priority 8 (business): replacement must not be the product itself and must be ACTIVE.
    if replacement_id == pid or replacement["status"] != "ACTIVE":
        raise_error(ERR_REPLACEMENT_INVALID, "replacement product must be a different ACTIVE product")

    product["status"] = "DISCONTINUED"
    product["replacement_product_id"] = replacement_id
    product["discontinued_at"] = CLOCK.now_iso()
    touch(product)

    # Cascade hop 1: DRAFT|OPEN blanket orders on this product -> substitution PENDING.
    pending_orders = [
        o for o in db["blanket_orders"].values()
        if o["product_id"] == pid and o["status"] in ("DRAFT", "OPEN")
    ]
    for order in pending_orders:
        order["substitution_status"] = "PENDING"
        touch(order)
    # Cascade hop 2: SCHEDULED releases of just-PENDING orders -> ON_HOLD.
    pending_ids = {o["id"] for o in pending_orders}
    for rel in db["releases"].values():
        if rel["blanket_order_id"] in pending_ids and rel["status"] == "SCHEDULED":
            rel["status"] = "ON_HOLD"
            touch(rel)
    # Fan-out: AVAILABLE lots of this product -> BLOCKED.
    for lot in db["lots"].values():
        if lot["product_id"] == pid and lot["status"] == "AVAILABLE":
            lot["status"] = "BLOCKED"
            touch(lot)
    return success_object(serialize(product))
