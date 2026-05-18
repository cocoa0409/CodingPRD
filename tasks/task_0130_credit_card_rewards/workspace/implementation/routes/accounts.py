"""Account routes: create, fetch, mark-delinquent, clear-delinquency, close,
activate-category, list-activations, list-ledger.
"""
from __future__ import annotations

import re

from flask import Blueprint, g, request

from auth import is_cardholder, require_roles
from constants import (
    PRE_ACTIVATION_LEAD_DAYS,
    ROLE_CARDHOLDER,
    ROLE_PLATFORM_ADMIN,
)
from errors import err
from response import ok_array, ok_object
from serializers import (
    account_view,
    ledger_entry_view,
    quarterly_activation_view,
)
from services.account import (
    clear_delinquency,
    close_account,
    create_account,
    mark_delinquent,
    ownership_check,
)
from services.ledger import list_entries_for_account
from store import store
from utils import (
    add_days,
    fmt_iso,
    get_body,
    paginate,
    parse_pagination,
    quarter_window,
    require_str,
)

bp = Blueprint("accounts", __name__)

_QUARTER_RE = re.compile(r"^\d{4}Q[1-4]$")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _get_account_or_404(account_id: str) -> dict:
    a = store.accounts.get(account_id)
    if a is None:
        raise err("ERR_NOT_FOUND", "Account not found")
    return a


def _ownership_for_read(account: dict) -> None:
    if is_cardholder() and account["cardholder_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Cardholder does not own this account")


# -----------------------------------------------------------------------------
# CRUD
# -----------------------------------------------------------------------------
@bp.post("/accounts")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_account():
    body = get_body(request)
    cardholder_id = require_str(body, "cardholder_id")
    if cardholder_id not in store.cardholders:
        raise err("ERR_REFERENCE_NOT_FOUND", "cardholder_id does not resolve")

    with store.lock:
        acct = create_account(cardholder_id)
    return ok_object(account_view(acct), status=201)


@bp.get("/accounts/<account_id>")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def get_account(account_id: str):
    a = _get_account_or_404(account_id)
    _ownership_for_read(a)
    return ok_object(account_view(a))


# -----------------------------------------------------------------------------
# Lifecycle transitions
# -----------------------------------------------------------------------------
@bp.post("/accounts/<account_id>/mark-delinquent")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_mark_delinquent(account_id: str):
    a = _get_account_or_404(account_id)
    with store.lock:
        mark_delinquent(a)
    return ok_object(account_view(a))


@bp.post("/accounts/<account_id>/clear-delinquency")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_clear_delinquency(account_id: str):
    a = _get_account_or_404(account_id)
    with store.lock:
        clear_delinquency(a)
    return ok_object(account_view(a))


@bp.post("/accounts/<account_id>/close")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def post_close(account_id: str):
    a = _get_account_or_404(account_id)
    if is_cardholder():
        ownership_check(a, g.user_id)
    with store.lock:
        close_account(a)
    return ok_object(account_view(a))


# -----------------------------------------------------------------------------
# Quarterly activations
# -----------------------------------------------------------------------------
@bp.post("/accounts/<account_id>/activate-category")
@require_roles(ROLE_CARDHOLDER)
def post_activate_category(account_id: str):
    a = _get_account_or_404(account_id)
    ownership_check(a, g.user_id)

    body = get_body(request)
    category_id = require_str(body, "category_id")
    quarter_label = require_str(body, "quarter_label")

    # Body FK existence (priority 4)
    category = store.cashback_categories.get(category_id)
    if category is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "category_id does not resolve")

    # State: account must be ACTIVE (priority 6)
    if a["lifecycle_state"] == "CLOSED":
        raise err("ERR_ACCOUNT_CLOSED", "Account is closed")
    if a["lifecycle_state"] != "ACTIVE":
        raise err("ERR_ACCOUNT_CLOSED", f"Account not ACTIVE: {a['lifecycle_state']}")

    # Business: category must be ROTATING_QUARTERLY (priority 8)
    if category["category_type"] != "ROTATING_QUARTERLY":
        raise err(
            "ERR_CATEGORY_NOT_ACTIVATABLE",
            "Category is not activatable (only ROTATING_QUARTERLY)",
        )

    if not _QUARTER_RE.match(quarter_label):
        raise err("ERR_VALIDATION", "quarter_label must match /^\\d{4}Q[1-4]$/")

    # Window check (priority 9): now < activation_window_end AND
    # now >= activation_window_start - PRE_ACTIVATION_LEAD_DAYS
    start, end = quarter_window(quarter_label)
    now = store.now()
    earliest = add_days(start, -PRE_ACTIVATION_LEAD_DAYS)
    if now >= end or now < earliest:
        raise err(
            "ERR_ACTIVATION_WINDOW_CLOSED",
            "Activation window for this quarter is closed or too far in the future",
        )

    # Uniqueness (priority 10)
    uniq_key = (account_id, category_id, quarter_label)
    with store.lock:
        if uniq_key in store.activation_uniq:
            raise err(
                "ERR_ACTIVATION_ALREADY_EXISTS",
                "An activation already exists for (account, category, quarter)",
            )
        store.activation_uniq.add(uniq_key)
        aid = store.new_id()
        iso = store.now_iso()
        rec = {
            "id": aid,
            "account_id": account_id,
            "category_id": category_id,
            "quarter_label": quarter_label,
            "activation_window_start": fmt_iso(start),
            "activation_window_end": fmt_iso(end),
            "activated_at": iso,
            "status": "ACTIVATED",
            "created_at": iso,
        }
        store.quarterly_activations[aid] = rec

    return ok_object(quarterly_activation_view(rec), status=201)


@bp.get("/accounts/<account_id>/activations")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def get_activations(account_id: str):
    a = _get_account_or_404(account_id)
    _ownership_for_read(a)

    quarter_label = request.args.get("quarter_label")
    rows = [
        r for r in store.quarterly_activations.values() if r["account_id"] == account_id
    ]
    if quarter_label:
        rows = [r for r in rows if r["quarter_label"] == quarter_label]
    rows.sort(key=lambda r: (r["activated_at"], r["id"]))

    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(rows, limit, offset)
    return ok_array([quarterly_activation_view(r) for r in page], pagination)


# -----------------------------------------------------------------------------
# Ledger listing
# -----------------------------------------------------------------------------
@bp.get("/accounts/<account_id>/ledger")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def get_ledger(account_id: str):
    a = _get_account_or_404(account_id)
    _ownership_for_read(a)

    rows = list_entries_for_account(account_id)
    entry_type = request.args.get("entry_type")
    if entry_type:
        rows = [r for r in rows if r["entry_type"] == entry_type]

    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(rows, limit, offset)
    return ok_array([ledger_entry_view(r) for r in page], pagination)


# -----------------------------------------------------------------------------
# Transactions under an account
# -----------------------------------------------------------------------------
@bp.get("/accounts/<account_id>/transactions")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def get_account_transactions(account_id: str):
    from serializers import transaction_view

    a = _get_account_or_404(account_id)
    _ownership_for_read(a)

    rows = [t for t in store.transactions.values() if t["account_id"] == account_id]
    status_q = request.args.get("status")
    type_q = request.args.get("txn_type")
    if status_q:
        rows = [r for r in rows if r["status"] == status_q]
    if type_q:
        rows = [r for r in rows if r["txn_type"] == type_q]
    rows.sort(key=lambda r: (r["posted_at"], r["id"]))

    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(rows, limit, offset)
    return ok_array([transaction_view(r) for r in page], pagination)
