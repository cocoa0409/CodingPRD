"""Estimate endpoints: create, fetch, list, issue (OCC), accept, expire-check."""
from flask import Blueprint, g, request

import clock
from db import db, stamp_create, touch
from errors import err
from middleware import require_roles
from response import created, ok, ok_list
from services import calc, serialize
from services.helpers import body, pagination, paginate, require_fields, sort_by_created

bp = Blueprint("estimates", __name__)


@bp.post("/flooring/estimates")
@require_roles("SalesRep", "Admin")
def create_estimate():
    data = body()
    require_fields(data, ["job_id", "variant", "valid_until"])
    job_id = data["job_id"]
    variant = data["variant"]
    valid_until = data["valid_until"]

    with db.lock:
        job = db.jobs.get(job_id)
        if job is None:
            raise err("ERR_NOT_FOUND", "Job not found.")

        if variant not in ("PROVISIONAL", "MEASURED"):
            raise err("ERR_INVALID_REQUEST", "variant must be PROVISIONAL or MEASURED.")
        # valid_until must be a parseable ISO instant (field-level validity).
        try:
            clock.parse(valid_until)
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "valid_until must be a valid ISO 8601 instant.")

        # Variant/state matching.
        if variant == "PROVISIONAL":
            if job["status"] != "DRAFT":
                raise err(
                    "ERR_VARIANT_STATE_MISMATCH",
                    "PROVISIONAL estimate requires the job to be in DRAFT.",
                )
        else:  # MEASURED
            if job["status"] not in ("MEASURED", "ESTIMATED"):
                raise err(
                    "ERR_VARIANT_STATE_MISMATCH",
                    "MEASURED estimate requires the job to be in MEASURED or ESTIMATED.",
                )

        product = db.products[job["product_id"]]
        if variant == "PROVISIONAL":
            computed = calc.provisional_estimate(product, job["declared_sqft"])
        else:
            computed = calc.measured_estimate(
                product,
                job["measured_sqft"],
                job["tear_out_sqft"],
                job["waste_factor_pct"],
            )

        record = stamp_create(
            {
                "job_id": job_id,
                "variant": variant,
                "billable_sqft": computed["billable_sqft"],
                "material_cost_cents": computed["material_cost_cents"],
                "underlayment_cost_cents": computed["underlayment_cost_cents"],
                "labor_cost_cents": computed["labor_cost_cents"],
                "total_cents": computed["total_cents"],
                "status": "DRAFT",
                "valid_until": valid_until,
                "expected_job_version": None,
            }
        )
        db.estimates[record["id"]] = record
    return created(serialize.estimate_view(record))


@bp.get("/flooring/estimates/<eid>")
@require_roles("Admin", "SalesRep", "Estimator", "Customer")
def get_estimate(eid):
    with db.lock:
        e = db.estimates.get(eid)
        if e is None:
            raise err("ERR_NOT_FOUND", "Estimate not found.")
        return ok(serialize.estimate_view(e))


@bp.get("/flooring/estimates")
@require_roles("Admin", "SalesRep", "Estimator", "Customer")
def list_estimates():
    limit, offset = pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")
    variant = request.args.get("variant")
    with db.lock:
        items = list(db.estimates.values())
        if job_id is not None:
            items = [e for e in items if e["job_id"] == job_id]
        if status is not None:
            items = [e for e in items if e["status"] == status]
        if variant is not None:
            items = [e for e in items if e["variant"] == variant]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.estimate_view(e) for e in page]
    return ok_list(views, limit, offset, total)


