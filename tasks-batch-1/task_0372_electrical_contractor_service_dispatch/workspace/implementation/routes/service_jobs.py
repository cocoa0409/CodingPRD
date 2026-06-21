"""ServiceJob endpoints (PRD §3.3, §3.5, §3.7, §3.8, §3.9).

Lifecycle: DRAFT -> QUOTED -> SCHEDULED -> IN_PROGRESS -> COMPLETED ->
INVOICED -> CLOSED, plus WARRANTY (reopened) and CANCELLED.
"""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_enum,
                     require_fields, require_number, serialize, serialize_list,
                     sort_by_created)
from middleware import get_identity, require_roles
from services import domain
from services.billing import compute_invoice

bp = Blueprint("service_jobs", __name__)


def _owns(job, user_id, role):
    """Customer ownership check on a job (PRD §2.1)."""
    return not (role == "Customer" and job["customer_id"] != user_id)


def _latest_active_dispatch(job_id):
    """Most-recent non-CANCELLED dispatch for the job (by created_at)."""
    cands = [
        d for d in db.dispatches.values()
        if d["job_id"] == job_id and d["status"] != "CANCELLED"
    ]
    if not cands:
        return None
    cands.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return cands[-1]


def _job_technician(job_id):
    """The technician on the latest non-CANCELLED dispatch for the job, or None."""
    d = _latest_active_dispatch(job_id)
    if d is None:
        return None
    return db.technicians.get(d["technician_id"])


@bp.post("/v1/service-jobs")
def create_job():
    user_id, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    body = get_json_body()
    require_fields(body, ["customer_id", "scope", "job_class"])

    customer = db.customers.get(body["customer_id"])
    if customer is None:
        raise err("ERR_NOT_FOUND", "Customer not found")

    # Ownership: a Customer may only open a job for themselves.
    if role == "Customer" and customer["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customers may only open jobs for themselves")

    require_enum(body["scope"], domain.JOB_SCOPES, "scope")
    require_enum(body["job_class"], domain.JOB_CLASSES, "job_class")
    priority = body.get("priority", "STANDARD")
    if priority is None:
        priority = "STANDARD"
    require_enum(priority, domain.JOB_PRIORITIES, "priority")

    active_membership = domain.active_membership_for_customer(db, customer["id"])

    record = {
        "customer_id": customer["id"],
        "scope": body["scope"],
        "job_class": body["job_class"],
        "priority": priority,
        "requires_permit": body["scope"] in domain.PERMIT_SCOPES,
        "membership_id": active_membership["id"] if active_membership else None,
        "pricing_mode": None,
        "status": "DRAFT",
        "total_due_cents": 0,
        "warranty_until": None,
        # actual_labor_hours is captured at completion (internal until then).
        "actual_labor_hours": None,
    }
    db.stamp_new(record)
    db.service_jobs[record["id"]] = record
    return response.object_response(serialize(record), 201)


