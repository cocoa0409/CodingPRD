"""The proceeds allocation register: an append-only event log read three ways
(PRD 3.10).
"""

from flask import Blueprint

import db
import listing
import lookup
import response
import shape
from middleware import CLERK, FINANCE, MONITOR, RPO, SYSADMIN, authorize
from services import derive

bp = Blueprint("allocations", __name__)

ALLOCATION_BASES = ("FIXED_RESERVE", "PERCENTAGE", "CHALLENGE_FORFEITURE")
ALLOCATION_STATUSES = ("POSTED", "REVERSED")
READ_ROLES = (RPO, CLERK, MONITOR, FINANCE, SYSADMIN)


def _fund_rank(row):
    fund = db.get("funds", row["fund_id"])
    rank = fund["priority_rank"] if fund is not None else 0
    return (rank, row["created_at"], row["_seq"])


@bp.get("/funds/<row_id>/proceeds-allocations")
@authorize(*READ_ROLES)
def list_fund_allocations(row_id):
    limit, offset = listing.bounds()
    status = shape.query_enum("status", ALLOCATION_STATUSES)
    basis = shape.query_enum("allocation_basis", ALLOCATION_BASES)
    fund = lookup.must("funds", row_id)
    rows = [r for r in db.all_rows("proceeds_allocations") if r["fund_id"] == fund["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if basis is not None:
        rows = [r for r in rows if r["allocation_basis"] == basis]
    return listing.respond(rows, derive.allocation_out, limit, offset, listing.by_created_at)


@bp.get("/conveyances/<row_id>/proceeds-allocations")
@authorize(*READ_ROLES)
def list_conveyance_allocations(row_id):
    limit, offset = listing.bounds()
    status = shape.query_enum("status", ALLOCATION_STATUSES)
    conveyance = lookup.must("conveyances", row_id)
    rows = [r for r in db.all_rows("proceeds_allocations")
            if r.get("conveyance_id") == conveyance["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing.respond(rows, derive.allocation_out, limit, offset, _fund_rank)


@bp.get("/proceeds-allocations")
@authorize(*READ_ROLES)
def list_allocations():
    limit, offset = listing.bounds()
    conveyance_id = shape.query_str("conveyance_id")
    fund_id = shape.query_str("fund_id")
    basis = shape.query_enum("allocation_basis", ALLOCATION_BASES)
    status = shape.query_enum("status", ALLOCATION_STATUSES)
    rows = db.all_rows("proceeds_allocations")
    if conveyance_id is not None:
        rows = [r for r in rows if r.get("conveyance_id") == conveyance_id]
    if fund_id is not None:
        rows = [r for r in rows if r["fund_id"] == fund_id]
    if basis is not None:
        rows = [r for r in rows if r["allocation_basis"] == basis]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing.respond(rows, derive.allocation_out, limit, offset, listing.by_created_at)
