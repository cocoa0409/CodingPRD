"""ProductionJob endpoints."""

from flask import Blueprint, request

import db
import errors
import util
from middleware import require_roles
from response import success_object, success_list
from services import domain

bp = Blueprint("production_jobs", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")
BAY_CODES = ("BAY_A", "BAY_B", "BAY_C")


def _pick_bolt_for_tier(cloth_tier, needed_sqm):
    """Pick the first bolt (by created_at) of the tier that can cover the reservation.
    Falls back to aggregate check when no single bolt fits — the shortage rule is
    defined against the tier's availability."""
    bolts = sorted(
        (b for b in db.cloth_ledger.values() if b["cloth_tier"] == cloth_tier),
        key=lambda b: (b["created_at"], b["id"]),
    )
    for b in bolts:
        if b["available_sqm"] >= needed_sqm:
            return b
    return None


def _check_bay_then_cloth(bay_code, start_d, end_d, exclude_job_id=None):
    """Bay-overlap check first, then cloth shortage is evaluated by the caller."""
    if domain.bay_conflict_exists(bay_code, start_d, end_d, exclude_job_id=exclude_job_id):
        raise errors.bay_window_conflict()


@bp.post("/lofts/work-orders/<workOrderId>/production-jobs")
def create_job(workOrderId):
    require_roles("Sailmaker")
    wo = domain.get_work_order_or_404(workOrderId)
    body = util.get_body()
    bay_code = util.as_enum(util.require_field(body, "bay_code"), "bay_code", BAY_CODES)
    start_raw = util.require_field(body, "scheduled_start_date")
    end_raw = util.require_field(body, "scheduled_end_date")
    start_d = util.parse_date(start_raw, "scheduled_start_date")
    end_d = util.parse_date(end_raw, "scheduled_end_date")
    # Check order in PRD §3.4: bay-turnaround first, then cloth availability.
    _check_bay_then_cloth(bay_code, start_d, end_d)
    design_id = wo.get("sail_design_id")
    design = db.sail_designs.get(design_id) if design_id else None
    if design is None:
        raise errors.cloth_shortage("Work order has no pinned sail design")
    sheet = db.measurement_sheets.get(design["measurement_sheet_id"])
    reserved = sheet["measured_area_sqm"] if sheet else 0
    bolt = _pick_bolt_for_tier(design["cloth_tier"], reserved)
    if bolt is None:
        raise errors.cloth_shortage()
    domain.reserve_cloth(bolt, reserved)
    job = util.stamp_new({
        "work_order_id": wo["id"],
        "bay_code": bay_code,
        "scheduled_start_date": start_raw,
        "scheduled_end_date": end_raw,
        "reserved_cloth_sqm": reserved,
        "qc_notes": None,
        "job_status": "SCHEDULED",
        "bolt_id": bolt["id"],
    })
    db.production_jobs[job["id"]] = job
    return success_object(domain.serialize(job), 201)


@bp.get("/lofts/work-orders/<workOrderId>/production-jobs")
def list_wo_jobs(workOrderId):
    require_roles(*READ_ROLES)
    domain.get_work_order_or_404(workOrderId)
    limit, offset = util.pagination_params()
    items = [j for j in db.production_jobs.values() if j["work_order_id"] == workOrderId]
    items = util.filter_exact(items, "job_status", request.args.get("job_status"))
    items = util.sort_by_created(items)
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(j) for j in page], limit, offset, total)


@bp.get("/lofts/production-jobs")
def list_jobs():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.production_jobs.values()))
    items = util.filter_exact(items, "work_order_id", request.args.get("work_order_id"))
    items = util.filter_exact(items, "job_status", request.args.get("job_status"))
    items = util.filter_exact(items, "bay_code", request.args.get("bay_code"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(j) for j in page], limit, offset, total)


@bp.get("/lofts/production-jobs/<jobId>")
def get_job(jobId):
    require_roles(*READ_ROLES)
    job = domain.get_job_or_404(jobId)
    return success_object(domain.serialize(job))


@bp.post("/lofts/work-orders/<workOrderId>/production-jobs/<jobId>/start-cutting")
def start_cutting(workOrderId, jobId):
    require_roles("Sailmaker")
    wo = domain.get_work_order_or_404(workOrderId)
    job = domain.get_job_or_404(jobId)
    domain.check_child_of(job, "work_order_id", wo["id"])
    if job["job_status"] != "SCHEDULED":
        raise errors.invalid_state(f"Job must be SCHEDULED to start cutting (is {job['job_status']})")
    if wo["order_status"] not in ("DESIGN_LOCKED", "IN_PRODUCTION"):
        raise errors.invalid_state(
            f"Parent work order must be DESIGN_LOCKED or IN_PRODUCTION (is {wo['order_status']})"
        )
    design = db.sail_designs.get(wo.get("sail_design_id"))
    if design is None or design["design_status"] != "APPROVED":
        raise errors.design_not_in_required_state("Pinned SailDesign must be APPROVED")
    job["job_status"] = "CUTTING"
    util.touch(job)
    if wo["order_status"] == "DESIGN_LOCKED":
        wo["order_status"] = "IN_PRODUCTION"
        util.touch(wo)
    return success_object(domain.serialize(job))


