"""Exhibition routes (§3.1)."""

from flask import Blueprint, g, request

import db
import response as resp
from middleware import require_roles
from services import exhibition_service, allocation_service
from services.common import must_exist, serialize


bp = Blueprint("exhibitions", __name__)


@bp.route("/exhibitions", methods=["POST"])
def create_exhibition():
    require_roles("VenueAdmin")
    row = exhibition_service.create_exhibition(g.body)
    return resp.created(serialize(row))


@bp.route("/exhibitions/<exhibition_id>", methods=["GET"])
def get_exhibition(exhibition_id):
    require_roles("VenueAdmin", "VenueOps", "Exhibitor", "GateOperator", "ServiceProvider")
    ex = must_exist(db.exhibitions, exhibition_id, "Exhibition")
    return resp.success(serialize(ex))


@bp.route("/exhibitions/<exhibition_id>/open-intake", methods=["POST"])
def open_intake(exhibition_id):
    require_roles("VenueAdmin")
    row = exhibition_service.open_intake(exhibition_id, g.body)
    return resp.success(serialize(row))


@bp.route("/exhibitions/<exhibition_id>/publish-allocation", methods=["POST"])
def publish_allocation(exhibition_id):
    require_roles("VenueAdmin")
    row = exhibition_service.publish_allocation(exhibition_id, g.body)
    return resp.success(serialize(row))


@bp.route("/exhibitions/<exhibition_id>/start-setup", methods=["POST"])
def start_setup(exhibition_id):
    require_roles("VenueAdmin")
    row = exhibition_service.start_setup(exhibition_id, g.body)
    return resp.success(serialize(row))


@bp.route("/exhibitions/<exhibition_id>/open-doors", methods=["POST"])
def open_doors(exhibition_id):
    require_roles("VenueAdmin")
    row = exhibition_service.open_doors(exhibition_id, g.body)
    return resp.success(serialize(row))


@bp.route("/exhibitions/<exhibition_id>/close-doors", methods=["POST"])
def close_doors(exhibition_id):
    require_roles("VenueAdmin")
    row = exhibition_service.close_doors(exhibition_id, g.body)
    return resp.success(serialize(row))


@bp.route("/exhibitions/<exhibition_id>/close", methods=["POST"])
def close_exhibition(exhibition_id):
    require_roles("VenueAdmin")
    row = exhibition_service.close_exhibition(exhibition_id, g.body)
    return resp.success(serialize(row))


@bp.route("/exhibitions/<exhibition_id>/entitlement-report", methods=["GET"])
def entitlement_report(exhibition_id):
    require_roles("VenueAdmin", "Exhibitor")
    return resp.success(exhibition_service.entitlement_report(exhibition_id))


@bp.route("/exhibitions/<exhibition_id>/audit-log", methods=["GET"])
def audit_log(exhibition_id):
    require_roles("VenueAdmin")
    must_exist(db.exhibitions, exhibition_id, "Exhibition")
    sk = request.args.get("subject_kind")
    if sk and sk not in ("ALLOCATION", "ENTITLEMENT"):
        from errors import AppError, ERR_INVALID_INPUT
        raise AppError(ERR_INVALID_INPUT, "Invalid subject_kind.", 422)
    limit, offset = resp.parse_pagination(request.args)
    items, total = allocation_service.list_audit_log(exhibition_id, sk, limit, offset)
    return resp.success_list([serialize(i) for i in items], total, limit, offset)


@bp.route("/exhibitions/<exhibition_id>/occupancy", methods=["GET"])
def occupancy(exhibition_id):
    require_roles("VenueAdmin", "VenueOps", "GateOperator")
    return resp.success(exhibition_service.occupancy(exhibition_id))
