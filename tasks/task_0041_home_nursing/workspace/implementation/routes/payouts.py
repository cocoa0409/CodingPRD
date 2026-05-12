"""Routes for /payout-batches."""
from flask import Blueprint

from db import public
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services import settlement as svc


bp = Blueprint("payouts", __name__)


@bp.route("/payout-batches", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def build_batch():
    body = get_json_body()
    batch = svc.build_payout_batch(body)
    return success(public(batch), status=201)


@bp.route("/payout-batches", methods=["GET"])
@require_auth(roles={"PlatformAdmin"})
def list_batches():
    limit, offset = get_pagination()
    rows, total = svc.list_payout_batches(limit, offset)
    return success_list([public(r) for r in rows], limit, offset, total)
