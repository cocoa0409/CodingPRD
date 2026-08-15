"""Jobs and their lifecycle actions (PRD 3.2, 3.4, 3.7)."""

from flask import Blueprint, request

from db import store
from errors import (ERR_CONTAINMENT_DEFICIENT, ERR_DOWNTIME_OPEN,
                    ERR_INVOICE_NOT_PAID, ERR_JHA_NOT_APPROVED,
                    ERR_JOB_HAS_COMMITTED_WASTE, ERR_JOB_STOPPED,
                    ERR_MANIFEST_UNRECONCILED, ERR_NO_ACTIVE_RATE_SCHEDULE,
                    ERR_NO_ASSIGNMENTS, ERR_NO_CONFIRMED_CREW,
                    ERR_OPERATOR_NOT_CERTIFIED, ERR_PERMIT_NOT_ACTIVE,
                    ERR_PRESSURE_RATING_INSUFFICIENT, ERR_SITE_CREDIT_HOLD,
                    conflict, invalid_state, not_found, unprocessable)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.calculations import (approved_jha, build_invoice_lines,
                                   compute_downtime_closure, job_assignments,
                                   job_downtime, job_incidents, job_manifests,
                                   job_permits, job_containment,
                                   recompute_facility, recompute_invoice_totals,
                                   recompute_standby_accrual)
from util import (get_body, list_paginated, new_entity, now, opt_field,
                  req_field, touch)

bp = Blueprint("jobs", __name__)

JOB_TYPES = ["VACUUM", "HYDROBLAST", "COMBINED"]
PRICING_MODES = ["UNIT_RATE", "TIME_AND_MATERIALS"]
EXECUTION_STATUSES = ["QUOTED", "SCHEDULED", "MOBILIZED", "IN_PROGRESS",
                      "FIELD_COMPLETE", "INVOICED", "CLOSED", "CANCELLED"]


def _get_job(job_id):
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("Job not found")
    return job


@bp.post("/v1/jobs")
def create_job():
    require_roles(["ProjectManager"])
    body = get_body()
    site_id = req_field(body, "site_id")
    job_type = req_field(body, "job_type", choices=JOB_TYPES)
    pricing_mode = req_field(body, "pricing_mode", choices=PRICING_MODES)
    description = req_field(body, "description")
    estimated_gallons = opt_field(body, "estimated_gallons", kind="int",
                                  gte_zero=True, default=0)
    site = store.sites.get(site_id)
    if site is None:
        raise not_found("Site not found")
    if not site["active_rate_schedule_id"]:
        raise unprocessable(ERR_NO_ACTIVE_RATE_SCHEDULE,
                            "Site has no ACTIVE rate schedule")
    store.job_seq += 1
    job = new_entity(store.jobs, {
        "site_id": site_id,
        "job_type": job_type,
        "pricing_mode": pricing_mode,
        "description": description,
        "estimated_gallons": estimated_gallons,
        "pinned_rate_schedule_id": site["active_rate_schedule_id"],
        "execution_status": "QUOTED",
        "safety_status": "CLEAR",
        "gallons_removed": 0,
        "feet_cleaned": 0,
        "standby_accrued_cents": 0,
        "_seq": store.job_seq,
    })
    return success_object(job, status=201)


