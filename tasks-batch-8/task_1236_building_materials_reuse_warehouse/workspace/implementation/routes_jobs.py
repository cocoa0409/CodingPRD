"""Routes: deconstruction jobs, hazmat screenings, salvage batches."""
from flask import Blueprint, request

import db
from errors import ApiError, err_not_owner
from response import success_obj, success_list
from services import (
    recompute_job_tonnage,
    vehicle_conflicts,
)
from util import (
    authenticate,
    require_role,
    get_body,
    req_str,
    opt_str,
    req_enum,
    req_num,
    opt_num,
    opt_fk,
    req_dt,
    lookup,
    paginate,
    serialize,
    D,
    dec1,
    period_of,
)

bp = Blueprint("jobs", __name__)

SCREENING_RESULTS = {"NOT_TESTED", "NEGATIVE", "POSITIVE"}
RESOLVE_OUTCOMES = {"REMEDIATED", "DISPOSE_HAZARD"}

JOB_CANCEL_SIMPLE = {
    "REQUESTED",
    "SCREENING_PENDING",
    "CLEARED",
    "HAZMAT_HOLD",
    "REMEDIATION_IN_PROGRESS",
}


def _get_job(job_id):
    return lookup(db.jobs, "job", job_id)


def _check_lead_owner(ctx, job):
    if ctx.role == "CrewLead" and job["lead_crew_member_id"] != ctx.user_id:
        raise err_not_owner("CrewLead may only act on jobs they lead")


def _cancel_job_cascade(job):
    """Shared cascade for SCHEDULED / IN_PROGRESS cancellation."""
    for a in db.assignments.values():
        if a["job_id"] == job["id"] and a["status"] == "ASSIGNED":
            a["status"] = "CANCELLED"
            db.touch(a)
    for appt in db.appointments.values():
        if (
            appt["subject_type"] == "DECONSTRUCTION_JOB"
            and appt["subject_id"] == job["id"]
            and appt["status"] == "BOOKED"
        ):
            appt["status"] = "CANCELLED"
            db.touch(appt)


# ---------------------------------------------------------------------------
# Deconstruction jobs
# ---------------------------------------------------------------------------


@bp.post("/reuse/deconstruction-jobs")
def create_job():
    data = get_body()
    title = req_str(data, "title")
    site_address_text = req_str(data, "site_address_text")
    quoted_fee_cents = req_num(data, "quoted_fee_cents", ge=0)
    if int(D(quoted_fee_cents)) != D(quoted_fee_cents):
        from errors import err_invalid_request

        raise err_invalid_request("quoted_fee_cents must be an integer")
    included_labor_cents = opt_num(data, "included_labor_cents", 0, ge=0)
    if int(D(included_labor_cents)) != D(included_labor_cents):
        from errors import err_invalid_request

        raise err_invalid_request("included_labor_cents must be an integer")
    donor_id = opt_fk(data, "donor_id")
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "WarehouseAdmin"])
    if donor_id is not None:
        lookup(db.donors, "donor", donor_id)
    job = {
        **db.base_fields(),
        "title": title,
        "site_address_text": site_address_text,
        "donor_id": donor_id,
        "quoted_fee_cents": int(D(quoted_fee_cents)),
        "included_labor_cents": int(D(included_labor_cents)),
        "status": "REQUESTED",
        "lead_crew_member_id": None,
        "vehicle_id": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "clearing_screening_id": None,
        "estimated_diverted_weight_lbs": 0,
        "certified_diverted_weight_lbs": 0,
        "actual_fee_cents": 0,
    }
    db.jobs[job["id"]] = job
    return success_obj(serialize(job), 201)


@bp.get("/reuse/deconstruction-jobs")
def list_jobs():
    ctx = authenticate()
    require_role(
        ctx, ["CrewCoordinator", "WarehouseAdmin", "CrewLead", "HazmatTechnician", "IntakeStaff"]
    )
    records = list(db.jobs.values())
    for param in (
        "status",
        "donor_id",
        "lead_crew_member_id",
        "vehicle_id",
        "clearing_screening_id",
    ):
        v = request.args.get(param)
        if v is not None:
            records = [j for j in records if j.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(j) for j in page], meta)


