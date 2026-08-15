"""Job ledger: manual entries, listing, void compensation (PRD 2.8)."""

from flask import Blueprint, request

import db
import response
from errors import not_found, validation, invalid_state, already_terminal
from middleware import require_roles, check_owner_job
from services import storage as storage_svc
from validation import get_body, req_str, req_int, opt_str, parse_pagination, page
from .jobs import get_job_or_404, TERMINAL_JOB_STATES

bp = Blueprint("ledger", __name__)

# API-postable kinds; CHARGE is system-created only.
API_KINDS = ("PAYMENT", "CREDIT", "DEPOSIT")


def get_entry_or_404(entry_id):
    entry = db.ledger.get(entry_id)
    if entry is None:
        raise not_found(f"LedgerEntry '{entry_id}' does not exist")
    return entry


@bp.post("/yard/ledger-entries")
@require_roles("Accountant")
def create_entry():
    body = get_body()
    job_id = req_str(body, "job_id")
    job = get_job_or_404(job_id)
    kind = body.get("kind")
    if kind == "CHARGE":
        raise validation("Ledger entries of kind CHARGE are system-created only")
    if not isinstance(kind, str) or kind not in API_KINDS:
        raise validation("Field 'kind' must be one of ['CREDIT', 'DEPOSIT', 'PAYMENT']")
    amount = req_int(body, "amount_cents", gt=0)
    memo = opt_str(body, "memo")
    if job["status"] in TERMINAL_JOB_STATES:
        raise invalid_state("Manual entries may be posted only while the job is not terminal")
    entry = storage_svc.post_ledger(job["id"], kind, "OTHER", amount, memo=memo)
    return response.success_object(db.pub(entry), status=201)


@bp.get("/yard/refit-jobs/<jobId>/ledger-entries")
@require_roles("Accountant", "ServiceWriter", "Owner")
def list_entries(jobId):
    job = get_job_or_404(jobId)
    check_owner_job(job)
    limit, offset = parse_pagination()
    kind = request.args.get("kind")
    status = request.args.get("status")
    items = [e for e in db.ledger.values() if e["job_id"] == job["id"]]
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)


@bp.post("/yard/ledger-entries/<entryId>/void")
@require_roles("Accountant")
def void_entry(entryId):
    entry = get_entry_or_404(entryId)
    if entry["status"] == "VOIDED":
        raise already_terminal("LedgerEntry is already VOIDED")
    entry["status"] = "VOIDED"
    return response.success_object(db.pub(entry))
