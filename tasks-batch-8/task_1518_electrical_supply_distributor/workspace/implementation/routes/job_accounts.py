"""JobAccount endpoints (PRD §3.3)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from db import new_record, sort_key, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_JOB_ACCOUNT_NOT_FOUND,
    ERR_JOB_NOT_OPEN,
    ERR_JOB_HAS_OPEN_RELEASES,
)
from middleware import ROLES, atomic, require_roles
from response import success_list, success_object
from serializers import ser_job_account
from util import (
    get_json_body,
    optional_bool,
    optional_number,
    paginate,
    require_date,
    require_string,
)

bp = Blueprint("job_accounts", __name__, url_prefix="/distributor")

# Release statuses that block job-account closure (PRD §3.3).
ACTIVE_RELEASE_STATUSES = (
    "REQUESTED",
    "CREDIT_APPROVED",
    "PARTIALLY_ALLOCATED",
    "ALLOCATED",
    "SCHEDULED",
    "DELIVERED",
)


def _query_arg(name: str):
    value = request.args.get(name)
    return value if value not in (None, "") else None


@bp.post("/job-accounts")
@require_roles("SalesRep")
@atomic
def create_job_account():
    body = get_json_body()
    contractor_id = require_string(body, "contractor_id")
    job_name = require_string(body, "job_name")
    jobsite_address = require_string(body, "jobsite_address")
    pricing_mode = require_string(body, "pricing_mode")
    if pricing_mode not in ("FIRM_PRICE", "ESCALATION"):
        raise_err(ERR_INVALID_REQUEST, "pricing_mode must be FIRM_PRICE or ESCALATION")
    cap = optional_number(body, "escalation_cap_pct")
    if cap is not None and cap < 0:
        raise_err(ERR_INVALID_REQUEST, "escalation_cap_pct must be >= 0")
    if pricing_mode == "FIRM_PRICE" and cap is not None:
        raise_err(ERR_INVALID_REQUEST, "escalation_cap_pct is forbidden when pricing_mode is FIRM_PRICE")
    lien_waiver_required = optional_bool(body, "lien_waiver_required", False)

    contractor = db.contractors.get(contractor_id)
    if contractor is None:
        raise_err(ERR_CONTRACTOR_NOT_FOUND, "No contractor with the given id")

    job = new_record(
        {
            "contractor_id": contractor_id,
            "job_name": job_name,
            "jobsite_address": jobsite_address,
            "pricing_mode": pricing_mode,
            "escalation_cap_pct": cap,
            "lien_waiver_required": lien_waiver_required,
            "lien_waiver_expires_on": None,
            "status": "OPEN",
        }
    )
    db.job_accounts[job["id"]] = job
    return success_object(ser_job_account(job), 201)


@bp.get("/job-accounts")
@require_roles(*ROLES)
def list_job_accounts():
    contractor_id = _query_arg("contractor_id")
    status = _query_arg("status")
    items = sorted(db.job_accounts.values(), key=sort_key)
    if contractor_id is not None:
        items = [j for j in items if j["contractor_id"] == contractor_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([ser_job_account(j) for j in page], limit, offset, total)


@bp.get("/job-accounts/<job_id>")
@require_roles(*ROLES)
def get_job_account(job_id: str):
    job = db.job_accounts.get(job_id)
    if job is None:
        raise_err(ERR_JOB_ACCOUNT_NOT_FOUND, "No job account with the given id")
    return success_object(ser_job_account(job))


@bp.post("/job-accounts/<job_id>/close")
@require_roles("BranchManager")
@atomic
def close_job_account(job_id: str):
    job = db.job_accounts.get(job_id)
    if job is None:
        raise_err(ERR_JOB_ACCOUNT_NOT_FOUND, "No job account with the given id")
    if job["status"] != "OPEN":
        raise_err(ERR_JOB_NOT_OPEN, "Close requires the job account in OPEN")
    has_open_quote = any(
        q["job_account_id"] == job["id"] and q["status"] in ("DRAFT", "SUBMITTED")
        for q in db.quotes.values()
    )
    has_open_release = any(
        r["job_account_id"] == job["id"] and r["status"] in ACTIVE_RELEASE_STATUSES
        for r in db.releases.values()
    )
    if has_open_quote or has_open_release:
        raise_err(ERR_JOB_HAS_OPEN_RELEASES, "Close blocked: non-terminal quotes or releases exist on the job account")
    job["status"] = "CLOSED"
    touch(job)
    return success_object(ser_job_account(job))


@bp.post("/job-accounts/<job_id>/lien-waivers")
@require_roles("CreditManager")
@atomic
def file_lien_waiver(job_id: str):
    body = get_json_body()
    expires_on = require_date(body, "expires_on")
    job = db.job_accounts.get(job_id)
    if job is None:
        raise_err(ERR_JOB_ACCOUNT_NOT_FOUND, "No job account with the given id")
    job["lien_waiver_expires_on"] = expires_on
    touch(job)
    return success_object(ser_job_account(job), 201)
