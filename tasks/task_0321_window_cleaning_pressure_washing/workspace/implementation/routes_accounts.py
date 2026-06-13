"""Account, Property, Deposit, and clock endpoints."""
from flask import Blueprint

import db
from auth import require_roles
from clock import set_logical_now
from errors import err
from helpers import (
    REGIONS, body, get_or_404, paginate, pagination_params,
    post_ledger, req_int, req_number, req_str, req_enum,
    apply_quote_expiry,
)
from response import success, list_success
from serialize import public, public_list

bp = Blueprint("accounts", __name__)


# ---------------------------------------------------------------- Accounts
@bp.post("/accounts")
def create_account():
    require_roles({"Customer", "Billing"})
    data = body()
    company_name = req_str(data, "company_name")
    contact_email = req_str(data, "contact_email")
    region_code = req_enum(data, "region_code", REGIONS)
    # contact_email unique across accounts -> referential/business invalidity.
    for a in db.accounts.values():
        if a["contact_email"] == contact_email:
            raise err("ERR_INVALID_REQUEST", "contact_email must be unique")
    rec = db.new_record(db.accounts, {
        "company_name": company_name,
        "contact_email": contact_email,
        "region_code": region_code,
        "balance_cents": 0,
        "deposit_held_cents": 0,
        "status": "ACTIVE",
    })
    return success(public(rec), status=201)


@bp.get("/accounts/<rid>")
def read_account(rid):
    require_roles({"Customer", "Billing", "Dispatcher"})
    rec = get_or_404(db.accounts, rid)
    return success(public(rec))


@bp.get("/accounts/<rid>/ledger-entries")
def list_account_ledger(rid):
    require_roles({"Billing", "Customer"})
    get_or_404(db.accounts, rid)
    limit, offset = pagination_params()
    rows = [le for le in db.ledger_entries.values() if le["account_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/accounts/<rid>/properties")
def list_account_properties(rid):
    require_roles({"Customer", "Billing", "Dispatcher"})
    get_or_404(db.accounts, rid)
    limit, offset = pagination_params()
    rows = [p for p in db.properties.values() if p["account_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/accounts/<rid>/deposits")
def list_account_deposits(rid):
    require_roles({"Billing", "Customer"})
    get_or_404(db.accounts, rid)
    limit, offset = pagination_params()
    rows = [d for d in db.deposits.values() if d["account_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/accounts/<rid>/invoices")
def list_account_invoices(rid):
    require_roles({"Billing", "Customer"})
    get_or_404(db.accounts, rid)
    limit, offset = pagination_params()
    rows = [i for i in db.invoices.values() if i["account_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/accounts/<rid>/service-agreements")
def list_account_agreements(rid):
    require_roles({"Customer", "Billing"})
    get_or_404(db.accounts, rid)
    limit, offset = pagination_params()
    rows = [a for a in db.agreements.values() if a["account_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/accounts/<rid>/quotes")
def list_account_quotes(rid):
    require_roles({"Customer", "Billing"})
    get_or_404(db.accounts, rid)
    limit, offset = pagination_params()
    rows = [q for q in db.quotes.values() if q["account_id"] == rid]
    for q in rows:
        apply_quote_expiry(q)
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


# ---------------------------------------------------------------- Properties
@bp.post("/properties")
def create_property():
    require_roles({"Customer", "Billing"})
    data = body()
    account_id = req_str(data, "account_id")
    address_line = req_str(data, "address_line")
    pane_count = req_int(data, "pane_count")
    glass_sqft = req_number(data, "glass_sqft")
    stories = req_int(data, "stories")
    if pane_count < 0:
        raise err("ERR_INVALID_REQUEST", "pane_count must be >= 0")
    if glass_sqft < 0:
        raise err("ERR_INVALID_REQUEST", "glass_sqft must be >= 0")
    if stories < 1:
        raise err("ERR_INVALID_REQUEST", "stories must be >= 1")
    soft_wash_sqft = 0
    if data.get("soft_wash_sqft") is not None:
        soft_wash_sqft = req_number(data, "soft_wash_sqft")
        if soft_wash_sqft < 0:
            raise err("ERR_INVALID_REQUEST", "soft_wash_sqft must be >= 0")
    get_or_404(db.accounts, account_id)
    rec = db.new_record(db.properties, {
        "account_id": account_id,
        "address_line": address_line,
        "pane_count": pane_count,
        "glass_sqft": glass_sqft,
        "stories": stories,
        "soft_wash_sqft": soft_wash_sqft,
    })
    return success(public(rec), status=201)


@bp.get("/properties/<rid>")
def read_property(rid):
    require_roles({"Customer", "Billing", "Dispatcher"})
    rec = get_or_404(db.properties, rid)
    return success(public(rec))


# ---------------------------------------------------------------- Deposits
@bp.post("/deposits")
def create_deposit():
    require_roles({"Billing", "Customer"})
    data = body()
    account_id = req_str(data, "account_id")
    agreement_id = req_str(data, "agreement_id")
    amount_cents = req_int(data, "amount_cents")
    if amount_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    get_or_404(db.accounts, account_id)
    get_or_404(db.agreements, agreement_id)
    rec = db.new_record(db.deposits, {
        "account_id": account_id,
        "agreement_id": agreement_id,
        "amount_cents": amount_cents,
        "status": "HELD",
    })
    # DEPOSIT debit ledger entry (+amount_cents); recompute balances.
    post_ledger(account_id, "DEPOSIT", rec["id"], amount_cents)
    return success(public(rec), status=201)


@bp.get("/deposits/<rid>")
def read_deposit(rid):
    require_roles({"Billing", "Customer"})
    rec = get_or_404(db.deposits, rid)
    return success(public(rec))


# ---------------------------------------------------------------- Clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles({"Billing", "Dispatcher"})
    data = body()
    to_iso = req_str(data, "to_iso8601")
    try:
        set_logical_now(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    return success({}, status=200)
