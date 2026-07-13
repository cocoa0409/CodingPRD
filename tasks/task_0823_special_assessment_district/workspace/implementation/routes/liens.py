from flask import Blueprint, request

from store import (ser, by_seq, liens_of_parcel, installments_of_parcel,
                   foreclosures_of_parcel)
from web import protected, ALL_ROLES, ok, ok_list, pagination
from fetch import get_parcel
from util import fmt_dt

bp = Blueprint("liens", __name__)

UNPAID = ("SCHEDULED", "DUE", "DELINQUENT")


@bp.get("/parcels/<pid>/liens")
@protected(ALL_ROLES)
def list_liens(pid):
    get_parcel(pid)
    items = liens_of_parcel(pid)
    status = request.args.get("status")
    lien_type = request.args.get("lien_type")
    if status:
        items = [l for l in items if l["status"] == status]
    if lien_type:
        items = [l for l in items if l["lien_type"] == lien_type]
    items = by_seq(items)
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


@bp.get("/parcels/<pid>/disclosure")
@protected(ALL_ROLES)
def disclosure(pid):
    parcel = get_parcel(pid)
    insts = installments_of_parcel(pid)
    unpaid = [i for i in insts if i["status"] in UNPAID]

    annual = 0
    next_due = None
    if unpaid:
        current = min(unpaid, key=lambda i: (i["installment_year"], i["_seq"]))
        annual = current["amount_due_cents"]
        nxt = min(unpaid, key=lambda i: (i["due_date"], i["_seq"]))
        next_due = fmt_dt(nxt["due_date"])

    delinquent_count = sum(1 for i in insts if i["status"] == "DELINQUENT")

    liens = liens_of_parcel(pid)
    if any(l["status"] == "RECORDED" for l in liens):
        lien_status = "RECORDED"
    elif any(l["status"] == "FORECLOSED" for l in liens):
        lien_status = "FORECLOSED"
    elif any(l["status"] == "RELEASED" for l in liens):
        lien_status = "RELEASED"
    else:
        lien_status = "NONE"

    fcs = foreclosures_of_parcel(pid)
    if fcs:
        foreclosure_status = max(fcs, key=lambda f: f["_seq"])["status"]
    else:
        foreclosure_status = "NONE"

    report = {
        "remaining_principal_cents": parcel["remaining_principal_cents"],
        "annual_installment_cents": annual,
        "next_due_date": next_due,
        "delinquent_installment_count": delinquent_count,
        "lien_status": lien_status,
        "foreclosure_status": foreclosure_status,
    }
    return ok(report)
