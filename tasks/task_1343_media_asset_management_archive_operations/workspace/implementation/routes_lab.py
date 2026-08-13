"""MigrationJob, DigitizationTicket and Workstation routes (the lab)."""
from flask import Blueprint, request

import calc
import cascades
from auth import ALL_ROLES, require_roles
from db import STORE, new_id, now, stamp
from envelope import ok, paginate
from errors import raise_err
from serializers import job_out, ticket_out, workstation_out
from validate import (
    FORMAT_CLASSES, OBSOLETE_FORMATS, OUTPUT_FORMATS, STORAGE_TIERS,
    WORKSTATION_STATUSES, body, opt_str, req_dt, req_enum, req_enum_list,
    req_str,
)

bp = Blueprint("lab", __name__, url_prefix="/archive")


def _get_job(jid):
    rec = STORE.jobs.get(jid)
    if rec is None:
        raise_err("ERR_JOB_NOT_FOUND", "Migration job not found")
    return rec


def _get_ticket(tid):
    rec = STORE.tickets.get(tid)
    if rec is None:
        raise_err("ERR_TICKET_NOT_FOUND", "Digitization ticket not found")
    return rec


def _get_workstation(wid):
    rec = STORE.workstations.get(wid)
    if rec is None:
        raise_err("ERR_WORKSTATION_NOT_FOUND", "Workstation not found")
    return rec


def _check_schedule_conflict(workstation_id, new_start, new_end):
    """30-minute turnaround buffer on BOTH sides of every occupied slot.
    Allowed iff new_end + 30min <= t.start OR new_start >= t.end + 30min;
    a gap of exactly 30 minutes is allowed, touching adjacency is a conflict."""
    for t in STORE.tickets.values():
        if t["workstation_id"] != workstation_id:
            continue
        if t["status"] not in ("ASSIGNED", "DIGITIZING"):
            continue
        if new_end + calc.TURNAROUND <= t["scheduled_start"]:
            continue
        if new_start >= t["scheduled_end"] + calc.TURNAROUND:
            continue
        raise_err(
            "ERR_WORKSTATION_SCHEDULE_CONFLICT",
            "Slot violates the 30-minute turnaround buffer on this workstation",
        )


def _assign_gates(ticket, ws):
    """Shared assignment gates, in PRD 3.9 order."""
    if ticket["status"] != "QUEUED":
        raise_err("ERR_TICKET_NOT_QUEUED", "assign requires QUEUED")
    if ws["status"] != "ACTIVE":
        raise_err("ERR_WORKSTATION_UNAVAILABLE", "Workstation is not ACTIVE")
    asset = STORE.assets.get(ticket["asset_id"])
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    if asset["format_class"] not in ws["supported_formats"]:
        raise_err(
            "ERR_WORKSTATION_FORMAT_UNSUPPORTED",
            "The workstation does not support the asset's format_class",
        )
    _check_schedule_conflict(ws["id"], ticket["scheduled_start"], ticket["scheduled_end"])
    return asset


# --- MigrationJob ---------------------------------------------------------------
@bp.post("/migration-jobs")
def create_job():
    require_roles("ArchivistLead")
    j = body()
    asset_id = req_str(j, "asset_id")
    asset = STORE.assets.get(asset_id)
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    # OCC field presence/type
    if "expected_asset_version" not in j or j["expected_asset_version"] is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'expected_asset_version': is required")
    if isinstance(j["expected_asset_version"], bool) or not isinstance(
        j["expected_asset_version"], int
    ):
        raise_err("ERR_INVALID_REQUEST", "Field 'expected_asset_version': must be an integer")
    expected = j["expected_asset_version"]
    # State preconditions
    if asset["catalog_status"] == "DISPOSED":
        raise_err("ERR_ASSET_DISPOSED", "The asset has been disposed")
    if any(
        x["asset_id"] == asset_id and x["status"] == "IN_PROGRESS"
        for x in STORE.jobs.values()
    ):
        raise_err(
            "ERR_JOB_IN_PROGRESS_EXISTS",
            "Another migration job for this asset is IN_PROGRESS",
        )
    # Optimistic concurrency
    if expected != asset["version"]:
        raise_err(
            "ERR_STALE_ASSET_VERSION",
            "expected_asset_version does not match the asset's current version",
        )
    # Safety gate
    if calc.hold_status(asset) != "CLEAR":
        raise_err("ERR_LEGAL_HOLD_ACTIVE", "Asset is under an active legal hold")
    # Shape: valid tier, differing from the current tier
    target_tier = req_enum(j, "target_tier", STORAGE_TIERS)
    if target_tier == asset["storage_tier"]:
        raise_err("ERR_INVALID_REQUEST", "target_tier must differ from the current storage_tier")
    # Supersede the queue, then bump the asset version as part of the create
    t = now()
    for x in STORE.jobs.values():
        if x["asset_id"] == asset_id and x["status"] == "QUEUED":
            x["status"] = "SUPERSEDED"
            x["updated_at"] = t
            x["version"] += 1
    asset["version"] += 1
    asset["updated_at"] = t
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "target_tier": target_tier,
        "status": "QUEUED",
        "retry_count": 0,
        "checksum_sha256": None,
        "failure_reason": None,
        "_completed_at": None,
    }
    stamp(rec)
    STORE.jobs[rec["id"]] = rec
    return ok(job_out(rec), 201)