@bp.post("/flooring/estimates/<eid>/issue")
@require_roles("SalesRep", "Admin")
def issue_estimate(eid):
    data = body()
    require_fields(data, ["expected_job_version"])
    expected_job_version = data["expected_job_version"]

    with db.lock:
        e = db.estimates.get(eid)
        if e is None:
            raise err("ERR_NOT_FOUND", "Estimate not found.")
        job = db.jobs.get(e["job_id"])
        if job is None:
            raise err("ERR_NOT_FOUND", "Job not found.")

        # State legality: estimate must be DRAFT, variant MEASURED, job MEASURED/ESTIMATED.
        if e["status"] != "DRAFT" or e["variant"] != "MEASURED":
            raise err("ERR_INVALID_STATE", "Only a DRAFT MEASURED estimate can be issued.")
        if job["status"] not in ("MEASURED", "ESTIMATED"):
            raise err("ERR_INVALID_STATE", "Job must be MEASURED or ESTIMATED to issue.")

        # §3.12 / §3.5 issue ordering: valid_until freshness, THEN OCC.
        try:
            valid_until_dt = clock.parse(e["valid_until"])
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "Stored valid_until is invalid.")
        if valid_until_dt <= clock.now():
            raise err("ERR_VALID_UNTIL_IN_PAST", "valid_until must be strictly after now.")

        if expected_job_version != job["version"]:
            raise err("ERR_STALE_JOB_VERSION", "expected_job_version does not match the job's version.")

        e["expected_job_version"] = expected_job_version

        # Supersede the prior ISSUED estimate of the same job.
        for other in db.estimates.values():
            if (
                other["id"] != e["id"]
                and other["job_id"] == job["id"]
                and other["status"] == "ISSUED"
            ):
                other["status"] = "VOIDED"
                touch(other)

        e["status"] = "ISSUED"
        touch(e)

        # Bubble-up: MEASURED -> ESTIMATED; ESTIMATED stays ESTIMATED.
        if job["status"] == "MEASURED":
            job["status"] = "ESTIMATED"
        touch(job)
        return ok(serialize.estimate_view(e))


@bp.post("/flooring/estimates/<eid>/accept")
@require_roles("Customer")
def accept_estimate(eid):
    with db.lock:
        e = db.estimates.get(eid)
        if e is None:
            raise err("ERR_NOT_FOUND", "Estimate not found.")
        job = db.jobs.get(e["job_id"])
        if job is None:
            raise err("ERR_NOT_FOUND", "Job not found.")

        # Ownership (§2.1 / §3.6): acting customer must own the job.
        if g.user_id != job["customer_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "You do not own this job.")

        # State legality.
        if e["status"] != "ISSUED" or e["variant"] != "MEASURED":
            raise err("ERR_INVALID_STATE", "Only an ISSUED MEASURED estimate can be accepted.")
        if job["status"] != "ESTIMATED":
            raise err("ERR_INVALID_STATE", "Job must be ESTIMATED to accept an estimate.")

        # Temporal: current clock strictly before valid_until.
        valid_until_dt = clock.parse(e["valid_until"])
        if clock.now() >= valid_until_dt:
            raise err("ERR_ESTIMATE_EXPIRED", "The estimate has expired.")

        product = db.products[job["product_id"]]

        e["status"] = "ACCEPTED"
        touch(e)

        job["status"] = "ACCEPTED"
        touch(job)

        # Spawn the MaterialOrder (cascade).
        lead_time_days = product["lead_time_days"]
        order = stamp_create(
            {
                "job_id": job["id"],
                "product_id": product["id"],
                "order_sqft": e["billable_sqft"],
                "lead_time_days": lead_time_days,
                "expected_ready_date": calc.ready_date(lead_time_days),
                "status": "ORDERED",
                "backorder_count": 0,
            }
        )
        db.material_orders[order["id"]] = order
        return ok(serialize.estimate_view(e))


@bp.post("/flooring/estimates/<eid>/expire-check")
@require_roles("SalesRep", "Admin", "Scheduler")
def expire_check(eid):
    with db.lock:
        e = db.estimates.get(eid)
        if e is None:
            raise err("ERR_NOT_FOUND", "Estimate not found.")
        if e["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Only an ISSUED estimate can be expire-checked.")
        valid_until_dt = clock.parse(e["valid_until"])
        if clock.now() >= valid_until_dt:
            e["status"] = "EXPIRED"
            touch(e)
        return ok(serialize.estimate_view(e))
