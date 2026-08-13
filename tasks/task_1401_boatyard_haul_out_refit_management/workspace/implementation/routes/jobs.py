"""Refit jobs (PRD 3.2, 3.10, 3.11)."""

from flask import Blueprint, request

import clock
import db
import response
from errors import (
    not_found, validation, invalid_state, already_terminal, stale,
    ERR_DUPLICATE_ACTIVE_JOB, ERR_INSURANCE_MISSING, ApiError,
)
from middleware import require_roles, check_owner_vessel, check_owner_job
from services import insurance as insurance_svc
from services import lifecycle, storage as storage_svc
from validation import (
    get_body, req_str, opt_str, opt_enum, req_enum, parse_pagination, page,
)
from .vessels import get_vessel_or_404

bp = Blueprint("jobs", __name__)

BILLING_MODES = ("DAILY", "MONTHLY_CONTRACT")
JOB_STATUSES = (
    "DRAFT", "INTAKE", "HAUL_SCHEDULED", "ON_HARD", "WORK_IN_PROGRESS",
    "READY_FOR_SPLASH", "AWAITING_TRIAL", "COMPLETE", "CLOSED", "CANCELLED",
)
TERMINAL_JOB_STATES = ("CLOSED", "CANCELLED")
# States from which POST /cancel is a legal transition.
CANCELLABLE_STATES = (
    "DRAFT", "INTAKE", "HAUL_SCHEDULED", "ON_HARD", "WORK_IN_PROGRESS",
    "READY_FOR_SPLASH",
)
SEA_TRIAL_OUTCOMES = ("PASS", "FAIL")


def get_job_or_404(job_id):
    job = db.jobs.get(job_id)
    if job is None:
        raise not_found(f"RefitJob '{job_id}' does not exist")
    return job


def _assert_job_not_terminal(job):
    if job["status"] in TERMINAL_JOB_STATES:
        raise already_terminal(f"RefitJob '{job['id']}' is in terminal state {job['status']}")


@bp.post("/yard/refit-jobs")
@require_roles("ServiceWriter")
def create_job():
    body = get_body()
    vessel_id = req_str(body, "vessel_id")
    vessel = get_vessel_or_404(vessel_id)
    billing_mode = opt_enum(body, "billing_mode", BILLING_MODES, default="DAILY")
    if billing_mode is None:
        billing_mode = "DAILY"
    scope_notes = opt_str(body, "scope_notes")

    # One active job per vessel (business rule: ERR_DUPLICATE_ACTIVE_JOB).
    for j in db.jobs.values():
        if j["vessel_id"] == vessel["id"] and j["status"] not in TERMINAL_JOB_STATES:
            raise ApiError(ERR_DUPLICATE_ACTIVE_JOB, 409,
                           "Vessel already has a refit job in a non-terminal state")

    now = db.now_iso()
    job = {
        "id": db.new_id(),
        "vessel_id": vessel["id"],
        "billing_mode": billing_mode,
        "scope_notes": scope_notes,
        "status": "DRAFT",
        "hauled_at": None,
        "splashed_at": None,
        "lay_days": 0,
        "last_accrual_date": None,
        "open_hold_count": 0,
        "completed_at": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "_hauled": None,
        "_last_accrual": None,
    }
    db.jobs[job["id"]] = job
    return response.success_object(db.pub(job), status=201)


@bp.get("/yard/refit-jobs/<jobId>")
@require_roles("ServiceWriter", "YardManager", "Owner", "Accountant", "EnvironmentalOfficer")
def get_job(jobId):
    job = get_job_or_404(jobId)
    check_owner_job(job)
    return response.success_object(db.pub(job))


@bp.get("/yard/vessels/<vesselId>/refit-jobs")
@require_roles("ServiceWriter", "YardManager", "Owner")
def list_jobs_of_vessel(vesselId):
    vessel = get_vessel_or_404(vesselId)
    check_owner_vessel(vessel)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [j for j in db.jobs.values() if j["vessel_id"] == vessel["id"]]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)


