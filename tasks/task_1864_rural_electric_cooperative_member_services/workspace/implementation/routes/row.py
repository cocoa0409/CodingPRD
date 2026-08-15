"""RightOfWayAgreement endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, require_member_ownership, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import row as row_svc
from db import store

bp = Blueprint("row", __name__)


@bp.route("/coop/right-of-way-agreements", methods=["POST"])
def create_row():
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    body = get_json_body()
    result = row_svc.create_row(body)
    return created(result)


@bp.route("/coop/right-of-way-agreements/<row_id>", methods=["GET"])
def get_row(row_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator", "LegalCounsel", "MemberServicesRep", "Member"])
    result = row_svc.get_row(row_id)
    if role == "Member":
        loc = store.service_locations.get(result["service_location_id"])
        if loc:
            require_member_ownership(loc.get("member_id"))
    return ok(result)


@bp.route("/coop/right-of-way-agreements", methods=["GET"])
def list_rows():
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator", "LegalCounsel", "MemberServicesRep"])
    service_location_id = request.args.get("service_location_id")
    status = request.args.get("status")
    rows = row_svc.list_rows(service_location_id, status)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/right-of-way-agreements/<row_id>/consent", methods=["POST"])
def consent_row(row_id):
    uid, role = get_context()
    require_roles(["Member"])
    result = row_svc.consent_row(row_id, uid)
    return ok(result)


@bp.route("/coop/right-of-way-agreements/<row_id>/record", methods=["POST"])
def record_row(row_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = row_svc.record_row(row_id)
    return ok(result)


@bp.route("/coop/right-of-way-agreements/<row_id>/contest", methods=["POST"])
def contest_row(row_id):
    uid, role = get_context()
    require_roles(["Member"])
    result = row_svc.contest_row(row_id, uid)
    return ok(result)


@bp.route("/coop/right-of-way-agreements/<row_id>/condemn", methods=["POST"])
def condemn_row(row_id):
    uid, role = get_context()
    require_roles(["LegalCounsel"])
    result = row_svc.condemn_row(row_id)
    return ok(result)


@bp.route("/coop/right-of-way-agreements/<row_id>/release", methods=["POST"])
def release_row(row_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = row_svc.release_row(row_id)
    return ok(result)
