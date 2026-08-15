"""DecliningBalanceAccount, LedgerEntry and RefundRequest endpoints
(PRD 3.5, 3.7)."""

import json

from flask import Blueprint, g, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE_TRANSITION, ERR_STALE_VERSION, ERR_ACCOUNT_FROZEN,
    ERR_ACCOUNT_NOT_CLOSABLE, ERR_ACCOUNT_UNIQUENESS,
    ERR_IDEMPOTENCY_CONFLICT, ERR_PENDING_REFUND_EXISTS,
    ERR_REFUND_BELOW_MINIMUM, ERR_SOD_ADJUSTER_CANNOT_APPROVE,
    ERR_SOD_PAYER_IS_APPROVER,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_int, v_enum, find_or_404,
    pub, paginate,
)
from response import success
from services.core import new_row, touch
from services.ledger import post_entry, ALL_ENTRY_TYPES
from services.pricing import refund_amount, MIN_REFUND_CENTS

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = {"DINING_DOLLARS", "CAMPUS_CASH"}
NON_TERMINAL_ACCOUNT = {"OPEN", "FROZEN", "CLOSE_PENDING"}


# ------------------------------------------------------------------ accounts
@bp.route("/api/card-holders/<hid>/accounts", methods=["POST"])
def create_account(hid):
    authenticate()
    require_roles("BursarOffice", "CardOfficeAdmin")
    body = get_body()
    account_type = v_enum(body, "account_type", ACCOUNT_TYPES)
    term_id = body.get("term_id")
    if account_type == "DINING_DOLLARS":
        if term_id is None:
            err(ERR_VALIDATION, "term_id is required for DINING_DOLLARS accounts")
        if not isinstance(term_id, str):
            err(ERR_VALIDATION, "term_id must be a string")
    else:
        if term_id is not None:
            err(ERR_VALIDATION, "term_id must be null for CAMPUS_CASH accounts")
    holder = find_or_404(store.holders, hid)
    if account_type == "DINING_DOLLARS":
        find_or_404(store.terms, term_id)
    for a in store.accounts.values():
        if (a["holder_id"] == holder["id"]
                and a["account_type"] == account_type
                and a.get("term_id") == (term_id if account_type == "DINING_DOLLARS" else None)
                and a["status"] in NON_TERMINAL_ACCOUNT):
            err(ERR_ACCOUNT_UNIQUENESS,
                "A non-terminal account already exists for this holder, type and term")
    acct = new_row()
    acct.update({
        "holder_id": holder["id"],
        "account_type": account_type,
        "term_id": term_id if account_type == "DINING_DOLLARS" else None,
        "balance_cents": 0,
        "status": "OPEN",
        "frozen_reason": None,
        "last_adjusted_by": None,
    })
    store.accounts[acct["id"]] = acct
    return success(pub(acct), 201)


def _own_account_or_403(acct):
    if g.role == "CardHolder" and acct["holder_id"] != g.user_id:
        err(ERR_NOT_RESOURCE_OWNER, "CardHolder may act only on its own accounts")