@bp.get("/reuse/deconstruction-jobs/<jobId>")
def get_job(jobId):
    ctx = authenticate()
    require_role(
        ctx, ["CrewCoordinator", "WarehouseAdmin", "CrewLead", "HazmatTechnician", "IntakeStaff"]
    )
    return success_obj(serialize(_get_job(jobId)))


@bp.post("/reuse/deconstruction-jobs/<jobId>/request-screening")
def request_screening(jobId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator"])
    job = _get_job(jobId)
    if job["status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_JOB_STATE", 409, "request-screening requires REQUESTED"
        )
    job["status"] = "SCREENING_PENDING"
    db.touch(job)
    return success_obj(serialize(job))


@bp.post("/reuse/deconstruction-jobs/<jobId>/schedule")
def schedule_job(jobId):
    data = get_body()
    lead_crew_member_id = req_str(data, "lead_crew_member_id")
    vehicle_id = req_str(data, "vehicle_id")
    scheduled_start = req_dt(data, "scheduled_start")
    scheduled_end = req_dt(data, "scheduled_end")
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator"])
    job = _get_job(jobId)
    # Body FK existence (priority 5)
    lead = lookup(db.crew_members, "crew_member", lead_crew_member_id)
    vehicle = lookup(db.vehicles, "vehicle", vehicle_id)
    # State (priority 7)
    if job["status"] != "CLEARED":
        raise ApiError("ERR_JOB_NOT_CLEARED", 409, "schedule requires CLEARED")
    # Safety (priority 8): the clearing screener may not lead the job
    clearing = db.screenings.get(job.get("clearing_screening_id") or "")
    if clearing and clearing["performed_by_crew_id"] == lead_crew_member_id:
        raise ApiError(
            "ERR_SCREENER_CANNOT_LEAD",
            403,
            "The technician who cleared the job may not lead it",
        )
    # Business constraints (priority 9)
    if lead["status"] != "ACTIVE" or not lead["lead_certified"]:
        raise ApiError(
            "ERR_CERTIFICATION_MISMATCH",
            422,
            "Job lead must be ACTIVE and lead_certified",
        )
    if vehicle["status"] != "AVAILABLE":
        raise ApiError(
            "ERR_VEHICLE_NOT_AVAILABLE", 409, "Vehicle is not AVAILABLE"
        )
    if vehicle_conflicts(vehicle_id, scheduled_start, scheduled_end):
        raise ApiError(
            "ERR_VEHICLE_TIME_OVERLAP",
            409,
            "Vehicle has a conflicting occupation within the 60-minute buffer",
        )
    # Temporal arithmetic (priority 10)
    if not scheduled_end > scheduled_start:
        from errors import err_invalid_time_window

        raise err_invalid_time_window("scheduled_end must be after scheduled_start")
    job["status"] = "SCHEDULED"
    job["lead_crew_member_id"] = lead_crew_member_id
    job["vehicle_id"] = vehicle_id
    job["scheduled_start"] = scheduled_start
    job["scheduled_end"] = scheduled_end
    db.touch(job)
    return success_obj(serialize(job))


@bp.post("/reuse/deconstruction-jobs/<jobId>/start")
def start_job(jobId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "CrewLead"])
    job = _get_job(jobId)
    _check_lead_owner(ctx, job)
    if job["status"] != "SCHEDULED":
        raise ApiError("ERR_JOB_NOT_SCHEDULED", 409, "start requires SCHEDULED")
    has_crew = any(
        a["job_id"] == job["id"] and a["status"] == "ASSIGNED"
        for a in db.assignments.values()
    )
    if not has_crew:
        raise ApiError(
            "ERR_NO_CREW_ASSIGNED", 409, "No ASSIGNED crew assignment for this job"
        )
    job["status"] = "IN_PROGRESS"
    db.touch(job)
    return success_obj(serialize(job))


@bp.post("/reuse/deconstruction-jobs/<jobId>/complete")
def complete_job(jobId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "CrewLead"])
    job = _get_job(jobId)
    _check_lead_owner(ctx, job)
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_JOB_NOT_IN_PROGRESS", 409, "complete requires IN_PROGRESS")
    quarantined = any(
        b["job_id"] == job["id"] and b["status"] == "QUARANTINED"
        for b in db.batches.values()
    )
    if quarantined:
        raise ApiError(
            "ERR_QUARANTINED_BATCHES_OPEN",
            422,
            "Job has batches in QUARANTINED status",
        )
    job["status"] = "COMPLETED"
    recompute_job_tonnage(job)
    db.touch(job)
    return success_obj(serialize(job))


