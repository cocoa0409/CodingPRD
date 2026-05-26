"""ParentAccount, top-up, and ledger routes."""
from flask import Blueprint, request
import db
from response import success_object, success_array, iso_utc
from middleware import require_role
from validation import (
    parse_pagination, get_json_body, enforce_keys, require_str, require_int,
)
from services import (
    common_fields_init, common_fields_init_no_version, bump_version,
    get_or_404, sort_by_created_at, paginate, clean, now,
    compute_balance, serialize_parent_account,
)
from calculations import DAILY_TOPUP_CAP_CENTS
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_TOPUP_CAP_EXCEEDED,
    ERR_DUPLICATE_IDEMPOTENCY_KEY, raise_err,
)

bp = Blueprint("parent_accounts", __name__)


@bp.get("/school-meals/parent-accounts/<aid>")
def read_parent_account(aid):
    from middleware import get_auth
    user_id, role = get_auth()
    if role not in {"Parent", "SchoolStaff", "DistrictReviewer"}:
        from errors import ERR_FORBIDDEN
        raise_err(ERR_FORBIDDEN, "role not allowed")
    rec = get_or_404(db.parent_accounts, aid, "ParentAccount")
    if role == "Parent" and user_id != rec["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this account")
    return success_object(clean(serialize_parent_account(rec)))


@bp.post("/school-meals/parent-accounts/<aid>/topup")
def topup(aid):
    user_id, role = require_role({"Parent"})
    rec = get_or_404(db.parent_accounts, aid, "ParentAccount")
    if user_id != rec["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this account")
    body = get_json_body()
    enforce_keys(body, required={"amount_cents", "idempotency_key"}, optional=set())
    require_int(body["amount_cents"], "amount_cents", min_val=1)
    require_str(body["idempotency_key"], "idempotency_key")
    amount = body["amount_cents"]
    key = body["idempotency_key"]

    # Idempotency check: same key on same account.
    # PRD §3.6: same key + same amount → return prior entry, no new entry.
    #           same key + different amount → ERR_DUPLICATE_IDEMPOTENCY_KEY (409).
    for entry in db.ledger_entries.values():
        if (
            entry["parent_account_id"] == aid
            and entry["entry_type"] == "TOPUP"
            and entry.get("idempotency_key") == key
        ):
            if entry["amount_cents"] == amount:
                return success_object(clean(entry), status=201)
            raise_err(ERR_DUPLICATE_IDEMPOTENCY_KEY, "idempotency_key already used with different amount")

    # Roll daily window if needed.
    n = now()
    today_str = n.strftime("%Y-%m-%d")
    if rec.get("daily_topup_window_date") != today_str:
        rec["daily_topup_total_cents"] = 0
        rec["daily_topup_window_date"] = today_str

    # Cap check.
    if rec["daily_topup_total_cents"] + amount > DAILY_TOPUP_CAP_CENTS:
        raise_err(ERR_TOPUP_CAP_EXCEEDED, "daily top-up cap exceeded")

    # Create ledger entry (no version / no updated_at on LedgerEntry per §2.4).
    entry = {
        **common_fields_init_no_version(),
        "parent_account_id": aid,
        "entry_type": "TOPUP",
        "amount_cents": amount,
        "linked_transaction_id": None,
        "idempotency_key": key,
    }
    db.ledger_entries[entry["id"]] = entry

    # Update window total and reconcile balance.
    rec["daily_topup_total_cents"] += amount
    rec["balance_cents"] = compute_balance(aid)
    bump_version(rec)

    return success_object(clean(entry), status=201)


@bp.get("/school-meals/parent-accounts/<aid>/ledger")
def list_account_ledger(aid):
    from middleware import get_auth
    user_id, role = get_auth()
    if role not in {"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"}:
        from errors import ERR_FORBIDDEN
        raise_err(ERR_FORBIDDEN, "role not allowed")
    rec = get_or_404(db.parent_accounts, aid, "ParentAccount")
    if role == "Parent" and user_id != rec["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this account")
    limit, offset = parse_pagination()
    entry_type = request.args.get("entry_type")
    items = [e for e in db.ledger_entries.values() if e["parent_account_id"] == aid]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


@bp.get("/school-meals/ledger-entries/<lid>")
def read_ledger_entry(lid):
    from middleware import get_auth
    user_id, role = get_auth()
    if role not in {"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"}:
        from errors import ERR_FORBIDDEN
        raise_err(ERR_FORBIDDEN, "role not allowed")
    rec = get_or_404(db.ledger_entries, lid, "LedgerEntry")
    if role == "Parent":
        acct = db.parent_accounts.get(rec["parent_account_id"])
        if acct is None or user_id != acct["household_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this entry")
    return success_object(clean(rec))


@bp.get("/school-meals/ledger-entries")
def list_ledger_entries():
    require_role({"SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    limit, offset = parse_pagination()
    parent_account_id = request.args.get("parent_account_id")
    linked_txn = request.args.get("linked_transaction_id")
    entry_type = request.args.get("entry_type")
    items = list(db.ledger_entries.values())
    if parent_account_id is not None:
        items = [e for e in items if e["parent_account_id"] == parent_account_id]
    if linked_txn is not None:
        items = [e for e in items if e.get("linked_transaction_id") == linked_txn]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)
