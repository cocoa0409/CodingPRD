"""ExhibitorApplication routes (§3.3)."""

from flask import Blueprint, g, request

import response as resp
from middleware import require_roles
from services import application_service
from services.common import serialize


bp = Blueprint("applications", __name__)


@bp.route("/exhibitions/<exhibition_id>/applications", methods=["POST"])
def create_application(exhibition_id):
    require_roles("Exhibitor")
    row = application_service.create_application(exhibition_id, g.body)
    return resp.created(serialize(row))


@bp.route("/applications/<application_id>/submit", methods=["POST"])
def submit(application_id):
    require_roles("Exhibitor")
    row = application_service.submit_application(application_id, g.body)
    return resp.success(serialize(row))


@bp.route("/applications/<application_id>/start-review", methods=["POST"])
def start_review(application_id):
    require_roles("VenueAdmin")
    row = application_service.start_review(application_id, g.body)
    return resp.success(serialize(row))


@bp.route("/applications/<application_id>/qualify", methods=["POST"])
def qualify(application_id):
    require_roles("VenueAdmin")
    row = application_service.qualify_application(application_id, g.body)
    return resp.success(serialize(row))


@bp.route("/applications/<application_id>/reject", methods=["POST"])
def reject(application_id):
    require_roles("VenueAdmin")
    row = application_service.reject_application(application_id, g.body)
    return resp.success(serialize(row))


@bp.route("/applications/<application_id>/withdraw", methods=["POST"])
def withdraw(application_id):
    require_roles("Exhibitor")
    row = application_service.withdraw_application(application_id, g.body)
    return resp.success(serialize(row))


@bp.route("/exhibitions/<exhibition_id>/applications", methods=["GET"])
def list_applications(exhibition_id):
    require_roles("VenueAdmin")
    status = request.args.get("status")
    sort_by = request.args.get("sort_by")
    limit, offset = resp.parse_pagination(request.args)
    items, total = application_service.list_applications(exhibition_id, status, sort_by, limit, offset)
    return resp.success_list([serialize(i) for i in items], total, limit, offset)
