"""SchoolAllocation endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from services import serializers

bp = Blueprint("allocations", __name__)

ALL_ROLES = middleware.ROLES


def get_allocation_or_404(allocation_id):
    alloc = db.allocations.get(allocation_id)
    if alloc is None:
        errors.fail(errors.ERR_NOT_FOUND, "School allocation %s does not exist." % allocation_id)
    return alloc


@bp.get("/school-allocations")
def list_allocations():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    filters = [
        ("grant_id", V.query_filter("grant_id")),
        ("school_id", V.query_filter("school_id")),
        ("snapshot_id", V.query_filter("snapshot_id")),
        ("status", V.query_filter("status")),
        ("program_model", V.query_filter("program_model")),
        ("eligibility_flag", V.query_filter("eligibility_flag")),
    ]
    page, limit, offset, total = V.sorted_page(list(db.allocations.values()), filters)
    return response.success_list(
        [serializers.allocation_view(a) for a in page], limit, offset, total
    )


@bp.get("/school-allocations/<allocation_id>")
def get_allocation(allocation_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.allocation_view(get_allocation_or_404(allocation_id)))


@bp.post("/school-allocations/<allocation_id>/certify")
def certify_allocation(allocation_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    alloc = get_allocation_or_404(allocation_id)
    data = V.json_body()
    V.check_unknown(data, set())
    # Tier 5: allocation state, then the cross-entity grant gate.
    if alloc["status"] != "PENDING":
        errors.fail(
            errors.ERR_ALLOCATION_NOT_PENDING,
            "Allocation certification requires status PENDING.",
        )
    grant = db.grants[alloc["grant_id"]]
    if grant["status"] != "ALLOCATED":
        errors.fail(
            errors.ERR_GRANT_INVALID_STATE,
            "Allocation certification requires the grant to be ALLOCATED.",
        )
    alloc["status"] = "CERTIFIED"
    db.touch(alloc)
    return response.success_object(serializers.allocation_view(alloc))
