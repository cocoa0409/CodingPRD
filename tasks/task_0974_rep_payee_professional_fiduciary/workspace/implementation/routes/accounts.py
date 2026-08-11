"""Trust accounts + ledger endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_NOT_ZERO,
    ERR_ALREADY_TERMINAL,
    ERR_CLIENT_NOT_FOUND,
    ERR_DUPLICATE_UNIQUE_FIELD,
    ERR_INVALID_STATE,
    ERR_PENDING_DISBURSEMENTS,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_account, serialize_ledger_entry
from services.cascade import clock_now_iso
from services.derived import recompute_client_rollups, recompute_bond_rollups
from util import (
    new_id,
    parse_pagination,
    require_body,
    get_string,
    get_enum,
    reject_unexpected,
)

bp = Blueprint("accounts", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
ACCOUNT_TYPES = ("OPERATING", "RESTRICTED", "DEDICATED")


@bp.route("/trust-accounts", methods=["POST"])
def create_account():
    require_roles("FinancialOfficer")
    body = require_body()
    reject_unexpected(body, {"client_id", "account_type", "bank_account_ref"})
    client_id = get_string(body, "client_id")
    account_type = get_enum(body, "account_type", ACCOUNT_TYPES)
    ref = get_string(body, "bank_account_ref")

    if client_id not in store.clients:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")

    for a in store.accounts.values():
        if a["bank_account_ref"] == ref:
            raise err(ERR_DUPLICATE_UNIQUE_FIELD, 409, "bank_account_ref already in use")

    now = clock_now_iso()
    aid = new_id()
    acct = {
        "id": aid,
        "client_id": client_id,
        "account_type": account_type,
        "bank_account_ref": ref,
        "balance_cents": 0,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.accounts[aid] = acct
    recompute_client_rollups(client_id)
    recompute_bond_rollups()
    return success_object(serialize_account(acct), status=201)


@bp.route("/trust-accounts", methods=["GET"])
def list_accounts():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    account_type = request.args.get("account_type")
    status = request.args.get("status")
    items = list(store.accounts.values())
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    if account_type is not None:
        items = [a for a in items if a["account_type"] == account_type]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_account(a) for a in page], limit, offset, total)


@bp.route("/trust-accounts/<aid>", methods=["GET"])
def get_account(aid):
    require_roles(*READ_ROLES)
    a = store.accounts.get(aid)
    if not a:
        raise err(ERR_ACCOUNT_NOT_FOUND, 404, "account not found")
    return success_object(serialize_account(a))


@bp.route("/trust-accounts/<aid>/close", methods=["POST"])
def close_account(aid):
    require_roles("FinancialOfficer")
    a = store.accounts.get(aid)
    if not a:
        raise err(ERR_ACCOUNT_NOT_FOUND, 404, "account not found")
    if a["status"] == "CLOSED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Account is CLOSED")
    if a["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, 409, "Only OPEN -> CLOSED")
    # gates in order: balance zero, then no pending disbursements
    if a.get("balance_cents", 0) != 0:
        raise err(ERR_ACCOUNT_NOT_ZERO, 422, "balance_cents must be 0 to close")
    for d in store.disbursements.values():
        if d["account_id"] == aid and d["status"] in ("REQUESTED", "PENDING_CONSERVATOR", "APPROVED"):
            raise err(ERR_PENDING_DISBURSEMENTS, 422, "Account has pending disbursements")
    now = clock_now_iso()
    a["status"] = "CLOSED"
    a["updated_at"] = now
    a["version"] += 1
    recompute_client_rollups(a["client_id"])
    recompute_bond_rollups()
    return success_object(serialize_account(a))


@bp.route("/trust-accounts/<aid>/ledger", methods=["GET"])
def get_ledger(aid):
    require_roles(*READ_ROLES)
    a = store.accounts.get(aid)
    if not a:
        raise err(ERR_ACCOUNT_NOT_FOUND, 404, "account not found")
    limit, offset = parse_pagination()
    entry_type = request.args.get("entry_type")
    items = []
    for eid in store.ledger_order:
        e = store.ledger_entries[eid]
        if e["account_id"] != aid:
            continue
        if entry_type is not None and e["entry_type"] != entry_type:
            continue
        items.append(e)
    # already chronological by ledger_order insertion
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_ledger_entry(e) for e in page], limit, offset, total)
