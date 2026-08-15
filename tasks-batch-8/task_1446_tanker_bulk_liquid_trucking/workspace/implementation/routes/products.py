"""Products: chemical master data (PRD 3.1)."""
from flask import Blueprint, request

from authz import ALL_ROLES, FLEET_ADMIN, require_roles
from db import store
from respond import success
from serialize import ser_product
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_enum, req_number, req_str, sorted_by_creation,
)

bp = Blueprint("products", __name__)

COMPATIBILITY_GROUPS = (
    "PETROLEUM", "SOLVENT", "ACID", "CAUSTIC", "VEG_OIL", "FOOD_GRADE", "LATEX",
)
HAZMAT_CLASSES = ("NONE", "CLASS_3_FLAMMABLE", "CLASS_8_CORROSIVE", "CLASS_6_TOXIC")
PACKING_GROUPS = ("NONE", "I", "II", "III")


@bp.route("/products", methods=["POST"])
def create_product():
    require_roles([FLEET_ADMIN])
    data = json_body()
    reject_unknown(data, {"name", "compatibility_group", "hazmat_class",
                          "packing_group", "density_lb_per_gal",
                          "temp_coeff_per_degF", "placard_code"})
    p = {
        "id": new_id(),
        "_seq": next(store.seq),
        "name": req_str(data, "name"),
        "compatibility_group": req_enum(data, "compatibility_group", COMPATIBILITY_GROUPS),
        "hazmat_class": req_enum(data, "hazmat_class", HAZMAT_CLASSES),
        "packing_group": req_enum(data, "packing_group", PACKING_GROUPS),
        "density_lb_per_gal": req_number(data, "density_lb_per_gal", minimum=0, exclusive_minimum=True),
        "temp_coeff_per_degF": req_number(data, "temp_coeff_per_degF", minimum=0),
        "placard_code": req_str(data, "placard_code"),
    }
    p.update(new_common_fields())
    store.products[p["id"]] = p
    return success(ser_product(p), status=201)


@bp.route("/products", methods=["GET"])
def list_products():
    require_roles(ALL_ROLES)
    group = request.args.get("compatibility_group")
    items = [p for p in store.products.values()
             if group is None or p["compatibility_group"] == group]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_product(p) for p in page],
                   response_type="array", pagination=pagination)


@bp.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    require_roles(ALL_ROLES)
    return success(ser_product(get_or_404(store.products, "products", pid)))
