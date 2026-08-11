"""Job account endpoints."""
from flask import Blueprint, request

import db
import services as svc
from authz import require_roles, owner_or_forbid, scoped_account_filter
from envelope import ok_object, ok_list
from errors import raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE
from serializers import ser_job, sorted_rows
from validate import body_json, req_str, opt_int, pagination_params

bp = Blueprint("jobs", __name__)

CREATORS = ["StoreAssociate", "Contractor"]
READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "Contractor"]
LIFECYCLE = ["StoreManager", "Contractor"]


def _get_job(job_id):
    j = db.job_accounts.get(job_id)
    if j is None:
        raise_err(ERR_NOT_FOUND, "job account %s not found" % job_id)
    return j


@bp.post("/job-accounts")
def create_job():
    uid, role = require_roles(CREATORS)
    data = body_json()
    # Ownership (stage 3) precedes body-reference resolution (stage 5).
    if role == "Contractor":
        requested = data.get("contractor_account_id")
        if isinstance(requested, str):
            owner_or_forbid(uid, role, requested)
    contractor_account_id = data.get("contractor_account_id")
    jurisdiction_id = data.get("jurisdiction_id")
    if isinstance(contractor_account_id, str) and contractor_account_id not in db.contractor_accounts:
        raise_err(ERR_REFERENCE_NOT_FOUND,
                  "contractor_account_id %s not found" % contractor_account_id)
    if isinstance(jurisdiction_id, str) and jurisdiction_id not in db.jurisdictions:
        raise_err(ERR_REFERENCE_NOT_FOUND, "jurisdiction_id %s not found" % jurisdiction_id)
    contractor_account_id = req_str(data, "contractor_account_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    job_name = req_str(data, "job_name")
    site_address = req_str(data, "site_address")
    budget_cap = opt_int(data, "budget_cap_cents", default=None, minimum=0, nullable=True)
    job = svc.stamp_new({
        "contractor_account_id": contractor_account_id,
        "jurisdiction_id": jurisdiction_id,
        "job_name": job_name,
        "site_address": site_address,
        "budget_cap_cents": budget_cap,
        "status": "OPEN",
    })
    db.job_accounts[job["id"]] = job
    return ok_object(ser_job(job), 201)


@bp.get("/job-accounts/<job_id>")
def get_job(job_id):
    uid, role = require_roles(READERS)
    job = _get_job(job_id)
    owner_or_forbid(uid, role, job["contractor_account_id"])
    return ok_object(ser_job(job))


@bp.get("/job-accounts")
def list_jobs():
    uid, role = require_roles(READERS)
    limit, offset = pagination_params()
    contractor_filter = scoped_account_filter(uid, role, request.args.get("contractor_account_id"))
    jurisdiction_filter = request.args.get("jurisdiction_id")
    rows = list(db.job_accounts.values())
    if contractor_filter is not None:
        rows = [j for j in rows if j["contractor_account_id"] == contractor_filter]
    if jurisdiction_filter is not None:
        rows = [j for j in rows if j["jurisdiction_id"] == jurisdiction_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser_job(j) for j in page], total, limit, offset)


def _job_transition(job_id, allowed_from, target):
    uid, role = require_roles(LIFECYCLE)
    job = _get_job(job_id)
    owner_or_forbid(uid, role, job["contractor_account_id"])
    if job["status"] not in allowed_from:
        raise_err(ERR_INVALID_STATE, "job is not in %s" % "/".join(sorted(allowed_from)))
    job["status"] = target
    svc.bump(job)
    return ok_object(ser_job(job))


@bp.post("/job-accounts/<job_id>/place-on-hold")
def place_on_hold(job_id):
    return _job_transition(job_id, {"OPEN"}, "ON_HOLD")


@bp.post("/job-accounts/<job_id>/resume")
def resume(job_id):
    return _job_transition(job_id, {"ON_HOLD"}, "OPEN")


@bp.post("/job-accounts/<job_id>/complete")
def complete(job_id):
    uid, role = require_roles(LIFECYCLE)
    job = _get_job(job_id)
    owner_or_forbid(uid, role, job["contractor_account_id"])
    if job["status"] not in {"OPEN", "ON_HOLD"}:
        raise_err(ERR_INVALID_STATE, "job is not OPEN or ON_HOLD")
    for o in db.orders.values():
        if o["job_account_id"] == job_id and o["fulfillment_status"] in {"PENDING", "OUT_FOR_DELIVERY"}:
            raise_err(ERR_INVALID_STATE, "job has open orders")
    for d in db.deliveries.values():
        if d["job_account_id"] == job_id and d["status"] in {"SCHEDULED", "EN_ROUTE"}:
            raise_err(ERR_INVALID_STATE, "job has open deliveries")
    job["status"] = "COMPLETE"
    svc.bump(job)
    return ok_object(ser_job(job))
