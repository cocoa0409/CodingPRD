"""Deposits endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_NOT_OPEN,
    ERR_ALREADY_TERMINAL,
    ERR_BOND_COVERAGE_EXCEEDED,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_CLIENT_NOT_FOUND,
    ERR_DEPOSIT_NOT_FOUND,
    ERR_ENTITLEMENT_ACCOUNT_MISMATCH,
    ERR_ENTITLEMENT_NOT_FOUND,
    ERR_INVALID_STATE,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_deposit
from services.calcs import compute_provisional_excess
from services.cascade import clock_now_iso, clock_month_str
from services.derived import (
    append_ledger,
    recompute_client_rollups,
    recompute_bond_rollups,
)
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_int,
    get_enum,
    reject_unexpected,
)

bp = Blueprint("deposits", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
SOURCES = ("SSA_BENEFIT", "PENSION", "REFUND", "OTHER")


@bp.route("/deposits", methods=["POST"])
def create_deposit():
    require_roles("FinancialOfficer")
    body = require_body()
    reject_unexpected(body, {
        "account_id", "source", "amount_cents", "received_date", "entitlement_id",
    })
    account_id = get_string(body, "account_id")
    source = get_enum(body, "source", SOURCES)
    amount = get_int(body, "amount_cents", min_value=1)
    received = parse_date(get_string(body, "received_date"), "received_date")
    entitlement_id = body.get("entitlement_id")
    if entitlement_id is not None and not isinstance(entitlement_id, str):
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, 400, "entitlement_id must be a string or null")

    acct = store.accounts.get(account_id)
    if not acct:
        raise err(ERR_ACCOUNT_NOT_FOUND, 404, "account not found")
    ent = None
    if entitlement_id is not None:
        ent = store.entitlements.get(entitlement_id)
        if not ent:
            raise err(ERR_ENTITLEMENT_NOT_FOUND, 404, "entitlement not found")

    c = store.clients.get(acct["client_id"])
    if not c:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    if c["status"] == "TERMINATED":
        raise err(ERR_CLIENT_NOT_ACTIVE, 409, "Client is TERMINATED")

    # coherence: entitlement must belong to the account's client
    if ent is not None and ent["client_id"] != acct["client_id"]:
        raise err(ERR_ENTITLEMENT_ACCOUNT_MISMATCH, 422, "entitlement belongs to a different client")

    now = clock_now_iso()
    did = new_id()
    d = {
        "id": did,
        "account_id": account_id,
        "entitlement_id": entitlement_id,
        "source": source,
        "amount_cents": amount,
        "received_date": received,
        "posted_at": None,
        "status": "RECEIVED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.deposits[did] = d
    return success_object(serialize_deposit(d), status=201)


@bp.route("/deposits", methods=["GET"])
def list_deposits():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    entitlement_id = request.args.get("entitlement_id")
    source = request.args.get("source")
    status = request.args.get("status")
    items = list(store.deposits.values())
    if account_id is not None:
        items = [d for d in items if d["account_id"] == account_id]
    if entitlement_id is not None:
        items = [d for d in items if d.get("entitlement_id") == entitlement_id]
    if source is not None:
        items = [d for d in items if d["source"] == source]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_deposit(d) for d in page], limit, offset, total)


@bp.route("/deposits/<did>", methods=["GET"])
def get_deposit(did):
    require_roles(*READ_ROLES)
    d = store.deposits.get(did)
    if not d:
        raise err(ERR_DEPOSIT_NOT_FOUND, 404, "deposit not found")
    return success_object(serialize_deposit(d))


@bp.route("/deposits/<did>/post", methods=["POST"])
def post_deposit(did):
    require_roles("FinancialOfficer")
    d = store.deposits.get(did)
    if not d:
        raise err(ERR_DEPOSIT_NOT_FOUND, 404, "deposit not found")
    if d["status"] == "RETURNED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Deposit is RETURNED")
    if d["status"] != "RECEIVED":
        raise err(ERR_INVALID_STATE, 409, "Only RECEIVED -> POSTED")
    acct = store.accounts[d["account_id"]]
    if acct["status"] != "OPEN":
        raise err(ERR_ACCOUNT_NOT_OPEN, 409, "account not OPEN")

    # entitlement coherence at post
    if d.get("entitlement_id"):
        ent = store.entitlements.get(d["entitlement_id"])
        if ent and ent["client_id"] != acct["client_id"]:
            raise err(ERR_ENTITLEMENT_ACCOUNT_MISMATCH, 422, "entitlement belongs to a different client")

    # bond coverage check
    active_bonds = [b for b in store.bonds.values() if b["status"] == "ACTIVE"]
    if active_bonds:
        # choose the active bond (window overlap constraint means at most one)
        bond = active_bonds[0]
        fum_now = sum(
            a.get("balance_cents", 0)
            for a in store.accounts.values()
            if a["status"] in ("OPEN", "FROZEN")
        )
        if fum_now + d["amount_cents"] > bond["coverage_amount_cents"]:
            raise err(ERR_BOND_COVERAGE_EXCEEDED, 422, "post would exceed bond coverage")

    now = clock_now_iso()
    d["status"] = "POSTED"
    d["posted_at"] = now
    d["updated_at"] = now
    d["version"] += 1

    append_ledger(d["account_id"], "DEPOSIT_POSTED", d["amount_cents"], d["id"], now)
    recompute_client_rollups(acct["client_id"])
    recompute_bond_rollups()

    # auto-create spend-down plan when applicable
    client = store.clients[acct["client_id"]]
    current_month = clock_month_str()
    if (client["medicaid_enrolled"]
            and client["countable_resources_cents"] > client["medicaid_resource_limit_cents"]):
        exists = any(
            sp["client_id"] == client["id"]
            and sp["status"] in ("DRAFT", "ACTIVE")
            and sp["target_month"] == current_month
            for sp in store.spend_down_plans.values()
        )
        if not exists:
            sp_id = new_id()
            provisional = compute_provisional_excess(client, current_month)
            sp = {
                "id": sp_id,
                "client_id": client["id"],
                "target_month": current_month,
                "entries": [],
                "provisional_excess_cents": provisional,
                "final_excess_cents": None,
                "auto_created": True,
                "status": "DRAFT",
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            store.spend_down_plans[sp_id] = sp

    return success_object(serialize_deposit(d))


@bp.route("/deposits/<did>/return", methods=["POST"])
def return_deposit(did):
    require_roles("FinancialOfficer")
    d = store.deposits.get(did)
    if not d:
        raise err(ERR_DEPOSIT_NOT_FOUND, 404, "deposit not found")
    if d["status"] == "RETURNED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Deposit is RETURNED")
    if d["status"] != "POSTED":
        raise err(ERR_INVALID_STATE, 409, "Only POSTED -> RETURNED")
    now = clock_now_iso()
    d["status"] = "RETURNED"
    d["updated_at"] = now
    d["version"] += 1
    append_ledger(d["account_id"], "DEPOSIT_RETURNED", -d["amount_cents"], d["id"], now)
    acct = store.accounts[d["account_id"]]
    recompute_client_rollups(acct["client_id"])
    recompute_bond_rollups()
    return success_object(serialize_deposit(d))
