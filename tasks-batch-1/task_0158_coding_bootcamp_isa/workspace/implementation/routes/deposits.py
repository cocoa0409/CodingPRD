"""Deposit reads (PRD §3.3, §3.5)."""
from flask import Blueprint, request

from db import db
from middleware import require_role
from response import success
from services import serialize
from services.common import parse_pagination, sort_by_created, paginate, lookup

bp = Blueprint("deposits", __name__)


@bp.get("/deposits/<did>")
def get_deposit(did):
    require_role("AdmissionsOfficer", "ComplianceOfficer", "Student")
    d = lookup(db.deposits, did)
    return success(serialize.deposit_view(d))


@bp.get("/deposits")
def list_deposits():
    require_role("AdmissionsOfficer", "ComplianceOfficer")
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    rows = list(db.deposits.values())
    if enrollment_id is not None:
        rows = [d for d in rows if d["enrollment_id"] == enrollment_id]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.deposit_view(d) for d in window], pagination=pg)