@bp.post("/reuse/deconstruction-jobs/<jobId>/begin-remediation")
def begin_remediation(jobId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator"])
    job = _get_job(jobId)
    if job["status"] != "HAZMAT_HOLD":
        raise ApiError(
            "ERR_JOB_NOT_IN_HAZMAT_HOLD", 409, "begin-remediation requires HAZMAT_HOLD"
        )
    job["status"] = "REMEDIATION_IN_PROGRESS"
    db.touch(job)
    return success_obj(serialize(job))


@bp.post("/reuse/deconstruction-jobs/<jobId>/complete-remediation")
def complete_remediation(jobId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator"])
    job = _get_job(jobId)
    if job["status"] != "REMEDIATION_IN_PROGRESS":
        raise ApiError(
            "ERR_JOB_NOT_REMEDIATING",
            409,
            "complete-remediation requires REMEDIATION_IN_PROGRESS",
        )
    job["status"] = "SCREENING_PENDING"
    db.touch(job)
    return success_obj(serialize(job))


@bp.post("/reuse/deconstruction-jobs/<jobId>/cancel")
def cancel_job(jobId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "WarehouseAdmin"])
    job = _get_job(jobId)
    if job["status"] in JOB_CANCEL_SIMPLE:
        job["status"] = "CANCELLED"
    elif job["status"] == "SCHEDULED":
        job["status"] = "CANCELLED"
        _cancel_job_cascade(job)
    elif job["status"] == "IN_PROGRESS":
        weighed = any(
            b["job_id"] == job["id"] and b["status"] in ("WEIGHED", "SORTED")
            for b in db.batches.values()
        )
        if weighed:
            raise ApiError(
                "ERR_JOB_HAS_WEIGHED_BATCHES",
                409,
                "Job has WEIGHED or SORTED batches",
            )
        job["status"] = "CANCELLED"
        _cancel_job_cascade(job)
        for b in db.batches.values():
            if b["job_id"] == job["id"] and b["status"] == "MANIFESTED":
                b["status"] = "DISPOSED_HAZARD"
                b["contamination_weight_lbs"] = b["estimated_weight_lbs"]
                b["diverted_weight_lbs"] = 0
                db.touch(b)
        recompute_job_tonnage(job)
    else:
        raise ApiError(
            "ERR_INVALID_JOB_STATE", 409, "Job cannot be cancelled from this state"
        )
    db.touch(job)
    return success_obj(serialize(job))


# ---------------------------------------------------------------------------
# Hazmat screenings
# ---------------------------------------------------------------------------


@bp.post("/reuse/hazmat-screenings")
def create_screening():
    data = get_body()
    job_id = req_str(data, "job_id")
    lead_result = req_enum(data, "lead_result", SCREENING_RESULTS)
    asbestos_result = req_enum(data, "asbestos_result", SCREENING_RESULTS)
    notes = opt_str(data, "notes", "")
    ctx = authenticate()
    require_role(ctx, ["HazmatTechnician"])
    # The technician acts as themselves: X-User-ID is their CrewMember id.
    technician = lookup(db.crew_members, "crew_member", ctx.user_id)
    job = lookup(db.jobs, "job", job_id)
    if not technician["hazmat_certified"]:
        raise ApiError(
            "ERR_CERTIFICATION_MISMATCH",
            422,
            "Screening technician must hold hazmat certification",
        )
    if lead_result == "POSITIVE" or asbestos_result == "POSITIVE":
        outcome = "FAILED"
    elif lead_result == "NEGATIVE" and asbestos_result == "NEGATIVE":
        outcome = "CLEARED"
    else:
        outcome = "PENDING"
    round_no = sum(1 for s in db.screenings.values() if s["job_id"] == job_id) + 1
    screening = {
        **db.lean_fields(),
        "job_id": job_id,
        "performed_by_crew_id": ctx.user_id,
        "screening_round": round_no,
        "lead_result": lead_result,
        "asbestos_result": asbestos_result,
        "notes": notes,
        "outcome": outcome,
    }
    db.screenings[screening["id"]] = screening
    # Drive the job without any further request
    if job["status"] == "SCREENING_PENDING":
        if outcome == "CLEARED":
            job["status"] = "CLEARED"
            job["clearing_screening_id"] = screening["id"]
            db.touch(job)
        elif outcome == "FAILED":
            job["status"] = "HAZMAT_HOLD"
            db.touch(job)
    elif job["status"] == "IN_PROGRESS" and outcome == "FAILED":
        # Post-hoc discovery: conditional cascade + compensation
        job["status"] = "HAZMAT_HOLD"
        for b in db.batches.values():
            if b["job_id"] == job["id"] and b["status"] == "WEIGHED":
                b["status"] = "QUARANTINED"
                db.touch(b)
        recompute_job_tonnage(job)
        db.touch(job)
    return success_obj(serialize(screening), 201)


@bp.get("/reuse/hazmat-screenings")
def list_screenings():
    ctx = authenticate()
    require_role(
        ctx,
        ["HazmatTechnician", "CrewCoordinator", "WarehouseAdmin", "IntakeStaff", "StoreManager"],
    )
    records = list(db.screenings.values())
    for param in ("job_id", "performed_by_crew_id", "outcome"):
        v = request.args.get(param)
        if v is not None:
            records = [s for s in records if s.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(s) for s in page], meta)


