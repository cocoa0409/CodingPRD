from flask import Blueprint, request, g

import store
from store import (DB, make, touch, ser, now, by_seq,
                   installments_of_parcel, liens_of_parcel, payments_of_installment)
from web import (protected, ALL_ROLES, ok, ok_list, pagination, body_json,
                 require, as_int, as_str, owner_check, ApiError)
from fetch import get_installment, get_parcel, get_bond
import calc
import logic
from util import add_days

bp = Blueprint("installments", __name__)


@bp.get("/installments/<iid>")
@protected(ALL_ROLES)
def get_installment_route(iid):
    return ok(ser(get_installment(iid)))


@bp.get("/installments")
@protected(ALL_ROLES)
def list_installments():
    items = list(DB["installments"].values())
    pid = request.args.get("parcel_id")
    bid = request.args.get("bond_id")
    status = request.args.get("status")
    year = request.args.get("installment_year")
    if pid:
        items = [i for i in items if i["parcel_id"] == pid]
    if bid:
        items = [i for i in items if i["bond_id"] == bid]
    if status:
        items = [i for i in items if i["status"] == status]
    if year is not None:
        try:
            y = int(year)
        except ValueError:
            raise ApiError("ERR_VALIDATION", "installment_year must be an integer")
        items = [i for i in items if i["installment_year"] == y]
    items = by_seq(items)
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


@bp.post("/installments/<iid>/payments")
@protected(["CountyTreasurer", "ParcelOwner"])
def record_payment(iid):
    inst = get_installment(iid)
    if g.role == "ParcelOwner":
        owner_check(inst["parcel_id"])
    if inst["status"] not in ("DUE", "DELINQUENT"):
        raise ApiError("ERR_INSTALLMENT_NOT_PAYABLE")
    b = body_json()
    amount = as_int(require(b, "amount_cents"), "amount_cents", minimum=1)
    payment_date = require(b, "payment_date")
    paid_by = as_str(require(b, "paid_by"), "paid_by")
    from util import parse_dt
    payment_dt = parse_dt(payment_date)
    if amount != inst["amount_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    parcel = get_parcel(inst["parcel_id"])
    was_delinquent = inst["status"] == "DELINQUENT"

    payment = make("payments", {
        "installment_id": inst["id"],
        "amount_cents": amount,
        "payment_date": payment_dt,
        "paid_by": paid_by,
        "reversed": False,
        "reversed_at": None,
    }, versioned=False)

    inst["status"] = "PAID"
    touch(inst)

    if was_delinquent:
        for lien in liens_of_parcel(parcel["id"]):
            if (lien["lien_type"] == "DELINQUENCY" and lien["status"] == "RECORDED"
                    and lien.get("_installment_id") == inst["id"]):
                lien["status"] = "RELEASED"
                touch(lien)

    logic.debit_parcel_principal(parcel, inst["principal_cents"])

    bond = DB["bonds"].get(inst["bond_id"])
    if bond is not None:
        logic.maybe_retire_bond(bond)

    return ok(ser(payment), status=201)


@bp.get("/installments/<iid>/payments")
@protected(ALL_ROLES)
def list_payments(iid):
    get_installment(iid)
    items = by_seq(payments_of_installment(iid))
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


@bp.post("/installments/<iid>/mark-delinquent")
@protected(["CountyTreasurer"])
def mark_delinquent(iid):
    inst = get_installment(iid)
    if inst["status"] != "DUE":
        raise ApiError("ERR_INSTALLMENT_NOT_PAYABLE")
    if now() < add_days(inst["due_date"], calc.GRACE_DAYS):
        raise ApiError("ERR_GRACE_NOT_ELAPSED")

    base = inst["principal_cents"] + inst["interest_cents"] + inst["admin_fee_cents"]
    penalty, redemption = calc.delinquency_charges(base, inst["due_date"], now())
    inst["penalty_cents"] = penalty
    inst["redemption_interest_cents"] = redemption
    inst["amount_due_cents"] = base + penalty + redemption
    inst["status"] = "DELINQUENT"
    touch(inst)

    parcel = get_parcel(inst["parcel_id"])
    lien = logic.record_lien(parcel, "DELINQUENCY", inst["amount_due_cents"])
    lien["_installment_id"] = inst["id"]

    return ok(ser(inst))
