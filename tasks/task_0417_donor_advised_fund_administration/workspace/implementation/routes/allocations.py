"""PoolAllocation read endpoints (PRD 3.4). Allocations are created/mutated only
through rebalance execute and grant payout, never directly."""
from flask import Blueprint, request

from db import db
from middleware import get_identity, require_role, get_pagination, paginate
from response import object_response, array_response
from services import serialize
from services.lookup import get_or_404, filtered_sorted

bp = Blueprint("allocations", __name__)

ALLOC_ROLES = {"SponsorAdmin", "DonorAdvisor", "GrantOfficer"}


@bp.get("/daf/allocations/<allocation_id>")
def get_allocation(allocation_id):
    _, role = get_identity()
    require_role(role, ALLOC_ROLES)
    allocation = get_or_404(db.allocations, allocation_id)
    return object_response(serialize.allocation(allocation))


@bp.get("/daf/allocations")
def list_allocations():
    _, role = get_identity()
    require_role(role, ALLOC_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.allocations, {
        "donor_account_id": request.args.get("donor_account_id"),
        "investment_pool_id": request.args.get("investment_pool_id"),
        "status": request.args.get("status"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.allocation(a) for a in page], meta)
