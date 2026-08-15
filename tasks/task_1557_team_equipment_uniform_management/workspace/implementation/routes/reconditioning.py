"""Reconditioning jobs (PRD §3.5): certification cycle with provider capacity."""
from datetime import datetime, timedelta

from flask import Blueprint, request

from db import db, clock, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_GEAR_ITEM_NOT_FOUND,
    ERR_RECONDITIONING_JOB_NOT_FOUND,
    ERR_GEAR_NOT_IN_STOCK,
    ERR_JOB_NOT_OPEN,
    ERR_VENDOR_CAPACITY_EXCEEDED,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES, render_list
from util import UTC, parse_date

bp = Blueprint("reconditioning", __name__)

JOB_STATUSES = {"OUT", "PASSED", "FAILED"}
RESULT_GRADES = {"A", "B", "C"}
RECONDITIONING_SLA_DAYS = 45
CERT_VALIDITY_DAYS = 365
MAX_CONCURRENT_JOBS_PER_PROVIDER = 2


@bp.post("/reconditioning-jobs")
@endpoint("EquipmentManager")
def create_job(ctx):
    b = ctx.body
    item_id = b.get("item_id")
    provider_name = b.get("provider_name")
    sent_on = parse_date(b.get("sent_on"))
    if not isinstance(item_id, str) or not item_id:
        raise_err(ERR_INVALID_REQUEST, "item_id is required")
    if not isinstance(provider_name, str) or not provider_name:
        raise_err(ERR_INVALID_REQUEST, "provider_name is required")
    if sent_on is None:
        raise_err(ERR_INVALID_REQUEST, "sent_on must be a YYYY-MM-DD date")
    item = db.gear_items.get(item_id)
    if item is None:
        raise_err(ERR_GEAR_ITEM_NOT_FOUND, "gear item not found")
    if item["status"] != "IN_STOCK":
        raise_err(ERR_GEAR_NOT_IN_STOCK, "job creation requires gear in IN_STOCK")
    due_back = sent_on + timedelta(days=RECONDITIONING_SLA_DAYS)
    # Half-open window overlap: new.sent < existing.due AND existing.sent < new.due
    concurrent = 0
    for job in db.jobs.values():
        if job["status"] != "OUT" or job["provider_name"] != provider_name:
            continue
        existing_sent = datetime.strptime(job["sent_on"], "%Y-%m-%d").date()
        existing_due = datetime.strptime(job["due_back_on"], "%Y-%m-%d").date()
        if sent_on < existing_due and existing_sent < due_back:
            concurrent += 1
    if concurrent >= MAX_CONCURRENT_JOBS_PER_PROVIDER:
        raise_err(ERR_VENDOR_CAPACITY_EXCEEDED, "provider capacity exceeded")
    job = stamp(
        {
            "item_id": item_id,
            "provider_name": provider_name,
            "sent_on": sent_on.isoformat(),
            "due_back_on": due_back.isoformat(),
            "status": "OUT",
            "result_grade": None,
            "result_recorded_on": None,
            "certification_valid_until": None,
        }
    )
    db.jobs[job["id"]] = job
    item["status"] = "OUT_FOR_RECONDITIONING"
    touch(item)
    return success(serialize(job), 201)


@bp.get("/reconditioning-jobs")
@endpoint(*ALL_ROLES)
def list_jobs(ctx):
    status = request.args.get("status")
    if status is not None and status not in JOB_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    return render_list(
        db.jobs,
        {
            "item_id": request.args.get("item_id"),
            "provider_name": request.args.get("provider_name"),
            "status": status,
        },
    )


@bp.get("/reconditioning-jobs/<job_id>")
@endpoint(*ALL_ROLES)
def get_job(ctx, job_id):
    job = db.jobs.get(job_id)
    if job is None:
        raise_err(ERR_RECONDITIONING_JOB_NOT_FOUND, "reconditioning job not found")
    return success(serialize(job))


@bp.post("/reconditioning-jobs/<job_id>/record-result")
@endpoint("EquipmentManager")
def record_result(ctx, job_id):
    b = ctx.body
    outcome = b.get("outcome")
    result_grade = b.get("result_grade")
    if outcome not in ("PASSED", "FAILED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be PASSED or FAILED")
    if outcome == "PASSED" and result_grade not in RESULT_GRADES:
        raise_err(ERR_INVALID_REQUEST, "PASSED requires result_grade in {A, B, C}")
    job = db.jobs.get(job_id)
    if job is None:
        raise_err(ERR_RECONDITIONING_JOB_NOT_FOUND, "reconditioning job not found")
    if job["status"] != "OUT":
        raise_err(ERR_JOB_NOT_OPEN, "record-result requires job in OUT")
    today = clock().date()
    job["result_recorded_on"] = today.isoformat()
    item = db.gear_items.get(job["item_id"])
    if outcome == "PASSED":
        cert_until = today + timedelta(days=CERT_VALIDITY_DAYS)
        job["certification_valid_until"] = cert_until.isoformat()
        job["result_grade"] = result_grade
        job["status"] = "PASSED"
        if item is not None:
            item["status"] = "IN_STOCK"
            item["condition_grade"] = result_grade
            item["certification_expires_on"] = datetime(
                cert_until.year, cert_until.month, cert_until.day, tzinfo=UTC
            )
            touch(item)
    else:
        job["status"] = "FAILED"
        job["result_grade"] = None
        if item is not None:
            item["status"] = "IN_STOCK"
            item["condition_grade"] = "F"
            touch(item)
    touch(job)
    return success(serialize(job))
