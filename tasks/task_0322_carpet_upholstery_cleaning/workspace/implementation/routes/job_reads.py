"""Remaining job sub-resource read endpoints (PRD §3.6).

  GET /cleaning-jobs/{id}/scheduled-slots — slots booked for a job
  GET /cleaning-jobs/{id}/wallet-ledger    — ledger movements produced by a job
"""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require
from response import ok_array
from services.common import (
    by_created_asc,
    paginate,
    parse_pagination,
    public_list,
)
from services.lookups import get_job

bp = Blueprint("job_reads", __name__)


@bp.get("/cleaning-jobs/<jid>/scheduled-slots")
def list_job_slots(jid):
    require(["Customer", "ServiceManager", "Dispatcher", "Billing"])
    get_job(jid)
    limit, offset = parse_pagination()
    rows = [s for s in db.scheduled_slots.values() if s["cleaning_job_id"] == jid]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


@bp.get("/cleaning-jobs/<jid>/wallet-ledger")
def list_job_wallet_ledger(jid):
    require(["Customer", "ServiceManager", "Billing"])
    get_job(jid)
    limit, offset = parse_pagination()
    rows = [e for e in db.wallet_ledger_entries.values() if e.get("cleaning_job_id") == jid]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)
