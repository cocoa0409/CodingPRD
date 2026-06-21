"""NicuStay read/list/cancel (PRD §3.4). Stays are created via escalation."""

from flask import Blueprint, request

import db
from errors import invalid_state, not_found
from helpers import paginate, parse_pagination, require_enum, sort_created_at_asc
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("nicu_stays", __name__)

STAY_STATUSES = {"PENDING_BED", "ACTIVE", "STEPPED_DOWN", "CLOSED", "CANCELLED"}


def _get_stay(stay_id):
    s = db.nicu_stays.get(stay_id)
    if s is None:
        raise not_found("NICU stay not found.")
    return s


@bp.get("/nicu-stays/<stay_id>")
def get_stay(stay_id):
    require_roles("Neonatologist", "RegistrySupervisor")
    return ok_object(db.public(_get_stay(stay_id)))


@bp.get("/nicu-stays")
def list_stays():
    require_roles("Neonatologist", "RegistrySupervisor")
    limit, offset = parse_pagination()
    newborn_id = request.args.get("newborn_id")
    status = request.args.get("status")
    rows = list(db.nicu_stays.values())
    if newborn_id is not None:
        rows = [r for r in rows if r["newborn_id"] == newborn_id]
    if status is not None:
        require_enum(status, "status", STAY_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/nicu-stays/<stay_id>/cancel")
def cancel_stay(stay_id):
    require_roles("Neonatologist")
    s = _get_stay(stay_id)
    if s["status"] != "PENDING_BED":
        raise invalid_state("Only a PENDING_BED stay may be cancelled.")
    s["status"] = "CANCELLED"
    db.stamp_update(s)
    return ok_object(db.public(s))