@bp.get("/v1/jobs")
def list_jobs():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("site_id", "execution_status", "pinned_rate_schedule_id"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.jobs, filters, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/jobs/<jobId>")
def get_job(jobId):
    require_roles(ALL_ROLES)
    return success_object(_get_job(jobId))


@bp.post("/v1/jobs/<jobId>/schedule")
def schedule_job(jobId):
    require_roles(["ProjectManager"])
    job = _get_job(jobId)
    if job["execution_status"] != "QUOTED":
        raise invalid_state("Only a QUOTED job can be scheduled")
    if not any(a["status"] in ("SCHEDULED", "CONFIRMED")
               for a in job_assignments(jobId)):
        raise unprocessable(ERR_NO_ASSIGNMENTS,
                            "Job has no SCHEDULED or CONFIRMED assignment")
    job["execution_status"] = "SCHEDULED"
    touch(job)
    return success_object(job)


@bp.post("/v1/jobs/<jobId>/mobilize")
def mobilize_job(jobId):
    require_roles(["ProjectManager"])
    job = _get_job(jobId)
    if job["execution_status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED job can be mobilized")
    if not any(a["status"] == "CONFIRMED" for a in job_assignments(jobId)):
        raise unprocessable(ERR_NO_CONFIRMED_CREW,
                            "Job has no CONFIRMED assignment")
    job["execution_status"] = "MOBILIZED"
    touch(job)
    return success_object(job)


@bp.post("/v1/jobs/<jobId>/start-work")
def start_work(jobId):
    require_roles(["ProjectManager"])
    job = _get_job(jobId)
    if job["execution_status"] != "MOBILIZED":
        raise invalid_state("Only a MOBILIZED job can start work")
    # Gate 1: safety posture.
    if job["safety_status"] != "CLEAR":
        raise conflict(ERR_JOB_STOPPED, "Job safety status is STOP_WORK")
    # Gate 2: an APPROVED JHA exists.
    jha = approved_jha(jobId)
    if jha is None:
        raise unprocessable(ERR_JHA_NOT_APPROVED,
                            "No APPROVED hazard analysis exists for the job")
    # Gate 3: confined-space permit when the approved JHA declares confined space.
    if jha["confined_space"]:
        has_active_cs = any(
            p["permit_type"] == "CONFINED_SPACE" and p["status"] == "ACTIVE"
            for p in job_permits(jobId))
        if not has_active_cs:
            raise unprocessable(ERR_PERMIT_NOT_ACTIVE,
                                "An ACTIVE CONFINED_SPACE permit is required")
    if job["job_type"] in ("HYDROBLAST", "COMBINED"):
        # Gate 4: hydroblast-capable equipment pressure ratings.
        capable = []
        for a in job_assignments(jobId):
            if (a["resource_kind"] == "EQUIPMENT"
                    and a["status"] in ("SCHEDULED", "CONFIRMED", "RELEASED")):
                unit = store.equipment_units.get(a["equipment_unit_id"])
                if unit is not None and unit["unit_type"] in ("HYDROBLASTER", "COMBO"):
                    capable.append(unit)
        required_psi = jha["max_operating_pressure_psi"]
        if not capable or any(u["max_pressure_psi"] < required_psi for u in capable):
            raise unprocessable(
                ERR_PRESSURE_RATING_INSUFFICIENT,
                "Assigned hydroblast equipment pressure rating is insufficient or absent")
        # Gate 5: operator hydroblast certification.
        for a in job_assignments(jobId):
            if (a["resource_kind"] == "OPERATOR"
                    and a["status"] in ("SCHEDULED", "CONFIRMED", "RELEASED")):
                operator = store.operators.get(a["operator_id"])
                if operator is None or not operator["hydroblast_certified"]:
                    raise unprocessable(
                        ERR_OPERATOR_NOT_CERTIFIED,
                        "An assigned operator is not hydroblast certified")
    # Gate 6: fiscal gate on the site.
    site = store.sites[job["site_id"]]
    if site["credit_status"] != "GOOD_STANDING":
        raise unprocessable(ERR_SITE_CREDIT_HOLD, "Site is on CREDIT_HOLD")
    job["execution_status"] = "IN_PROGRESS"
    touch(job)
    return success_object(job)


@bp.post("/v1/jobs/<jobId>/complete-field-work")
def complete_field_work(jobId):
    require_roles(["ProjectManager"])
    body = get_body()
    gallons_removed = req_field(body, "gallons_removed", kind="int", gte_zero=True)
    feet_cleaned = req_field(body, "feet_cleaned", kind="int", gte_zero=True)
    job = _get_job(jobId)
    if job["execution_status"] != "IN_PROGRESS":
        raise invalid_state("Only an IN_PROGRESS job can complete field work")
    if job["safety_status"] != "CLEAR":
        raise conflict(ERR_JOB_STOPPED, "Job safety status is STOP_WORK")
    records = job_containment(jobId)
    latest = max(records, key=lambda c: c["sequence"]) if records else None
    if latest is None or latest["status"] != "VERIFIED":
        raise unprocessable(
            ERR_CONTAINMENT_DEFICIENT,
            "Latest containment record is absent or not VERIFIED")
    if any(d["status"] == "OPEN" for d in job_downtime(jobId)):
        raise unprocessable(ERR_DOWNTIME_OPEN,
                            "An OPEN downtime event exists on the job")
    job["gallons_removed"] = gallons_removed
    job["feet_cleaned"] = feet_cleaned
    job["execution_status"] = "FIELD_COMPLETE"
    touch(job)
    return success_object(job)


@bp.post("/v1/jobs/<jobId>/cancel")
def cancel_job(jobId):
    require_roles(["ProjectManager"])
    job = _get_job(jobId)
    if job["execution_status"] not in ("QUOTED", "SCHEDULED", "MOBILIZED",
                                       "IN_PROGRESS", "FIELD_COMPLETE"):
        raise invalid_state("Job cannot be cancelled from its current state")
    if any(m["status"] in ("IN_TRANSIT", "RECEIVED", "RECONCILED")
           for m in job_manifests(jobId)):
        raise conflict(ERR_JOB_HAS_COMMITTED_WASTE,
                       "Job has manifests with committed waste")
    for a in job_assignments(jobId):
        if a["status"] in ("SCHEDULED", "CONFIRMED"):
            a["status"] = "CANCELLED"
            touch(a)
    for p in job_permits(jobId):
        if p["status"] in ("ISSUED", "ACTIVE", "SUSPENDED"):
            p["status"] = "REVOKED"
            touch(p)
    affected_facilities = set()
    for m in job_manifests(jobId):
        if m["status"] in ("DRAFT", "ISSUED"):
            was_issued = m["status"] == "ISSUED"
            m["status"] = "VOIDED"
            touch(m)
            if was_issued:
                profile = store.waste_profiles.get(m["waste_profile_id"])
                if profile is not None:
                    affected_facilities.add(profile["facility_id"])
    for facility_id in affected_facilities:
        facility = store.facilities.get(facility_id)
        if facility is not None:
            recompute_facility(facility)
    cancel_time = now()
    for d in job_downtime(jobId):
        if d["status"] == "OPEN":
            compute_downtime_closure(d, cancel_time)
            d["status"] = "CLOSED"
            touch(d)
    recompute_standby_accrual(job)
    job["execution_status"] = "CANCELLED"
    touch(job)
    return success_object(job)


@bp.post("/v1/jobs/<jobId>/stop-work")
def stop_work(jobId):
    require_roles(["SafetyManager"])
    job = _get_job(jobId)
    if job["safety_status"] != "CLEAR" or job["execution_status"] not in (
            "SCHEDULED", "MOBILIZED", "IN_PROGRESS", "FIELD_COMPLETE"):
        raise invalid_state("Stop-work is not permitted from the job's current state")
    _apply_stop_work(job)
    return success_object(job)


def _apply_stop_work(job):
    """Shared cascade: explicit stop-work and SERIOUS/MAJOR incident auto-stop."""
    job["safety_status"] = "STOP_WORK"
    for p in job_permits(job["id"]):
        if p["status"] == "ACTIVE":
            p["status"] = "SUSPENDED"
            touch(p)
    touch(job)


@bp.post("/v1/jobs/<jobId>/resume-work")
def resume_work(jobId):
    require_roles(["SafetyManager"])
    job = _get_job(jobId)
    if job["safety_status"] != "STOP_WORK":
        raise invalid_state("Only a stopped job can resume work")
    if any(i["status"] != "CLOSED" for i in job_incidents(jobId)):
        raise invalid_state("All incident reports must be CLOSED before resuming")
    if approved_jha(jobId) is None:
        raise unprocessable(ERR_JHA_NOT_APPROVED,
                            "No APPROVED hazard analysis exists for the job")
    job["safety_status"] = "CLEAR"
    touch(job)
    return success_object(job)


@bp.post("/v1/jobs/<jobId>/close")
def close_job(jobId):
    require_roles(["ProjectManager"])
    job = _get_job(jobId)
    if job["execution_status"] != "INVOICED":
        raise invalid_state("Only an INVOICED job can be closed")
    live = [inv for inv in store.invoices.values()
            if inv["job_id"] == jobId and inv["status"] != "VOID"]
    if not live or live[0]["status"] != "PAID":
        raise unprocessable(ERR_INVOICE_NOT_PAID,
                            "The job's invoice must be PAID before closing")
    job["execution_status"] = "CLOSED"
    touch(job)
    return success_object(job)


@bp.post("/v1/jobs/<jobId>/generate-invoice")
def generate_invoice(jobId):
    require_roles(["ProjectManager"])
    job = _get_job(jobId)
    if job["execution_status"] != "FIELD_COMPLETE":
        raise invalid_state("Only a FIELD_COMPLETE job can generate an invoice")
    if any(m["status"] not in ("RECONCILED", "VOIDED")
           for m in job_manifests(jobId)):
        raise unprocessable(ERR_MANIFEST_UNRECONCILED,
                            "All manifests must be RECONCILED or VOIDED")
    if any(d["status"] == "OPEN" for d in job_downtime(jobId)):
        raise unprocessable(ERR_DOWNTIME_OPEN,
                            "An OPEN downtime event exists on the job")
    regeneration = sum(1 for inv in store.invoices.values()
                       if inv["job_id"] == jobId) + 1
    lines = build_invoice_lines(job)
    invoice = new_entity(store.invoices, {
        "job_id": jobId,
        "invoice_number": "INV-%d-%d" % (job["_seq"], regeneration),
        "pricing_mode_snapshot": job["pricing_mode"],
        "lines": lines,
        "status": "DRAFT",
    })
    recompute_invoice_totals(invoice)
    for d in job_downtime(jobId):
        if d["status"] == "CLOSED" and (d["billable_minutes"] or 0) > 0:
            d["status"] = "BILLED"
            d["invoice_id"] = invoice["id"]
            touch(d)
    recompute_standby_accrual(job)
    job["execution_status"] = "INVOICED"
    touch(job)
    return success_object(invoice, status=201)
