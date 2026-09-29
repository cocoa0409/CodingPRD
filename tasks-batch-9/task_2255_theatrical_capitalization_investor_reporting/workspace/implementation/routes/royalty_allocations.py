"""Royalty allocations; created only by wrap certification (PRD 3.7)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from middleware import MANAGEMENT_ROLES, endpoint, lookup

bp = Blueprint("royalty_allocations", __name__)

ALLOCATION_STATUSES = ("ALLOCATED", "REVERSED")


@bp.get("/royalty-allocations/<allocation_id>")
@endpoint(MANAGEMENT_ROLES)
def read_royalty_allocation(allocation_id):
    return response.obj(lookup("royalty_allocations", allocation_id,
                               errors.ERR_ROYALTY_ALLOCATION_NOT_FOUND))


@bp.get("/royalty-allocations")
@endpoint(MANAGEMENT_ROLES)
def list_royalty_allocations():
    wrap_id = v.q_str("wrap_id")
    participant_id = v.q_str("royalty_participant_id")
    status = v.q_enum("status", ALLOCATION_STATUSES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("royalty_allocations")
            if (wrap_id is None or r["wrap_id"] == wrap_id)
            and (participant_id is None
                 or r["royalty_participant_id"] == participant_id)
            and (status is None or r["status"] == status)]
    return response.listing(rows, limit, offset)
