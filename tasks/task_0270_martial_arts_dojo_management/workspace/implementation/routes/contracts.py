"""Contracts: sign, buyout-quote, run-billing, terminate (PRD §3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_VALIDATION,
    ERR_INVALID_STATE,
)
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, require_int, parse_pagination, paginate,
    sort_by_created,
)
from services.serialize import view, view_list
from services.access import require_version_field, check_occ
from services import domain

bp = Blueprint("contracts", __name__)
TERM_MONTHS_ALLOWED = {3, 6, 12, 24}


@bp.post("/dojo/contracts")
def create_contract():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    body = get_json_body()
    require_fields(body, ["member_id", "program_id", "term_months", "billing_anchor_day"])

    # FK existence (priority 4)
    member = db.members.get(body["member_id"])
    if member is None:
        raise err(ERR_FK_NOT_FOUND, "member_id references a non-existent member.")
    program = db.programs.get(body["program_id"])
    if program is None:
        raise err(ERR_FK_NOT_FOUND, "program_id references a non-existent program.")

    # structural validity (priority 5): version field present + integer types
    supplied = require_version_field(body, "expected_member_version")
    if not isinstance(body["term_months"], int) or isinstance(body["term_months"], bool):
        raise err(ERR_INVALID_REQUEST, "term_months must be an integer.")
    if not isinstance(body["billing_anchor_day"], int) or isinstance(body["billing_anchor_day"], bool):
        raise err(ERR_INVALID_REQUEST, "billing_anchor_day must be an integer.")

    # OCC match (priority 7)
    check_occ(supplied, member["version"])

    # interval/business validation (priority 14, ERR_VALIDATION)
    if body["term_months"] not in TERM_MONTHS_ALLOWED:
        raise err(ERR_VALIDATION, "term_months must be one of {3,6,12,24}.")
    if not (1 <= body["billing_anchor_day"] <= 28):
        raise err(ERR_VALIDATION, "billing_anchor_day must be 1..28.")

    locked_pct = domain.live_family_discount_pct(member.get("family_id"))

    now = db.now_iso()
    cid = db.new_id()
    contract = {
        "id": cid,
        "member_id": body["member_id"],
        "program_id": body["program_id"],
        "term_months": body["term_months"],
        "billing_anchor_day": body["billing_anchor_day"],
        "months_billed": 0,
        "status": "ACTIVE",
        "locked_family_discount_pct": float(locked_pct),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.contracts[cid] = contract
    return success(view(contract), 201)


@bp.get("/dojo/contracts/<cid>")
def get_contract(cid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    contract = db.contracts.get(cid)
    if contract is None:
        raise err(ERR_NOT_FOUND, "Contract not found.")
    return success(view(contract), 200)


@bp.get("/dojo/contracts")
def list_contracts():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = []
    for c in db.contracts.values():
        if member_id is not None and c["member_id"] != member_id:
            continue
        if program_id is not None and c["program_id"] != program_id:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(c)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.get("/dojo/contracts/<cid>/buyout-quote")
def buyout_quote(cid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    contract = db.contracts.get(cid)
    if contract is None:
        raise err(ERR_NOT_FOUND, "Contract not found.")
    program = db.programs[contract["program_id"]]
    member = db.members[contract["member_id"]]
    remaining = contract["term_months"] - contract["months_billed"]
    if remaining < 0:
        remaining = 0
    live_pct = domain.live_family_discount_pct(member.get("family_id"))
    monthly = domain.recurring_tuition_amount(program, live_pct)
    provisional = domain.buyout_amount(remaining, monthly)
    return success({
        "provisional_buyout_cents": provisional,
        "remaining_months": remaining,
        "live_discount_pct": float(live_pct),
    }, 200)


@bp.post("/dojo/contracts/<cid>/run-billing")
def run_billing(cid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    contract = db.contracts.get(cid)
    if contract is None:
        raise err(ERR_NOT_FOUND, "Contract not found.")
    member = db.members[contract["member_id"]]
    program = db.programs[contract["program_id"]]

    # state preconditions (priority 8)
    if contract["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Contract not ACTIVE.")
    if not (contract["months_billed"] < contract["term_months"]):
        raise err(ERR_INVALID_STATE, "Contract term already fully billed.")
    if member["account_status"] == "WITHDRAWN":
        raise err(ERR_INVALID_STATE, "Owning member is WITHDRAWN.")

    amount = domain.recurring_tuition_amount(program, contract["locked_family_discount_pct"])
    domain.make_invoice(member["id"], "TUITION", amount, contract_id=contract["id"])
    contract["months_billed"] = contract["months_billed"] + 1
    # FULFILLED when the term is met
    if contract["months_billed"] == contract["term_months"]:
        contract["status"] = "FULFILLED"
    domain.touch(contract)
    # recompute balance — may auto-suspend (which cascades the contract PAST_DUE)
    domain.recompute_member_balance(member["id"])
    return success(view(contract), 200)


@bp.post("/dojo/contracts/<cid>/terminate")
def terminate_contract(cid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    contract = db.contracts.get(cid)
    if contract is None:
        raise err(ERR_NOT_FOUND, "Contract not found.")
    body = get_json_body()
    supplied = require_version_field(body, "expected_contract_version")
    check_occ(supplied, contract["version"])
    if contract["status"] not in ("ACTIVE", "PAST_DUE"):
        raise err(ERR_INVALID_STATE, "Contract not in a terminable state.")

    member = db.members[contract["member_id"]]
    program = db.programs[contract["program_id"]]
    contract["status"] = "TERMINATED"
    if contract["months_billed"] < contract["term_months"]:
        remaining = contract["term_months"] - contract["months_billed"]
        monthly = domain.recurring_tuition_amount(program, contract["locked_family_discount_pct"])
        amount = domain.buyout_amount(remaining, monthly)
        domain.make_invoice(member["id"], "BUYOUT", amount, contract_id=contract["id"])
    domain.touch(contract)  # version bump
    domain.recompute_member_balance(member["id"])
    return success(view(contract), 200)
