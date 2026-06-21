"""Schedule B Exception endpoints (PRD §3.5). Raise / get / list / transition
(waive, curative, clear, revert).
"""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_exception
from services.domain import touch, require_agency_owns_order
from helpers import (
    get_body, require_str, require_enum, opt_bool,
    parse_pagination, paginate, sort_by_created,
)
from routes.commitments import _get_commitment_or_404

bp = Blueprint("exceptions", __name__)

EXCEPTION_TYPES = {"STANDARD", "SPECIAL", "SUBORDINATE_LIEN"}
EXCEPTION_STATUSES = {"RAISED", "CURATIVE_PENDING", "WAIVED", "CLEARED", "VOID"}


def _get_exception_or_404(eid):
    e = db.exceptions.get(eid)
    if e is None:
        raise errors.not_found("Exception not found")
    return e


def _agency_guard_for_commitment(commitment):
    if g.user_role == "Agency":
        order = db.orders.get(commitment["order_id"])
        if order is not None:
            require_agency_owns_order(order)


@bp.route("/title/commitments/<cid>/exceptions", methods=["POST"])
@require_roles("TitleOfficer")
def create_exception(cid):
    commitment = _get_commitment_or_404(cid)
    body = get_body()
    exception_type = require_enum(body, "exception_type", EXCEPTION_TYPES)
    description = require_str(body, "description")
    curative_required = opt_bool(body, "curative_required", False)

    ts = now_ts()
    eid = new_id()
    record = {
        "id": eid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "commitment_id": commitment["id"],
        "exception_type": exception_type,
        "description": description,
        "curative_required": curative_required,
        "status": "RAISED",
    }
    db.exceptions[eid] = record
    return success(serialize_exception(record), status=201)


@bp.route("/title/commitments/<cid>/exceptions", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter", "Agency")
def list_exceptions(cid):
    commitment = _get_commitment_or_404(cid)
    _agency_guard_for_commitment(commitment)
    limit, offset = parse_pagination()
    items = [e for e in db.exceptions.values() if e["commitment_id"] == commitment["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_exception(e) for e in page], limit, offset, total)


@bp.route("/title/exceptions/<eid>", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter")
def get_exception(eid):
    e = _get_exception_or_404(eid)
    return success(serialize_exception(e), status=200)


def _has_resolved_curative(subject_type, subject_id):
    for c in db.curative_actions.values():
        if (c["subject_type"] == subject_type and c["subject_id"] == subject_id
                and c["status"] == "RESOLVED"):
            return True
    return False


@bp.route("/title/exceptions/<eid>/transitions", methods=["POST"])
@require_roles("TitleOfficer")
def transition_exception(eid):
    body = get_body()
    e = _get_exception_or_404(eid)
    to_status = require_enum(body, "to_status", EXCEPTION_STATUSES)
    cur = e["status"]

    if to_status == "WAIVED":
        if cur != "RAISED":
            raise errors.invalid_state("Exception is not RAISED")
        # Safety (priority 9): a curative_required exception cannot be waived.
        if e["curative_required"]:
            raise errors.ApiError(errors.ERR_CURATIVE_REQUIRED, 409,
                                  "A curative-required exception cannot be waived")
        e["status"] = "WAIVED"
        touch(e)
    elif to_status == "CURATIVE_PENDING":
        if cur != "RAISED":
            raise errors.invalid_state("Exception is not RAISED")
        e["status"] = "CURATIVE_PENDING"
        touch(e)
    elif to_status == "CLEARED":
        if cur != "CURATIVE_PENDING":
            raise errors.invalid_state("Exception is not CURATIVE_PENDING")
        # Safety (priority 9): a RESOLVED CurativeAction on this exception is required.
        if not _has_resolved_curative("EXCEPTION", e["id"]):
            raise errors.ApiError(errors.ERR_NO_RESOLVED_CURATIVE, 409,
                                  "No RESOLVED CurativeAction on this exception")
        e["status"] = "CLEARED"
        touch(e)
    elif to_status == "RAISED":
        # Revert from CURATIVE_PENDING (curative failed).
        if cur != "CURATIVE_PENDING":
            raise errors.invalid_state("Exception is not CURATIVE_PENDING")
        e["status"] = "RAISED"
        touch(e)
    else:
        raise errors.invalid_state("Unsupported exception transition")

    return success(serialize_exception(e), status=200)
