"""Package config and shipment endpoints."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    serialize_package_config,
    serialize_shipment,
    to_int,
    parse_iso,
    sort_by_created_at,
    pagination_params,
    paginate,
)
from services.calculations import compute_placard, PACKAGE_CAPACITY_L

bp = Blueprint("package_shipment", __name__)


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


def _latest_sds_classification(batch_id):
    """Latest non-SUPERSEDED SDS classification for the batch; falls back to batch snapshot."""
    latest = None
    for s in db.sds_documents.values():
        if s["batch_job_id"] != batch_id:
            continue
        if s["status"] == "SUPERSEDED":
            continue
        if latest is None or s["authoring_revision"] > latest["authoring_revision"]:
            latest = s
    if latest is not None:
        return latest["ghs_classification"]
    # Fallback: batch snapshot
    b = db.batch_jobs.get(batch_id)
    return b["highest_component_ghs_snapshot"] if b else "NON_HAZ"


def _get_pkg_config(batch_id):
    for p in db.package_configs.values():
        if p["batch_job_id"] == batch_id:
            return p
    return None


def _get_shipment(batch_id):
    for s in db.shipments.values():
        if s["batch_job_id"] == batch_id:
            return s
    return None


# ---------------- Package config ----------------

@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/package-config", methods=["POST"])
def create_package_config(id, batchJobId):
    require_role({"ShippingClerk"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    body = request.get_json(silent=True) or {}
    package_type = body.get("package_type")
    if package_type not in PACKAGE_CAPACITY_L:
        raise errors.invalid_request("package_type invalid")
    un_rated = body.get("un_rated")
    if not isinstance(un_rated, bool):
        raise errors.invalid_request("un_rated must be boolean")
    package_count = to_int(body.get("package_count"), "package_count")
    if package_count <= 0:
        raise errors.invalid_request("package_count must be > 0")

    # UN-rated mandatory when classification != NON_HAZ
    ghs_classification = _latest_sds_classification(batch["id"])
    if not un_rated and ghs_classification != "NON_HAZ":
        raise errors.ApiError(errors.ERR_UN_RATED_PACKAGE_REQUIRED, 422, "un_rated required for non-NON_HAZ")

    total_volume_l, placard_required, placard_class = compute_placard(
        ghs_classification, package_type, package_count
    )

    now = now_iso()
    pid = new_id()
    pkg = {
        "id": pid,
        "batch_job_id": batch["id"],
        "package_type": package_type,
        "un_rated": un_rated,
        "package_count": package_count,
        "total_volume_l": total_volume_l,
        "placard_required": placard_required,
        "placard_class": placard_class,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.package_configs[pid] = pkg
    return success_object(serialize_package_config(pkg), status=201)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/package-config", methods=["GET"])
def get_package_config(id, batchJobId):
    require_role({"Any"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    rows = [p for p in db.package_configs.values() if p["batch_job_id"] == batchJobId]
    rows = sort_by_created_at(rows)
    limit, offset = pagination_params()
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_package_config(p) for p in slice_], limit, offset, total)


# ---------------- Shipment ----------------

@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/shipment", methods=["POST"])
def create_shipment(id, batchJobId):
    require_role({"ShippingClerk"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    body = request.get_json(silent=True) or {}
    carrier_name = body.get("carrier_name")
    if not isinstance(carrier_name, str):
        raise errors.invalid_request("carrier_name required")
    vehicle_placards = body.get("vehicle_placards")
    if not isinstance(vehicle_placards, list):
        raise errors.invalid_request("vehicle_placards must be list")
    departure_at = body.get("departure_at")
    if not departure_at:
        raise errors.invalid_request("departure_at required")
    parse_iso(departure_at)

    now = now_iso()
    sid = new_id()
    shipment = {
        "id": sid,
        "batch_job_id": batch["id"],
        "carrier_name": carrier_name,
        "vehicle_placards": list(vehicle_placards),
        "departure_at": departure_at,
        "shipped_volume_l": None,
        "status": "PLANNED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.shipments[sid] = shipment
    return success_object(serialize_shipment(shipment), status=201)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/shipment", methods=["GET"])
def get_shipment(id, batchJobId):
    require_role({"Any"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    rows = [s for s in db.shipments.values() if s["batch_job_id"] == batchJobId]
    rows = sort_by_created_at(rows)
    limit, offset = pagination_params()
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_shipment(s) for s in slice_], limit, offset, total)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/shipment/start-loading", methods=["POST"])
def start_loading(id, batchJobId):
    require_role({"ShippingClerk"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    shipment = _get_shipment(batchJobId)
    if shipment is None:
        raise errors.not_found("shipment not found")
    if shipment["status"] != "PLANNED":
        raise errors.invalid_state("shipment not PLANNED")
    if batch["status"] != "COMPLETED":
        raise errors.invalid_state("batch not COMPLETED")
    shipment["status"] = "LOADING"
    shipment["version"] += 1
    shipment["updated_at"] = now_iso()
    return success_object(serialize_shipment(shipment))


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/shipment/dispatch", methods=["POST"])
def dispatch_shipment(id, batchJobId):
    require_role({"ShippingClerk"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    shipment = _get_shipment(batchJobId)
    if shipment is None:
        raise errors.not_found("shipment not found")
    if shipment["status"] != "LOADING":
        raise errors.invalid_state("shipment not LOADING")

    pkg = _get_pkg_config(batchJobId)
    if pkg is None:
        raise errors.invalid_state("package config missing")

    if pkg["placard_required"]:
        if pkg["placard_class"] not in (shipment.get("vehicle_placards") or []):
            raise errors.ApiError(errors.ERR_PLACARD_MISSING, 422, "placard_class not on vehicle")
        if not shipment.get("carrier_name"):
            raise errors.invalid_request("carrier_name required when placard required")

    shipment["status"] = "DISPATCHED"
    shipment["shipped_volume_l"] = pkg["total_volume_l"]
    shipment["version"] += 1
    shipment["updated_at"] = now_iso()
    return success_object(serialize_shipment(shipment))


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/shipment/cancel", methods=["POST"])
def cancel_shipment(id, batchJobId):
    require_role({"ShippingClerk"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    shipment = _get_shipment(batchJobId)
    if shipment is None:
        raise errors.not_found("shipment not found")
    if shipment["status"] not in {"PLANNED", "LOADING"}:
        raise errors.invalid_state("shipment not PLANNED or LOADING")
    shipment["status"] = "CANCELLED"
    shipment["version"] += 1
    shipment["updated_at"] = now_iso()
    return success_object(serialize_shipment(shipment))
