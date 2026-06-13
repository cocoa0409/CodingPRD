"""Missed-pickup credits and contamination notices (PRD §3.8, §3.9)."""
from flask import Blueprint, request

import db
from errors import err
from response import ok, ok_list
from routes.helpers import gate, require_ownership
from services import validate as V
from services.common import touch, sort_by_created
from services.lookup import get_or_404
from services.serialize import credit_out, notice_out

bp = Blueprint("credits_notices", __name__)


# --------------------------------------------------------------------------
# Missed-pickup credits
# --------------------------------------------------------------------------
@bp.route("/accounts/<aid>/credits", methods=["GET"])
def list_account_credits(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    limit, offset = V.parse_pagination(request.args)
    items = [c for c in db.missed_pickup_credits.values() if c["account_id"] == a["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([credit_out(c) for c in page], limit, offset, total)


@bp.route("/credits", methods=["GET"])
def list_credits():
    gate({"Dispatcher", "AccountHolder"})
    limit, offset = V.parse_pagination(request.args)
    event_id = request.args.get("pickup_event_id")
    invoice_id = request.args.get("applied_invoice_id")
    items = list(db.missed_pickup_credits.values())
    if event_id is not None:
        items = [c for c in items if c["pickup_event_id"] == event_id]
    if invoice_id is not None:
        items = [c for c in items if c["applied_invoice_id"] == invoice_id]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([credit_out(c) for c in page], limit, offset, total)


@bp.route("/credits/<cid>", methods=["GET"])
def get_credit(cid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    c = get_or_404(db.missed_pickup_credits, cid)
    require_ownership(role, user_id, c["account_id"])
    return ok(credit_out(c))


# --------------------------------------------------------------------------
# Contamination notices
# --------------------------------------------------------------------------
@bp.route("/accounts/<aid>/contamination-notices", methods=["GET"])
def list_account_notices(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    limit, offset = V.parse_pagination(request.args)
    items = [n for n in db.contamination_notices.values() if n["account_id"] == a["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([notice_out(n) for n in page], limit, offset, total)


@bp.route("/contamination-notices", methods=["GET"])
def list_notices():
    gate({"Dispatcher", "AccountHolder"})
    limit, offset = V.parse_pagination(request.args)
    event_id = request.args.get("pickup_event_id")
    items = list(db.contamination_notices.values())
    if event_id is not None:
        items = [n for n in items if n["pickup_event_id"] == event_id]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([notice_out(n) for n in page], limit, offset, total)


@bp.route("/contamination-notices/<nid>", methods=["GET"])
def get_notice(nid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    n = get_or_404(db.contamination_notices, nid)
    require_ownership(role, user_id, n["account_id"])
    return ok(notice_out(n))


@bp.route("/contamination-notices/<nid>/acknowledge", methods=["POST"])
def acknowledge_notice(nid):
    user_id, role = gate({"AccountHolder"})
    n = get_or_404(db.contamination_notices, nid)
    require_ownership(role, user_id, n["account_id"])
    if n["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Notice is not OPEN.")
    n["status"] = "ACKNOWLEDGED"
    touch(n)
    return ok(notice_out(n))


@bp.route("/contamination-notices/<nid>/waive", methods=["POST"])
def waive_notice(nid):
    gate({"Dispatcher"})
    n = get_or_404(db.contamination_notices, nid)
    if n["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise err("ERR_INVALID_STATE", "Notice is not OPEN or ACKNOWLEDGED.")
    n["fee_cents"] = 0  # fee waived; reverses the posting to the next invoice gross
    n["status"] = "WAIVED"
    touch(n)
    return ok(notice_out(n))