@bp.get("/reuse/hazmat-screenings/<screeningId>")
def get_screening(screeningId):
    ctx = authenticate()
    require_role(
        ctx,
        ["HazmatTechnician", "CrewCoordinator", "WarehouseAdmin", "IntakeStaff", "StoreManager"],
    )
    return success_obj(serialize(lookup(db.screenings, "screening", screeningId)))


# ---------------------------------------------------------------------------
# Salvage batches
# ---------------------------------------------------------------------------


@bp.post("/reuse/salvage-batches")
def create_batch():
    data = get_body()
    job_id = req_str(data, "job_id")
    offer_id = opt_fk(data, "offer_id")
    category_id = req_str(data, "category_id")
    estimated_weight_lbs = req_num(data, "estimated_weight_lbs", gt=0)
    ctx = authenticate()
    require_role(ctx, ["CrewLead", "CrewCoordinator"])
    job = lookup(db.jobs, "job", job_id)
    lookup(db.categories, "category", category_id)
    if offer_id is not None:
        lookup(db.offers, "offer", offer_id)
    if job["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError(
            "ERR_INVALID_JOB_STATE",
            409,
            "Batch manifest requires job SCHEDULED or IN_PROGRESS",
        )
    batch = {
        **db.base_fields(),
        "job_id": job_id,
        "offer_id": offer_id,
        "category_id": category_id,
        "status": "MANIFESTED",
        "estimated_weight_lbs": estimated_weight_lbs,
        "scale_weight_lbs": 0,
        "contamination_weight_lbs": 0,
        "diverted_weight_lbs": 0,
        "weighed_at": None,
        "report_period": "",
    }
    db.batches[batch["id"]] = batch
    recompute_job_tonnage(job)
    db.touch(job)
    return success_obj(serialize(batch), 201)


@bp.get("/reuse/salvage-batches")
def list_batches():
    ctx = authenticate()
    require_role(
        ctx, ["CrewLead", "CrewCoordinator", "IntakeStaff", "StoreManager", "WarehouseAdmin"]
    )
    records = list(db.batches.values())
    for param in ("job_id", "offer_id", "category_id", "status", "report_period"):
        v = request.args.get(param)
        if v is not None:
            records = [b for b in records if b.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(b) for b in page], meta)


@bp.get("/reuse/salvage-batches/<batchId>")
def get_batch(batchId):
    ctx = authenticate()
    require_role(
        ctx, ["CrewLead", "CrewCoordinator", "IntakeStaff", "StoreManager", "WarehouseAdmin"]
    )
    return success_obj(serialize(lookup(db.batches, "batch", batchId)))


