from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, require_enum, require_dt,
                  paginate, sorted_by_created)
from serialize import public, public_list
from services.common import get_return_or_fk, owner_check_return
from services import compute

bp = Blueprint("estimated_payments", __name__)

EDITORS = {"Taxpayer", "Preparer"}
QUARTERS = {"Q1", "Q2", "Q3", "Q4"}


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end). Overlap iff a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


@bp.post("/estimated-tax-payments")
def create_payment():
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    body = get_body()

    return_id = require_str(body, "return_id")
    ret = get_return_or_fk(return_id)
    owner_check_return(role, user_id, ret)

    quarter = require_enum(body, "quarter", QUARTERS)
    amount = require_int(body, "amount_cents", gt=0)
    paid_on = require_str(body, "paid_on")
    period_start = require_str(body, "period_start")
    period_end = require_str(body, "period_end")

    # validate datetimes parse
    from util import parse_iso
    ps = parse_iso(period_start, "period_start")
    pe = parse_iso(period_end, "period_end")
    parse_iso(paid_on, "paid_on")
    if pe <= ps:
        raise err(errors.ERR_INVALID_REQUEST, "period_end must be after period_start")

    # duplicate quarter on same return
    for p in db.estimated_tax_payments.values():
        if p["return_id"] == return_id and p["quarter"] == quarter:
            raise err(errors.ERR_DUPLICATE_CHILD,
                      "A payment for this quarter already exists on the return")

    # period overlap (half-open) against existing payments on same return
    for p in db.estimated_tax_payments.values():
        if p["return_id"] != return_id:
            continue
        e_start = parse_iso(p["period_start"])
        e_end = parse_iso(p["period_end"])
        if _overlaps_half_open(ps, pe, e_start, e_end):
            raise err(errors.ERR_PAYMENT_PERIOD_OVERLAP,
                      "Payment period overlaps an existing payment on this return")

    on_time = compute.compute_on_time(quarter, paid_on)

    payment = {
        "return_id": return_id,
        "quarter": quarter,
        "amount_cents": amount,
        "paid_on": paid_on,
        "period_start": period_start,
        "period_end": period_end,
        "on_time": on_time,
    }
    init_common(payment)
    db.estimated_tax_payments[payment["id"]] = payment
    touch(ret)
    return success(public(payment), status=201)


@bp.get("/estimated-tax-payments/<payment_id>")
def get_payment(payment_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    p = db.estimated_tax_payments.get(payment_id)
    if p is None:
        raise err(errors.ERR_RETURN_NOT_FOUND, "EstimatedTaxPayment not found")
    ret = db.tax_returns.get(p["return_id"])
    if ret is not None:
        owner_check_return(role, user_id, ret)
    return success(public(p))


@bp.get("/estimated-tax-payments")
def list_payments():
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    items = list(db.estimated_tax_payments.values())
    # restrict to caller-owned returns
    items = [p for p in items
             if (db.tax_returns.get(p["return_id"]) or {}).get("taxpayer_id") == user_id]
    return_filter = request.args.get("return_id")
    if return_filter is not None:
        items = [p for p in items if p["return_id"] == return_filter]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)
