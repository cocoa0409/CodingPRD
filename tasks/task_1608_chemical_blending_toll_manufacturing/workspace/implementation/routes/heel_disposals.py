"""Heel disposal endpoints."""
from decimal import Decimal
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    serialize_heel_disposal,
    to_decimal,
    parse_iso,
    as_float_3dp,
    sort_by_created_at,
    pagination_params,
    paginate,
    reconcile_lot_quantities,
)
from services.calculations import zone_admits

bp = Blueprint("heel_disposals", __name__)

DISPOSAL_METHODS = {"INCINERATION", "FUEL_BLENDING", "HAZARDOUS_LANDFILL"}


def _customer_or_404(cid):
    c = db.customers.get(cid)
    if c is None:
        raise errors.not_found("customer not found")
    return c


def _batch_or_404(customer_id, batch_id):
    b = db.batch_jobs.get(batch_id)
    if b is None or b["customer_id"] != customer_id:
        raise errors.not_found("batch job not found")
    return b


def _heel_or_404(batch_id, record_id):
    h = db.heel_disposals.get(record_id)
    if h is None or h["batch_job_id"] != batch_id:
        raise errors.not_found("heel disposal record not found")
    return h


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/heel-disposals", methods=["POST"])
def create_heel_disposal(id, batchJobId):
    require_role({"TankOperator"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    body = request.get_json(silent=True) or {}
    lot_id = body.get("raw_material_lot_id")
    if not lot_id:
        raise errors.invalid_request("raw_material_lot_id required")
    # Lot must exist
    lot = db.raw_material_lots.get(lot_id)
    if lot is None:
        raise errors.not_found("raw material lot not found")
    # Lot must be one already charged into this batch
    charged = any(
        c["batch_job_id"] == batch["id"] and c["raw_material_lot_id"] == lot_id
        for c in db.batch_charges.values()
    )
    if not charged:
        raise errors.invalid_request("lot was not charged into this batch")

    heel_returned_kg = to_decimal(body.get("heel_returned_kg", 0), "heel_returned_kg")
    heel_disposed_kg = to_decimal(body.get("heel_disposed_kg", 0), "heel_disposed_kg")
    if heel_returned_kg < 0 or heel_disposed_kg < 0:
        raise errors.invalid_request("heel masses must be >= 0")
    if heel_returned_kg == 0 and heel_disposed_kg == 0:
        raise errors.invalid_request("at least one of heel_returned_kg/heel_disposed_kg must be > 0")

    disposal_method = body.get("disposal_method")
    waste_manifest_number = body.get("waste_manifest_number")
    if disposal_method is not None and disposal_method not in DISPOSAL_METHODS:
        raise errors.invalid_request("disposal_method invalid")

    disposed_at = body.get("disposed_at")
    if not disposed_at:
        raise errors.invalid_request("disposed_at required")
    parse_iso(disposed_at)

    now = now_iso()
    hid = new_id()
    record = {
        "id": hid,
        "batch_job_id": batch["id"],
        "raw_material_lot_id": lot_id,
        "heel_returned_kg": as_float_3dp(heel_returned_kg),
        "heel_disposed_kg": as_float_3dp(heel_disposed_kg),
        "disposal_method": disposal_method,
        "waste_manifest_number": waste_manifest_number,
        "disposed_at": disposed_at,
        "status": "PENDING",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.heel_disposals[hid] = record
    return success_object(serialize_heel_disposal(record), status=201)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/heel-disposals", methods=["GET"])
def list_heel_disposals(id, batchJobId):
    require_role({"Any"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    rows = [h for h in db.heel_disposals.values() if h["batch_job_id"] == batchJobId]
    rows = sort_by_created_at(rows)
    limit, offset = pagination_params()
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_heel_disposal(h) for h in slice_], limit, offset, total)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/heel-disposals/<recordId>/post", methods=["POST"])
def post_heel_disposal(id, batchJobId, recordId):
    require_role({"TankOperator"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    record = _heel_or_404(batchJobId, recordId)
    if record["status"] != "PENDING":
        raise errors.invalid_state("heel disposal record not PENDING")

    # Per PRD §3.9 ordering: segregation check fires BEFORE manifest check.
    lot = db.raw_material_lots.get(record["raw_material_lot_id"])
    if record["heel_returned_kg"] and record["heel_returned_kg"] > 0:
        if lot is not None:
            if not zone_admits(lot["ghS_class"], lot["storage_zone"]):
                raise errors.ApiError(
                    errors.ERR_INCOMPATIBLE_SEGREGATION,
                    409,
                    "lot storage_zone does not admit ghS_class",
                )

    if record["heel_disposed_kg"] and record["heel_disposed_kg"] > 0:
        if not record.get("disposal_method"):
            raise errors.ApiError(errors.ERR_WASTE_MANIFEST_REQUIRED, 422, "disposal_method required")
        wmn = record.get("waste_manifest_number")
        if not wmn or (isinstance(wmn, str) and not wmn.strip()):
            raise errors.ApiError(errors.ERR_WASTE_MANIFEST_REQUIRED, 422, "waste_manifest_number required")

    now = now_iso()
    record["status"] = "POSTED"
    record["version"] += 1
    record["updated_at"] = now

    # Disposed mass leaves the lot's on_hand; returned stays
    if lot is not None:
        reconcile_lot_quantities(lot["id"])
        lot["version"] += 1
        lot["updated_at"] = now

    return success_object(serialize_heel_disposal(record))