@bp.get("/v1/service-jobs/<job_id>")
def get_job(job_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer", "Technician"})
    record = db.service_jobs.get(job_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Service job not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/service-jobs")
def list_jobs():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer", "Technician"})
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")

    items = list(db.service_jobs.values())
    if customer_id is not None:
        items = [j for j in items if j["customer_id"] == customer_id]
    if membership_id is not None:
        items = [j for j in items if j["membership_id"] == membership_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)


@bp.post("/v1/service-jobs/<job_id>/complete")
def complete_job(job_id):
    user_id, role = get_identity()
    require_roles(role, {"Technician"})
    job = db.service_jobs.get(job_id)
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")

    body = get_json_body()
    actual_labor_hours = body.get("actual_labor_hours")
    if actual_labor_hours is not None:
        require_number(actual_labor_hours, "actual_labor_hours")
        if actual_labor_hours < 0:
            raise err("ERR_INVALID_REQUEST", "actual_labor_hours must be >= 0")

    # State: only from IN_PROGRESS.
    if job["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Job must be IN_PROGRESS to complete")

    # Permit gating.
    if job["requires_permit"]:
        passed = any(
            p["job_id"] == job["id"] and p["status"] == "PASSED"
            for p in db.permits.values()
        )
        if not passed:
            raise err("ERR_PERMIT_NOT_PASSED", "Job requires a PASSED permit before completion")

    # Capture realized hours for the eventual invoice.
    if actual_labor_hours is not None:
        job["actual_labor_hours"] = actual_labor_hours

    # Side effect: active dispatch (ON_SITE) -> CLEARED.
    for d in db.dispatches.values():
        if d["job_id"] == job["id"] and d["status"] == "ON_SITE":
            d["status"] = "CLEARED"
            db.touch(d)

    job["status"] = "COMPLETED"
    db.touch(job)
    return response.object_response(serialize(job), 200)


@bp.post("/v1/service-jobs/<job_id>/invoice")
def invoice_job(job_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    job = db.service_jobs.get(job_id)
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")

    # Invoicing is permitted only when the job is COMPLETED (PRD §3.7). A job that
    # has re-entered the work loop via a warranty callback returns to COMPLETED and
    # can be re-invoiced (PRD §3.8), so the single-invoice guard only blocks a
    # re-invoice of a job that is NOT back in COMPLETED — i.e. an already-INVOICED
    # job, which surfaces ERR_ALREADY_INVOICED rather than a bare state error.
    if job["status"] != "COMPLETED":
        existing = [iv for iv in db.invoices.values() if iv["job_id"] == job["id"]]
        if existing:
            raise err("ERR_ALREADY_INVOICED", "Job already has an invoice")
        raise err("ERR_INVALID_STATE", "Job must be COMPLETED to invoice")

    # The accepted estimate drives the labor subtotal.
    accepted = None
    for e in db.estimates.values():
        if e["job_id"] == job["id"] and e["status"] == "ACCEPTED":
            accepted = e
            break

    technician = _job_technician(job["id"])
    components = compute_invoice(job, accepted, technician)

    invoice = {"job_id": job["id"]}
    invoice.update(components)
    db.stamp_new(invoice)
    db.invoices[invoice["id"]] = invoice

    # Job side effects.
    job["total_due_cents"] = invoice["total_cents"]
    warranty_end = clock.now() + timedelta(days=domain.WARRANTY_DAYS)
    job["warranty_until"] = clock.format_iso(warranty_end)
    job["status"] = "INVOICED"
    db.touch(job)
    return response.object_response(serialize(job), 200)


@bp.post("/v1/service-jobs/<job_id>/close")
def close_job(job_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    job = db.service_jobs.get(job_id)
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")

    # State: only from INVOICED.
    if job["status"] != "INVOICED":
        raise err("ERR_INVALID_STATE", "Job must be INVOICED to close")

    # Cannot close while an OPEN callback exists.
    open_cb = any(
        c["job_id"] == job["id"] and c["status"] == "OPEN"
        for c in db.callbacks.values()
    )
    if open_cb:
        raise err("ERR_OPEN_CALLBACK", "Cannot close a job with an open callback")

    job["status"] = "CLOSED"
    db.touch(job)
    return response.object_response(serialize(job), 200)


@bp.post("/v1/service-jobs/<job_id>/cancel")
def cancel_job(job_id):
    user_id, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    job = db.service_jobs.get(job_id)
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")

    # Ownership: Customer may cancel only own job.
    if not _owns(job, user_id, role):
        raise err("ERR_NOT_RESOURCE_OWNER", "Customers may only cancel their own job")

    # State: cancellable from DRAFT, QUOTED, or SCHEDULED.
    if job["status"] not in ("DRAFT", "QUOTED", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Job cannot be cancelled from its current state")

    # Cascade: supersede open estimates (SENT/DRAFT).
    for e in db.estimates.values():
        if e["job_id"] == job["id"] and e["status"] in ("SENT", "DRAFT"):
            e["status"] = "SUPERSEDED"
            db.touch(e)

    # Cascade: if SCHEDULED, cancel the active dispatch (frees the window).
    if job["status"] == "SCHEDULED":
        for d in db.dispatches.values():
            if d["job_id"] == job["id"] and d["status"] in ("ASSIGNED", "EN_ROUTE", "ON_SITE"):
                d["status"] = "CANCELLED"
                db.touch(d)

    job["status"] = "CANCELLED"
    db.touch(job)
    return response.object_response(serialize(job), 200)