@bp.patch("/yard/refit-jobs/<jobId>")
@require_roles("ServiceWriter")
def patch_job(jobId):
    job = get_job_or_404(jobId)
    body = get_body()
    expected = body.get("expected_refit_job_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise validation("Field 'expected_refit_job_version' is required and must be an integer")
    billing_mode = opt_enum(body, "billing_mode", BILLING_MODES)
    scope_notes = opt_str(body, "scope_notes")
    # Optimistic concurrency (gate 6) precedes state legality (gate 7).
    if expected != job["version"]:
        raise stale("expected_refit_job_version does not match the job's current version")
    if job["status"] not in ("DRAFT", "INTAKE"):
        raise invalid_state("RefitJob may be patched only while in DRAFT or INTAKE")
    if billing_mode is not None:
        job["billing_mode"] = billing_mode
    if "scope_notes" in body:
        job["scope_notes"] = scope_notes
    db.touch(job)
    return response.success_object(db.pub(job))


@bp.post("/yard/refit-jobs/<jobId>/submit")
@require_roles("ServiceWriter")
def submit_job(jobId):
    job = get_job_or_404(jobId)
    _assert_job_not_terminal(job)
    if job["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT job can be submitted")
    cert = insurance_svc.qualifying_certificate_for_submit(job["vessel_id"], clock.today())
    if cert is None:
        raise ApiError(ERR_INSURANCE_MISSING, 409,
                       "No qualifying insurance certificate for the current date")
    job["status"] = "INTAKE"
    db.touch(job)
    return response.success_object(db.pub(job))


@bp.post("/yard/refit-jobs/<jobId>/cancel")
@require_roles("ServiceWriter")
def cancel_job(jobId):
    job = get_job_or_404(jobId)
    body = get_body()
    opt_str(body, "reason")  # accepted and discarded
    _assert_job_not_terminal(job)
    if job["status"] not in CANCELLABLE_STATES:
        raise invalid_state(f"A job in {job['status']} cannot be cancelled")
    lifecycle.cancel_job(job)
    return response.success_object(db.pub(job))


@bp.get("/yard/refit-jobs/<jobId>/statement")
@require_roles("ServiceWriter", "Accountant", "Owner")
def get_statement(jobId):
    job = get_job_or_404(jobId)
    check_owner_job(job)
    return response.success_object(storage_svc.build_statement(job))


@bp.post("/yard/refit-jobs/<jobId>/record-sea-trial")
@require_roles("YardManager")
def record_sea_trial(jobId):
    job = get_job_or_404(jobId)
    body = get_body()
    outcome = req_enum(body, "outcome", SEA_TRIAL_OUTCOMES)
    notes = opt_str(body, "notes")
    failed_wo = None
    if outcome == "FAIL":
        failed_id = body.get("failed_work_order_id")
        if not isinstance(failed_id, str):
            raise validation("Field 'failed_work_order_id' is required when outcome is FAIL")
        failed_wo = db.work_orders.get(failed_id)
        if failed_wo is None:
            raise not_found(f"WorkOrder '{failed_id}' does not exist")
    _assert_job_not_terminal(job)
    if job["status"] != "AWAITING_TRIAL":
        raise invalid_state("Sea trial may be recorded only while AWAITING_TRIAL")
    if outcome == "PASS":
        job["status"] = "COMPLETE"
        job["completed_at"] = clock.today().isoformat()
        db.touch(job)
    else:
        if failed_wo["job_id"] != job["id"] or failed_wo["status"] != "COMPLETE":
            raise invalid_state(
                "failed_work_order_id must reference a COMPLETE work order of this job")
        # Sea-trial-fail cascade: job back to WORK_IN_PROGRESS; the referenced
        # work order re-enters the change-order cycle.
        job["status"] = "WORK_IN_PROGRESS"
        db.touch(job)
        failed_wo["status"] = "CHANGE_REQUESTED"
        db.touch(failed_wo)
    return response.success_object(db.pub(job))