@bp.get("/migration-jobs")
def list_jobs():
    require_roles(*ALL_ROLES)
    recs = list(STORE.jobs.values())
    for param, field in (("asset_id", "asset_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, job_out)


@bp.get("/migration-jobs/<jid>")
def get_job(jid):
    require_roles(*ALL_ROLES)
    return ok(job_out(_get_job(jid)))


@bp.post("/migration-jobs/<jid>/start")
def start_job(jid):
    require_roles("LabTechnician")
    rec = _get_job(jid)
    if rec["status"] != "QUEUED":
        raise_err("ERR_JOB_NOT_QUEUED", "start requires QUEUED")
    rec["status"] = "IN_PROGRESS"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(job_out(rec))


@bp.post("/migration-jobs/<jid>/complete")
def complete_job(jid):
    require_roles("LabTechnician")
    rec = _get_job(jid)
    if rec["status"] != "IN_PROGRESS":
        raise_err("ERR_JOB_NOT_IN_PROGRESS", "complete requires IN_PROGRESS")
    j = body()
    checksum = req_str(j, "checksum_sha256")
    rec["status"] = "COMPLETED"
    rec["checksum_sha256"] = checksum
    rec["_completed_at"] = now()
    rec["updated_at"] = now()
    rec["version"] += 1
    asset = STORE.assets.get(rec["asset_id"])
    if asset is not None:
        cascades.migration_complete_cascade(asset, rec)
    return ok(job_out(rec))


@bp.post("/migration-jobs/<jid>/fail")
def fail_job(jid):
    require_roles("LabTechnician")
    rec = _get_job(jid)
    if rec["status"] != "IN_PROGRESS":
        raise_err("ERR_JOB_NOT_IN_PROGRESS", "fail requires IN_PROGRESS")
    j = body()
    reason = req_str(j, "reason")
    rec["status"] = "FAILED"
    rec["failure_reason"] = reason
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(job_out(rec))


@bp.post("/migration-jobs/<jid>/retry")
def retry_job(jid):
    require_roles("LabTechnician")
    rec = _get_job(jid)
    if rec["status"] != "FAILED":
        raise_err("ERR_JOB_NOT_FAILED", "retry requires FAILED")
    if rec["retry_count"] >= calc.MAX_MIGRATION_RETRIES:
        raise_err("ERR_RETRY_BUDGET_EXHAUSTED", "Migration retry budget exhausted (cap 2)")
    rec["status"] = "QUEUED"
    rec["retry_count"] += 1
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(job_out(rec))


@bp.post("/migration-jobs/<jid>/cancel")
def cancel_job(jid):
    require_roles("ArchivistLead")
    rec = _get_job(jid)
    if rec["status"] not in ("QUEUED", "HOLD_PAUSED"):
        raise_err("ERR_JOB_NOT_CANCELLABLE", "cancel requires QUEUED or HOLD_PAUSED")
    rec["status"] = "CANCELLED"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(job_out(rec))


# --- DigitizationTicket -----------------------------------------------------------
@bp.post("/digitization-tickets")
def create_ticket():
    require_roles("ArchivistLead")
    j = body()
    asset_id = req_str(j, "asset_id")
    asset = STORE.assets.get(asset_id)
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    if asset["catalog_status"] == "DISPOSED":
        raise_err("ERR_ASSET_DISPOSED", "The asset has been disposed")
    scheduled_start = req_dt(j, "scheduled_start")
    scheduled_end = req_dt(j, "scheduled_end")
    if not (scheduled_end > scheduled_start):
        raise_err("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start")
    output_format = req_enum(j, "output_format", OUTPUT_FORMATS)
    if asset["format_class"] not in OBSOLETE_FORMATS:
        raise_err("ERR_FORMAT_NOT_OBSOLETE", "Asset format_class is not in OBSOLETE_FORMATS")
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "workstation_id": None,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "output_format": output_format,
        "status": "QUEUED",
        "rework_count": 0,
        "qc_notes": None,
    }
    stamp(rec)
    STORE.tickets[rec["id"]] = rec
    return ok(ticket_out(rec), 201)


@bp.get("/digitization-tickets")
def list_tickets():
    require_roles(*ALL_ROLES)
    recs = list(STORE.tickets.values())
    for param, field in (
        ("asset_id", "asset_id"),
        ("workstation_id", "workstation_id"),
        ("status", "status"),
    ):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, ticket_out)


