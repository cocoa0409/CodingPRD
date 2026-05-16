"""TestEvent + TestCenter + TestCenterCapacity routes."""

from flask import Blueprint, request

from middleware import require_roles
from response import success, success_list
from services.common import get_json_body, paginate, parse_pagination
from services.serializers import (
    serialize_capacity,
    serialize_test_center,
    serialize_test_event,
)
from services.test_event_service import (
    allocate_capacity,
    create_test_center,
    create_test_event,
    extend_deadline,
    get_test_center_or_404,
    get_test_event_or_404,
    list_capacities_for_event,
    list_test_centers,
    list_test_events,
)

bp = Blueprint("test_events", __name__)


@bp.route("/test-events", methods=["POST"])
@require_roles("Registrar")
def create_test_event_route():
    body = get_json_body()
    e = create_test_event(body)
    return success(serialize_test_event(e), status=201)


@bp.route("/test-events", methods=["GET"])
@require_roles("Candidate", "Proctor", "Registrar", "AccommodationsOfficer", "CreditsOfficer")
def list_test_events_route():
    limit, offset = parse_pagination()
    test_type = request.args.get("test_type")
    status = request.args.get("status")
    items = list_test_events(test_type, status)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_test_event(x) for x in page], limit, offset, total)


@bp.route("/test-events/<test_event_id>", methods=["GET"])
@require_roles("Candidate", "Proctor", "Registrar", "AccommodationsOfficer", "CreditsOfficer")
def get_test_event_route(test_event_id):
    e = get_test_event_or_404(test_event_id)
    return success(serialize_test_event(e))


@bp.route("/test-events/<test_event_id>/extend-deadline", methods=["POST"])
@require_roles("Registrar")
def extend_deadline_route(test_event_id):
    body = get_json_body()
    e = extend_deadline(test_event_id, body)
    return success(serialize_test_event(e), status=200)


# ---- TestCenter ----


@bp.route("/test-centers", methods=["POST"])
@require_roles("Registrar")
def create_test_center_route():
    body = get_json_body()
    c = create_test_center(body)
    return success(serialize_test_center(c), status=201)


@bp.route("/test-centers", methods=["GET"])
@require_roles("Candidate", "Proctor", "Registrar", "AccommodationsOfficer", "CreditsOfficer")
def list_test_centers_route():
    limit, offset = parse_pagination()
    items = list_test_centers()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_test_center(x) for x in page], limit, offset, total)


@bp.route("/test-centers/<test_center_id>", methods=["GET"])
@require_roles("Candidate", "Proctor", "Registrar", "AccommodationsOfficer", "CreditsOfficer")
def get_test_center_route(test_center_id):
    c = get_test_center_or_404(test_center_id)
    return success(serialize_test_center(c))


# ---- TestCenterCapacity ----


@bp.route("/test-events/<test_event_id>/test-center-capacities", methods=["POST"])
@require_roles("Registrar")
def allocate_capacity_route(test_event_id):
    body = get_json_body()
    cap = allocate_capacity(test_event_id, body)
    return success(serialize_capacity(cap), status=201)


@bp.route("/test-events/<test_event_id>/test-center-capacities", methods=["GET"])
@require_roles("Candidate", "Proctor", "Registrar", "AccommodationsOfficer", "CreditsOfficer")
def list_capacities_route(test_event_id):
    limit, offset = parse_pagination()
    items = list_capacities_for_event(test_event_id)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_capacity(x) for x in page], limit, offset, total)
