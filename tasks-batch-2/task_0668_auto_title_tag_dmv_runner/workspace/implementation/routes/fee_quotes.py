"""FeeQuote read endpoints (PRD §3.3; scaffold §1.5)."""

from flask import Blueprint, g, request

import errors
from db import db
from helpers import parse_pagination, paginate
from middleware import require_roles
from response import success, list_success
from serializers import fee_quote_out

bp = Blueprint("fee_quotes", __name__)


def _account_owns_quote(quote, user_id):
    txn = db.transactions.get(quote["transaction_id"])
    return txn is not None and txn["account_id"] == user_id


@bp.route("/dmv/fee-quotes", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "AccountHolder")
def list_fee_quotes():
    limit, offset = parse_pagination()
    transaction_id = request.args.get("transaction_id")
    status = request.args.get("status")
    items = list(db.fee_quotes.values())
    if transaction_id is not None:
        items = [q for q in items if q["transaction_id"] == transaction_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    if g.user_role == "AccountHolder":
        items = [q for q in items if _account_owns_quote(q, g.user_id)]
    page, total = paginate(items, limit, offset)
    return list_success([fee_quote_out(q) for q in page], limit, offset, total)


@bp.route("/dmv/fee-quotes/<qid>", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "AccountHolder")
def get_fee_quote(qid):
    q = db.fee_quotes.get(qid)
    if q is None:
        raise errors.not_found("fee quote not found")
    if g.user_role == "AccountHolder" and not _account_owns_quote(q, g.user_id):
        raise errors.not_resource_owner("AccountHolder may only read own quotes")
    return success(fee_quote_out(q), 200)
