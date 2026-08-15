"""Contracts: disburse advance, exercise option, terminate; recoupment accounts."""

from flask import Blueprint

from db import db, today
from errors import raise_err
from helpers import (
    get_body, touch, serialize, get_or_404, list_page, apply_filters,
    add_months, v_bool,
)
from middleware import auth, check_ownership
from response import ok, ok_list
from services.calc import effective_base_rate_bps, recompute_account_totals
from services.domain import (
    has_open_memo, account_of_contract, artist_of_contract, label_of_contract,
)

bp = Blueprint("contracts", __name__)


@bp.get("/api/contracts/<cid>")
def get_contract(cid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    contract = get_or_404(db.contracts, cid)
    check_ownership(role, uid, contract["artist_id"])
    return ok(serialize(contract))


@bp.get("/api/contracts")
def list_contracts():
    auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager"])
    def _label_id(c):
        artist = db.artists.get(c["artist_id"])
        return artist["label_id"] if artist else ""
    items = apply_filters(db.contracts.values(), [
        ("label_id", _label_id),
        ("artist_id", lambda c: c["artist_id"]),
        ("deal_memo_id", lambda c: c["deal_memo_id"]),
        ("status", lambda c: c["status"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/contracts/<cid>/disburse-advance")
def disburse_advance(cid):
    auth(["FinanceController"])
    contract = get_or_404(db.contracts, cid)
    get_body()
    if contract["advance_status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "Advance is not PENDING")
    account = account_of_contract(cid)
    account["advance_balance_cents"] += contract["advance_cents"]
    recompute_account_totals(account)
    touch(account)
    contract["advance_status"] = "FUNDED"
    touch(contract)
    return ok(serialize(contract))


@bp.post("/api/contracts/<cid>/exercise-option")
def exercise_option(cid):
    auth(["LabelAdmin"])
    contract = get_or_404(db.contracts, cid)
    get_body()
    if contract["status"] != "OPTION_WINDOW":
        raise_err("ERR_INVALID_STATE", "Contract is not in its option window")
    # Referential gate (renegotiation) precedes the temporal gate per validation order.
    if has_open_memo(contract["artist_id"]):
        raise_err("ERR_RENEGOTIATION_IN_PROGRESS",
                  "An open deal memo exists for this artist")
    if today() > contract["_current_term_end_date"]:
        raise_err("ERR_OPTION_WINDOW_CLOSED", "current_term_end_date has passed")
    contract["options_exercised"] += 1
    new_end = add_months(contract["_current_term_end_date"], contract["option_term_months"])
    contract["_current_term_end_date"] = new_end
    contract["current_term_end_date"] = new_end.isoformat()
    contract["effective_base_rate_bps"] = effective_base_rate_bps(contract)
    contract["status"] = "EXTENDED"
    touch(contract)
    return ok(serialize(contract))


@bp.post("/api/contracts/<cid>/terminate")
def terminate_contract(cid):
    auth(["LabelAdmin"])
    contract = get_or_404(db.contracts, cid)
    body = get_body()
    write_off = v_bool(body, "write_off_unrecouped")
    if contract["status"] not in ("ACTIVE", "OPTION_WINDOW", "EXTENDED"):
        raise_err("ERR_INVALID_STATE", "Contract in %s cannot be terminated" % contract["status"])
    account = account_of_contract(cid)
    if account["total_unrecouped_cents"] > 0 and write_off is not True:
        raise_err("ERR_UNRECOUPED_BALANCE",
                  "Unrecouped balance must be written off to terminate")
    if write_off is True and account["total_unrecouped_cents"] > 0:
        account["writeoff_cents"] = account["total_unrecouped_cents"]
        account["recording_balance_cents"] = 0
        account["advance_balance_cents"] = 0
        account["tour_support_balance_cents"] = 0
        account["promo_balance_cents"] = 0
        recompute_account_totals(account)
        touch(account)
    contract["status"] = "TERMINATED"
    touch(contract)
    return ok(serialize(contract))


@bp.get("/api/contracts/<cid>/recoupment-accounts")
def contract_accounts(cid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    contract = get_or_404(db.contracts, cid)
    check_ownership(role, uid, contract["artist_id"])
    account = account_of_contract(cid)
    items = [account] if account is not None else []
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.get("/api/recoupment-accounts/<aid>")
def get_account(aid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    account = get_or_404(db.recoupment_accounts, aid)
    contract = db.contracts.get(account["contract_id"])
    check_ownership(role, uid, contract["artist_id"] if contract else None)
    return ok(serialize(account))