@bp.post("/reuse/salvage-batches/<batchId>/weigh")
def weigh_batch(batchId):
    data = get_body()
    scale_weight_lbs = req_num(data, "scale_weight_lbs")
    contamination_weight_lbs = opt_num(data, "contamination_weight_lbs", 0)
    ctx = authenticate()
    require_role(ctx, ["CrewLead", "CrewCoordinator"])
    batch = lookup(db.batches, "batch", batchId)
    if batch["status"] != "MANIFESTED":
        raise ApiError("ERR_BATCH_NOT_WEIGHABLE", 409, "weigh requires MANIFESTED")
    job = db.jobs[batch["job_id"]]
    if job["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise ApiError(
            "ERR_JOB_NOT_IN_PROGRESS",
            409,
            "weigh requires job IN_PROGRESS or COMPLETED",
        )
    if (
        D(scale_weight_lbs) <= 0
        or D(contamination_weight_lbs) < 0
        or D(contamination_weight_lbs) > D(scale_weight_lbs)
    ):
        raise ApiError(
            "ERR_INVALID_WEIGHTS",
            400,
            "scale_weight_lbs must be > 0 and 0 <= contamination_weight_lbs <= scale_weight_lbs",
        )
    batch["status"] = "WEIGHED"
    batch["scale_weight_lbs"] = scale_weight_lbs
    batch["contamination_weight_lbs"] = contamination_weight_lbs
    batch["diverted_weight_lbs"] = dec1(
        D(scale_weight_lbs) - D(contamination_weight_lbs)
    )
    batch["weighed_at"] = db.now()
    batch["report_period"] = period_of(db.now())
    db.touch(batch)
    recompute_job_tonnage(job)
    db.touch(job)
    return success_obj(serialize(batch))


@bp.post("/reuse/salvage-batches/<batchId>/quarantine")
def quarantine_batch(batchId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["HazmatTechnician", "StoreManager", "WarehouseAdmin"])
    batch = lookup(db.batches, "batch", batchId)
    if batch["status"] != "WEIGHED":
        raise ApiError("ERR_BATCH_NOT_WEIGHED", 409, "quarantine requires WEIGHED")
    batch["status"] = "QUARANTINED"
    db.touch(batch)
    job = db.jobs[batch["job_id"]]
    recompute_job_tonnage(job)
    db.touch(job)
    return success_obj(serialize(batch))


@bp.post("/reuse/salvage-batches/<batchId>/resolve-quarantine")
def resolve_quarantine(batchId):
    data = get_body()
    outcome = req_enum(data, "outcome", RESOLVE_OUTCOMES)
    new_scale_weight_lbs = opt_num(data, "new_scale_weight_lbs")
    ctx = authenticate()
    require_role(ctx, ["HazmatTechnician", "StoreManager", "WarehouseAdmin"])
    batch = lookup(db.batches, "batch", batchId)
    if batch["status"] != "QUARANTINED":
        raise ApiError(
            "ERR_BATCH_NOT_QUARANTINED", 409, "resolve-quarantine requires QUARANTINED"
        )
    if new_scale_weight_lbs is not None:
        if D(new_scale_weight_lbs) <= 0 or D(new_scale_weight_lbs) < D(
            batch["contamination_weight_lbs"]
        ):
            raise ApiError(
                "ERR_INVALID_WEIGHTS",
                400,
                "new_scale_weight_lbs must be > 0 and >= contamination_weight_lbs",
            )
    job = db.jobs[batch["job_id"]]
    if outcome == "REMEDIATED":
        if new_scale_weight_lbs is not None:
            batch["scale_weight_lbs"] = new_scale_weight_lbs
            batch["diverted_weight_lbs"] = dec1(
                D(new_scale_weight_lbs) - D(batch["contamination_weight_lbs"])
            )
        batch["status"] = "WEIGHED"
    else:  # DISPOSE_HAZARD
        batch["status"] = "DISPOSED_HAZARD"
        batch["diverted_weight_lbs"] = 0
    db.touch(batch)
    recompute_job_tonnage(job)
    db.touch(job)
    return success_obj(serialize(batch))


@bp.post("/reuse/salvage-batches/<batchId>/mark-sorted")
def mark_sorted_batch(batchId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "StoreManager"])
    batch = lookup(db.batches, "batch", batchId)
    if batch["status"] != "WEIGHED":
        raise ApiError("ERR_BATCH_NOT_WEIGHED", 409, "mark-sorted requires WEIGHED")
    batch["status"] = "SORTED"
    db.touch(batch)
    return success_obj(serialize(batch))
