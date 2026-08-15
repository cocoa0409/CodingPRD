"""Top-level reverse-reachability endpoints (bare-id fetches + filtered lists)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    pagination_params,
    paginate,
    sort_by_created_at,
    serialize_batch_job,
    serialize_batch_charge,
    serialize_sds,
    serialize_package_config,
    serialize_shipment,
    serialize_heel_disposal,
)

bp = Blueprint("top_level", __name__)


@bp.route("/toll-operations/batch-jobs/<batchJobId>", methods=["GET"])
def get_batch_job_top(batchJobId):
    require_role({"Any"})
    b = db.batch_jobs.get(batchJobId)
    if b is None:
        raise errors.not_found("batch job not found")
    return success_object(serialize_batch_job(b))


@bp.route("/toll-operations/batch-jobs", methods=["GET"])
def list_batch_jobs_top():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = list(db.batch_jobs.values())
    cid = request.args.get("customer_id")
    if cid:
        rows = [b for b in rows if b["customer_id"] == cid]
    rid = request.args.get("recipe_id")
    if rid:
        rows = [b for b in rows if b["recipe_id"] == rid]
    paid = request.args.get("pricing_agreement_id")
    if paid:
        rows = [b for b in rows if b["pricing_agreement_id"] == paid]
    tid = request.args.get("tank_id")
    if tid:
        rows = [b for b in rows if b["tank_id"] == tid]
    st = request.args.get("status")
    if st:
        rows = [b for b in rows if b["status"] == st]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_batch_job(b) for b in slice_], limit, offset, total)


@bp.route("/toll-operations/batch-charges/<chargeId>", methods=["GET"])
def get_charge_top(chargeId):
    require_role({"Any"})
    c = db.batch_charges.get(chargeId)
    if c is None:
        raise errors.not_found("batch charge not found")
    return success_object(serialize_batch_charge(c))


@bp.route("/toll-operations/batch-charges", methods=["GET"])
def list_charges_top():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = list(db.batch_charges.values())
    bid = request.args.get("batch_job_id")
    if bid:
        rows = [c for c in rows if c["batch_job_id"] == bid]
    lid = request.args.get("raw_material_lot_id")
    if lid:
        rows = [c for c in rows if c["raw_material_lot_id"] == lid]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_batch_charge(c) for c in slice_], limit, offset, total)


@bp.route("/toll-operations/sds-documents/<sdsId>", methods=["GET"])
def get_sds_top(sdsId):
    require_role({"Any"})
    s = db.sds_documents.get(sdsId)
    if s is None:
        raise errors.not_found("sds not found")
    return success_object(serialize_sds(s))


@bp.route("/toll-operations/sds-documents", methods=["GET"])
def list_sds_top():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = list(db.sds_documents.values())
    bid = request.args.get("batch_job_id")
    if bid:
        rows = [s for s in rows if s["batch_job_id"] == bid]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_sds(s) for s in slice_], limit, offset, total)


@bp.route("/toll-operations/package-configs/<packageConfigId>", methods=["GET"])
def get_pkg_top(packageConfigId):
    require_role({"Any"})
    p = db.package_configs.get(packageConfigId)
    if p is None:
        raise errors.not_found("package config not found")
    return success_object(serialize_package_config(p))


@bp.route("/toll-operations/package-configs", methods=["GET"])
def list_pkg_top():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = list(db.package_configs.values())
    bid = request.args.get("batch_job_id")
    if bid:
        rows = [p for p in rows if p["batch_job_id"] == bid]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_package_config(p) for p in slice_], limit, offset, total)


@bp.route("/toll-operations/shipments/<shipmentId>", methods=["GET"])
def get_shipment_top(shipmentId):
    require_role({"Any"})
    s = db.shipments.get(shipmentId)
    if s is None:
        raise errors.not_found("shipment not found")
    return success_object(serialize_shipment(s))


@bp.route("/toll-operations/shipments", methods=["GET"])
def list_shipments_top():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = list(db.shipments.values())
    bid = request.args.get("batch_job_id")
    if bid:
        rows = [s for s in rows if s["batch_job_id"] == bid]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_shipment(s) for s in slice_], limit, offset, total)


@bp.route("/toll-operations/heel-disposals/<recordId>", methods=["GET"])
def get_heel_top(recordId):
    require_role({"Any"})
    h = db.heel_disposals.get(recordId)
    if h is None:
        raise errors.not_found("heel disposal not found")
    return success_object(serialize_heel_disposal(h))


@bp.route("/toll-operations/heel-disposals", methods=["GET"])
def list_heel_top():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = list(db.heel_disposals.values())
    bid = request.args.get("batch_job_id")
    if bid:
        rows = [h for h in rows if h["batch_job_id"] == bid]
    lid = request.args.get("raw_material_lot_id")
    if lid:
        rows = [h for h in rows if h["raw_material_lot_id"] == lid]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_heel_disposal(h) for h in slice_], limit, offset, total)
