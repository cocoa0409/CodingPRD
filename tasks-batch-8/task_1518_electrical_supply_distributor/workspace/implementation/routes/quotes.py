"""Quote endpoints (PRD §3.4)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from db import clock_date, clock_month, new_record, sort_key, touch
from errors import (
    raise_err,
    ERR_JOB_ACCOUNT_NOT_FOUND,
    ERR_QUOTE_NOT_FOUND,
    ERR_QUOTE_NOT_DRAFT,
    ERR_QUOTE_NOT_SUBMITTED,
    ERR_QUOTE_EXPIRED,
    ERR_QUOTE_HAS_NO_LINES,
    ERR_JOB_NOT_OPEN,
    ERR_STALE_QUOTE_VERSION,
)
from middleware import ROLES, atomic, require_roles
from response import success_list, success_object
from serializers import ser_quote
from services.billing import latest_index_at_or_before
from util import (
    get_json_body,
    maybe_expire_quote,
    paginate,
    parse_date,
    require_date,
    require_int,
    require_string,
)

bp = Blueprint("quotes", __name__, url_prefix="/distributor")


def _query_arg(name: str):
    value = request.args.get(name)
    return value if value not in (None, "") else None


def _get_quote_or_404(quote_id: str) -> dict:
    quote = db.quotes.get(quote_id)
    if quote is None:
        raise_err(ERR_QUOTE_NOT_FOUND, "No quote with the given id")
    return quote


@bp.post("/quotes")
@require_roles("SalesRep")
@atomic
def create_quote():
    body = get_json_body()
    job_account_id = require_string(body, "job_account_id")
    valid_until = require_date(body, "valid_until")
    job = db.job_accounts.get(job_account_id)
    if job is None:
        raise_err(ERR_JOB_ACCOUNT_NOT_FOUND, "No job account with the given id")
    quote = new_record(
        {
            "job_account_id": job_account_id,
            "valid_until": valid_until,
            "revision_no": 1,
            "status": "DRAFT",
            "award_month": None,
            "award_index_value": None,
        }
    )
    db.quotes[quote["id"]] = quote
    return success_object(ser_quote(quote), 201)


@bp.get("/quotes")
@require_roles(*ROLES)
def list_quotes():
    # Lazy expiry applies on any read of a DRAFT/SUBMITTED quote.
    for quote in db.quotes.values():
        maybe_expire_quote(quote)
    job_account_id = _query_arg("job_account_id")
    status = _query_arg("status")
    items = sorted(db.quotes.values(), key=sort_key)
    if job_account_id is not None:
        items = [q for q in items if q["job_account_id"] == job_account_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([ser_quote(q) for q in page], limit, offset, total)


@bp.get("/quotes/<quote_id>")
@require_roles(*ROLES)
def get_quote(quote_id: str):
    quote = _get_quote_or_404(quote_id)
    maybe_expire_quote(quote)
    return success_object(ser_quote(quote))


@bp.post("/quotes/<quote_id>/submit")
@require_roles("SalesRep")
@atomic
def submit_quote(quote_id: str):
    quote = _get_quote_or_404(quote_id)
    if quote["status"] != "DRAFT":
        raise_err(ERR_QUOTE_NOT_DRAFT, "Submit requires the quote in DRAFT")
    job = db.job_accounts[quote["job_account_id"]]
    if job["status"] != "OPEN":
        raise_err(ERR_JOB_NOT_OPEN, "Submit requires the job account in OPEN")
    if clock_date() > parse_date(quote["valid_until"]):
        quote["status"] = "EXPIRED"
        touch(quote)
        raise_err(ERR_QUOTE_EXPIRED, "Logical clock date is past valid_until")
    lines = [l for l in db.quote_lines.values() if l["quote_id"] == quote["id"]]
    if not lines:
        raise_err(ERR_QUOTE_HAS_NO_LINES, "Submit requires at least one quote line")
    quote["status"] = "SUBMITTED"
    touch(quote)
    return success_object(ser_quote(quote))


@bp.post("/quotes/<quote_id>/revise")
@require_roles("SalesRep")
@atomic
def revise_quote(quote_id: str):
    body = get_json_body()
    expected_version = require_int(body, "expected_quote_version")
    quote = _get_quote_or_404(quote_id)
    # OCC (priority 5) precedes the state precondition (priority 6): a stale
    # version surfaces ERR_STALE_QUOTE_VERSION even when the quote is also in
    # the wrong state for revision (PRD §2.10).
    if expected_version != quote["version"]:
        raise_err(ERR_STALE_QUOTE_VERSION, "expected_quote_version does not match the quote's current version")
    maybe_expire_quote(quote)
    if quote["status"] != "SUBMITTED":
        raise_err(ERR_QUOTE_NOT_SUBMITTED, "Revise requires the quote in SUBMITTED")
    quote["status"] = "DRAFT"
    quote["revision_no"] += 1
    touch(quote)
    return success_object(ser_quote(quote))


@bp.post("/quotes/<quote_id>/award")
@require_roles("BranchManager")
@atomic
def award_quote(quote_id: str):
    quote = _get_quote_or_404(quote_id)
    if quote["status"] != "SUBMITTED":
        raise_err(ERR_QUOTE_NOT_SUBMITTED, "Award requires the quote in SUBMITTED")
    job = db.job_accounts[quote["job_account_id"]]
    if job["status"] != "OPEN":
        raise_err(ERR_JOB_NOT_OPEN, "Award requires the job account in OPEN")
    if clock_date() > parse_date(quote["valid_until"]):
        quote["status"] = "EXPIRED"
        touch(quote)
        raise_err(ERR_QUOTE_EXPIRED, "Logical clock date is past valid_until")
    month = clock_month()
    quote["status"] = "AWARDED"
    quote["award_month"] = month
    quote["award_index_value"] = latest_index_at_or_before(month)
    touch(quote)
    return success_object(ser_quote(quote))
