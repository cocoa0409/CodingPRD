"""Contract routes: CRUD + sign/activate/renew/terminate with ET-fee economics."""
from flask import Blueprint, request

import calc
from auth import require_auth, require_role
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, require_int, opt_bool, find, assert_owns_client,
    paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("contracts", __name__)


@bp.route("/contracts", methods=["POST"])
def create_contract():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    body = get_body()
    client_id = require_str(body, "client_id")
    retainer_id = require_str(body, "retainer_id")
    client = find("client", client_id)
    retainer = find("retainer", retainer_id)
    term_cycles = require_int(body, "term_cycles", minimum=1)
    auto_renew = opt_bool(body, "auto_renew", default=True)

    rec = base_record(versioned=True)
    rec.update({
        "client_id": client_id,
        "retainer_id": retainer_id,
        "term_cycles": term_cycles,
        "auto_renew": auto_renew,
        "early_termination_fee_cents": 0,
        "cycles_elapsed": 0,
        "status": "PENDING",
    })
    store.contracts[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    contract = find("contract", cid)
    client = find("client", contract["client_id"])
    assert_owns_client(principal, client)
    return ok_object(contract, 200)


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    parse_pagination()
    client_filter = request.args.get("client_id")
    retainer_filter = request.args.get("retainer_id")
    status_filter = request.args.get("status")
    records = list(store.contracts.values())
    if principal.role == "Client":
        records = [c for c in records if c["client_id"] == principal.user_id]
    elif principal.role == "Reseller":
        records = [c for c in records
                   if (cl := store.clients.get(c["client_id"])) is not None
                   and cl.get("reseller_id") == principal.user_id]
    if client_filter is not None:
        records = [c for c in records if c["client_id"] == client_filter]
    if retainer_filter is not None:
        records = [c for c in records if c["retainer_id"] == retainer_filter]
    if status_filter is not None:
        records = [c for c in records if c["status"] == status_filter]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


@bp.route("/contracts/<cid>/sign", methods=["POST"])
def sign_contract(cid):
    principal = require_auth()
    require_role(principal, ["Client"])
    contract = find("contract", cid)
    client = find("client", contract["client_id"])
    assert_owns_client(principal, client)
    if contract["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Contract must be PENDING to sign")
    retainer = find("retainer", contract["retainer_id"])
    if retainer["status"] not in ("DRAFT", "ACTIVE"):
        raise err("ERR_RETAINER_NOT_SIGNABLE", "Linked retainer must be DRAFT or ACTIVE")
    contract["status"] = "SIGNED"
    touch(contract)
    return ok_object(contract, 200)


@bp.route("/contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    contract = find("contract", cid)
    if contract["status"] not in ("SIGNED", "RENEWED"):
        raise err("ERR_INVALID_STATE", "Contract must be SIGNED or RENEWED to activate")
    retainer = find("retainer", contract["retainer_id"])

    if contract["status"] == "SIGNED":
        if retainer["status"] != "ACTIVE":
            raise err("ERR_RETAINER_NOT_ACTIVE", "Linked retainer must be ACTIVE")
        contract["early_termination_fee_cents"] = calc.early_termination_fee(
            contract["term_cycles"], contract["cycles_elapsed"], retainer["billing_price_cents"]
        )
        contract["status"] = "ACTIVE"
    else:  # RENEWED -> ACTIVE (new term begins)
        contract["status"] = "ACTIVE"
    touch(contract)
    return ok_object(contract, 200)


@bp.route("/contracts/<cid>/renew", methods=["POST"])
def renew_contract(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    contract = find("contract", cid)
    if contract["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Contract must be ACTIVE to renew")
    retainer = find("retainer", contract["retainer_id"])
    contract["cycles_elapsed"] = 0
    contract["early_termination_fee_cents"] = calc.early_termination_fee(
        contract["term_cycles"], contract["cycles_elapsed"], retainer["billing_price_cents"]
    )
    contract["status"] = "RENEWED"
    touch(contract)
    return ok_object(contract, 200)


@bp.route("/contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    contract = find("contract", cid)
    if contract["status"] not in ("SIGNED", "ACTIVE", "RENEWED"):
        raise err("ERR_INVALID_STATE", "Contract must be SIGNED, ACTIVE, or RENEWED to terminate")
    retainer = find("retainer", contract["retainer_id"])
    contract["early_termination_fee_cents"] = calc.early_termination_fee(
        contract["term_cycles"], contract["cycles_elapsed"], retainer["billing_price_cents"]
    )
    contract["status"] = "TERMINATED"
    touch(contract)
    return ok_object(contract, 200)
