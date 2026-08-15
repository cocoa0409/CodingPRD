"""Disclosure endpoints."""

from flask import request, Blueprint
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from errors import (
    make_error, ERR_NOT_FOUND, ERR_INVALID_STATE,
)
from services.calculations import compute_allocation_lines

bp = Blueprint("disclosures", __name__)


def serialize_disclosure(disc):
    study = store.reserve_studies.get(disc["study_id"])
    alloc_lines = compute_allocation_lines(disc, study) if study else []
    # is_late: computed on read
    is_late = False
    if disc["status"] == "DISTRIBUTED" and disc.get("distributed_at"):
        dist_date = disc["distributed_at"][:10]  # YYYY-MM-DD from ISO timestamp
        if dist_date > disc["due_date"]:
            is_late = True

    return {
        "id": disc["id"],
        "created_at": disc["created_at"],
        "updated_at": disc["updated_at"],
        "version": disc["version"],
        "study_id": disc["study_id"],
        "disclosure_type": disc["disclosure_type"],
        "status": disc["status"],
        "due_date": disc["due_date"],
        "distributed_at": disc.get("distributed_at"),
        "is_late": is_late,
        "allocation_lines": alloc_lines,
    }


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


@bp.route("/reserve-studies/<id>/disclosures", methods=["GET"])
def list_disclosures(id):
    require_roles(*ANY_ROLE)
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")

    discs = [d for d in store.disclosures.values() if d["study_id"] == id]

    status_filter = request.args.get("status")
    if status_filter:
        discs = [d for d in discs if d["status"] == status_filter]

    type_filter = request.args.get("disclosure_type")
    if type_filter:
        discs = [d for d in discs if d["disclosure_type"] == type_filter]

    discs.sort(key=lambda d: d["created_at"])
    limit, offset = _parse_pagination()
    total = len(discs)
    page = discs[offset:offset + limit]
    return success_list([serialize_disclosure(d) for d in page], total, limit, offset)


@bp.route("/disclosures/<id>/distribute", methods=["POST"])
def distribute_disclosure(id):
    require_roles("AssociationManager")
    disc = store.disclosures.get(id)
    if not disc:
        raise make_error(ERR_NOT_FOUND, f"Disclosure {id} not found")

    if disc["status"] != "PENDING":
        raise make_error(ERR_INVALID_STATE, f"Disclosure is {disc['status']}, not PENDING")

    disc["status"] = "DISTRIBUTED"
    disc["distributed_at"] = store.now_iso()
    store.touch(disc)

    return success_object(serialize_disclosure(disc))