@bp.route("/api/accounts", methods=["GET"])
def list_accounts():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice", "CardHolder")
    rows = list(store.accounts.values())
    if g.role == "CardHolder":
        rows = [a for a in rows if a["holder_id"] == g.user_id]
    holder_id = request.args.get("holder_id")
    account_type = request.args.get("account_type")
    term_id = request.args.get("term_id")
    status = request.args.get("status")
    if holder_id is not None:
        if g.role == "CardHolder" and holder_id != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder")
        rows = [a for a in rows if a["holder_id"] == holder_id]
    if account_type is not None:
        rows = [a for a in rows if a["account_type"] == account_type]
    if term_id is not None:
        rows = [a for a in rows if a.get("term_id") == term_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/accounts/<aid>", methods=["GET"])
def get_account(aid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice", "CardHolder")
    acct = store.accounts.get(aid)
    if acct is not None:
        _own_account_or_403(acct)
    if acct is None:
        err(ERR_NOT_FOUND, "Account not found")
    return success(pub(acct), 200)


@bp.route("/api/accounts/<aid>/funding", methods=["POST"])
def fund_account(aid):
    authenticate()
    require_roles("CardHolder", "BursarOffice")
    acct = store.accounts.get(aid)
    if acct is not None:
        _own_account_or_403(acct)
    body = get_body()
    amount_cents = v_int(body, "amount_cents", min_v=1)
    idempotency_key = v_str(body, "idempotency_key")
    if acct is None:
        err(ERR_NOT_FOUND, "Account not found")
    idem_key = f"funding:{idempotency_key}"
    payload = json.dumps({"account_id": aid, "body": body}, sort_keys=True)
    prior = store.idempotency.get(idem_key)
    if prior is not None:
        if prior["payload"] == payload:
            return success(prior["data"], 201)
        err(ERR_IDEMPOTENCY_CONFLICT,
            "idempotency_key was already used with a divergent payload")
    if acct["status"] != "OPEN":
        err(ERR_ACCOUNT_FROZEN, "Funding requires an OPEN account")
    entry = post_entry(acct, "FUND", amount_cents, "Account funding")
    data = pub(entry)
    store.idempotency[idem_key] = {"payload": payload, "data": data}
    return success(data, 201)


@bp.route("/api/accounts/<aid>/adjustments", methods=["POST"])
def adjust_account(aid):
    authenticate()
    require_roles("BursarOffice")
    body = get_body()
    amount_cents = v_int(body, "amount_cents", min_v=1)
    direction = v_str(body, "direction")
    if direction == "CREDIT":
        direction = "ADJUSTMENT_CREDIT"
    elif direction == "DEBIT":
        direction = "ADJUSTMENT_DEBIT"
    if direction not in ("ADJUSTMENT_CREDIT", "ADJUSTMENT_DEBIT"):
        err(ERR_VALIDATION,
            "direction must select an ADJUSTMENT_CREDIT or ADJUSTMENT_DEBIT")
    reason = v_str(body, "reason")
    expected_version = v_int(body, "expected_account_version")
    acct = find_or_404(store.accounts, aid)
    if expected_version != acct["version"]:
        err(ERR_STALE_VERSION,
            "expected_account_version does not match the account version")
    acct["last_adjusted_by"] = g.user_id
    entry = post_entry(acct, direction, amount_cents, reason)
    return success(pub(entry), 201)


# ------------------------------------------------------------- ledger entries
def _entry_visible(entry):
    if g.role != "CardHolder":
        return True
    acct = store.accounts.get(entry["account_id"])
    return acct is not None and acct["holder_id"] == g.user_id


@bp.route("/api/ledger-entries", methods=["GET"])
def list_ledger_entries():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice",
                  "FraudAnalyst", "CardHolder")
    rows = list(store.ledger_entries.values())
    if g.role == "CardHolder":
        rows = [e for e in rows if _entry_visible(e)]
    account_id = request.args.get("account_id")
    ref_tx = request.args.get("reference_transaction_id")
    ref_dispute = request.args.get("reference_dispute_id")
    entry_type = request.args.get("entry_type")
    if account_id is not None:
        if g.role == "CardHolder":
            target = store.accounts.get(account_id)
            if target is not None and target["holder_id"] != g.user_id:
                err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder's account")
        rows = [e for e in rows if e["account_id"] == account_id]
    if ref_tx is not None:
        rows = [e for e in rows if e.get("reference_transaction_id") == ref_tx]
    if ref_dispute is not None:
        rows = [e for e in rows if e.get("reference_dispute_id") == ref_dispute]
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/ledger-entries/<lid>", methods=["GET"])
def get_ledger_entry(lid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice",
                  "FraudAnalyst", "CardHolder")
    entry = store.ledger_entries.get(lid)
    if entry is not None and not _entry_visible(entry):
        err(ERR_NOT_RESOURCE_OWNER, "CardHolder may read only its own ledger entries")
    if entry is None:
        err(ERR_NOT_FOUND, "Ledger entry not found")
    return success(pub(entry), 200)


# ------------------------------------------------------------ refund requests
@bp.route("/api/accounts/<aid>/refund-requests", methods=["POST"])
def create_refund_request(aid):
    authenticate()
    require_roles("CardHolder")
    acct = store.accounts.get(aid)
    if acct is not None:
        _own_account_or_403(acct)
    if acct is None:
        err(ERR_NOT_FOUND, "Account not found")
    if acct["status"] != "CLOSE_PENDING":
        err(ERR_ACCOUNT_NOT_CLOSABLE,
            "Refund requests require a CLOSE_PENDING account")
    for rr in store.refund_requests.values():
        if (rr["account_id"] == acct["id"]
                and rr["status"] in ("REQUESTED", "APPROVED")):
            err(ERR_PENDING_REFUND_EXISTS,
                "A pending refund request already exists on the account")
    variant, amount = refund_amount(acct)
    if amount < MIN_REFUND_CENTS:
        err(ERR_REFUND_BELOW_MINIMUM,
            "The computed refund amount is below the minimum")
    rr = new_row()
    rr.update({
        "account_id": acct["id"],
        "requested_by_holder_id": g.user_id,
        "refund_variant": variant,
        "amount_cents": amount,
        "status": "REQUESTED",
        "denial_reason": None,
        "approved_by": None,
        "paid_by": None,
    })
    store.refund_requests[rr["id"]] = rr
    return success(pub(rr), 201)


def _own_refund_or_403(rr):
    if g.role == "CardHolder" and rr["requested_by_holder_id"] != g.user_id:
        err(ERR_NOT_RESOURCE_OWNER,
            "CardHolder may act only on its own refund requests")


@bp.route("/api/refund-requests", methods=["GET"])
def list_refund_requests():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice", "CardHolder")
    rows = list(store.refund_requests.values())
    if g.role == "CardHolder":
        rows = [r for r in rows if r["requested_by_holder_id"] == g.user_id]
    account_id = request.args.get("account_id")
    holder_id = request.args.get("requested_by_holder_id")
    status = request.args.get("status")
    if account_id is not None:
        if g.role == "CardHolder":
            target = store.accounts.get(account_id)
            if target is not None and target["holder_id"] != g.user_id:
                err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder's account")
        rows = [r for r in rows if r["account_id"] == account_id]
    if holder_id is not None:
        if g.role == "CardHolder" and holder_id != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder")
        rows = [r for r in rows if r["requested_by_holder_id"] == holder_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/refund-requests/<rid>", methods=["GET"])
def get_refund_request(rid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice", "CardHolder")
    rr = store.refund_requests.get(rid)
    if rr is not None:
        _own_refund_or_403(rr)
    if rr is None:
        err(ERR_NOT_FOUND, "Refund request not found")
    return success(pub(rr), 200)


@bp.route("/api/refund-requests/<rid>/approve", methods=["POST"])
def approve_refund(rid):
    authenticate()
    require_roles("BursarOffice")
    rr = find_or_404(store.refund_requests, rid)
    if rr["status"] != "REQUESTED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a REQUESTED refund request can be approved")
    acct = store.accounts[rr["account_id"]]
    if acct.get("last_adjusted_by") is not None and \
            acct["last_adjusted_by"] == g.user_id:
        err(ERR_SOD_ADJUSTER_CANNOT_APPROVE,
            "The account's last adjuster may not approve its refund")
    rr["status"] = "APPROVED"
    rr["approved_by"] = g.user_id
    touch(rr)
    return success(pub(rr), 200)


@bp.route("/api/refund-requests/<rid>/deny", methods=["POST"])
def deny_refund(rid):
    authenticate()
    require_roles("BursarOffice")
    body = get_body()
    denial_reason = v_str(body, "denial_reason")
    rr = find_or_404(store.refund_requests, rid)
    if rr["status"] != "REQUESTED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a REQUESTED refund request can be denied")
    rr["status"] = "DENIED"
    rr["denial_reason"] = denial_reason
    touch(rr)
    return success(pub(rr), 200)


@bp.route("/api/refund-requests/<rid>/pay", methods=["POST"])
def pay_refund(rid):
    authenticate()
    require_roles("BursarOffice")
    rr = find_or_404(store.refund_requests, rid)
    if rr["status"] != "APPROVED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only an APPROVED refund request can be paid")
    if rr["approved_by"] == g.user_id:
        err(ERR_SOD_PAYER_IS_APPROVER,
            "The refund payer must differ from its approver")
    acct = store.accounts[rr["account_id"]]
    if acct["balance_cents"] - rr["amount_cents"] == 0:
        # The payout zeroes the balance: account -> REFUNDED in the same mutation.
        acct["status"] = "REFUNDED"
    post_entry(acct, "REFUND_PAYOUT", rr["amount_cents"],
               f"Refund payout for request {rr['id']}")
    rr["status"] = "PAID"
    rr["paid_by"] = g.user_id
    touch(rr)
    return success(pub(rr), 200)
