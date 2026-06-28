"""Member registration, reads, credit ledger, adjustments, suspension."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_enum, get_bool,
                    get_int, parse_pagination, paginate)
from db import db
from errors import err, ERR_NOT_FOUND
from middleware import authorize, get_auth
from response import success_object, success_list
from serialize import member_out, credit_ledger_out
from services import append_ledger, recompute_member_balances

bp = Blueprint("members", __name__)

ALL_OPERATORS = {"Member", "Bookseller", "InventoryManager", "StoreAdmin"}


@bp.route("/members", methods=["POST"])
def create_member():
    # Self-registration: open to Anonymous and StoreAdmin (PRD §3.2). No auth required.
    body = json_body(optional=False)
    email = get_str(body, "email", required=True)
    full_name = get_str(body, "full_name", required=True)
    tier = get_enum(body, "tier", ["REGULAR", "GOLD"], required=False, default="REGULAR")
    is_local_author = get_bool(body, "is_local_author", required=False, default=False)

    rec = make_record({
        "email": email,
        "full_name": full_name,
        "tier": tier,
        "is_local_author": is_local_author,
        "status": "ACTIVE",
        "store_credit_cents": 0,
        "loyalty_points": 0,
    })
    db.members[rec["id"]] = rec
    return success_object(member_out(rec), status=201)


def _find_member(mid):
    m = db.members.get(mid)
    if m is None:
        raise err(ERR_NOT_FOUND, "Member not found")
    return m


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    authorize(ALL_OPERATORS)
    m = _find_member(mid)
    return success_object(member_out(m), status=200)


@bp.route("/members/<mid>/credit-ledger", methods=["GET"])
def list_credit_ledger(mid):
    authorize(ALL_OPERATORS)
    m = _find_member(mid)
    entries = [e for e in db.credit_ledger.values() if e["member_id"] == mid]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(entries, limit, offset)
    return success_list([credit_ledger_out(e) for e in page], limit, offset, total)


@bp.route("/members/<mid>/credit-adjustments", methods=["POST"])
def credit_adjustment(mid):
    authorize({"StoreAdmin"})
    m = _find_member(mid)
    body = json_body(optional=False)
    delta = get_int(body, "delta_cents", required=True)
    entry = append_ledger(mid, delta, "ADJUSTMENT", None)
    recompute_member_balances(m)
    return success_object(credit_ledger_out(entry), status=201)


@bp.route("/members/<mid>/suspend", methods=["POST"])
def suspend_member(mid):
    authorize({"StoreAdmin"})
    m = _find_member(mid)
    m["status"] = "SUSPENDED"
    touch(m)
    return success_object(member_out(m), status=200)


_ = get_auth
