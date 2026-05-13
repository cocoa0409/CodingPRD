"""Work and RightsShare routes."""

from flask import Blueprint, request

from middleware import require_role
from response import success_response, list_response
from services import work as work_svc
from services import rights_share as share_svc

bp = Blueprint("works", __name__)


@bp.route("/works", methods=["POST"])
def create():
    require_role("RightsHolder")
    body = request.get_json(silent=True) or {}
    data = work_svc.create_work(body)
    return success_response(data, status_code=201)


@bp.route("/works/<work_id>", methods=["GET"])
def get(work_id):
    require_role("PlatformAdmin", "RightsHolder", "RegistrationReviewer", "DisputeOfficer", "FinanceOps")
    data = work_svc.get_work(work_id)
    return success_response(data)


@bp.route("/works", methods=["GET"])
def list_works():
    require_role("PlatformAdmin", "RegistrationReviewer", "FinanceOps")
    items, total, limit, offset = work_svc.list_works(request.args)
    return list_response(items, total, limit, offset)


@bp.route("/works/<work_id>/submit", methods=["POST"])
def submit(work_id):
    require_role("RightsHolder")
    data = work_svc.submit_work(work_id, request.get_json(silent=True) or {})
    return success_response(data)


@bp.route("/works/<work_id>/take-review", methods=["POST"])
def take_review(work_id):
    require_role("RegistrationReviewer")
    data = work_svc.take_review(work_id, request.get_json(silent=True) or {})
    return success_response(data)


@bp.route("/works/<work_id>/approve", methods=["POST"])
def approve(work_id):
    require_role("RegistrationReviewer")
    data = work_svc.approve_work(work_id, request.get_json(silent=True) or {})
    return success_response(data)


@bp.route("/works/<work_id>/reject", methods=["POST"])
def reject(work_id):
    require_role("RegistrationReviewer")
    data = work_svc.reject_work(work_id, request.get_json(silent=True) or {})
    return success_response(data)


@bp.route("/works/<work_id>/withdraw", methods=["POST"])
def withdraw(work_id):
    require_role("RightsHolder")
    data = work_svc.withdraw_work(work_id, request.get_json(silent=True) or {})
    return success_response(data)


@bp.route("/works/<work_id>/return-to-draft", methods=["POST"])
def return_to_draft(work_id):
    require_role("RegistrationReviewer")
    data = work_svc.return_to_draft(work_id, request.get_json(silent=True) or {})
    return success_response(data)


@bp.route("/works/<work_id>/shares", methods=["POST"])
def create_share(work_id):
    require_role("RightsHolder", "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    data = share_svc.create_share(work_id, body)
    return success_response(data, status_code=201)


@bp.route("/works/<work_id>/shares/<share_id>", methods=["PATCH"])
def update_share(work_id, share_id):
    require_role("RightsHolder", "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    data = share_svc.update_share(work_id, share_id, body)
    return success_response(data)


@bp.route("/works/<work_id>/shares/<share_id>/audit", methods=["GET"])
def list_audit(work_id, share_id):
    require_role("PlatformAdmin", "RightsHolder", "DisputeOfficer")
    items, total, limit, offset = share_svc.list_audit(work_id, share_id, request.args)
    return list_response(items, total, limit, offset)
