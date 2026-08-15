"""Contractor endpoints (PRD §3.1)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import new_record, sort_key, touch
from errors import raise_err, ERR_INVALID_REQUEST, ERR_CONTRACTOR_NOT_FOUND
from middleware import ROLES, atomic, require_roles
from response import success_list, success_object
from serializers import ser_contractor
from util import get_json_body, paginate, require_int, require_string

bp = Blueprint("contractors", __name__, url_prefix="/distributor")


@bp.post("/contractors")
@require_roles("CreditManager")
@atomic
def create_contractor():
    body = get_json_body()
    name = require_string(body, "name")
    credit_limit = require_int(body, "credit_limit_cents")
    if credit_limit <= 0:
        raise_err(ERR_INVALID_REQUEST, "credit_limit_cents must be > 0")
    contractor = new_record(
        {
            "name": name,
            "credit_limit_cents": credit_limit,
            "invoiced_balance_cents": 0,
            "committed_balance_cents": 0,
        }
    )
    db.contractors[contractor["id"]] = contractor
    return success_object(ser_contractor(contractor), 201)


@bp.get("/contractors")
@require_roles(*ROLES)
def list_contractors():
    items = sorted(db.contractors.values(), key=sort_key)
    page, limit, offset, total = paginate(items)
    return success_list([ser_contractor(c) for c in page], limit, offset, total)


@bp.get("/contractors/<contractor_id>")
@require_roles(*ROLES)
def get_contractor(contractor_id: str):
    contractor = db.contractors.get(contractor_id)
    if contractor is None:
        raise_err(ERR_CONTRACTOR_NOT_FOUND, "No contractor with the given id")
    return success_object(ser_contractor(contractor))


@bp.post("/contractors/<contractor_id>/payments")
@require_roles("CreditManager")
@atomic
def record_payment(contractor_id: str):
    body = get_json_body()
    amount = require_int(body, "amount_cents")
    if amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be > 0")
    contractor = db.contractors.get(contractor_id)
    if contractor is None:
        raise_err(ERR_CONTRACTOR_NOT_FOUND, "No contractor with the given id")
    contractor["invoiced_balance_cents"] -= amount
    touch(contractor)
    # Mirror of credit contagion: back at or below the limit releases holds.
    if contractor["invoiced_balance_cents"] <= contractor["credit_limit_cents"]:
        for job in db.job_accounts.values():
            if job["contractor_id"] == contractor["id"] and job["status"] == "CREDIT_HOLD":
                job["status"] = "OPEN"
                touch(job)
    return success_object(ser_contractor(contractor), 201)
