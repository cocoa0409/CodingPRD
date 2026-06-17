"""Job endpoints: create, fetch, list, measure, request-remeasure, cancel,
plus the parent-scoped list endpoints (estimates / material-orders /
install-slots / warranty-claims of a job)."""
from flask import Blueprint, g, request

from db import db, stamp_create, touch
from errors import err
from middleware import require_roles
from response import created, ok, ok_list
from services import calc, serialize
from services.helpers import (
    body,
    is_number,
    pagination,
    paginate,
    require_fields,
    require_int_min,
    require_nonneg_number,
    require_positive_number,
    sort_by_created,
)

bp = Blueprint("jobs", __name__)

JOB_STATUSES = {
    "DRAFT",
    "MEASURED",
    "RE_MEASURE",
    "ESTIMATED",
    "ACCEPTED",
    "IN_INSTALL",
    "COMPLETED",
    "CANCELLED",
}


@bp.post("/flooring/jobs")
@require_roles("SalesRep", "Admin")
def create_job():
    data = body()
    require_fields(data, ["customer_id", "sales_rep_id", "product_id", "declared_sqft"])
    customer_id = data["customer_id"]
    sales_rep_id = data["sales_rep_id"]
    product_id = data["product_id"]

    # declared_sqft > 0 (field bound) — but existence is checked first per §2.5.
    declared_sqft = data["declared_sqft"]

    with db.lock:
        # Existence of body FKs, left-to-right (customer, rep, product).
        if customer_id not in db.customers:
            raise err("ERR_NOT_FOUND", "Customer not found.")
        if sales_rep_id not in db.sales_reps:
            raise err("ERR_NOT_FOUND", "Sales rep not found.")
        product = db.products.get(product_id)
        if product is None:
            raise err("ERR_NOT_FOUND", "Product not found.")
        # Product must be ACTIVE.
        if product["status"] != "ACTIVE":
            raise err("ERR_PRODUCT_DISCONTINUED", "Referenced product is discontinued.")
        # Field bound.
        if not is_number(declared_sqft) or declared_sqft <= 0:
            raise err("ERR_INVALID_REQUEST", "declared_sqft must be a number > 0.")

        record = stamp_create(
            {
                "customer_id": customer_id,
                "sales_rep_id": sales_rep_id,
                "product_id": product_id,
                "declared_sqft": declared_sqft,
                "measured_sqft": None,
                "tear_out_sqft": None,
                "room_count": None,
                "waste_factor_pct": None,
                "status": "DRAFT",
                "warranty_risk_score": None,
                # Internal: remembers whether the job ever entered RE_MEASURE.
                "_ever_remeasured": False,
            }
        )
        db.jobs[record["id"]] = record
    return created(serialize.job_view(record))


@bp.get("/flooring/jobs/<jid>")
@require_roles("Admin", "SalesRep", "Estimator", "Scheduler", "Customer")
def get_job(jid):
    with db.lock:
        j = db.jobs.get(jid)
        if j is None:
            raise err("ERR_NOT_FOUND", "Job not found.")
        return ok(serialize.job_view(j))


@bp.get("/flooring/jobs")
@require_roles("Admin", "SalesRep", "Estimator", "Scheduler", "Customer")
def list_jobs():
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    sales_rep_id = request.args.get("sales_rep_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    with db.lock:
        items = list(db.jobs.values())
        if customer_id is not None:
            items = [j for j in items if j["customer_id"] == customer_id]
        if sales_rep_id is not None:
            items = [j for j in items if j["sales_rep_id"] == sales_rep_id]
        if product_id is not None:
            items = [j for j in items if j["product_id"] == product_id]
        if status is not None:
            items = [j for j in items if j["status"] == status]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.job_view(j) for j in page]
    return ok_list(views, limit, offset, total)


@bp.post("/flooring/jobs/<jid>/measure")
@require_roles("Estimator")
def measure_job(jid):
    data = body()
    require_fields(data, ["measured_sqft", "tear_out_sqft", "room_count"])
    with db.lock:
        j = db.jobs.get(jid)
        if j is None:
            raise err("ERR_NOT_FOUND", "Job not found.")
        if j["status"] not in ("DRAFT", "RE_MEASURE"):
            raise err("ERR_INVALID_STATE", "Job cannot be measured from its current state.")
        # Field bounds.
        measured_sqft = require_positive_number(data, "measured_sqft")
        tear_out_sqft = require_nonneg_number(data, "tear_out_sqft")
        room_count = require_int_min(data, "room_count", 1)

        product = db.products[j["product_id"]]
        j["measured_sqft"] = measured_sqft
        j["tear_out_sqft"] = tear_out_sqft
        j["room_count"] = room_count
        j["waste_factor_pct"] = calc.waste_factor_pct(
            product["category"], measured_sqft, room_count
        )
        j["status"] = "MEASURED"
        touch(j)
        return ok(serialize.job_view(j))


