"""Monthly bills endpoints."""
from flask import Blueprint, request, g

import db
from errors import err
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services.bills_svc import create_bill, finalize_bill, settle_bill


bp = Blueprint("bills", __name__)


def _serialize(b):
    return {k: v for k, v in b.items() if not k.startswith("_")}


@bp.route("/shuttle/bills", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def create_b():
    body = get_json_body()
    b = create_bill(body, actor_role=g.user_role, actor_id=g.user_id)
    return success(_serialize(b), status=201)


@bp.route("/shuttle/bills/<bid>/finalize", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def finalize_b(bid):
    b = db.monthly_bills.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Bill not found")
    finalize_bill(b, actor_role=g.user_role, actor_id=g.user_id)
    return success(_serialize(b))


@bp.route("/shuttle/bills/<bid>/settle", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def settle_b(bid):
    b = db.monthly_bills.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Bill not found")
    settle_bill(b, actor_role=g.user_role, actor_id=g.user_id)
    return success(_serialize(b))


@bp.route("/shuttle/bills", methods=["GET"])
@require_auth(roles={"Dispatcher", "Auditor"})
def list_bills():
    limit, offset = get_pagination()
    scope = request.args.get("payer_scope")
    pid = request.args.get("payer_id")
    status = request.args.get("status")
    bm = request.args.get("billing_month")
    items = list(db.monthly_bills.values())
    if scope:
        items = [b for b in items if b.get("payer_scope") == scope]
    if pid:
        items = [b for b in items if b.get("payer_id") == pid]
    if status:
        items = [b for b in items if b.get("status") == status]
    if bm:
        items = [b for b in items if b.get("billing_month") == bm]
    items.sort(key=lambda b: b.get("_seq", 0))
    page = items[offset:offset + limit]
    return success_list([_serialize(b) for b in page], limit, offset, len(items))
