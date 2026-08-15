"""Allocation policies (PRD §3.2): shortage rationing pools.

At most one OPEN policy per product; remaining_units initializes to
pool_units and never goes negative; OPEN/EXHAUSTED -> CLOSED is terminal.
"""
from flask import Blueprint

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from validation import (get_body, req_enum, req_int, opt_int, body_fk,
                        path_entity)

bp = Blueprint("policies", __name__)

POLICY_MODES = ["PRO_RATA", "EQUAL_SHARE"]


@bp.route("/wholesale/allocation-policies", methods=["POST"])
@endpoint(["OrderManager"])
def create_policy():
    body = get_body()
    product = body_fk(body, "product_id", store.products, "Product")
    pool_units = req_int(body, "pool_units", minimum=0)
    mode = req_enum(body, "policy_mode", POLICY_MODES)
    min_guarantee = opt_int(body, "min_guarantee_units", default=0, minimum=0)
    if any(p["product_id"] == product["id"] and p["policy_status"] == "OPEN"
           for p in store.allocation_policies.values()):
        raise ApiError(errors.ERR_DUPLICATE_UNIQUE_FIELD[0], errors.ERR_DUPLICATE_UNIQUE_FIELD[1],
                       "At most one OPEN allocation policy per product")
    policy = {
        "id": db.new_id(),
        "product_id": product["id"],
        "pool_units": pool_units,
        "remaining_units": pool_units,
        "policy_mode": mode,
        "min_guarantee_units": min_guarantee,
        "policy_status": "OPEN",
    }
    db.new_common(policy)
    store.allocation_policies[policy["id"]] = policy
    return created(policy)


@bp.route("/wholesale/allocation-policies", methods=["GET"])
@endpoint(ALL_ROLES)
def list_policies():
    pg = Paginator()
    rows = list(store.allocation_policies.values())
    rows = pg.filter(rows, "product_id")
    rows = pg.filter(rows, "policy_status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/allocation-policies/<policyId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_policy(policyId):
    policy = path_entity(store.allocation_policies, policyId, "AllocationPolicy")
    return ok(policy)


@bp.route("/wholesale/allocation-policies/<policyId>/close", methods=["POST"])
@endpoint(["OrderManager"])
def close_policy(policyId):
    policy = path_entity(store.allocation_policies, policyId, "AllocationPolicy")
    if policy["policy_status"] not in ("OPEN", "EXHAUSTED"):
        raise ApiError(errors.ERR_POLICY_NOT_CLOSABLE[0], errors.ERR_POLICY_NOT_CLOSABLE[1],
                       "Allocation policy must be OPEN or EXHAUSTED to close")
    policy["policy_status"] = "CLOSED"
    db.touch(policy)
    return ok(policy)
