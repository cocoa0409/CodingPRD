"""BackorderNotice endpoints: get/list, update-eta (cyclic forward-only loop)."""
from flask import Blueprint, request

from db import clock_date, now_ts, public, store, touch
from errors import ERR_BACKORDER_NOT_OPEN, ERR_ETA_NOT_FORWARD, raise_err
from middleware import ALL_ROLES, authenticate, require_roles
from response import success
from validation import body, get_or_404, paginate, parse_pagination, pdate, req_date

bp = Blueprint("backorder_notices", __name__)


@bp.route("/v1/backorder-notices/<rid>", methods=["GET"])
def get_backorder_notice(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.backorder_notices, rid, "backorder notice")
    return success(public(rec), code=200)


@bp.route("/v1/backorder-notices", methods=["GET"])
def list_backorder_notices():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.backorder_notices.values())
    po_line_id = request.args.get("po_line_id")
    status = request.args.get("status")
    if po_line_id is not None:
        records = [r for r in records if r["po_line_id"] == po_line_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


@bp.route("/v1/backorder-notices/<rid>/update-eta", methods=["POST"])
def update_eta(rid):
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    notice = get_or_404(store.backorder_notices, rid, "backorder notice")
    data = body()
    new_eta = req_date(data, "new_eta_date")

    # state guard: only OPEN or ETA_UPDATED notices accept updates
    if notice["status"] not in ("OPEN", "ETA_UPDATED"):
        raise_err(ERR_BACKORDER_NOT_OPEN, f"Cannot update the ETA of a notice in status {notice['status']}")

    # priority 8: strictly later than both the current ETA and the clock date
    if pdate(new_eta) <= pdate(notice["current_eta_date"]) or pdate(new_eta) <= clock_date():
        raise_err(ERR_ETA_NOT_FORWARD, "new_eta_date must be strictly later than the current ETA and the current clock date")

    notice["current_eta_date"] = new_eta
    notice["revision_count"] += 1
    notice["communicated_at"] = now_ts()
    notice["status"] = "ETA_UPDATED"
    touch(notice)
    return success(public(notice), code=200)
