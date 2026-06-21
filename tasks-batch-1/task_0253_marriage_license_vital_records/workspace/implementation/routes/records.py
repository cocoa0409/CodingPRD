"""MarriageRecord endpoints (PRD 3.5)."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from util import serialize, touch
from services.common import lookup, parse_pagination, sort_by_created
from services import derived

bp = Blueprint("records", __name__)


def _record_view(rec):
    out = serialize(rec)
    out["amendment_count"] = derived.compute_amendment_count(rec["id"])
    out["certified_copies_issued"] = derived.compute_certified_copies_issued(rec["id"])
    return out


@bp.route("/records/<record_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def get_record(record_id):
    rec = lookup("record", record_id)
    return success(_record_view(rec), status=200)


@bp.route("/records", methods=["GET"])
@require_roles("Clerk", "Registrar")
def list_records():
    limit, offset = parse_pagination()
    license_filter = request.args.get("license_id")
    return_filter = request.args.get("return_id")
    items = list(store.records.values())
    if license_filter is not None:
        items = [r for r in items if r["license_id"] == license_filter]
    if return_filter is not None:
        items = [r for r in items if r["return_id"] == return_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_record_view(r) for r in page], limit, offset, total)


@bp.route("/records/<record_id>/seal", methods=["POST"])
@require_roles("Registrar")
def seal_record(record_id):
    rec = lookup("record", record_id)
    if rec["status"] not in ("REGISTERED", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", "Record cannot be sealed from its current state")
    # Blocked if any certified-copy request for this record is still PENDING.
    has_pending = any(
        c["record_id"] == record_id and c["status"] == "PENDING"
        for c in store.certified_copies.values()
    )
    if has_pending:
        raise ApiError("ERR_RECORD_HAS_PENDING_COPIES", "Record has pending copy requests")
    rec["status"] = "SEALED"
    rec["is_confidential"] = True
    touch(rec)
    return success(_record_view(rec), status=200)


@bp.route("/records/<record_id>/certified-copies", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def list_record_copies(record_id):
    lookup("record", record_id)
    limit, offset = parse_pagination()
    items = [c for c in store.certified_copies.values() if c["record_id"] == record_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.route("/records/<record_id>/amendments", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def list_record_amendments(record_id):
    lookup("record", record_id)
    limit, offset = parse_pagination()
    items = [a for a in store.amendments.values() if a["record_id"] == record_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(a) for a in page], limit, offset, total)
