"""Inspection booking, findings, and repair-order cycles (PRD §3.7)."""

from flask import Blueprint

from core import (
    db, ApiError, auth, require_role, body_json, req_int, req_str, req_enum,
    req_dt, as_bool, need, get_or_404, create_entity, touch, ser, ok, paginate,
    sorted_all, apply_filters, forbid,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_SOD,
    ERR_INSPECTOR_UNAVAILABLE, ERR_CRITICAL_FINDINGS_OPEN,
    ERR_FINDING_NOT_RISK_ACCEPTABLE,
)

bp = Blueprint("inspect", __name__)

SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}


def _own_inspection(uid, inspection):
    """Entity-backed ownership: API653Inspector's X-User-ID is the Inspector id."""
    if inspection["inspector_id"] != uid:
        forbid("acting inspector is not the assigned inspector")


# -------------------------------------------------------------- inspections ---


@bp.post("/inspections")
def create_inspection():
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    b = body_json()
    job_id = req_str(b, "job_id")
    inspector_id = req_str(b, "inspector_id")
    scheduled_start = req_dt(b, "scheduled_start")
    scheduled_end = req_dt(b, "scheduled_end")
    expected = req_int(b, "expected_inspector_version")
    if not scheduled_start < scheduled_end:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "scheduled_start must be strictly before scheduled_end")
    job = get_or_404(db.cleaning_jobs, job_id, "cleaning job")
    inspector = get_or_404(db.inspectors, inspector_id, "inspector")
    if expected != inspector["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_inspector_version does not match")
    if job["status"] not in ("ENTRY_IN_PROGRESS", "ENTRY_COMPLETE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "job is not in ENTRY_IN_PROGRESS or ENTRY_COMPLETE")
    # Half-open intervals; adjacency (new.start == existing.end) is allowed.
    for other in db.inspections.values():
        if other["inspector_id"] == inspector_id \
                and other["status"] in ("SCHEDULED", "IN_PROGRESS"):
            if scheduled_start < other["scheduled_end"] \
                    and other["scheduled_start"] < scheduled_end:
                raise ApiError(ERR_INSPECTOR_UNAVAILABLE, 409,
                               "interval intersects an existing inspection")
    insp = create_entity({
        "job_id": job_id,
        "inspector_id": inspector_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "reported_by_user_id": None,
        "status": "SCHEDULED",
    })
    db.inspections[insp["id"]] = insp
    touch(inspector)  # booking advances the inspector version by one
    return ok(ser(insp), 201)


@bp.get("/inspections/<inspectionId>")
def get_inspection(inspectionId):
    auth()
    return ok(ser(get_or_404(db.inspections, inspectionId, "inspection")), 200)


@bp.get("/inspections")
def list_inspections():
    auth()
    items = apply_filters(sorted_all(db.inspections), [
        ("job_id", "job_id"),
        ("inspector_id", "inspector_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


@bp.post("/inspections/<inspectionId>/start")
def start_inspection(inspectionId):
    uid, role = auth()
    require_role(role, {"API653Inspector"})
    insp = get_or_404(db.inspections, inspectionId, "inspection")
    _own_inspection(uid, insp)
    if insp["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "inspection is not SCHEDULED")
    job = db.cleaning_jobs.get(insp["job_id"])
    if job is None or job["status"] != "ENTRY_COMPLETE":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not ENTRY_COMPLETE")
    insp["status"] = "IN_PROGRESS"
    touch(insp)
    job["status"] = "INSPECTION_IN_PROGRESS"
    touch(job)
    return ok(ser(insp), 200)


@bp.post("/inspections/<inspectionId>/report")
def report_inspection(inspectionId):
    uid, role = auth()
    require_role(role, {"API653Inspector"})
    insp = get_or_404(db.inspections, inspectionId, "inspection")
    _own_inspection(uid, insp)
    if insp["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "inspection is not IN_PROGRESS")
    insp["reported_by_user_id"] = uid
    insp["status"] = "REPORTED"
    touch(insp)
    return ok(ser(insp), 200)


@bp.post("/inspections/<inspectionId>/accept")
def accept_inspection(inspectionId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    insp = get_or_404(db.inspections, inspectionId, "inspection")
    if insp["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, 409, "inspection is not REPORTED")
    # PRD §3.7 normative order: segregation of duties first, then findings.
    if uid == insp["reported_by_user_id"]:
        raise ApiError(ERR_SOD, 403,
                       "acceptor must differ from the reporting inspector")
    if any(f["inspection_id"] == insp["id"] and f["severity"] == "CRITICAL"
           and f["status"] == "OPEN" for f in db.findings.values()):
        raise ApiError(ERR_CRITICAL_FINDINGS_OPEN, 409,
                       "an OPEN CRITICAL finding blocks acceptance")
    insp["status"] = "ACCEPTED"
    touch(insp)
    job = db.cleaning_jobs.get(insp["job_id"])
    if job is not None and job["status"] == "INSPECTION_IN_PROGRESS":
        job["status"] = "INSPECTION_ACCEPTED"
        touch(job)
    return ok(ser(insp), 200)


@bp.post("/inspections/<inspectionId>/reject")
def reject_inspection(inspectionId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    insp = get_or_404(db.inspections, inspectionId, "inspection")
    if insp["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, 409, "inspection is not REPORTED")
    insp["status"] = "REJECTED"
    touch(insp)
    return ok(ser(insp), 200)


@bp.post("/inspections/<inspectionId>/amend")
def amend_inspection(inspectionId):
    uid, role = auth()
    require_role(role, {"API653Inspector"})
    insp = get_or_404(db.inspections, inspectionId, "inspection")
    _own_inspection(uid, insp)
    if insp["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "inspection is not REJECTED")
    insp["status"] = "REPORTED"
    touch(insp)
    return ok(ser(insp), 200)


@bp.post("/inspections/<inspectionId>/cancel")
def cancel_inspection(inspectionId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    insp = get_or_404(db.inspections, inspectionId, "inspection")
    if insp["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "inspection is not SCHEDULED")
    insp["status"] = "CANCELLED"
    touch(insp)
    return ok(ser(insp), 200)


# ----------------------------------------------------- inspection findings ---


@bp.post("/inspection-findings")
def create_finding():
    uid, role = auth()
    require_role(role, {"API653Inspector"})
    b = body_json()
    inspection_id = req_str(b, "inspection_id")
    severity = req_enum(b, "severity", SEVERITIES)
    description = req_str(b, "description")
    requires_repair = as_bool(need(b, "requires_repair"), "requires_repair")
    insp = get_or_404(db.inspections, inspection_id, "inspection")
    _own_inspection(uid, insp)
    if insp["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "inspection is not IN_PROGRESS")
    f = create_entity({
        "inspection_id": inspection_id,
        "severity": severity,
        "description": description,
        "requires_repair": requires_repair,
        "status": "OPEN",
    })
    db.findings[f["id"]] = f
    return ok(ser(f), 201)


@bp.get("/inspection-findings/<findingId>")
def get_finding(findingId):
    auth()
    return ok(ser(get_or_404(db.findings, findingId, "finding")), 200)


@bp.get("/inspection-findings")
def list_findings():
    auth()
    items = apply_filters(sorted_all(db.findings), [
        ("inspection_id", "inspection_id"),
        ("status", "status"),
        ("severity", "severity"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


@bp.post("/inspection-findings/<findingId>/accept-risk")
def accept_risk(findingId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    f = get_or_404(db.findings, findingId, "finding")
    if f["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "finding is not OPEN")
    if f["severity"] not in ("MINOR", "MAJOR"):
        raise ApiError(ERR_FINDING_NOT_RISK_ACCEPTABLE, 409,
                       "only MINOR/MAJOR findings may be accepted as risk")
    f["status"] = "ACCEPTED_RISK"
    touch(f)
    return ok(ser(f), 200)


# ------------------------------------------------------------- repair orders ---


@bp.post("/repair-orders")
def create_repair():
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    b = body_json()
    finding_id = req_str(b, "finding_id")
    description = req_str(b, "description")
    f = get_or_404(db.findings, finding_id, "finding")
    if f["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "finding is not OPEN")
    insp = db.inspections.get(f["inspection_id"])
    job_id = insp["job_id"] if insp is not None else None
    r = create_entity({
        "finding_id": finding_id,
        "job_id": job_id,
        "description": description,
        "completed_by_user_id": None,
        "status": "OPEN",
    })
    db.repair_orders[r["id"]] = r
    f["status"] = "REPAIR_ORDERED"
    touch(f)
    return ok(ser(r), 201)


@bp.get("/repair-orders/<repairId>")
def get_repair(repairId):
    auth()
    return ok(ser(get_or_404(db.repair_orders, repairId, "repair order")), 200)


@bp.get("/repair-orders")
def list_repairs():
    auth()
    items = apply_filters(sorted_all(db.repair_orders), [
        ("finding_id", "finding_id"),
        ("job_id", "job_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


def _repair_owner(uid, repair):
    job = db.cleaning_jobs.get(repair["job_id"])
    if job is not None and job["contractor_id"] != uid:
        forbid("acting ContractorSupervisor does not own this job")


def _repair_inspector(uid, repair):
    f = db.findings.get(repair["finding_id"])
    insp = db.inspections.get(f["inspection_id"]) if f is not None else None
    if insp is not None and insp["inspector_id"] != uid:
        forbid("acting inspector is not the assigned inspector")
    return insp


@bp.post("/repair-orders/<repairId>/start")
def start_repair(repairId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    r = get_or_404(db.repair_orders, repairId, "repair order")
    _repair_owner(uid, r)
    if r["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "repair order is not OPEN")
    r["status"] = "IN_PROGRESS"
    touch(r)
    return ok(ser(r), 200)


@bp.post("/repair-orders/<repairId>/complete")
def complete_repair(repairId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    r = get_or_404(db.repair_orders, repairId, "repair order")
    _repair_owner(uid, r)
    if r["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "repair order is not IN_PROGRESS")
    r["completed_by_user_id"] = uid
    r["status"] = "COMPLETED"
    touch(r)
    return ok(ser(r), 200)


@bp.post("/repair-orders/<repairId>/verify")
def verify_repair(repairId):
    uid, role = auth()
    require_role(role, {"API653Inspector"})
    r = get_or_404(db.repair_orders, repairId, "repair order")
    _repair_inspector(uid, r)
    if r["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "repair order is not COMPLETED")
    if uid == r["completed_by_user_id"]:
        raise ApiError(ERR_SOD, 403,
                       "verifier must differ from the repair completer")
    r["status"] = "VERIFIED"
    touch(r)
    f = db.findings.get(r["finding_id"])
    if f is not None and f["status"] == "REPAIR_ORDERED":
        f["status"] = "RESOLVED"
        touch(f)
    return ok(ser(r), 200)


@bp.post("/repair-orders/<repairId>/reject")
def reject_repair(repairId):
    uid, role = auth()
    require_role(role, {"API653Inspector"})
    r = get_or_404(db.repair_orders, repairId, "repair order")
    _repair_inspector(uid, r)
    if r["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "repair order is not COMPLETED")
    r["status"] = "IN_PROGRESS"
    touch(r)
    return ok(ser(r), 200)
