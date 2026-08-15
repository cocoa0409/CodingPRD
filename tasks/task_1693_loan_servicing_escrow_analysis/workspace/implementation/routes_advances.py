"""Escrow advances."""

from flask import Blueprint, request

from auth import any_role, require_roles
from domain import (
    advance_sync,
    check_advance_cap,
    new_advance,
    post_ledger,
    replay,
)
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
    ERR_RECOVERY_EXCEEDS,
    not_found,
)
from routes_core import get_account_or_404
from serializers import advance_out
from store import store
from util import bump, fmt_date, ok, ok_list, today
from validate import body, req_enum

bp = Blueprint("advances", __name__)

REASONS = ("DISBURSEMENT_SHORTFALL", "FORCE_PLACEMENT_PREMIUM", "MANUAL_CORRECTION")


def get_advance_or_404(aid):
    a = store.advances.get(aid)
    if a is None:
        raise not_found("EscrowAdvance not found")
    return a


@bp.post("/servicing/escrow-accounts/<aid>/advances")
def create_advance(aid):
    require_roles("ComplianceOfficer")
    account = get_account_or_404(aid)
    data = body()
    amount = data.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "amount_cents is required and must be an integer")
    reason = req_enum(data, "reason", REASONS)
    if reason != "MANUAL_CORRECTION":
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Manual advances must use reason MANUAL_CORRECTION")
    if amount <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "amount_cents must be positive")
    check_advance_cap(aid, amount)
    adv = new_advance(account, reason, amount, None)
    post_ledger(account, "ADVANCE_ISSUED", amount, fmt_date(today()),
                "EscrowAdvance", adv["id"])
    replay(account)
    bump(account)
    return ok(advance_out(adv), 201)


@bp.get("/servicing/escrow-accounts/<aid>/advances")
def list_advances(aid):
    any_role()
    get_account_or_404(aid)
    rows = [a for a in sorted(store.advances.values(), key=lambda r: r["_seq"])
            if a["escrow_account_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([advance_out(r) for r in rows])


@bp.get("/servicing/advances/<aid>")
def get_advance(aid):
    any_role()
    return ok(advance_out(get_advance_or_404(aid)))


@bp.post("/servicing/advances/<aid>/recover")
def recover_advance(aid):
    require_roles("EscrowAnalyst")
    adv = get_advance_or_404(aid)
    data = body()
    amount = data.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "amount_cents is required and must be an integer")
    if adv["status"] in ("RECOVERED", "WRITTEN_OFF"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Advance is terminal")
    if amount <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "amount_cents must be positive")
    if amount > adv["outstanding_cents"]:
        raise ApiError(ERR_RECOVERY_EXCEEDS, 422,
                       "Recovery amount exceeds advance outstanding_cents")
    account = store.accounts.get(adv["escrow_account_id"])
    if amount > account["balance_cents"]:
        raise ApiError(ERR_INVALID_AMOUNT, 422,
                       "Recovery amount exceeds account balance")
    post_ledger(account, "ADVANCE_RECOVERY", -amount, fmt_date(today()),
                "EscrowAdvance", adv["id"])
    replay(account)
    adv["recovered_cents"] += amount
    advance_sync(adv)
    bump(adv)
    bump(account)
    return ok(advance_out(adv))


@bp.post("/servicing/advances/<aid>/write-off")
def write_off_advance(aid):
    require_roles("ComplianceOfficer")
    adv = get_advance_or_404(aid)
    if adv["status"] in ("RECOVERED", "WRITTEN_OFF"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Advance is terminal")
    adv["written_off_cents"] = adv["outstanding_cents"]
    adv["outstanding_cents"] = 0
    adv["status"] = "WRITTEN_OFF"
    bump(adv)
    return ok(advance_out(adv))
