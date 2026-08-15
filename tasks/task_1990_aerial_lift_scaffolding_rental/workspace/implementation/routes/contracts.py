"""Rental contracts: create, list, read, activate, close, invoice."""
from flask import Blueprint, request

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles, forbid
from response import ok, created, paginate
from services import calc, domain
from validation import validate_body

bp = Blueprint("contracts", __name__)


def _load_contract(cid):
    contract = store.contracts.get(cid)
    if contract is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Rental contract not found")
    return contract


def _check_customer_owns(contract, uid, role):
    if role == "Customer" and contract["customer_id"] != uid:
        forbid("A Customer may access only its own contracts")


@bp.post("/rental-contracts")
def create_contract():
    uid, role = get_context()
    require_roles(["RentalCoordinator"])
    body = validate_body({
        "customer_id": ("string", True),
        "jobsite_address": ("string", True),
        "damage_waiver_elected": ("boolean", False, {"default": False}),
    })
    customer = store.customers.get(body["customer_id"])
    if customer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer account not found")
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 402,
                       "Suspended customers cannot open new contracts")
    contract = db.new_common({
        "id": db.new_id(),
        "customer_id": body["customer_id"],
        "jobsite_address": body["jobsite_address"],
        "damage_waiver_elected": body["damage_waiver_elected"],
        "status": "DRAFT",
        "closed_at": None,
    })
    store.contracts[contract["id"]] = contract
    return created(domain.view_contract(contract))


@bp.get("/rental-contracts")
def list_contracts():
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    rows = list(store.contracts.values())
    if role == "Customer":
        requested = request.args.get("customer_id")
        if requested is not None and requested != uid:
            forbid("A Customer's listing is restricted to its own account")
        rows = [c for c in rows if c["customer_id"] == uid]
    else:
        rows = paginate.filter(rows, "customer_id")
    rows = paginate.filter(rows, "status")
    rows = [domain.view_contract(c) for c in rows]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/rental-contracts/<cid>")
def get_contract(cid):
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    contract = _load_contract(cid)
    _check_customer_owns(contract, uid, role)
    return ok(domain.view_contract(contract))


@bp.post("/rental-contracts/<cid>/activate")
def activate_contract(cid):
    uid, role = get_context()
    require_roles(["RentalCoordinator"])
    contract = _load_contract(cid)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not DRAFT")
    has_reserved = any(
        l["contract_id"] == cid and l["status"] == "RESERVED"
        for l in store.lines.values())
    if not has_reserved:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Activation requires at least one RESERVED line")
    customer = store.customers[contract["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 402,
                       "Suspended customers cannot activate contracts")
    provisional_sum = sum(
        calc.provisional_charge_cents(l)
        for l in store.lines.values()
        if l["contract_id"] == cid and l["status"] != "CANCELLED")
    if (calc.customer_balance_cents(customer["id"]) + provisional_sum
            > customer["credit_limit_cents"]):
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                       "Activation would exceed the customer's credit limit")
    contract["status"] = "ACTIVE"
    db.touch(contract)
    calc.maybe_suspend(customer)
    return ok(domain.view_contract(contract))


@bp.post("/rental-contracts/<cid>/close")
def close_contract(cid):
    uid, role = get_context()
    require_roles(["RentalCoordinator"])
    contract = _load_contract(cid)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not ACTIVE")
    for line in store.lines.values():
        if line["contract_id"] == cid and line["status"] not in ("RETURNED", "CANCELLED"):
            raise ApiError("ERR_LINES_OUTSTANDING", 409,
                           "Every line must be RETURNED or CANCELLED before close")
    for claim in store.claims.values():
        if claim["contract_id"] == cid and claim["status"] in ("OPEN", "ASSESSED", "DISPUTED"):
            raise ApiError("ERR_OPEN_CLAIMS_EXIST", 409,
                           "Open, assessed, or disputed claims block close")
    contract["status"] = "CLOSED"
    contract["closed_at"] = db.logical_stamp()
    db.touch(contract)
    customer = store.customers.get(contract["customer_id"])
    if customer is not None:
        calc.maybe_suspend(customer)
    return ok(domain.view_contract(contract))


@bp.get("/rental-contracts/<cid>/invoice")
def get_invoice(cid):
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    contract = _load_contract(cid)
    _check_customer_owns(contract, uid, role)
    return ok(domain.invoice_view(contract))
