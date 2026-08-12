"""Jobs lifecycle routes."""
from datetime import timedelta
from flask import Blueprint, request
import db
from db import clock, format_ts, iso_now
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import (
    base_record, touch, get_or_404, serialize_job, serialize_assignment,
    find_accepted_or_arrived_assignment, find_current_assignment,
    find_job_scope_items,
    recompute_active_assignment_count, find_job_services,
)
from services import dispatch as dispatch_svc

bp = Blueprint("jobs", __name__)


@bp.route("/jobs", methods=["POST"])
def create_job():
    require_role("Dispatcher")
    body = get_body()
    require_fields(body, ["property_id", "incident_type", "priority"])
    check_enum(body["incident_type"], {"FIRE", "STORM", "VANDALISM"}, "incident_type")
    check_enum(body["priority"], {"P1", "P2", "P3"}, "priority")
    prop = db.properties.get(body["property_id"])
    if prop is None:
        raise err("ERR_NOT_FOUND", "Property not found")
    market = db.markets.get(prop["market_id"])
    if market is None:
        raise err("ERR_NOT_FOUND", "Market not found")
    sla_field = "sla_minutes_" + body["priority"].lower()
    rec = base_record()
    rec.update({
        "property_id": prop["id"],
        "customer_id": prop["customer_id"],
        "incident_type": body["incident_type"],
        "priority": body["priority"],
        "sla_minutes": market[sla_field],
        "reported_at": iso_now(),
        "dispatched_at": None,
        "secured_at": None,
        "work_status": "INTAKE",
        "safety_cleared": False,
        "compliance_breach": False,
        "total_planned_sheets": 0,
    })
    db.jobs[rec["id"]] = rec
    return success_obj(serialize_job(rec), 201)


@bp.route("/jobs/<jid>", methods=["GET"])
def get_job(jid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.jobs, jid, "Job")
    return success_obj(serialize_job(rec))


