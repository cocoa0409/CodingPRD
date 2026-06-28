"""EscrowDeposit endpoints (PRD §3.7). Record (RECEIVED) / get / list / transition
(POST -> counts toward balance; REVERSE -> compensating, refused if it would drive
escrow_balance below 0).
"""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_deposit
from services.domain import touch, require_agency_owns_order, escrow_balance
from helpers import (
    get_body, require_str, require_int_min, require_enum,
    parse_pagination, paginate, sort_by_created,
)
from routes.orders import get_order_or_404

bp = Blueprint("deposits", __name__)

DEPOSIT_STATUSES = {"RECEIVED", "POSTED", "REVERSED"}


def _get_deposit_or_404(did):
    d = db.deposits.get(did)
    if d is None:
        raise errors.not_found("Deposit not found")
    return d


@bp.route("/title/orders/<oid>/deposits", methods=["POST"])
@require_roles("Agency", "Underwriter")
def create_deposit(oid):
    order = get_order_or_404(oid)
    require_agency_owns_order(order)
    body = get_body()
    amount_cents = require_int_min(body, "amount_cents", 1)
    source_ref = require_str(body, "source_ref")

    ts = now_ts()
    did = new_id()
    record = {
        "id": did,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "order_id": order["id"],
        "amount_cents": amount_cents,
        "source_ref": source_ref,
        "status": "RECEIVED",
    }
    db.deposits[did] = record
    return success(serialize_deposit(record), status=201)


@bp.route("/title/orders/<oid>/deposits", methods=["GET"])
@require_roles("Agency", "Underwriter", "TitleOfficer")
def list_deposits(oid):
    order = get_order_or_404(oid)
    require_agency_owns_order(order)
    limit, offset = parse_pagination()
    items = [d for d in db.deposits.values() if d["order_id"] == order["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_deposit(d) for d in page], limit, offset, total)


@bp.route("/title/deposits/<did>", methods=["GET"])
@require_roles("Agency", "Underwriter")
def get_deposit(did):
    d = _get_deposit_or_404(did)
    if g.user_role == "Agency":
        order = db.orders.get(d["order_id"])
        if order is not None:
            require_agency_owns_order(order)
    return success(serialize_deposit(d), status=200)


@bp.route("/title/deposits/<did>/transitions", methods=["POST"])
@require_roles("Underwriter")
def transition_deposit(did):
    body = get_body()
    d = _get_deposit_or_404(did)
    to_status = require_enum(body, "to_status", DEPOSIT_STATUSES)
    cur = d["status"]

    if to_status == "POSTED":
        if cur != "RECEIVED":
            raise errors.invalid_state("Deposit is not RECEIVED")
        d["status"] = "POSTED"
        touch(d)
    elif to_status == "REVERSED":
        if cur not in ("RECEIVED", "POSTED"):
            raise errors.invalid_state("Deposit cannot be reversed from " + cur)
        if cur == "POSTED":
            # Fiscal (priority 10): reversal must not drive escrow_balance below 0.
            # Removing this posted deposit subtracts its amount from the balance.
            if escrow_balance(d["order_id"]) - d["amount_cents"] < 0:
                raise errors.ApiError(errors.ERR_ESCROW_WOULD_GO_NEGATIVE, 409,
                                      "Reversing this deposit would drive escrow balance negative")
        d["status"] = "REVERSED"
        touch(d)
    else:
        raise errors.invalid_state("Unsupported deposit transition")

    return success(serialize_deposit(d), status=200)
