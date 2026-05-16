"""AccommodationRequest routes."""

from flask import Blueprint, request

from errors import err_insufficient_permissions
from middleware import current_user_id, current_user_role, require_roles
from response import success, success_list
from services.accommodation_service import (
    approve,
    create_accommodation_request,
    deny,
    get_accommodation_or_404,
    list_accommodation_requests,
    request_info,
    resubmit,
    start_review,
)
from services.common import get_json_body, paginate, parse_pagination
from services.serializers import serialize_accommodation_request

bp = Blueprint("accommodations", __name__)


@bp.route("/accommodation-requests", methods=["POST"])
@require_roles("Candidate")
def create_accommodation_request_route():
    body = get_json_body()
    a = create_accommodation_request(body, current_user_role(), current_user_id())
    return success(serialize_accommodation_request(a), status=201)


@bp.route("/accommodation-requests/<accommodation_id>/start-review", methods=["POST"])
@require_roles("AccommodationsOfficer")
def start_review_route(accommodation_id):
    a = start_review(accommodation_id, current_user_id())
    return success(serialize_accommodation_request(a))


@bp.route("/accommodation-requests/<accommodation_id>/request-info", methods=["POST"])
@require_roles("AccommodationsOfficer")
def request_info_route(accommodation_id):
    a = request_info(accommodation_id, current_user_id())
    return success(serialize_accommodation_request(a))


@bp.route("/accommodation-requests/<accommodation_id>/resubmit", methods=["PATCH"])
@require_roles("Candidate")
def resubmit_route(accommodation_id):
    body = get_json_body()
    a = resubmit(accommodation_id, body, current_user_id())
    return success(serialize_accommodation_request(a))


@bp.route("/accommodation-requests/<accommodation_id>/approve", methods=["POST"])
@require_roles("AccommodationsOfficer")
def approve_route(accommodation_id):
    a = approve(accommodation_id, current_user_id())
    return success(serialize_accommodation_request(a))


@bp.route("/accommodation-requests/<accommodation_id>/deny", methods=["POST"])
@require_roles("AccommodationsOfficer")
def deny_route(accommodation_id):
    a = deny(accommodation_id, current_user_id())
    return success(serialize_accommodation_request(a))


@bp.route("/accommodation-requests/<accommodation_id>", methods=["GET"])
@require_roles("Candidate", "Registrar", "AccommodationsOfficer")
def get_accommodation_route(accommodation_id):
    a = get_accommodation_or_404(accommodation_id)
    if current_user_role() == "Candidate" and current_user_id() != a["candidate_id"]:
        raise err_insufficient_permissions()
    return success(serialize_accommodation_request(a))


@bp.route("/accommodation-requests", methods=["GET"])
@require_roles("Registrar", "AccommodationsOfficer")
def list_accommodation_requests_route():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    test_event_id = request.args.get("test_event_id")
    items = list_accommodation_requests(status, test_event_id)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_accommodation_request(x) for x in page], limit, offset, total)
