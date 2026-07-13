"""Financial accounts and placement facilities (PRD 3.4, 3.5)."""
from flask import Blueprint, request

from store import store
from envelope import success
from helpers import (authenticate, authorize, get_body, require_str, require_int,
                     resolve, resolve_body_id, base_fields, paginate, sort_key, serialize)

bp = Blueprint("accounts", __name__)


@bp.post("/accounts")
def create_account():
    uid, role = authenticate()
    authorize(role, {"IntakeWorker", "Caseworker"})
    body = get_body()
    resolve_body_id(body, "client_id", "client")
    client_id = require_str(body, "client_id")
    institution_name = require_str(body, "institution_name")
    total = require_int(body, "total_balance_cents")

    account = base_fields()
    account.update({
        "client_id": client_id,
        "institution_name": institution_name,
        "total_balance_cents": total,
        "frozen_amount_cents": 0,
        "available_balance_cents": total,
        "status": "ACTIVE",
        "flagged_amount_cents": 0,
        "restitution_cents": 0,
    })
    store.accounts[account["id"]] = account
    return success(serialize(account, "account")), 201


@bp.get("/accounts/<aid>")
def get_account(aid):
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    account = resolve("account", aid)
    return success(serialize(account, "account")), 200


@bp.get("/accounts")
def list_accounts():
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    items = list(store.accounts.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    items.sort(key=sort_key)
    page, pag = paginate(items)
    return success([serialize(a, "account") for a in page], "array", pag), 200


@bp.post("/facilities")
def create_facility():
    uid, role = authenticate()
    authorize(role, {"Admin"})
    body = get_body()
    name = require_str(body, "name")
    total_beds = require_int(body, "total_beds")

    facility = base_fields()
    facility.update({
        "name": name,
        "total_beds": total_beds,
        "occupied_beds": 0,
        "available_beds": total_beds,
    })
    store.facilities[facility["id"]] = facility
    return success(serialize(facility, "facility")), 201


@bp.get("/facilities/<fid>")
def get_facility(fid):
    uid, role = authenticate()
    authorize(role, {"Admin", "Caseworker", "Supervisor"})
    facility = resolve("facility", fid)
    return success(serialize(facility, "facility")), 200
