"""Margin calls: reads, per-account listing, waiver (PRD 3.7)."""
from flask import Blueprint, request

from authz import ANY_ROLE, SUPERVISOR, require_roles
from cascades import posture_recheck
from db import store
from errors import call_not_found, call_not_open
from response import success
from serialize import ser_call
from store_ops import paginate, sorted_by_creation, touch
from routes.accounts import get_account_or_404

bp = Blueprint("calls", __name__)


def get_call_or_404(call_id):
    call = store.calls.get(call_id)
    if call is None:
        raise call_not_found()
    return call


@bp.route("/margin/accounts/<aid>/margin-calls", methods=["GET"])
def list_account_calls(aid):
    require_roles(ANY_ROLE)
    get_account_or_404(aid)
    status = request.args.get("call_status")
    items = [c for c in store.calls.values() if c["account_id"] == aid]
    if status is not None:
        items = [c for c in items if c["call_status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_call(c) for c in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/margin-calls/<cid>", methods=["GET"])
def get_call(cid):
    require_roles(ANY_ROLE)
    return success(ser_call(get_call_or_404(cid)))


@bp.route("/margin/margin-calls/<cid>/waive", methods=["POST"])
def waive_call(cid):
    require_roles([SUPERVISOR])
    call = get_call_or_404(cid)
    # Waive is permitted from OPEN or EXPIRED only (PRD 3.7).
    if call["call_status"] not in ("OPEN", "EXPIRED"):
        raise call_not_open()
    call["call_status"] = "WAIVED"
    call["cure_method"] = "WAIVER"
    call["resolved_at"] = store.clock
    touch(call)
    posture_recheck(store.accounts[call["account_id"]])
    return success(ser_call(call))
