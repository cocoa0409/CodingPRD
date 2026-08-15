"""Account, statement, settle-entries, and ledger query endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_PARTICIPANT_NOT_ACTIVE,
    ERR_ACCOUNT_CLOSED,
    ERR_ACCOUNT_EXISTS,
    ERR_CROSS_PLAN_REFERENCE,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from routes.deferral_elections import ledger_entry_view
from services.core import (
    body,
    get_or_404,
    stamp_new,
    touch,
    recompute_account_balances,
    vested_bp_for,
    account_entries,
    recompute_trusts_for_plan,
)

bp = Blueprint("accounts", __name__)


def account_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "participant_id": a["participant_id"],
        "plan_id": a["plan_id"],
        "status": a["status"],
        "settled_balance_cents": a["settled_balance_cents"],
        "provisional_balance_cents": a["provisional_balance_cents"],
        "vested_balance_cents": a["vested_balance_cents"],
    }


@bp.post("/api/accounts")
def create_account():
    data = body()
    from errors import ERR_INVALID_REQUEST

    participant_id = data.get("participant_id")
    plan_id = data.get("plan_id")
    for f, v in (("participant_id", participant_id), ("plan_id", plan_id)):
        if not isinstance(v, str) or not v:
            raise_err(ERR_INVALID_REQUEST, f"{f} is required and must be a string")

    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    participant = get_or_404(db.participants, participant_id, "Participant")
    plan = get_or_404(db.plans, plan_id, "Plan")

    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to open an account")
    if participant["status"] != "ACTIVE":
        raise_err(ERR_PARTICIPANT_NOT_ACTIVE, "Participant must be ACTIVE to open an account")

    for a in db.accounts.values():
        if a["participant_id"] == participant_id and a["plan_id"] == plan_id:
            raise_err(ERR_ACCOUNT_EXISTS, "An account already exists for this participant and plan")

    if participant["plan_id"] != plan_id:
        raise_err(ERR_CROSS_PLAN_REFERENCE, "account.plan_id must equal participant.plan_id")

    account = stamp_new(
        {
            "participant_id": participant_id,
            "plan_id": plan_id,
            "status": "ACTIVE",
            "settled_balance_cents": 0,
            "provisional_balance_cents": 0,
            "vested_balance_cents": 0,
        }
    )
    db.accounts[account["id"]] = account
    return ok_object(account_view(account), 201)


@bp.get("/api/accounts")
def list_accounts():
    user_context()
    items = list(db.accounts.values())
    for f in ("participant_id", "plan_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    # Refresh derived balances on read
    for a in items:
        recompute_account_balances(a)
    return _list_response([account_view(a) for a in items], request.args)


@bp.get("/api/accounts/<accountId>")
def get_account(accountId):
    user_context()
    a = get_or_404(db.accounts, accountId, "Account")
    recompute_account_balances(a)
    return ok_object(account_view(a))


@bp.get("/api/accounts/<accountId>/statement")
def account_statement(accountId):
    user_context()
    a = get_or_404(db.accounts, accountId, "Account")
    recompute_account_balances(a)
    entries = account_entries(a["id"])
    participant = db.participants[a["participant_id"]]
    plan = db.plans[a["plan_id"]]
    posted = [e for e in entries if e["entry_status"] == "POSTED"]
    pending = [e for e in entries if e["entry_status"] == "PENDING"]
    total_deferred = sum(e["amount_cents"] for e in posted if e["entry_type"] == "DEFERRAL_CREDIT")
    total_distributed = -sum(e["amount_cents"] for e in posted if e["entry_type"] == "DISTRIBUTION_DEBIT")
    return ok_object(
        {
            "settled_balance_cents": a["settled_balance_cents"],
            "provisional_balance_cents": a["provisional_balance_cents"],
            "vested_balance_cents": a["vested_balance_cents"],
            "vested_bp": vested_bp_for(participant, plan),
            "pending_entries_count": len(pending),
            "posted_entries_count": len(posted),
            "total_deferred_cents": total_deferred,
            "total_distributed_cents": total_distributed,
        }
    )


@bp.post("/api/accounts/<accountId>/settle-entries")
def settle_entries(accountId):
    body()
    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    a = get_or_404(db.accounts, accountId, "Account")
    if a["status"] == "CLOSED":
        raise_err(ERR_ACCOUNT_CLOSED, "Account is CLOSED")
    for e in account_entries(a["id"]):
        if e["entry_status"] == "PENDING":
            e["entry_status"] = "POSTED"
    recompute_account_balances(a)
    touch(a)
    recompute_trusts_for_plan(a["plan_id"])
    return ok_object(account_view(a))


@bp.get("/api/ledger-entries")
def list_ledger_entries():
    user_context()
    items = list(db.ledger_entries.values())
    for f in ("account_id", "fund_id", "crediting_run_id", "election_id", "distribution_request_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e[f] == v]
    return _list_response([ledger_entry_view(e) for e in items], request.args)


@bp.get("/api/ledger-entries/<entryId>")
def get_ledger_entry(entryId):
    user_context()
    e = get_or_404(db.ledger_entries, entryId, "AccountLedgerEntry")
    return ok_object(ledger_entry_view(e))