@bp.get("/digitization-tickets/<tid>")
def get_ticket(tid):
    require_roles(*ALL_ROLES)
    return ok(ticket_out(_get_ticket(tid)))


@bp.post("/digitization-tickets/auto-assign")
def auto_assign():
    require_roles("LabTechnician")
    j = body()
    workstation_id = req_str(j, "workstation_id")
    ws = _get_workstation(workstation_id)
    if ws["status"] != "ACTIVE":
        raise_err("ERR_WORKSTATION_UNAVAILABLE", "Workstation is not ACTIVE")
    # Eligible pool: QUEUED tickets whose asset format the station supports
    pool = []
    for t in STORE.tickets.values():
        if t["status"] != "QUEUED":
            continue
        asset = STORE.assets.get(t["asset_id"])
        if asset is None:
            continue
        if asset["format_class"] in ws["supported_formats"]:
            pool.append(t)
    if not pool:
        raise_err("ERR_NO_ELIGIBLE_TICKET", "No QUEUED ticket is eligible for this workstation")
    # Highest priority_score first; ties toward the earliest created_at
    t_now = now()
    pool.sort(key=lambda t: (-calc.priority_score(t), t["created_at"], t["_seq"]))
    chosen = pool[0]
    chosen["scheduled_start"] = t_now
    chosen["scheduled_end"] = t_now + calc.AUTO_ASSIGN_SLOT
    _check_schedule_conflict(ws["id"], chosen["scheduled_start"], chosen["scheduled_end"])
    chosen["workstation_id"] = ws["id"]
    chosen["status"] = "ASSIGNED"
    chosen["updated_at"] = t_now
    chosen["version"] += 1
    return ok(ticket_out(chosen))


@bp.post("/digitization-tickets/<tid>/assign")
def assign_ticket(tid):
    require_roles("LabTechnician")
    rec = _get_ticket(tid)
    j = body()
    workstation_id = req_str(j, "workstation_id")
    ws = _get_workstation(workstation_id)
    _assign_gates(rec, ws)
    rec["workstation_id"] = ws["id"]
    rec["status"] = "ASSIGNED"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(ticket_out(rec))


@bp.post("/digitization-tickets/<tid>/start")
def start_ticket(tid):
    require_roles("LabTechnician")
    rec = _get_ticket(tid)
    if rec["status"] != "ASSIGNED":
        raise_err("ERR_TICKET_NOT_ASSIGNED", "start requires ASSIGNED")
    if now() < rec["scheduled_start"]:
        raise_err("ERR_TICKET_NOT_DUE", "The scheduled start has not been reached")
    rec["status"] = "DIGITIZING"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(ticket_out(rec))


@bp.post("/digitization-tickets/<tid>/submit-qc")
def submit_qc(tid):
    require_roles("LabTechnician")
    rec = _get_ticket(tid)
    if rec["status"] != "DIGITIZING":
        raise_err("ERR_TICKET_NOT_DIGITIZING", "submit-qc requires DIGITIZING")
    rec["status"] = "QC_REVIEW"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(ticket_out(rec))