def _latest_issued_estimate(job_id):
    """Return the (single) currently-ISSUED estimate of a job, if any."""
    issued = [
        e for e in db.estimates.values() if e["job_id"] == job_id and e["status"] == "ISSUED"
    ]
    if not issued:
        return None
    # At most one ISSUED estimate per job by invariant; pick the latest created.
    issued.sort(key=lambda e: e["created_at"])
    return issued[-1]


@bp.post("/flooring/jobs/<jid>/request-remeasure")
@require_roles("SalesRep", "Admin")
def request_remeasure(jid):
    with db.lock:
        j = db.jobs.get(jid)
        if j is None:
            raise err("ERR_NOT_FOUND", "Job not found.")
        if j["status"] not in ("MEASURED", "ESTIMATED"):
            raise err("ERR_INVALID_STATE", "Job cannot be sent for re-measure from its current state.")
        # Void the currently ISSUED estimate, if any (cascade).
        issued = _latest_issued_estimate(jid)
        if issued is not None:
            issued["status"] = "VOIDED"
            touch(issued)
        j["status"] = "RE_MEASURE"
        j["_ever_remeasured"] = True
        touch(j)
        return ok(serialize.job_view(j))


@bp.post("/flooring/jobs/<jid>/cancel")
@require_roles("SalesRep", "Admin")
def cancel_job(jid):
    with db.lock:
        j = db.jobs.get(jid)
        if j is None:
            raise err("ERR_NOT_FOUND", "Job not found.")
        if j["status"] not in ("DRAFT", "MEASURED", "RE_MEASURE", "ESTIMATED", "ACCEPTED"):
            raise err("ERR_INVALID_STATE", "Job cannot be cancelled from its current state.")

        # Teardown cascade.
        # 1) VOID every non-terminal (DRAFT or ISSUED) estimate of the job.
        for e in db.estimates.values():
            if e["job_id"] == jid and e["status"] in ("DRAFT", "ISSUED"):
                e["status"] = "VOIDED"
                touch(e)
        # 2) CANCEL the job's material order if ORDERED or BACKORDERED.
        for m in db.material_orders.values():
            if m["job_id"] == jid and m["status"] in ("ORDERED", "BACKORDERED"):
                m["status"] = "CANCELLED"
                touch(m)
        # 3) CANCEL every SCHEDULED install slot of the job (releases capacity).
        for s in db.install_slots.values():
            if s["job_id"] == jid and s["status"] == "SCHEDULED":
                s["status"] = "CANCELLED"
                touch(s)

        j["status"] = "CANCELLED"
        touch(j)
        return ok(serialize.job_view(j))


# ---- Parent-scoped list endpoints ----


def _require_job(jid):
    j = db.jobs.get(jid)
    if j is None:
        raise err("ERR_NOT_FOUND", "Job not found.")
    return j


@bp.get("/flooring/jobs/<jid>/estimates")
@require_roles("Admin", "SalesRep", "Estimator", "Customer")
def list_job_estimates(jid):
    limit, offset = pagination()
    with db.lock:
        _require_job(jid)
        items = [e for e in db.estimates.values() if e["job_id"] == jid]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.estimate_view(e) for e in page]
    return ok_list(views, limit, offset, total)


@bp.get("/flooring/jobs/<jid>/material-orders")
@require_roles("Admin", "SalesRep", "Scheduler")
def list_job_material_orders(jid):
    limit, offset = pagination()
    with db.lock:
        _require_job(jid)
        items = [m for m in db.material_orders.values() if m["job_id"] == jid]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.material_order_view(m) for m in page]
    return ok_list(views, limit, offset, total)


@bp.get("/flooring/jobs/<jid>/install-slots")
@require_roles("Admin", "SalesRep", "Scheduler")
def list_job_install_slots(jid):
    limit, offset = pagination()
    with db.lock:
        _require_job(jid)
        items = [s for s in db.install_slots.values() if s["job_id"] == jid]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.slot_view(s) for s in page]
    return ok_list(views, limit, offset, total)


@bp.get("/flooring/jobs/<jid>/warranty-claims")
@require_roles("Admin", "SalesRep", "Customer")
def list_job_warranty_claims(jid):
    limit, offset = pagination()
    with db.lock:
        _require_job(jid)
        items = [w for w in db.warranty_claims.values() if w["job_id"] == jid]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.claim_view(w) for w in page]
    return ok_list(views, limit, offset, total)
