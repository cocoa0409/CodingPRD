"""Fee routes: pay, waive, dispute, resolve-dispute."""
from flask import Blueprint

from domain import (
    MAX_DISPUTE_ROUNDS,
    advance_item_resolution,
    ledger_append,
    touch,
    wallet_of,
)
from envelope import ok_object
from errors import domain as derr, not_found
from serializers import serialize_fee
from store import DB
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    parse_fields,
    require_ownership,
)

bp = Blueprint("fees", __name__)


def _get_fee(fid):
    f = DB.fees.get(fid)
    if f is None:
        raise not_found("ERR_FEE_NOT_FOUND", "FeeAssessment id does not exist.")
    return f


def _owner_of(fee):
    sub = DB.subscriptions.get(fee["subscription_id"])
    return sub["member_id"] if sub else None


@bp.post("/toy-rental/fees/<fid>/pay")
def pay_fee(fid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    f = _get_fee(fid)
    owner = _owner_of(f)
    require_ownership(role, uid, owner)
    if f["status"] != "INVOICED":
        raise derr("ERR_FEE_NOT_INVOICED", 409, "Fee is not INVOICED.")
    data = body()
    shape = parse_fields(data, [
        F("payment_source", True, "enum", values={"CARD", "WALLET_CREDIT"}),
    ])
    source = shape.values.get("payment_source")
    if source == "WALLET_CREDIT" and wallet_of(owner) < f["amount_cents"]:
        raise derr("ERR_WALLET_INSUFFICIENT", 422,
                   "Wallet credit does not cover the fee amount.")
    finalize_shape(shape)
    if source == "CARD":
        ledger_append(owner, f["amount_cents"], "FEE_SETTLED_CARD")
    else:
        ledger_append(owner, f["amount_cents"], "FEE_SETTLED_WALLET")
        ledger_append(owner, -f["amount_cents"], "WALLET_DEBIT")
    f["status"] = "PAID"
    touch(f)
    advance_item_resolution(f["box_item_id"])
    return ok_object(serialize_fee(f))


@bp.post("/toy-rental/fees/<fid>/waive")
def waive_fee(fid):
    uid, role = authenticate()
    authorize(role, {"CustomerService"})
    f = _get_fee(fid)
    if f["status"] not in ("INVOICED", "DISPUTED"):
        raise derr("ERR_FEE_NOT_INVOICED", 409,
                   "Fee is not INVOICED or DISPUTED.")
    data = body()
    shape = parse_fields(data, [F("reason", False, "str")])
    finalize_shape(shape)
    ledger_append(_owner_of(f), f["amount_cents"], "FEE_WAIVER")
    f["status"] = "WAIVED"
    touch(f)
    advance_item_resolution(f["box_item_id"])
    return ok_object(serialize_fee(f))


@bp.post("/toy-rental/fees/<fid>/dispute")
def dispute_fee(fid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    f = _get_fee(fid)
    owner = _owner_of(f)
    require_ownership(role, uid, owner)
    if f["status"] != "INVOICED":
        raise derr("ERR_FEE_NOT_INVOICED", 409, "Fee is not INVOICED.")
    data = body()
    shape = parse_fields(data, [F("reason", False, "str")])
    if f["dispute_rounds"] >= MAX_DISPUTE_ROUNDS:
        raise derr("ERR_DISPUTE_LIMIT_REACHED", 422,
                   "The dispute-round limit has been reached.")
    finalize_shape(shape)
    f["status"] = "DISPUTED"
    f["dispute_rounds"] += 1
    touch(f)
    return ok_object(serialize_fee(f))


@bp.post("/toy-rental/fees/<fid>/resolve-dispute")
def resolve_dispute(fid):
    uid, role = authenticate()
    authorize(role, {"CustomerService"})
    f = _get_fee(fid)
    if f["status"] != "DISPUTED":
        raise derr("ERR_FEE_NOT_INVOICED", 409, "Fee is not DISPUTED.")
    data = body()
    shape = parse_fields(data, [
        F("outcome", True, "enum", values={"UPHELD", "OVERTURNED"}),
    ])
    outcome = shape.values.get("outcome")
    finalize_shape(shape)
    if outcome == "UPHELD":
        f["status"] = "INVOICED"
        touch(f)
    else:
        ledger_append(_owner_of(f), f["amount_cents"], "FEE_WAIVER")
        f["status"] = "WAIVED"
        touch(f)
        advance_item_resolution(f["box_item_id"])
    return ok_object(serialize_fee(f))
