"""Commitment endpoints (PRD §3.4). Issue / re-issue (OCC-guarded create) / get /
list / transition (DRAFT->ISSUED, UPDATED->ISSUED revision loop, ISSUED->EXPIRED).

The create is the first order-scoped operation guarded by expected_order_version
(§2.7): the field is required and is matched against Order.version (412 on
mismatch). When the order already has an ISSUED commitment, the new commitment
supersedes it — the prior ISSUED commitment flips to UPDATED, its revision_no is
incremented, and the order's version is bumped by 1.
"""

from flask import Blueprint, request, g

import errors
from clock import parse_iso8601, clock
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_commitment
from services.domain import (
    touch, require_agency_owns_order, order_current_issued_commitment,
    void_commitment_open_exceptions,
)
from helpers import (
    get_body, require_str, require_enum, require_int_min, require_int,
    parse_pagination, paginate, sort_by_created,
)
from routes.orders import get_order_or_404

bp = Blueprint("commitments", __name__)

ESTATES = {"FEE_SIMPLE", "LEASEHOLD"}
COMMITMENT_STATUSES = {"DRAFT", "ISSUED", "UPDATED", "EXPIRED", "CANCELLED"}


def _get_commitment_or_404(cid):
    c = db.commitments.get(cid)
    if c is None:
        raise errors.not_found("Commitment not found")
    return c


def _parse_dt(value, field):
    try:
        return parse_iso8601(value)
    except (ValueError, TypeError):
        raise errors.invalid_request("%s must be a valid ISO 8601 instant" % field)


def _require_dt(body, name):
    """Require a string body field that parses as an ISO 8601 instant."""
    val = require_str(body, name)
    _parse_dt(val, name)
    return val


@bp.route("/title/orders/<oid>/commitments", methods=["POST"])
@require_roles("TitleOfficer")
def create_commitment(oid):
    order = get_order_or_404(oid)
    body = get_body()
    # Body well-formedness (priority 4).
    effective_date = _require_dt(body, "effective_date")
    expiry_date = _require_dt(body, "expiry_date")
    schedule_a_estate = require_enum(body, "schedule_a_estate", ESTATES)
    insured_amount_cents = require_int_min(body, "insured_amount_cents", 1)
    expected_order_version = require_int(body, "expected_order_version")

    # OCC (priority 5): expected_order_version must match the order's version.
    if expected_order_version != order["version"]:
        raise errors.stale_version()

    # If the order already has an ISSUED commitment, this create supersedes it.
    prior = order_current_issued_commitment(order["id"])
    if prior is not None:
        prior["status"] = "UPDATED"
        prior["revision_no"] += 1
        touch(prior)
        # Parent bump (OCC backing) for the commitment re-issue.
        order["version"] += 1
        order["updated_at"] = now_ts()

    ts = now_ts()
    cid = new_id()
    record = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "order_id": order["id"],
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "schedule_a_estate": schedule_a_estate,
        "insured_amount_cents": insured_amount_cents,
        "status": "DRAFT",
        "revision_no": 0,
    }
    db.commitments[cid] = record
    return success(serialize_commitment(record), status=201)


@bp.route("/title/orders/<oid>/commitments", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter", "Agency")
def list_order_commitments(oid):
    order = get_order_or_404(oid)
    require_agency_owns_order(order)
    limit, offset = parse_pagination()
    items = [c for c in db.commitments.values() if c["order_id"] == order["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_commitment(c) for c in page], limit, offset, total)


@bp.route("/title/commitments/<cid>", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter", "Agency")
def get_commitment(cid):
    c = _get_commitment_or_404(cid)
    if g.user_role == "Agency":
        order = db.orders.get(c["order_id"])
        if order is not None:
            require_agency_owns_order(order)
    return success(serialize_commitment(c), status=200)


@bp.route("/title/commitments/<cid>/transitions", methods=["POST"])
@require_roles("TitleOfficer")
def transition_commitment(cid):
    body = get_body()
    c = _get_commitment_or_404(cid)
    to_status = require_enum(body, "to_status", COMMITMENT_STATUSES)
    cur = c["status"]

    if to_status == "ISSUED":
        # DRAFT->ISSUED or UPDATED->ISSUED (revision loop).
        if cur not in ("DRAFT", "UPDATED"):
            raise errors.invalid_state("Commitment is not DRAFT or UPDATED")
        # No OTHER commitment on the same order may be ISSUED.
        other = order_current_issued_commitment(c["order_id"])
        if other is not None and other["id"] != c["id"]:
            raise errors.invalid_state("Another commitment on this order is already ISSUED")
        c["status"] = "ISSUED"
        touch(c)
    elif to_status == "EXPIRED":
        if cur != "ISSUED":
            raise errors.invalid_state("Commitment is not ISSUED")
        # Logical clock must be at/after expiry_date.
        expiry = _parse_dt(c["expiry_date"], "expiry_date")
        if clock.now() < expiry:
            raise errors.ApiError(errors.ERR_COMMITMENT_NOT_EXPIRABLE, 409,
                                  "Logical clock has not reached the commitment expiry")
        c["status"] = "EXPIRED"
        touch(c)
        # Side effect: void RAISED/CURATIVE_PENDING child exceptions.
        void_commitment_open_exceptions(c)
    else:
        # CANCELLED is only reachable via system cascade; DRAFT/UPDATED targets
        # are not client-driven transitions.
        raise errors.invalid_state("Unsupported commitment transition")

    return success(serialize_commitment(c), status=200)
