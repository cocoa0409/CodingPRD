"""Dealer endpoints."""
from flask import Blueprint

import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import err_not_found, err_dealer_mismatch, err_invalid_request

bp = Blueprint("dealers", __name__)


@bp.route("/dealers", methods=["POST"])
def create_dealer():
    caller = mw.authenticate()
    mw.authorize(caller, ["CreditManager"])
    body = mw.get_json_body(required=True)
    legal_name = mw.req_string(body, "legal_name")
    credit_limit_cents = mw.req_int(body, "credit_limit_cents")
    if credit_limit_cents <= 0:
        raise err_invalid_request("credit_limit_cents must be > 0")

    now = svc.stamp_now()
    d = {
        "id": db.new_id(),
        "legal_name": legal_name,
        "credit_limit_cents": credit_limit_cents,
        "fee_balance_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.dealers[d["id"]] = d
    return resp.created(ser.serialize_dealer(d))


@bp.route("/dealers/<did>", methods=["GET"])
def get_dealer(did):
    caller = mw.authenticate()
    mw.authorize(caller, ["CreditManager", "DealerUser"])
    # DealerUser ownership (priority 3) precedes existence (priority 4)
    if caller["role"] == "DealerUser" and did != caller["user_id"]:
        raise err_dealer_mismatch()
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found()
    return resp.ok(ser.serialize_dealer(d))


@bp.route("/dealers", methods=["GET"])
def list_dealers():
    caller = mw.authenticate()
    mw.authorize(caller, ["CreditManager"])
    limit, offset = mw.pagination_params()
    credit_status = mw.opt_query_enum("credit_status", {"GOOD_STANDING", "WATCH", "SUSPENDED"})
    items = list(db.dealers.values())
    items.sort(key=lambda d: d["_seq"])
    serialized = [ser.serialize_dealer(d) for d in items]
    if credit_status is not None:
        serialized = [s for s in serialized if s["credit_status"] == credit_status]
    total = len(serialized)
    page = serialized[offset : offset + limit]
    return resp.list_ok(page, limit, offset, total)


@bp.route("/dealers/<did>", methods=["PATCH"])
def patch_dealer(did):
    caller = mw.authenticate()
    mw.authorize(caller, ["CreditManager"])
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found()
    body = mw.get_json_body(required=True)
    credit_limit_cents = mw.req_int(body, "credit_limit_cents")
    if credit_limit_cents <= 0:
        raise err_invalid_request("credit_limit_cents must be > 0")
    d["credit_limit_cents"] = credit_limit_cents
    svc.touch(d)
    return resp.ok(ser.serialize_dealer(d))
