"""Customer accounts and customer contracts."""

from flask import Blueprint, request
from decimal import Decimal

from db import store
from errors import err
from helpers import (FAMILIES, dec, get_body, new_id, opt_enum, opt_int,
                     req_dt, req_enum, req_int, req_str, stamp_new, touch)
from middleware import require_any, require_roles
from response import ok, ok_list, paginate
from serialize import serialize, serialize_list

bp = Blueprint("customers", __name__)


def get_customer(cid):
    c = store.customers.get(cid)
    if c is None:
        raise err("ERR_CUSTOMER_NOT_FOUND", f"customer {cid} not found")
    return c


# -------------------------------------------------------------- customers --

@bp.route("/motion/customers", methods=["POST"])
@require_roles("ContractAdministrator")
def create_customer(user_id, role):
    body = get_body()
    name = req_str(body, "name")
    limit = req_int(body, "credit_limit_cents", minimum=0)
    rec = stamp_new({
        "id": new_id(),
        "name": name,
        "credit_limit_cents": limit,
        "credit_status": "GOOD",
        "status": "ACTIVE",
    })
    store.customers[rec["id"]] = rec
    return ok(serialize("CustomerAccount", rec), 201)


@bp.route("/motion/customers", methods=["GET"])
@require_any
def list_customers(user_id, role):
    items = list(store.customers.values())
    if request.args.get("credit_status") is not None:
        items = [c for c in items if c["credit_status"] == request.args["credit_status"]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("CustomerAccount", page), limit, offset, total)


@bp.route("/motion/customers/<cid>", methods=["GET"])
@require_any
def get_customer_route(user_id, role, cid):
    return ok(serialize("CustomerAccount", get_customer(cid)))


@bp.route("/motion/customers/<cid>", methods=["PATCH"])
@require_roles("ContractAdministrator")
def patch_customer(user_id, role, cid):
    c = get_customer(cid)
    body = get_body()
    credit_status = opt_enum(body, "credit_status", ("GOOD", "HOLD"))
    status = opt_enum(body, "status", ("ACTIVE", "INACTIVE"))
    if credit_status is not None:
        c["credit_status"] = credit_status
    if status is not None:
        c["status"] = status
    touch(c)
    return ok(serialize("CustomerAccount", c))


# -------------------------------------------------------------- contracts --

def get_contract(cid):
    c = store.contracts.get(cid)
    if c is None:
        raise err("ERR_CONTRACT_NOT_FOUND", f"contract {cid} not found")
    return c


@bp.route("/motion/contracts", methods=["POST"])
@require_roles("ContractAdministrator")
def create_contract(user_id, role):
    body = get_body()
    customer_id = req_str(body, "customer_id")
    if customer_id not in store.customers:
        raise err("ERR_CUSTOMER_NOT_FOUND", f"customer {customer_id} not found")
    family = req_enum(body, "family", FAMILIES)
    basis = req_enum(body, "price_basis", ("LIST_LESS", "CONTRACT_FIXED"))
    discount = body.get("discount_pct", 0)
    if not (isinstance(discount, (int, float)) and not isinstance(discount, bool)):
        raise err("ERR_INVALID_REQUEST", "discount_pct must be a number")
    if dec(discount) < 0 or dec(discount) > 1:
        raise err("ERR_INVALID_REQUEST", "discount_pct must be in [0,1]")
    fixed = opt_int(body, "fixed_unit_price_cents", default=None, minimum=0)
    lag = opt_int(body, "lag_protection_days", default=0, minimum=0)
    eff_from = req_dt(body, "effective_from")
    eff_to = req_dt(body, "effective_to")
    rec = stamp_new({
        "id": new_id(),
        "customer_id": customer_id,
        "family": family,
        "price_basis": basis,
        "discount_pct": discount,
        "fixed_unit_price_cents": fixed,
        "lag_protection_days": lag,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "status": "DRAFT",
    })
    store.contracts[rec["id"]] = rec
    return ok(serialize("CustomerContract", rec), 201)


@bp.route("/motion/contracts", methods=["GET"])
@require_any
def list_contracts(user_id, role):
    items = list(store.contracts.values())
    q = request.args
    if q.get("customer_id") is not None:
        items = [c for c in items if c["customer_id"] == q["customer_id"]]
    if q.get("family") is not None:
        items = [c for c in items if c["family"] == q["family"]]
    if q.get("status") is not None:
        items = [c for c in items if c["status"] == q["status"]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("CustomerContract", page), limit, offset, total)


@bp.route("/motion/contracts/<cid>", methods=["GET"])
@require_any
def get_contract_route(user_id, role, cid):
    return ok(serialize("CustomerContract", get_contract(cid)))


@bp.route("/motion/contracts/<cid>/activate", methods=["POST"])
@require_roles("ContractAdministrator")
def activate_contract(user_id, role, cid):
    c = get_contract(cid)
    # state (priority 5)
    if c["status"] != "DRAFT":
        raise err("ERR_CONTRACT_NOT_DRAFT", "activate requires contract DRAFT")
    # shape (priority 7)
    if c["effective_from"] >= c["effective_to"]:
        raise err("ERR_CONTRACT_WINDOW_INVALID", "effective_from must be < effective_to")
    if c["price_basis"] == "CONTRACT_FIXED" and c["fixed_unit_price_cents"] is None:
        raise err("ERR_CONTRACT_FIXED_PRICE_MISSING",
                  "CONTRACT_FIXED requires fixed_unit_price_cents")
    # half-open window non-overlap vs other ACTIVE contracts of (customer, family)
    for other in store.contracts.values():
        if (
            other["id"] != c["id"]
            and other["customer_id"] == c["customer_id"]
            and other["family"] == c["family"]
            and other["status"] == "ACTIVE"
            and c["effective_from"] < other["effective_to"]
            and other["effective_from"] < c["effective_to"]
        ):
            raise err("ERR_CONTRACT_WINDOW_OVERLAP",
                      "overlapping ACTIVE contract window for this customer and family")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(serialize("CustomerContract", c))


@bp.route("/motion/contracts/<cid>/terminate", methods=["POST"])
@require_roles("ContractAdministrator")
def terminate_contract(user_id, role, cid):
    c = get_contract(cid)
    if c["status"] not in ("DRAFT", "ACTIVE"):
        raise err("ERR_CONTRACT_NOT_TERMINABLE", "terminate requires DRAFT or ACTIVE")
    c["status"] = "TERMINATED"
    touch(c)
    return ok(serialize("CustomerContract", c))
