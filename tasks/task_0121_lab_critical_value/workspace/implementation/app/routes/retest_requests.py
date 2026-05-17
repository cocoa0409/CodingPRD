"""RetestRequest endpoints: fetch, list, cancel."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import (
    ROLE_LAB_DIRECTOR,
    ROLE_LAB_TECH,
    ROLE_ORDERING_PROVIDER,
    require_roles,
)
from ..errors import err_forbidden, err_invalid_state
from ..helpers import paginate, parse_pagination, require_json_object
from ..responses import listing, ok
from ..services.lookups import (
    get_lab_order,
    get_retest_request,
)
from ..services.serialize import retest_request_view
from ..services.workflows import bump
from ..store import store

bp = Blueprint("retest_requests", __name__)


@bp.route("/retest-requests/<rid>", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def fetch_retest(rid, **_):
    return ok(retest_request_view(get_retest_request(rid)))


@bp.route("/retest-requests", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def list_retests(**_):
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    lab_order_f = request.args.get("lab_order_id")
    items = list(store().retest_requests.values())
    if status_f:
        items = [r for r in items if r["status"] == status_f]
    if lab_order_f:
        items = [r for r in items if r["lab_order_id"] == lab_order_f]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return listing([retest_request_view(r) for r in page], total, limit, offset)


@bp.route("/retest-requests/<rid>/cancel", methods=["POST"])
@require_roles(ROLE_ORDERING_PROVIDER)
def cancel_retest(rid, _caller_id=None, **_):
    require_json_object()
    with store().lock:
        retest = get_retest_request(rid)
        if retest["status"] != "ISSUED":
            raise err_invalid_state(f"RetestRequest must be ISSUED to cancel (was {retest['status']})")
        original_order = get_lab_order(retest["lab_order_id"])
        if original_order["ordering_provider_id"] != _caller_id:
            raise err_forbidden("Only the original ordering provider may cancel this retest")

        # If new replacement order exists, it must still be ORDERED (or absent)
        new_order_id = retest.get("new_lab_order_id")
        new_order = store().lab_orders.get(new_order_id) if new_order_id else None
        if new_order is not None and new_order["status"] != "ORDERED":
            raise err_invalid_state("Replacement LabOrder is no longer ORDERED")

        retest["status"] = "CANCELED"
        bump(retest)
        if new_order is not None:
            new_order["status"] = "CANCELED"
            bump(new_order)
    return ok(retest_request_view(retest))
