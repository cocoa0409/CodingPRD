"""TitleSearch endpoints (PRD §3.3). Order a search under an order; exam workflow;
completion persists chain_verified + gap window and opens the parent order's gap.
"""

from flask import Blueprint, request, g

import errors
from clock import parse_iso8601
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_title_search
from services.domain import touch, require_agency_owns_order
from helpers import (
    get_body, require_str, require_enum, require_bool,
    parse_pagination, paginate, sort_by_created,
)
from routes.orders import get_order_or_404

bp = Blueprint("title_searches", __name__)

SEARCH_STATUSES = {"ORDERED", "IN_EXAM", "COMPLETED", "CANCELLED"}


def _get_search_or_404(sid):
    s = db.title_searches.get(sid)
    if s is None:
        raise errors.not_found("Title search not found")
    return s


def _parse_dt(value, field):
    try:
        return parse_iso8601(value)
    except (ValueError, TypeError):
        raise errors.invalid_request("%s must be a valid ISO 8601 instant" % field)


@bp.route("/title/orders/<oid>/title-searches", methods=["POST"])
@require_roles("TitleOfficer")
def create_title_search(oid):
    order = get_order_or_404(oid)
    body = get_body()
    searched_parcel_id = require_str(body, "searched_parcel_id")
    effective_date = require_str(body, "effective_date")
    _parse_dt(effective_date, "effective_date")

    ts = now_ts()
    sid = new_id()
    record = {
        "id": sid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "order_id": order["id"],
        "searched_parcel_id": searched_parcel_id,
        "effective_date": effective_date,
        "status": "ORDERED",
        "chain_verified": False,
        "gap_from_date": None,
        "gap_to_date": None,
    }
    db.title_searches[sid] = record
    return success(serialize_title_search(record), status=201)


@bp.route("/title/orders/<oid>/title-searches", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter", "Agency")
def list_title_searches(oid):
    order = get_order_or_404(oid)
    require_agency_owns_order(order)
    limit, offset = parse_pagination()
    items = [s for s in db.title_searches.values() if s["order_id"] == order["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_title_search(s) for s in page], limit, offset, total)


@bp.route("/title/title-searches/<sid>", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter")
def get_title_search(sid):
    s = _get_search_or_404(sid)
    return success(serialize_title_search(s), status=200)


@bp.route("/title/title-searches/<sid>/transitions", methods=["POST"])
@require_roles("TitleOfficer")
def transition_title_search(sid):
    body = get_body()
    s = _get_search_or_404(sid)
    to_status = require_enum(body, "to_status", SEARCH_STATUSES)
    cur = s["status"]

    if to_status == "IN_EXAM":
        if cur != "ORDERED":
            raise errors.invalid_state("Title search is not ORDERED")
        s["status"] = "IN_EXAM"
        touch(s)
    elif to_status == "COMPLETED":
        if cur != "IN_EXAM":
            raise errors.invalid_state("Title search is not IN_EXAM")
        # Body well-formedness (priority 4): chain_verified, gap_from_date, gap_to_date.
        chain_verified = require_bool(body, "chain_verified")
        gap_from_date = require_str(body, "gap_from_date")
        gap_to_date = require_str(body, "gap_to_date")
        gap_from = _parse_dt(gap_from_date, "gap_from_date")
        gap_to = _parse_dt(gap_to_date, "gap_to_date")
        # gap_from_date <= gap_to_date else ERR_INVALID_GAP_WINDOW (422).
        if gap_from > gap_to:
            raise errors.ApiError(errors.ERR_INVALID_GAP_WINDOW, 422,
                                  "gap_from_date must be <= gap_to_date")
        s["chain_verified"] = chain_verified
        s["gap_from_date"] = gap_from_date
        s["gap_to_date"] = gap_to_date
        s["status"] = "COMPLETED"
        touch(s)
        # Side effect: parent Order.gap_open set true.
        order = db.orders.get(s["order_id"])
        if order is not None:
            order["gap_open"] = True
            touch(order)
    elif to_status == "CANCELLED":
        if cur not in ("ORDERED", "IN_EXAM"):
            raise errors.invalid_state("Title search cannot be cancelled from " + cur)
        s["status"] = "CANCELLED"
        touch(s)
    else:
        raise errors.invalid_state("Unsupported title search transition")

    return success(serialize_title_search(s), status=200)
