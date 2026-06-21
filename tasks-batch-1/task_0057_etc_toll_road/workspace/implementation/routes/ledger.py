from flask import Blueprint, request
import errors
from errors import err
from db import db
from middleware import get_auth, require_roles
from response import success
from util import paginate, sorted_by_created
from serialize import public, public_list

bp = Blueprint("ledger", __name__)

READ_ROLES = {"AccountHolder", "TollOperator", "SystemAdmin"}


@bp.get("/etc/ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    e = db.ledger_entries.get(entry_id)
    if e is None:
        raise err(errors.ERR_NOT_FOUND, "Ledger entry not found")
    return success(public(e))


@bp.get("/etc/ledger-entries")
def list_ledger_entries():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    items = list(db.ledger_entries.values())
    account_id = request.args.get("account_id")
    ref_tx = request.args.get("ref_transaction_id")
    ref_v = request.args.get("ref_violation_id")
    if account_id is not None:
        items = [e for e in items if e["account_id"] == account_id]
    if ref_tx is not None:
        items = [e for e in items if e.get("ref_transaction_id") == ref_tx]
    if ref_v is not None:
        items = [e for e in items if e.get("ref_violation_id") == ref_v]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)
