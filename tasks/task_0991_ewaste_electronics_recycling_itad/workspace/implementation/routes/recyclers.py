"""Recycler registry endpoints (PRD §3.2)."""

from flask import Blueprint

import db
import serialize
import utils
from errors import ApiError, ERR_RECYCLER_NOT_FOUND, ERR_VALIDATION
from middleware import require_roles
from response import ok_object, paginate, sort_created
from services import calculations as calc

bp = Blueprint("recyclers", __name__)

STANDARDS = {"R2", "E_STEWARDS"}
BATCH_STATUSES = {"STAGING", "IN_TRANSIT", "DELIVERED", "PROCESSED"}


def get_recycler_or_404(recycler_id):
    recycler = db.recyclers.get(recycler_id)
    if recycler is None:
        raise ApiError(ERR_RECYCLER_NOT_FOUND, 404, "no Recycler with the given id")
    return recycler


@bp.post("/itad/recyclers")
def create_recycler():
    uid, role = require_roles("ComplianceOfficer")
    data = utils.body_json()
    name = utils.req_str(data, "name")
    standard = utils.req_enum(data, "certification_standard", STANDARDS)
    expires_at = utils.req_datetime(data, "certification_expires_at")
    categories = utils.req_enum_list(data, "accepted_categories", calc.CATEGORIES)
    capacity = utils.req_number(data, "daily_intake_capacity_kg")
    if capacity <= 0:
        raise ApiError(ERR_VALIDATION, 400, "daily_intake_capacity_kg must be greater than zero")
    violation_count = utils.opt_int(data, "violation_count")
    if violation_count is None:
        violation_count = 0
    if violation_count < 0:
        raise ApiError(ERR_VALIDATION, 400, "violation_count must be >= 0")
    recycler = {
        "id": utils.new_id(),
        "name": name,
        "certification_standard": standard,
        "certification_expires_at": expires_at,
        "accepted_categories": categories,
        "daily_intake_capacity_kg": capacity,
        "violation_count": violation_count,
        "total_processed_kg": calc.Decimal("0"),
    }
    utils.stamp_new(recycler)
    db.recyclers[recycler["id"]] = recycler
    return ok_object(serialize.recycler(recycler, calc.recycler_risk_score(recycler)), code=201)


@bp.get("/itad/recyclers/<recycler_id>")
def read_recycler(recycler_id):
    uid, role = require_roles("PlatformAdmin", "ComplianceOfficer", "LogisticsCoordinator")
    recycler = get_recycler_or_404(recycler_id)
    return ok_object(serialize.recycler(recycler, calc.recycler_risk_score(recycler)))


@bp.get("/itad/recyclers/<recycler_id>/recycle-batches")
def list_recycler_batches(recycler_id):
    uid, role = require_roles("PlatformAdmin", "ComplianceOfficer", "LogisticsCoordinator")
    recycler = get_recycler_or_404(recycler_id)
    records = [b for b in db.batches.values() if b["recycler_id"] == recycler["id"]]
    from flask import request
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in BATCH_STATUSES:
            raise ApiError(ERR_VALIDATION, 400, "invalid status filter")
        records = [b for b in records if b["status"] == status_filter]
    records = sort_created(records)
    return paginate([serialize.batch(b) for b in records])