@bp.post("/digitization-tickets/<tid>/qc-pass")
def qc_pass(tid):
    require_roles("LabTechnician")
    rec = _get_ticket(tid)
    if rec["status"] != "QC_REVIEW":
        raise_err("ERR_TICKET_NOT_IN_QC", "qc-pass requires QC_REVIEW")
    j = body()
    qc_notes = opt_str(j, "qc_notes", None)
    rec["status"] = "COMPLETED"
    rec["qc_notes"] = qc_notes
    rec["updated_at"] = now()
    rec["version"] += 1
    # Create the derivative asset from the original
    orig = STORE.assets.get(rec["asset_id"])
    if orig is not None:
        derivative = {
            "id": new_id(),
            "ingest_batch_id": orig["ingest_batch_id"],
            "source_asset_id": orig["id"],
            "title": orig["title"],
            "description": orig["description"],
            "media_type": orig["media_type"],
            "format_class": rec["output_format"],
            "duration_seconds": orig["duration_seconds"],
            "size_gb": orig["size_gb"],
            "rights_holder": orig["rights_holder"],
            "keywords": list(orig["keywords"]),
            "content_rating": orig["content_rating"],
            "catalog_status": "METADATA_DRAFT",
            "storage_tier": "ONLINE",
            "metadata_submitted_by_user_id": None,
        }
        stamp(derivative)
        STORE.assets[derivative["id"]] = derivative
    return ok(ticket_out(rec))


@bp.post("/digitization-tickets/<tid>/qc-fail")
def qc_fail(tid):
    require_roles("LabTechnician")
    rec = _get_ticket(tid)
    if rec["status"] != "QC_REVIEW":
        raise_err("ERR_TICKET_NOT_IN_QC", "qc-fail requires QC_REVIEW")
    j = body()
    qc_notes = req_str(j, "qc_notes")
    rec["qc_notes"] = qc_notes
    rec["workstation_id"] = None
    if rec["rework_count"] < calc.MAX_QC_REWORKS:
        rec["rework_count"] += 1
        rec["status"] = "QUEUED"
    else:
        rec["status"] = "QC_FAILED"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(ticket_out(rec))


@bp.post("/digitization-tickets/<tid>/cancel")
def cancel_ticket(tid):
    require_roles("ArchivistLead")
    rec = _get_ticket(tid)
    if rec["status"] not in ("QUEUED", "ASSIGNED"):
        raise_err("ERR_TICKET_NOT_CANCELLABLE", "cancel requires QUEUED or ASSIGNED")
    rec["status"] = "CANCELLED"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(ticket_out(rec))


# --- Workstation ------------------------------------------------------------------
@bp.post("/workstations")
def create_workstation():
    require_roles("SystemAdmin")
    j = body()
    name = req_str(j, "name")
    supported_formats = req_enum_list(j, "supported_formats", FORMAT_CLASSES)
    for w in STORE.workstations.values():
        if w["name"] == name:
            raise_err("ERR_DUPLICATE_WORKSTATION_NAME", "A workstation with this name already exists")
    rec = {
        "id": new_id(),
        "name": name,
        "supported_formats": supported_formats,
        "status": "ACTIVE",
    }
    stamp(rec)
    STORE.workstations[rec["id"]] = rec
    return ok(workstation_out(rec), 201)


@bp.get("/workstations")
def list_workstations():
    require_roles(*ALL_ROLES)
    recs = list(STORE.workstations.values())
    v = request.args.get("status")
    if v is not None:
        recs = [r for r in recs if r["status"] == v]
    return paginate(recs, workstation_out)


@bp.get("/workstations/<wid>")
def get_workstation(wid):
    require_roles(*ALL_ROLES)
    return ok(workstation_out(_get_workstation(wid)))


@bp.patch("/workstations/<wid>")
def patch_workstation(wid):
    require_roles("SystemAdmin")
    rec = _get_workstation(wid)
    j = body()
    status = req_enum(j, "status", WORKSTATION_STATUSES)
    if status == "MAINTENANCE":
        for t in STORE.tickets.values():
            if t["workstation_id"] == wid and t["status"] in ("ASSIGNED", "DIGITIZING"):
                raise_err(
                    "ERR_WORKSTATION_BUSY",
                    "Cannot enter MAINTENANCE while tickets are ASSIGNED or DIGITIZING",
                )
    rec["status"] = status
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(workstation_out(rec))
