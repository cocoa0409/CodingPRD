"""Permit case endpoints."""
from datetime import timedelta
from flask import Blueprint, request
import db
from db import clock, format_ts, parse_ts
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import base_record, touch, get_or_404, serialize_permit_case

bp = Blueprint("permits", __name__)


def lazily_expire_notification(case):
    """If clock is past deadline_at and case still PENDING NOTIFICATION -> EXPIRED."""
    if case["kind"] != "NOTIFICATION":
        return
    if case["status"] != "PENDING":
        return
    if case.get("deadline_at") is None:
        return
    now_dt = clock.now()
    deadline = parse_ts(case["deadline_at"])
    if now_dt > deadline:
        case["status"] = "EXPIRED"
        touch(case)
        job = db.jobs.get(case["job_id"])
        if job is not None:
            job["compliance_breach"] = True
            touch(job)


@bp.route("/jobs/<jid>/permit-cases", methods=["POST"])
def create_permit_case(jid):
    require_role("Dispatcher")
    job = get_or_404(db.jobs, jid, "Job")
    body = get_body()
    require_fields(body, ["kind"])
    kind = check_enum(body["kind"], {"PERMIT", "NOTIFICATION"}, "kind")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    if kind == "NOTIFICATION":
        if job["work_status"] != "SECURED":
            raise err("ERR_INVALID_STATE", "NOTIFICATION requires job SECURED")
    # one open case per kind per job: open = PENDING, plus FILED for PERMIT
    for p in db.permit_cases.values():
        if p["job_id"] == job["id"] and p["kind"] == kind:
            if p["status"] == "PENDING":
                raise err("ERR_PERMIT_CASE_OPEN", "Open case of this kind exists")
            if kind == "PERMIT" and p["status"] == "FILED":
                raise err("ERR_PERMIT_CASE_OPEN", "Open case of this kind exists")
    prop = db.properties.get(job["property_id"])
    market = db.markets.get(prop["market_id"])
    deadline_at = None
    if kind == "NOTIFICATION":
        secured_dt = parse_ts(job["secured_at"])
        deadline_at = format_ts(secured_dt + timedelta(hours=market["notification_deadline_hours"]))
    rec = base_record()
    rec.update({
        "job_id": job["id"],
        "kind": kind,
        "status": "PENDING",
        "deadline_at": deadline_at,
        "filed_at": None,
        "confirmation_number": None,
        "is_late": False,
        "penalty_billed": False,
        "decision_note": None,
    })
    db.permit_cases[rec["id"]] = rec
    return success_obj(serialize_permit_case(rec), 201)


@bp.route("/jobs/<jid>/permit-cases", methods=["GET"])
def list_permit_cases(jid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    get_or_404(db.jobs, jid, "Job")
    limit, offset = paginate_args()
    items = [p for p in db.permit_cases.values() if p["job_id"] == jid]
    for p in items:
        lazily_expire_notification(p)
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_permit_case(p) for p in page], total, limit, offset)


@bp.route("/permit-cases/<pid>/file", methods=["POST"])
def file_permit_case(pid):
    require_role("Dispatcher")
    rec = get_or_404(db.permit_cases, pid, "PermitCase")
    body = get_body()
    require_fields(body, ["confirmation_number"])
    if rec["status"] in ("FILED", "APPROVED", "REJECTED", "EXPIRED"):
        raise err("ERR_ALREADY_TERMINAL", "PermitCase is terminal")
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "PermitCase must be PENDING")
    now_dt = clock.now()
    rec["filed_at"] = format_ts(now_dt)
    rec["confirmation_number"] = body["confirmation_number"]
    is_late = False
    if rec["kind"] == "NOTIFICATION" and rec.get("deadline_at"):
        deadline = parse_ts(rec["deadline_at"])
        if now_dt > deadline:
            is_late = True
    rec["is_late"] = is_late
    rec["status"] = "FILED"
    touch(rec)
    if is_late:
        job = db.jobs.get(rec["job_id"])
        if job is not None:
            job["compliance_breach"] = False
            touch(job)
    return success_obj(serialize_permit_case(rec))


@bp.route("/permit-cases/<pid>/record-decision", methods=["POST"])
def record_decision(pid):
    require_role("PlatformAdmin")
    rec = get_or_404(db.permit_cases, pid, "PermitCase")
    body = get_body()
    require_fields(body, ["decision"])
    decision = check_enum(body["decision"], {"APPROVED", "REJECTED"}, "decision")
    if rec["kind"] != "PERMIT":
        raise err("ERR_INVALID_STATE", "Decisions only for PERMIT cases")
    if rec["status"] in ("APPROVED", "REJECTED", "EXPIRED"):
        raise err("ERR_ALREADY_TERMINAL", "PermitCase is terminal")
    if rec["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "PermitCase must be FILED")
    rec["status"] = decision
    if "decision_note" in body:
        rec["decision_note"] = body["decision_note"]
    touch(rec)
    return success_obj(serialize_permit_case(rec))
