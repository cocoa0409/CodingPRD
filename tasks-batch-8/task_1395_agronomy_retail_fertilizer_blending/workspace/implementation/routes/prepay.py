"""PrepayProgram and PrepayContract routes."""

from flask import Blueprint, request, g

import db
from errors import (
    not_found, invalid_transition, business, stale,
    ERR_PROGRAM_NOT_ENROLLING, ERR_NO_CURRENT_PRICE, ERR_PREPAY_FUNDING_DEADLINE_PASSED,
    ERR_PREPAY_OVERFUND, ERR_CONTRACT_IN_USE, ERR_GROWER_NOT_ORDERABLE,
)
from middleware import require_roles, check_grower_ownership, ALL_ROLES
from response import success_object, success_list, iso8601_ms
from services.core import (
    scaffold_entity, touch, public, lazy_program, current_published_sheet,
    append_ledger, recompute_grower_balances,
)
from util import (
    get_body, require, reject_unknown, as_string, as_enum, as_number, as_int,
    parse_pagination, paginate, parse_instant, D, r0_int,
)

bp = Blueprint("prepay", __name__)

SEASONS = {"FALL", "SPRING"}


def _get_program(pid):
    x = db.prepay_programs.get(pid)
    if x is None:
        raise not_found("Prepay program not found")
    return x


def _get_contract(cid):
    x = db.prepay_contracts.get(cid)
    if x is None:
        raise not_found("Prepay contract not found")
    return x


def _get_grower(gid):
    x = db.growers.get(gid)
    if x is None:
        raise not_found("Grower not found")
    return x


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@bp.post("/agronomy/prepay-programs")
def create_program():
    require_roles("BranchAdmin")
    body = get_body()
    reject_unknown(body, {"name", "season", "enrollment_open_on", "enrollment_close_on",
                          "funding_deadline", "deposit_pct", "discount_pct", "default_penalty_pct"})
    name = as_string(require(body, "name"), "name")
    season = as_enum(require(body, "season"), "season", SEASONS)
    open_on = parse_instant(require(body, "enrollment_open_on"), "enrollment_open_on")
    close_on = parse_instant(require(body, "enrollment_close_on"), "enrollment_close_on")
    deadline = parse_instant(require(body, "funding_deadline"), "funding_deadline")
    deposit_pct = as_number(require(body, "deposit_pct"), "deposit_pct", minimum=0)
    discount_pct = as_number(require(body, "discount_pct"), "discount_pct", minimum=0)
    penalty_pct = as_number(require(body, "default_penalty_pct"), "default_penalty_pct", minimum=0)
    program = scaffold_entity(db.prepay_programs, {
        "name": name,
        "season": season,
        "enrollment_open_on": iso8601_ms(open_on),
        "enrollment_close_on": iso8601_ms(close_on),
        "funding_deadline": iso8601_ms(deadline),
        "deposit_pct": float(deposit_pct),
        "discount_pct": float(discount_pct),
        "default_penalty_pct": float(penalty_pct),
        "status": "ENROLLMENT_OPEN",
    })
    program["_enrollment_open_on"] = open_on
    program["_enrollment_close_on"] = close_on
    program["_funding_deadline"] = deadline
    return success_object(public(program), 201)


