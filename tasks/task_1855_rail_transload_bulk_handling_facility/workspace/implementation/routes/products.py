"""Product endpoints: create, get."""

from flask import Blueprint

from db import STORE, new_entity, public
from errors import raise_err, ERR_NOT_FOUND
from middleware import auth_context, require_role, ALL_ROLES
from response import ok
from validate import body, req_str, req_enum, req_bool

bp = Blueprint("products", __name__)

HAZARD_CLASSES = ("NON_HAZARDOUS", "HAZARDOUS", "FOOD_GRADE")
SEGREGATION_GROUPS = ("FERTILIZER", "FOOD_GRAIN", "CHEMICAL", "PETROLEUM")


@bp.route("/transload/products", methods=["POST"])
def create_product():
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    data = body()
    name = req_str(data, "name")
    hazard_class = req_enum(data, "hazard_class", HAZARD_CLASSES)
    segregation_group = req_enum(data, "segregation_group", SEGREGATION_GROUPS)
    requires_full_clean = req_bool(data, "requires_full_clean")
    prod = new_entity(STORE.products, {
        "name": name,
        "hazard_class": hazard_class,
        "segregation_group": segregation_group,
        "requires_full_clean": requires_full_clean,
    })
    return ok(public(prod), status=201)


@bp.route("/transload/products/<pid>", methods=["GET"])
def get_product(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    prod = STORE.products.get(pid)
    if prod is None:
        raise_err(ERR_NOT_FOUND, "product id does not exist")
    return ok(public(prod))
