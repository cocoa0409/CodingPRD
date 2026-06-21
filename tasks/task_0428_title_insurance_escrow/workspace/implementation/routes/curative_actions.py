"""CurativeAction endpoints (PRD §3.5). Open under an order against an EXCEPTION or
CLAIM / get / list / transition (RESOLVE unblocks the dependent clear/pay; ABANDON).
"""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_curative_action
from services.domain import touch, require_agency_owns_order
from helpers import (
    get_body, require_str, require_enum,
    parse_pagination, paginate, sort_by_created,
)
from routes.orders import get_order_or_404

bp = Blueprint("curative_actions", __name__)

SUBJECT_TYPES = {"EXCEPTION", "CLAIM"}
ACTION_TYPES = {"PAYOFF", "RELEASE_FILED", "QUIET_TITLE", "INDEMNITY"}
CURATIVE_STATUSES = {"OPEN", "RESOLVED", "ABANDONED"}


def _get_curative_or_404(cid):
    c = db.curative_actions.get(cid)
    if c is None:
        raise errors.not_found("Curative action not found")
    return c


@bp.route("/title/orders/<oid>/curative-actions", methods=["POST"])
@require_roles("TitleOfficer", "Underwriter")
def create_curative_action(oid):
    order = get_order_or_404(oid)
    body = get_body()
    subject_type = require_enum(body, "subject_type", SUBJECT_TYPES)
    subject_id = require_str(body, "subject_id")
    action_type = require_enum(body, "action_type", ACTION_TYPES)

    # Existence (priority 3): the polymorphic subject must resolve.
    if subject_type == "EXCEPTION":
        if subject_id not in db.exceptions:
            raise errors.not_found("Subject exception not found")
    else:  # CLAIM
        if subject_id not in db.claims:
            raise errors.not_found("Subject claim not found")

    ts = now_ts()
    cid = new_id()
    record = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "order_id": order["id"],
        "subject_type": subject_type,
        "subject_id": subject_id,
        "action_type": action_type,
        "status": "OPEN",
    }
    db.curative_actions[cid] = record
    return success(serialize_curative_action(record), status=201)


@bp.route("/title/orders/<oid>/curative-actions", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter", "Agency")
def list_curative_actions(oid):
    order = get_order_or_404(oid)
    require_agency_owns_order(order)
    limit, offset = parse_pagination()
    items = [c for c in db.curative_actions.values() if c["order_id"] == order["id"]]
    subject_type = request.args.get("subject_type")
    if subject_type is not None:
        items = [c for c in items if c["subject_type"] == subject_type]
    subject_id = request.args.get("subject_id")
    if subject_id is not None:
        items = [c for c in items if c["subject_id"] == subject_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_curative_action(c) for c in page], limit, offset, total)


@bp.route("/title/curative-actions/<cid>", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter")
def get_curative_action(cid):
    c = _get_curative_or_404(cid)
    return success(serialize_curative_action(c), status=200)


@bp.route("/title/curative-actions/<cid>/transitions", methods=["POST"])
@require_roles("TitleOfficer", "Underwriter")
def transition_curative_action(cid):
    body = get_body()
    c = _get_curative_or_404(cid)
    to_status = require_enum(body, "to_status", CURATIVE_STATUSES)
    cur = c["status"]

    if to_status == "RESOLVED":
        if cur != "OPEN":
            raise errors.invalid_state("Curative action is not OPEN")
        c["status"] = "RESOLVED"
        touch(c)
    elif to_status == "ABANDONED":
        if cur != "OPEN":
            raise errors.invalid_state("Curative action is not OPEN")
        c["status"] = "ABANDONED"
        touch(c)
    else:
        raise errors.invalid_state("Unsupported curative action transition")

    return success(serialize_curative_action(c), status=200)