@bp.get("/agronomy/prepay-programs")
def list_programs():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.prepay_programs.values())
    for p in items:
        lazy_program(p)
    if "season" in request.args:
        items = [p for p in items if p["season"] == request.args["season"]]
    if "status" in request.args:
        items = [p for p in items if p["status"] == request.args["status"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/prepay-programs/<programId>")
def get_program(programId):
    require_roles(*ALL_ROLES)
    program = _get_program(programId)
    lazy_program(program)
    return success_object(public(program))


@bp.post("/agronomy/prepay-programs/<programId>/close-enrollment")
def close_enrollment(programId):
    require_roles("BranchAdmin")
    program = _get_program(programId)
    lazy_program(program)
    if program["status"] != "ENROLLMENT_OPEN":
        raise invalid_transition("Program not ENROLLMENT_OPEN")
    program["status"] = "ENROLLMENT_CLOSED"
    touch(program)
    return success_object(public(program))


@bp.post("/agronomy/prepay-programs/<programId>/settle")
def settle_program(programId):
    require_roles("BranchAdmin")
    program = _get_program(programId)
    lazy_program(program)
    if program["status"] != "ENROLLMENT_CLOSED":
        raise invalid_transition("Program not ENROLLMENT_CLOSED")
    if db.CLOCK.now() <= program["_funding_deadline"]:
        raise invalid_transition("funding window still open")

    # Cascade hop 1: default every SIGNED/PARTIALLY_FUNDED contract
    defaulted = [c for c in db.prepay_contracts.values()
                 if c["prepay_program_id"] == program["id"]
                 and c["status"] in ("SIGNED", "PARTIALLY_FUNDED")]
    defaulted.sort(key=lambda c: (c["created_at"], c["id"]))
    for c in defaulted:
        c["status"] = "DEFAULTED"
        # hop 2: forfeiture ledger entry
        forfeited = r0_int(D(c["funded_cents"]) * D(program["default_penalty_pct"]))
        c["forfeited_cents"] = forfeited
        grower = db.growers[c["grower_id"]]
        if forfeited > 0:
            append_ledger(grower["id"], "PREPAY_FORFEITED", -forfeited, c["id"])
        else:
            append_ledger(grower["id"], "PREPAY_FORFEITED", 0, c["id"])
        recompute_grower_balances(grower)
        touch(grower)
        touch(c)

    # hop 3: orders referencing defaulted contracts with PREPAY_APPLIED
    defaulted_ids = {c["id"] for c in defaulted}
    for order in db.blend_orders.values():
        if order.get("prepay_contract_id") in defaulted_ids and order["payment_status"] == "PREPAY_APPLIED":
            order["payment_status"] = "UNPAID"
            order["price_mode"] = "FLOATING"
            if order["fulfillment_status"] == "BOOKED":
                from services.orders import release_inventory
                release_inventory(order)
                order["fulfillment_status"] = "QUOTED"
            touch(order)

    program["status"] = "SETTLED"
    touch(program)
    return success_object(public(program))


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@bp.post("/agronomy/growers/<growerId>/prepay-contracts")
def create_contract(growerId):
    require_roles("Grower", "CreditManager")
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    body = get_body()
    reject_unknown(body, {"prepay_program_id", "product_id", "committed_tons", "expected_grower_version"})
    program_id = require(body, "prepay_program_id")
    product_id = require(body, "product_id")
    committed = as_number(require(body, "committed_tons"), "committed_tons", minimum=0, exclusive_min=True)
    expected_version = as_int(require(body, "expected_grower_version"), "expected_grower_version", minimum=0)
    # body FK resolution
    program = db.prepay_programs.get(program_id)
    if program is None:
        raise not_found("Prepay program not found")
    product = db.products.get(product_id)
    if product is None:
        raise not_found("Product not found")
    # OCC
    if expected_version != grower["version"]:
        raise stale("expected_grower_version does not match grower version")
    # grower must be ACTIVE
    if grower["credit_status"] != "ACTIVE":
        raise business(ERR_GROWER_NOT_ORDERABLE, 409, "Grower credit status is not ACTIVE")
    # program enrollment
    lazy_program(program)
    now = db.CLOCK.now()
    if program["status"] != "ENROLLMENT_OPEN" or not (
            program["_enrollment_open_on"] <= now <= program["_enrollment_close_on"]):
        raise business(ERR_PROGRAM_NOT_ENROLLING, 409, "Program not enrolling")
    # current price
    sheet = current_published_sheet(product["id"])
    if sheet is None:
        raise business(ERR_NO_CURRENT_PRICE, 422, "No current published price sheet")
    unit_price = r0_int(D(sheet["price_per_ton_cents"]) * (D(1) - D(program["discount_pct"])))
    contract_value = r0_int(D(unit_price) * committed)
    deposit_due = r0_int(D(contract_value) * D(program["deposit_pct"]))
    contract = scaffold_entity(db.prepay_contracts, {
        "grower_id": grower["id"],
        "prepay_program_id": program["id"],
        "product_id": product["id"],
        "committed_tons": float(committed),
        "unit_price_cents": unit_price,
        "contract_value_cents": contract_value,
        "deposit_due_cents": deposit_due,
        "funded_cents": 0,
        "drawn_cents": 0,
        "forfeited_cents": 0,
        "status": "SIGNED",
    })
    touch(grower)
    return success_object(public(contract), 201)


@bp.get("/agronomy/growers/<growerId>/prepay-contracts")
def list_grower_contracts(growerId):
    require_roles(*ALL_ROLES)
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    limit, offset = parse_pagination()
    items = [c for c in db.prepay_contracts.values() if c["grower_id"] == grower["id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/prepay-contracts")
def list_contracts():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.prepay_contracts.values())
    if "prepay_program_id" in request.args:
        items = [c for c in items if c["prepay_program_id"] == request.args["prepay_program_id"]]
    if "product_id" in request.args:
        items = [c for c in items if c["product_id"] == request.args["product_id"]]
    if "grower_id" in request.args:
        items = [c for c in items if c["grower_id"] == request.args["grower_id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    if g.role == "Grower":
        items = [c for c in items if c["grower_id"] == g.user_id]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/prepay-contracts/<contractId>")
def get_contract(contractId):
    require_roles(*ALL_ROLES)
    contract = _get_contract(contractId)
    check_grower_ownership(contract["grower_id"])
    return success_object(public(contract))


@bp.post("/agronomy/prepay-contracts/<contractId>/fund")
def fund_contract(contractId):
    require_roles("CreditManager")
    contract = _get_contract(contractId)
    body = get_body()
    reject_unknown(body, {"amount_cents"})
    amount = as_int(require(body, "amount_cents"), "amount_cents", minimum=1)
    program = db.prepay_programs[contract["prepay_program_id"]]
    lazy_program(program)
    if contract["status"] not in ("SIGNED", "PARTIALLY_FUNDED"):
        raise invalid_transition("Contract not in SIGNED or PARTIALLY_FUNDED")
    if db.CLOCK.now() > program["_funding_deadline"]:
        raise business(ERR_PREPAY_FUNDING_DEADLINE_PASSED, 409, "Funding deadline passed")
    if contract["funded_cents"] + amount > contract["contract_value_cents"]:
        raise business(ERR_PREPAY_OVERFUND, 422, "Funding would exceed contract value")
    contract["funded_cents"] += amount
    grower = db.growers[contract["grower_id"]]
    append_ledger(grower["id"], "PREPAY_FUNDED", amount, contract["id"])
    recompute_grower_balances(grower)
    if contract["funded_cents"] >= contract["contract_value_cents"]:
        contract["status"] = "FUNDED"
    else:
        contract["status"] = "PARTIALLY_FUNDED"
    touch(contract)
    touch(grower)
    return success_object(public(contract))


@bp.post("/agronomy/prepay-contracts/<contractId>/refund")
def refund_contract(contractId):
    require_roles("CreditManager")
    contract = _get_contract(contractId)
    if contract["status"] not in ("FUNDED", "PARTIALLY_FUNDED"):
        raise invalid_transition("Contract not in FUNDED or PARTIALLY_FUNDED")
    # contract-in-use
    for order in db.blend_orders.values():
        if order.get("prepay_contract_id") == contract["id"] \
                and order["payment_status"] not in ("PAID", "CANCELLED"):
            raise business(ERR_CONTRACT_IN_USE, 409, "Contract referenced by an open order")
    refund_amount = contract["funded_cents"] - contract["drawn_cents"]
    grower = db.growers[contract["grower_id"]]
    append_ledger(grower["id"], "PREPAY_REFUNDED", -refund_amount, contract["id"])
    recompute_grower_balances(grower)
    contract["status"] = "REFUNDED"
    touch(contract)
    touch(grower)
    return success_object(public(contract))
