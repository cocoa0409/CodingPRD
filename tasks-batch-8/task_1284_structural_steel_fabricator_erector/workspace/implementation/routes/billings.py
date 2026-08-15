"""Progress billing endpoints: create (OCC + snapshot) / submit / approve /
pay / void."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_DUPLICATE_BILLING_PERIOD,
    ERR_INVALID_STATE,
    ERR_JOB_NOT_BILLABLE,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
)
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_int, req_str, require_role
from . import list_response

bp = Blueprint("billings", __name__)

ADMIN = {"FABRICATOR_ADMIN"}
GC_PM = {"GC_PM"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(b):
    return public(b)


def get_billing_or_404(bid):
    b = store.billings.get(bid)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Progress billing not found.")
    return b


@bp.post("/progress-billings")
def create_billing():
    uid, role = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    # Rung 3: body FK existence
    job_id = body.get("job_id")
    if job_id is not None and job_id not in store.jobs:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    # Rung 4: shape
    job_id = req_str(body, "job_id")
    period_label = req_str(body, "period_label")
    expected_job_version = req_int(body, "expected_job_version")
    job = store.jobs[job_id]
    # Rung 5: OCC on the job version
    if expected_job_version != job["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_job_version does not match current version.")
    # Rung 8: job must be billable
    if job["status"] not in ("FABRICATING", "ERECTING", "COMPLETE"):
        raise ApiError(
            ERR_JOB_NOT_BILLABLE,
            409,
            "Billing creation requires job FABRICATING, ERECTING, or COMPLETE.",
        )
    # Rung 9: period_label unique per job among non-VOIDED billings
    if any(
        b
        for b in store.billings.values()
        if b["job_id"] == job_id and b["period_label"] == period_label and b["status"] != "VOIDED"
    ):
        raise ApiError(
            ERR_DUPLICATE_BILLING_PERIOD, 409, "period_label already used by a non-VOIDED billing."
        )
    snapshot = domain.compute_billing_snapshot(job)
    b = new_record()
    b.update(
        {
            "job_id": job_id,
            "period_label": period_label,
            "pct_complete_snapshot": snapshot["pct_complete_snapshot"],
            "earned_cum_cents": snapshot["earned_cum_cents"],
            "retainage_cum_cents": snapshot["retainage_cum_cents"],
            "retainage_booked_cents": snapshot["retainage_booked_cents"],
            "net_due_cents": snapshot["net_due_cents"],
            "status": "DRAFT",
            "submitted_by_user_id": None,
        }
    )
    store.billings[b["id"]] = b
    touch(job)  # billing creation increments the job's version by 1
    return ok_object(view(b), 201)


@bp.get("/progress-billings")
def list_billings():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.billings.values(), view, [("job_id", "job_id"), ("status", "status")]
    )


@bp.get("/progress-billings/<bid>")
def get_billing(bid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_billing_or_404(bid)))


@bp.post("/progress-billings/<bid>/submit")
def submit_billing(bid):
    uid, role = authenticate()
    require_role(role, ADMIN)
    b = get_billing_or_404(bid)
    if b["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Billing must be DRAFT to submit.")
    b["status"] = "SUBMITTED"
    b["submitted_by_user_id"] = uid
    touch(b)
    return ok_object(view(b))


@bp.post("/progress-billings/<bid>/approve")
def approve_billing(bid):
    uid, role = authenticate()
    require_role(role, GC_PM)
    b = get_billing_or_404(bid)
    if b["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Billing must be SUBMITTED to approve.")
    b["status"] = "APPROVED"
    touch(b)
    # Booking lands on the job aggregates (derived live); job version increments
    touch(store.jobs[b["job_id"]])
    return ok_object(view(b))


@bp.post("/progress-billings/<bid>/pay")
def pay_billing(bid):
    uid, role = authenticate()
    require_role(role, GC_PM)
    b = get_billing_or_404(bid)
    if b["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Billing must be APPROVED to pay.")
    b["status"] = "PAID"
    touch(b)
    domain.compound_completion_check(store.jobs[b["job_id"]])
    return ok_object(view(b))


@bp.post("/progress-billings/<bid>/void")
def void_billing(bid):
    uid, role = authenticate()
    require_role(role, GC_PM)
    b = get_billing_or_404(bid)
    if b["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Billing must be APPROVED to void.")
    b["status"] = "VOIDED"
    touch(b)
    job = store.jobs[b["job_id"]]
    touch(job)  # exact reversal of the booking (aggregates derived live)
    domain.compound_completion_check(job)
    return ok_object(view(b))