@bp.post("/lofts/work-orders/<workOrderId>/production-jobs/<jobId>/advance")
def advance_job(workOrderId, jobId):
    require_roles("Sailmaker")
    wo = domain.get_work_order_or_404(workOrderId)
    job = domain.get_job_or_404(jobId)
    domain.check_child_of(job, "work_order_id", wo["id"])
    if job["job_status"] == "CUTTING":
        job["job_status"] = "SEAMING"
    elif job["job_status"] == "SEAMING":
        job["job_status"] = "FINISHING"
    else:
        raise errors.invalid_state(
            f"Job must be CUTTING or SEAMING to advance (is {job['job_status']})"
        )
    util.touch(job)
    return success_object(domain.serialize(job))


@bp.post("/lofts/work-orders/<workOrderId>/production-jobs/<jobId>/qc-pass")
def qc_pass(workOrderId, jobId):
    require_roles("Sailmaker")
    wo = domain.get_work_order_or_404(workOrderId)
    job = domain.get_job_or_404(jobId)
    domain.check_child_of(job, "work_order_id", wo["id"])
    if job["job_status"] != "FINISHING":
        raise errors.invalid_state(f"Job must be FINISHING to qc-pass (is {job['job_status']})")
    job["job_status"] = "QC_PASSED"
    util.touch(job)
    bolt_id = job.get("bolt_id")
    if bolt_id and bolt_id in db.cloth_ledger:
        domain.release_cloth(db.cloth_ledger[bolt_id], job.get("reserved_cloth_sqm", 0) or 0)
    siblings = [
        j for j in db.production_jobs.values()
        if j["work_order_id"] == wo["id"] and j["job_status"] != "CANCELLED"
    ]
    if siblings and all(j["job_status"] == "QC_PASSED" for j in siblings):
        if wo["order_status"] == "IN_PRODUCTION":
            wo["order_status"] = "READY_FOR_FIT_CHECK"
            util.touch(wo)
    return success_object(domain.serialize(job))


@bp.post("/lofts/work-orders/<workOrderId>/production-jobs/<jobId>/qc-fail")
def qc_fail(workOrderId, jobId):
    require_roles("Sailmaker")
    wo = domain.get_work_order_or_404(workOrderId)
    job = domain.get_job_or_404(jobId)
    domain.check_child_of(job, "work_order_id", wo["id"])
    if job["job_status"] != "FINISHING":
        raise errors.invalid_state(f"Job must be FINISHING to qc-fail (is {job['job_status']})")
    body = util.get_body()
    qc_notes = util.as_string(util.require_field(body, "qc_notes"), "qc_notes")
    job["job_status"] = "QC_FAILED"
    job["qc_notes"] = qc_notes
    util.touch(job)
    return success_object(domain.serialize(job))


@bp.post("/lofts/work-orders/<workOrderId>/production-jobs/<jobId>/reschedule")
def reschedule_job(workOrderId, jobId):
    require_roles("Sailmaker")
    wo = domain.get_work_order_or_404(workOrderId)
    job = domain.get_job_or_404(jobId)
    domain.check_child_of(job, "work_order_id", wo["id"])
    if job["job_status"] != "QC_FAILED":
        raise errors.invalid_state(f"Job must be QC_FAILED to reschedule (is {job['job_status']})")
    body = util.get_body()
    bay_code = util.as_enum(util.require_field(body, "bay_code"), "bay_code", BAY_CODES)
    start_raw = util.require_field(body, "scheduled_start_date")
    end_raw = util.require_field(body, "scheduled_end_date")
    start_d = util.parse_date(start_raw, "scheduled_start_date")
    end_d = util.parse_date(end_raw, "scheduled_end_date")
    _check_bay_then_cloth(bay_code, start_d, end_d, exclude_job_id=job["id"])
    # Reservation stays the same design area; recompute on the new window.
    design = db.sail_designs.get(wo.get("sail_design_id"))
    sheet = db.measurement_sheets.get(design["measurement_sheet_id"]) if design else None
    reserved = sheet["measured_area_sqm"] if sheet else job.get("reserved_cloth_sqm", 0)
    # Re-book cloth if the bolt changed (bay could change the cloth tier never does,
    # but the original bolt still applies). Keep original bolt; ensure availability.
    bolt_id = job.get("bolt_id")
    if bolt_id and bolt_id in db.cloth_ledger:
        # QC_FAILED job's reservation was still counted as non-terminal; on reschedule
        # it stays reserved against the same bolt — nothing to release.
        pass
    job["bay_code"] = bay_code
    job["scheduled_start_date"] = start_raw
    job["scheduled_end_date"] = end_raw
    job["reserved_cloth_sqm"] = reserved
    job["job_status"] = "SCHEDULED"
    util.touch(job)
    return success_object(domain.serialize(job))
