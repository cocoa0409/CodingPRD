"""Ledger entry read endpoints (reverse reachability)."""

from flask import request

from .auth import require, require_owner
from .blueprint import bp
from .envelope import ok_list
from .errors import not_found
from .serialize import ser_ledger_entry
from .store import STORE
from .util import paged, pagination_params, sort_created


@bp.get("/freelance-desk/contributors/<cid>/ledger-entries")
def list_contributor_ledger(cid):
    uid, role = require(["DeskAdmin", "FinanceUser", "Contributor"])
    if cid not in STORE.contributors:
        not_found("Contributor")
    if role == "Contributor":
        require_owner(uid, cid)
    items = [e for e in STORE.ledger_entries.values() if e["contributor_id"] == cid]
    kind = request.args.get("entry_kind")
    if kind:
        items = [e for e in items if e["entry_kind"] == kind]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_ledger_entry(e) for e in page], limit, offset, total)


@bp.get("/freelance-desk/invoices/<iid>/ledger-entries")
def list_invoice_ledger(iid):
    require(["DeskAdmin", "FinanceUser"])
    if iid not in STORE.invoices:
        not_found("Invoice")
    items = [e for e in STORE.ledger_entries.values() if e["invoice_id"] == iid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_ledger_entry(e) for e in page], limit, offset, total)
