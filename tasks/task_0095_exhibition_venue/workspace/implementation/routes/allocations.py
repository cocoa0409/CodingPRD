"""BoothAllocation routes (§3.4)."""

from flask import Blueprint, g

import response as resp
from middleware import require_roles, require_exhibitor_ownership
from services import allocation_service
from services.common import serialize


bp = Blueprint("allocations", __name__)


@bp.route("/allocations", methods=["POST"])
def create_allocation():
    require_roles("VenueAdmin")
    row = allocation_service.create_allocation(g.body)
    return resp.created(serialize(row))


@bp.route("/allocations/<alloc_id>/object", methods=["POST"])
def object_allocation(alloc_id):
    require_roles("Exhibitor")
    row = allocation_service.object_allocation(alloc_id, g.body)
    return resp.success(serialize(row))


@bp.route("/allocations/<alloc_id>/confirm", methods=["POST"])
def confirm_allocation(alloc_id):
    require_roles("Exhibitor")
    row = allocation_service.confirm_allocation(alloc_id, g.body)
    return resp.success(serialize(row))


@bp.route("/allocations/<alloc_id>/start-relocation", methods=["POST"])
def start_relocation(alloc_id):
    require_roles("VenueAdmin")
    row = allocation_service.start_relocation(alloc_id, g.body)
    return resp.success(serialize(row))


@bp.route("/allocations/<alloc_id>/relocate", methods=["POST"])
def relocate(alloc_id):
    require_roles("VenueAdmin")
    row = allocation_service.relocate_allocation(alloc_id, g.body)
    return resp.success(serialize(row))


@bp.route("/allocations/<alloc_id>/revoke", methods=["POST"])
def revoke(alloc_id):
    require_roles("VenueAdmin")
    row = allocation_service.revoke_allocation(alloc_id, g.body)
    return resp.success(serialize(row))


@bp.route("/allocations/<alloc_id>", methods=["GET"])
def get_allocation(alloc_id):
    require_roles("VenueAdmin", "Exhibitor")
    row = allocation_service.get_allocation(alloc_id)
    require_exhibitor_ownership(row)
    return resp.success(serialize(row))
