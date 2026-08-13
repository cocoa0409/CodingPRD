"""StatementCycle endpoints (PRD §3.6)."""

from datetime import date

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_STATEMENT_PERIOD_OVERLAP,
)
from middleware import require_roles
from response import paginate, parse_pagination, success_list, success_object
from serialization import statement_cycle_view
from services.account import get_account_or_404

bp = Blueprint("statement_cycles", __name__)


@bp.post("/bank/accounts/<account_id>/statement-cycles")
def schedule_cycle(account_id):
    require_roles(["OpsOfficer", "System"])
    get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    start_raw = body.get("cycle_start")
    end_raw = body.get("cycle_end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise ApiError(ERR_INVALID_REQUEST, "cycle_start and cycle_end are required")
    try:
        start = date.fromisoformat(start_raw)
        end = date.fromisoformat(end_raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "cycle_start and cycle_end must be YYYY-MM-DD dates")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, "cycle_end must fall strictly after cycle_start")

    # Half-open [cycle_start, cycle_end): cycles may touch but never overlap.
    for other in db.statement_cycles.values():
        if other["account_id"] != account_id:
            continue
        o_start = date.fromisoformat(other["cycle_start"])
        o_end = date.fromisoformat(other["cycle_end"])
        if start < o_end and end > o_start:
            raise ApiError(
                ERR_STATEMENT_PERIOD_OVERLAP,
                "The period overlaps an existing statement cycle on this account",
            )

    cyc = {
        "id": db.new_uuid(),
        "account_id": account_id,
        "cycle_start": start.isoformat(),
        "cycle_end": end.isoformat(),
        "status": "SCHEDULED",
        "suppression_reason": None,
        "produced_date": None,
        "created_at": db.now_timestamp(),
        "updated_at": db.now_timestamp(),
        "version": 1,
        "_seq": db.next_creation_seq(),
    }
    db.statement_cycles[cyc["id"]] = cyc
    return success_object(statement_cycle_view(cyc), status=201)


@bp.get("/bank/accounts/<account_id>/statement-cycles")
def list_cycles(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    get_account_or_404(account_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")

    items = [c for c in db.statement_cycles.values() if c["account_id"] == account_id]
    items.sort(key=lambda c: c["_seq"])
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([statement_cycle_view(c) for c in page], total, limit, offset)