@bp.route("/jobs", methods=["GET"])
def list_jobs():
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    limit, offset = paginate_args()
    items = list(db.jobs.values())
    pid = request.args.get("property_id")
    cid = request.args.get("customer_id")
    ws = request.args.get("work_status")
    if pid:
        items = [j for j in items if j["property_id"] == pid]
    if cid:
        items = [j for j in items if j["customer_id"] == cid]
    if ws:
        items = [j for j in items if j["work_status"] == ws]
    items.sort(key=lambda j: j["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_job(j) for j in page], total, limit, offset)


@bp.route("/jobs/<jid>/dispatch", methods=["POST"])
def dispatch_job(jid):
    require_role("Dispatcher")
    job = get_or_404(db.jobs, jid, "Job")
    body = get_body()
    # state gate first
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    if job["work_status"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "Job must be INTAKE to dispatch")
    sub = None
    sub_id = body.get("subcontractor_id")
    if sub_id is not None:
        sub = db.subcontractors.get(sub_id)
        if sub is None:
            raise err("ERR_NOT_FOUND", "Subcontractor not found")
        if sub["status"] != "ACTIVE":
            raise err("ERR_SUBCONTRACTOR_SUSPENDED", "Subcontractor is suspended")
        prop = db.properties.get(job["property_id"])
        cov = None
        for c in db.coverages.values():
            if c["subcontractor_id"] == sub["id"] and c["market_id"] == prop["market_id"]:
                cov = c
                break
        if cov is None or cov["status"] != "ACTIVE":
            raise err("ERR_MARKET_MISMATCH", "Subcontractor has no coverage in job market")
        active_count = dispatch_svc.active_assignment_count(sub["id"])
        if active_count >= cov["max_concurrent_jobs"]:
            raise err("ERR_CAPACITY_FULL", "Subcontractor at max concurrent jobs")
    else:
        pair = dispatch_svc.dispatch_selection(job, exclude_prior_offerees=False)
        if pair is None:
            raise err("ERR_NO_COVERAGE", "No eligible subcontractor in this market")
        sub, _ = pair
    assignment = dispatch_svc.create_offer(job, sub)
    job["work_status"] = "DISPATCHED"
    job["dispatched_at"] = iso_now()
    touch(job)
    return success_obj(serialize_assignment(assignment), 201)


@bp.route("/jobs/<jid>/check-in", methods=["POST"])
def check_in_job(jid):
    user_id, _ = require_role("Subcontractor")
    job = get_or_404(db.jobs, jid, "Job")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    # assignee check: caller must equal subcontractor_id of job's ACCEPTED assignment
    accepted = None
    for a in db.assignments.values():
        if a["job_id"] == job["id"] and a["status"] == "ACCEPTED":
            accepted = a
            break
    if accepted is None or accepted["subcontractor_id"] != user_id:
        raise err("ERR_NOT_ASSIGNEE", "Caller is not the assignee")
    if job["work_status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Job must be DISPATCHED for check-in")
    now_dt = clock.now()
    accepted["status"] = "ARRIVED"
    accepted["arrived_at"] = format_ts(now_dt)
    dispatched_at_str = job.get("dispatched_at")
    if dispatched_at_str:
        from db import parse_ts
        dispatched_dt = parse_ts(dispatched_at_str)
        elapsed_seconds = (now_dt - dispatched_dt).total_seconds()
        response_minutes = int(elapsed_seconds // 60)
        accepted["response_minutes"] = response_minutes
        accepted["sla_breach"] = response_minutes > job["sla_minutes"]
    touch(accepted)
    job["work_status"] = "ON_SITE"
    touch(job)
    return success_obj(serialize_assignment(accepted))


@bp.route("/jobs/<jid>/complete-securing", methods=["POST"])
def complete_securing(jid):
    user_id, _ = require_role("Subcontractor")
    job = get_or_404(db.jobs, jid, "Job")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    # The assignee is the subcontractor of the job's currently accepted
    # assignment — which may already be COMPLETED on the §3.6 re-secure path.
    assignee = find_current_assignment(job["id"])
    if assignee is None or assignee["subcontractor_id"] != user_id:
        raise err("ERR_NOT_ASSIGNEE", "Caller is not the assignee")
    if job["work_status"] != "ON_SITE":
        raise err("ERR_INVALID_STATE", "Job must be ON_SITE to complete securing")
    if not job.get("safety_cleared"):
        raise err("ERR_HAZARD_NOT_MITIGATED", "Safety not cleared")
    items = find_job_scope_items(job["id"])
    non_void = [s for s in items if s["status"] != "VOIDED"]
    if len(non_void) == 0:
        raise err("ERR_SCOPE_EMPTY", "No non-void scope items")
    for s in non_void:
        if s["status"] != "INSTALLED":
            raise err("ERR_SCOPE_ITEMS_PENDING", "Scope item still PLANNED")
    # transitions
    job["work_status"] = "SECURED"
    job["secured_at"] = iso_now()
    touch(job)
    if assignee["status"] == "ARRIVED":
        assignee["status"] = "COMPLETED"
        touch(assignee)
        sub = db.subcontractors.get(assignee["subcontractor_id"])
        if sub is not None:
            if assignee.get("sla_breach"):
                sub["breached_job_count"] = sub.get("breached_job_count", 0) + 1
            else:
                sub["completed_job_count"] = sub.get("completed_job_count", 0) + 1
            touch(sub)
        recompute_active_assignment_count(assignee["subcontractor_id"])
    # resume PAUSED services
    for s in find_job_services(job["id"]):
        if s["status"] == "PAUSED":
            s["status"] = "ACTIVE"
            touch(s)
    return success_obj(serialize_job(job))


@bp.route("/jobs/<jid>/verify-repair", methods=["POST"])
def verify_repair(jid):
    user_id, _ = require_role("Customer")
    job = get_or_404(db.jobs, jid, "Job")
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = check_enum(body["outcome"], {"VERIFIED", "REJECTED"}, "outcome")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    if job["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Caller does not own this job")
    if outcome == "VERIFIED":
        if job["work_status"] != "SECURED":
            raise err("ERR_INVALID_STATE", "Job must be SECURED to verify")
        job["work_status"] = "READY_FOR_REMOVAL"
    else:  # REJECTED
        if job["work_status"] != "READY_FOR_REMOVAL":
            raise err("ERR_INVALID_STATE", "Job must be READY_FOR_REMOVAL to reject")
        job["work_status"] = "SECURED"
    touch(job)
    return success_obj(serialize_job(job))


@bp.route("/jobs/<jid>/record-removal", methods=["POST"])
def record_removal(jid):
    user_id, _ = require_role("Subcontractor")
    job = get_or_404(db.jobs, jid, "Job")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    # assignee check: the subcontractor_id of the job's current/last accepted-arrived-completed assignment
    assignee = None
    for a in db.assignments.values():
        if a["job_id"] == job["id"] and a["status"] in ("ACCEPTED", "ARRIVED", "COMPLETED"):
            if assignee is None or a["offer_seq"] > assignee["offer_seq"]:
                assignee = a
    if assignee is None or assignee["subcontractor_id"] != user_id:
        raise err("ERR_NOT_ASSIGNEE", "Caller is not the assignee")
    if job["work_status"] != "READY_FOR_REMOVAL":
        raise err("ERR_INVALID_STATE", "Job must be READY_FOR_REMOVAL")
    # services must all be deactivated
    for s in find_job_services(job["id"]):
        if s["status"] in ("ACTIVE", "PAUSED"):
            raise err("ERR_SERVICES_STILL_ACTIVE", "Temporary service still active")
    job["work_status"] = "REMOVED"
    touch(job)
    return success_obj(serialize_job(job))


@bp.route("/jobs/<jid>/close", methods=["POST"])
def close_job(jid):
    require_role("Dispatcher")
    job = get_or_404(db.jobs, jid, "Job")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    if job["work_status"] != "REMOVED":
        raise err("ERR_INVALID_STATE", "Job must be REMOVED to close")
    invoices = [i for i in db.invoices.values() if i["job_id"] == job["id"]]
    has_final_paid = any(i["variant"] == "FINAL" and i["status"] == "PAID" for i in invoices)
    all_paid = all(i["status"] == "PAID" for i in invoices) if invoices else False
    if not has_final_paid or not all_paid:
        raise err("ERR_INVOICES_UNPAID", "Job requires a PAID FINAL invoice and no unpaid invoices")
    job["work_status"] = "CLOSED"
    touch(job)
    return success_obj(serialize_job(job))
