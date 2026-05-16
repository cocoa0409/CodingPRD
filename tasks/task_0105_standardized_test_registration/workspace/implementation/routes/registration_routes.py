"""Registration routes: create, get, list, self-cancel, admin-cancel, check-in.
Also: nested IDVerification and ScoreReport routes are mounted here for
hierarchical resolution.
"""

from flask import Blueprint, request

from errors import err_insufficient_permissions
from middleware import current_user_id, current_user_role, require_roles
from response import success, success_list
from services.common import get_json_body, paginate, parse_pagination
from services.id_verification_service import (
    clear_id_verification,
    get_id_verification,
    reject_id_verification,
    submit_id_verification,
)
from services.registration_service import (
    cancel_registration,
    check_in_registration,
    create_registration,
    get_scoped_registration_or_404,
    list_registrations_for_event,
)
from services.serializers import (
    serialize_id_verification,
    serialize_refund,
    serialize_registration,
    serialize_score_report,
)
import db

bp = Blueprint("registrations", __name__)


@bp.route("/test-events/<test_event_id>/registrations", methods=["POST"])
@require_roles("Candidate", "Registrar")
def create_registration_route(test_event_id):
    body = get_json_body()
    r = create_registration(test_event_id, body, current_user_role(), current_user_id())
    return success(serialize_registration(r), status=201)


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>", methods=["GET"])
@require_roles("Candidate", "Proctor", "Registrar")
def get_registration_route(test_event_id, registration_id):
    r = get_scoped_registration_or_404(test_event_id, registration_id)
    if current_user_role() == "Candidate" and current_user_id() != r["candidate_id"]:
        raise err_insufficient_permissions()
    return success(serialize_registration(r))


@bp.route("/test-events/<test_event_id>/registrations", methods=["GET"])
@require_roles("Proctor", "Registrar")
def list_registrations_route(test_event_id):
    limit, offset = parse_pagination()
    test_center_id = request.args.get("test_center_id")
    status = request.args.get("status")
    items = list_registrations_for_event(test_event_id, test_center_id, status)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_registration(x) for x in page], limit, offset, total)


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>", methods=["DELETE"])
@require_roles("Candidate")
def self_cancel_registration_route(test_event_id, registration_id):
    body = get_json_body() if request.data else {}
    r = cancel_registration(
        test_event_id, registration_id, body, "SELF_INITIATED",
        current_user_role(), current_user_id(),
    )
    return success(serialize_registration(r))


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/admin-cancel", methods=["POST"])
@require_roles("Registrar")
def admin_cancel_registration_route(test_event_id, registration_id):
    body = get_json_body()
    r = cancel_registration(
        test_event_id, registration_id, body, "OFFICIAL_CANCELLATION",
        current_user_role(), current_user_id(),
    )
    return success(serialize_registration(r))


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/check-in", methods=["POST"])
@require_roles("Proctor")
def check_in_route(test_event_id, registration_id):
    r = check_in_registration(test_event_id, registration_id, current_user_role(), current_user_id())
    return success(serialize_registration(r))


# ---- IDVerification ----


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/id-verification/submit", methods=["POST"])
@require_roles("Candidate")
def submit_id_verification_route(test_event_id, registration_id):
    body = get_json_body()
    v = submit_id_verification(test_event_id, registration_id, body, current_user_role(), current_user_id())
    return success(serialize_id_verification(v), status=201)


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/id-verification/clear", methods=["POST"])
@require_roles("Registrar")
def clear_id_verification_route(test_event_id, registration_id):
    body = get_json_body()
    v = clear_id_verification(test_event_id, registration_id, body)
    return success(serialize_id_verification(v))


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/id-verification/reject", methods=["POST"])
@require_roles("Registrar")
def reject_id_verification_route(test_event_id, registration_id):
    body = get_json_body()
    v = reject_id_verification(test_event_id, registration_id, body)
    return success(serialize_id_verification(v))


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/id-verification", methods=["GET"])
@require_roles("Candidate", "Proctor", "Registrar")
def get_id_verification_route(test_event_id, registration_id):
    v = get_id_verification(test_event_id, registration_id, current_user_role(), current_user_id())
    return success(serialize_id_verification(v))


# ---- Refund history ----


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/refunds", methods=["GET"])
@require_roles("Candidate", "Registrar")
def list_refunds_route(test_event_id, registration_id):
    r = get_scoped_registration_or_404(test_event_id, registration_id)
    if current_user_role() == "Candidate" and current_user_id() != r["candidate_id"]:
        raise err_insufficient_permissions()
    limit, offset = parse_pagination()
    items = [t for t in db.refund_transactions.all() if t["registration_id"] == registration_id]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_refund(x) for x in page], limit, offset, total)
