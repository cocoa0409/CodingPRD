"""Customer endpoints: create, get, patch, OCC allocation adjustments."""

from flask import Blueprint

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_STALE_VERSION, ERR_ALLOCATION_BELOW_FLOOR,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok
from validate import (
    body, req_str, req_int, req_nonneg_int, opt_enum,
)

bp = Blueprint("customers", __name__)

CREDIT_STANDINGS = ("GOOD_STANDING", "CREDIT_WATCH", "CREDIT_HOLD")
DEMURRAGE_BASES = ("CONSTRUCTIVE", "ACTUAL")
SIT_DAY_BASES = ("CALENDAR", "BUSINESS")


@bp.route("/transload/customers", methods=["POST"])
def create_customer():
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    data = body()
    name = req_str(data, "name")
    allocated_car_spots = req_nonneg_int(data, "allocated_car_spots")
    credit_standing = opt_enum(data, "credit_standing", CREDIT_STANDINGS, "GOOD_STANDING")
    demurrage_basis = opt_enum(data, "demurrage_basis", DEMURRAGE_BASES, "CONSTRUCTIVE")
    sit_day_basis = opt_enum(data, "sit_day_basis", SIT_DAY_BASES, "CALENDAR")
    cust = new_entity(STORE.customers, {
        "name": name,
        "credit_standing": credit_standing,
        "demurrage_basis": demurrage_basis,
        "sit_day_basis": sit_day_basis,
        "allocated_car_spots": allocated_car_spots,
    })
    return ok(public(cust), status=201)


@bp.route("/transload/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    cust = STORE.customers.get(cid)
    if cust is None:
        raise_err(ERR_NOT_FOUND, "customer id does not exist")
    return ok(public(cust))


@bp.route("/transload/customers/<cid>", methods=["PATCH"])
def patch_customer(cid):
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    cust = STORE.customers.get(cid)
    if cust is None:
        raise_err(ERR_NOT_FOUND, "customer id does not exist")
    data = body()
    credit_standing = opt_enum(data, "credit_standing", CREDIT_STANDINGS, None)
    demurrage_basis = opt_enum(data, "demurrage_basis", DEMURRAGE_BASES, None)
    sit_day_basis = opt_enum(data, "sit_day_basis", SIT_DAY_BASES, None)
    if credit_standing is not None:
        cust["credit_standing"] = credit_standing
    if demurrage_basis is not None:
        cust["demurrage_basis"] = demurrage_basis
    if sit_day_basis is not None:
        cust["sit_day_basis"] = sit_day_basis
    touch(cust)
    return ok(public(cust))


@bp.route("/transload/customers/<cid>/allocation-adjustments", methods=["POST"])
def allocation_adjustment(cid):
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    cust = STORE.customers.get(cid)
    if cust is None:
        raise_err(ERR_NOT_FOUND, "customer id does not exist")
    data = body()
    expected_version = req_int(data, "expected_customer_version")
    new_allocation = req_nonneg_int(data, "new_allocated_car_spots")
    # Priority 15: floor check -- the new allocation must be at least the
    # customer's current occupied+reserved spots.
    occupied, reserved = domain.customer_spot_usage(cid)
    if new_allocation < occupied + reserved:
        raise_err(
            ERR_ALLOCATION_BELOW_FLOOR,
            "new_allocated_car_spots is below the current occupied+reserved floor",
        )
    # Priority 16: optimistic concurrency, evaluated with the mutation.
    if expected_version != cust["version"]:
        raise_err(ERR_STALE_VERSION, "expected_customer_version does not match the current version")
    cust["allocated_car_spots"] = new_allocation
    touch(cust)
    return ok(public(cust), status=201)
