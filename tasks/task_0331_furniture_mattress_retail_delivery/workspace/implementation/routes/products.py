"""Product (catalog) endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import domain, serializers

bp = Blueprint("products", __name__)

CATEGORIES = {"SOFA", "SECTIONAL", "MATTRESS", "BED_FRAME", "TABLE"}


def _validate_options(body, field):
    """available_fabrics / available_sizes: array of { code, surcharge_cents }."""
    options = body.get(field)
    if options is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    if not isinstance(options, list) or len(options) == 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty array." % field)
    cleaned = []
    for opt in options:
        if not isinstance(opt, dict):
            raise err("ERR_INVALID_REQUEST", "Each %s entry must be an object." % field)
        code = opt.get("code")
        surcharge = opt.get("surcharge_cents")
        if not isinstance(code, str) or code == "":
            raise err("ERR_INVALID_REQUEST", "Each %s entry needs a string code." % field)
        if not isinstance(surcharge, int) or isinstance(surcharge, bool):
            raise err("ERR_INVALID_REQUEST",
                      "Each %s entry needs integer surcharge_cents." % field)
        cleaned.append({"code": code, "surcharge_cents": surcharge})
    return cleaned


@bp.post("/products")
def create_product():
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    body = helpers.get_body()

    sku = helpers.require_str(body, "sku")
    name = helpers.require_str(body, "name")
    category = helpers.require_enum(body, "category", CATEGORIES)
    base_price = helpers.require_int(body, "base_price_cents", minimum=1)
    fabrics = _validate_options(body, "available_fabrics")
    sizes = _validate_options(body, "available_sizes")

    # STANDARD fabric must be present with surcharge_cents 0 (PRD §3.1).
    standard = next((f for f in fabrics if f["code"] == "STANDARD"), None)
    if standard is None or standard["surcharge_cents"] != 0:
        raise err("ERR_INVALID_REQUEST",
                  "available_fabrics must include STANDARD at surcharge_cents 0.")

    is_special = helpers.optional_bool(body, "is_special_order", default=False)
    lead_days = helpers.optional_int(body, "lead_days", default=0, minimum=0)
    protection_eligible = helpers.optional_bool(body, "protection_eligible", default=True)

    rec = {
        "sku": sku,
        "name": name,
        "category": category,
        "base_price_cents": base_price,
        "available_fabrics": fabrics,
        "available_sizes": sizes,
        "is_special_order": is_special,
        "lead_days": lead_days,
        "protection_eligible": protection_eligible,
    }
    helpers.stamp_create(rec)
    db.products[rec["id"]] = rec
    return response.object_response(serializers.product(rec), status=201)


@bp.get("/products/<pid>")
def get_product(pid):
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = helpers.fetch(db.products, pid)
    return response.object_response(serializers.product(rec))


@bp.get("/products/<pid>/order-lines")
def list_product_order_lines(pid):
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    helpers.fetch(db.products, pid)
    limit, offset = helpers.get_pagination()
    rows = [ln for ln in db.order_lines.values() if ln["product_id"] == pid]
    page, total = helpers.paginate(rows, limit, offset)
    return response.array_response(
        [serializers.order_line(ln) for ln in page], limit, offset, total)
