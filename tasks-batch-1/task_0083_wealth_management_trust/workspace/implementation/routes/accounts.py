"""Accounting periods + ledger entries (PRD §3.3, §3.4, §3.7)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, parse_pagination, paginate
from response import success
from services import serialize, calc
from services.helpers import (
    get_json_body, require_int, require_enum, require_datetime, parse_datetime, must_exist,
)
from services.ledger import (
    recompute_after_ledger_mutation, recompute_account_figures, recompute_k1,
)

bp = Blueprint("accounts", __name__)

RECEIPT_KINDS = {"INTEREST", "DIVIDEND_ORDINARY", "DIVIDEND_QUALIFIED", "CAPITAL_GAIN", "CONTRIBUTION"}
EXPENSE_KINDS = {"TRUSTEE_FEE", "INVESTMENT_FEE", "TAX_PAYMENT", "ADMINISTRATIVE"}


@bp.route("/trusts/<tid>/accounts", methods=["POST"])
def create_account(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    t = must_exist(db.trusts, tid)
    body = get_json_body()
    tax_year = require_int(body, "tax_year")
    period_start = require_datetime(body, "period_start")
    period_end = require_datetime(body, "period_end")
    ps = parse_datetime(period_start, "period_start")
    pe = parse_datetime(period_end, "period_end")
    if not (pe > ps):
        raise err("ERR_VALIDATION", "period_end must be strictly after period_start")

    with db.LOCK:
        # Half-open [start, end) overlap; abutting allowed.
        for a in db.accounts.values():
            if a["trust_id"] != tid:
                continue
            ex_s = parse_datetime(a["period_start"])
            ex_e = parse_datetime(a["period_end"])
            if ps < ex_e and ex_s < pe:  # true overlap of half-open intervals
                raise err("ERR_ACCOUNT_PERIOD_OVERLAP")
        a = db.base_fields()
        a.update({
            "trust_id": tid,
            "tax_year": tax_year,
            "period_start": period_start,
            "period_end": period_end,
            "status": "OPEN",
            "dni_cents": 0,
            "dni_carried_out_cents": 0,
            "taxable_income_cents": 0,
        })
        db.accounts[a["id"]] = a
    return success(serialize.account(a), status=201)


@bp.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    a = must_exist(db.accounts, aid)
    _trustee_scope(role, user_id, a["trust_id"])
    return success(serialize.account(a))


@bp.route("/trusts/<tid>/accounts", methods=["GET"])
def list_trust_accounts(tid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    must_exist(db.trusts, tid)
    _trustee_scope(role, user_id, tid)
    limit, offset = parse_pagination()
    items = [a for a in db.accounts.values() if a["trust_id"] == tid]
    page, meta = paginate(items, limit, offset)
    return success([serialize.account(a) for a in page], pagination=meta)


@bp.route("/accounts/<aid>/close", methods=["POST"])
def close_account(aid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    a = must_exist(db.accounts, aid)
    t = db.trusts[a["trust_id"]]
    with db.LOCK:
        if a["status"] != "OPEN":
            raise err("ERR_INVALID_STATE")
        if t["status"] not in ("ACTIVE", "AMENDMENT_PENDING", "TERMINATING", "REVOKED"):
            raise err("ERR_INVALID_STATE", "Owning trust is not in a state that admits close.")
        a["status"] = "CLOSED"
        recompute_account_figures(a)
        recompute_k1(a)
        db.touch(a)
    return success(serialize.account(a))


# ---- Receipts ----
@bp.route("/accounts/<aid>/receipts", methods=["POST"])
def create_receipt(aid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    a = must_exist(db.accounts, aid)
    t = db.trusts[a["trust_id"]]
    _trustee_scope(role, user_id, t["id"])
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")
    receipt_kind = require_enum(body, "receipt_kind", RECEIPT_KINDS)
    with db.LOCK:
        if a["status"] != "OPEN":
            raise err("ERR_PERIOD_FROZEN")
        if amount_cents <= 0:
            raise err("ERR_INVALID_AMOUNT")
        ledger_side = calc.receipt_ledger_side(receipt_kind, t["capital_gains_to_income"])
        r = db.base_fields()
        r.update({
            "account_id": aid,
            "amount_cents": amount_cents,
            "receipt_kind": receipt_kind,
            "ledger_side": ledger_side,
        })
        db.receipts[r["id"]] = r
        recompute_after_ledger_mutation(a, t)
    return success(serialize.receipt(r), status=201)


@bp.route("/accounts/<aid>/receipts", methods=["GET"])
def list_receipts(aid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    a = must_exist(db.accounts, aid)
    _trustee_scope(role, user_id, a["trust_id"])
    limit, offset = parse_pagination()
    items = [r for r in db.receipts.values() if r["account_id"] == aid]
    page, meta = paginate(items, limit, offset)
    return success([serialize.receipt(r) for r in page], pagination=meta)


# ---- Disbursements ----
@bp.route("/accounts/<aid>/disbursements", methods=["POST"])
def create_disbursement(aid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    a = must_exist(db.accounts, aid)
    t = db.trusts[a["trust_id"]]
    _trustee_scope(role, user_id, t["id"])
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")
    expense_kind = require_enum(body, "expense_kind", EXPENSE_KINDS)
    with db.LOCK:
        if a["status"] != "OPEN":
            raise err("ERR_PERIOD_FROZEN")
        if amount_cents <= 0:
            raise err("ERR_INVALID_AMOUNT")
        ledger_side = calc.disbursement_ledger_side(expense_kind)
        d = db.base_fields()
        d.update({
            "account_id": aid,
            "amount_cents": amount_cents,
            "expense_kind": expense_kind,
            "ledger_side": ledger_side,
            "is_system_generated": False,
        })
        db.disbursements[d["id"]] = d
        recompute_after_ledger_mutation(a, t)
    return success(serialize.disbursement(d), status=201)


@bp.route("/accounts/<aid>/disbursements", methods=["GET"])
def list_disbursements(aid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    a = must_exist(db.accounts, aid)
    _trustee_scope(role, user_id, a["trust_id"])
    limit, offset = parse_pagination()
    items = [d for d in db.disbursements.values() if d["account_id"] == aid]
    page, meta = paginate(items, limit, offset)
    return success([serialize.disbursement(d) for d in page], pagination=meta)


def _trustee_scope(role, user_id, trust_id):
    """A Trustee actor must hold an ACTIVE appointment on the owning trust (PRD §2.1)."""
    if role != "Trustee":
        return
    for ap in db.trustee_appointments.values():
        if ap["trust_id"] == trust_id and ap["trustee_id"] == user_id and ap["status"] == "ACTIVE":
            return
    raise err("ERR_NOT_OWNER")
