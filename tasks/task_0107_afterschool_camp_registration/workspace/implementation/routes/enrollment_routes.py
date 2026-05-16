"""Enrollment routes."""

from flask import Blueprint

from config import ROLE_GUARDIAN, ROLE_PROGRAM_ADMIN
from db import db
from errors import APIError
from middleware import get_json_body, require_auth
from response import success_response
from services.enrollments import (
    cancel_enrollment,
    confirm_enrollment,
    create_enrollment,
    fee_quote,
)
from services.lookups import (
    assert_family_scope,
    get_child,
    get_enrollment,
    get_session,
)
from services.serializers import serialize_enrollment
from services.validators import require_int, require_string


enrollment_bp = Blueprint("enrollment", __name__)


@enrollment_bp.route("/enrollments", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def post_enrollment():
    body = get_json_body()
    child_id = require_string(body, "child_id", min_len=1)
    session_id = require_string(body, "session_id", min_len=1)
    # PRD §3.4 explicitly designates negative or out-of-range week_index
    # as ERR_INVALID_WEEK_INDEX — keep validator generic and let the
    # service raise the domain-specific error.
    week_index = require_int(body, "week_index")
    # Existence + ownership before delegating to service
    child = get_child(child_id)
    session = get_session(session_id)
    assert_family_scope(child["family_id"])
    row = create_enrollment(child_id, session_id, week_index)
    return success_response(serialize_enrollment(row), status=201)


@enrollment_bp.route("/enrollments/<enrollment_id>/confirm", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def confirm_enrollment_route(enrollment_id):
    from flask import g
    from db import detect_race_and_mark_losers
    e = get_enrollment(enrollment_id)
    child = db.children.get(e["child_id"])
    if child is None:
        raise APIError("ERR_RESOURCE_NOT_FOUND", "Parent child not found.")
    assert_family_scope(child["family_id"])
    # PRD §3.2 confirm-vs-revoke-medical race detection (already
    # registered in before_request; here we resolve winner/loser).
    my_seq = getattr(g, "request_entry_seq", None)
    if my_seq is not None and detect_race_and_mark_losers(
        child["id"], "confirm", my_seq,
    ):
        raise APIError("ERR_AUTHORIZATION_NOT_ACTIVE")
    confirm_enrollment(enrollment_id)
    return success_response(serialize_enrollment(e))


@enrollment_bp.route("/enrollments/<enrollment_id>/cancel", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def cancel_enrollment_route(enrollment_id):
    e = get_enrollment(enrollment_id)
    child = db.children.get(e["child_id"])
    if child is None:
        raise APIError("ERR_RESOURCE_NOT_FOUND", "Parent child not found.")
    assert_family_scope(child["family_id"])
    cancel_enrollment(enrollment_id)
    return success_response(serialize_enrollment(e))


@enrollment_bp.route("/enrollments/<enrollment_id>", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def read_enrollment(enrollment_id):
    e = get_enrollment(enrollment_id)
    child = db.children.get(e["child_id"])
    if child is None:
        raise APIError("ERR_RESOURCE_NOT_FOUND", "Parent child not found.")
    assert_family_scope(child["family_id"])
    return success_response(serialize_enrollment(e))


@enrollment_bp.route("/enrollments/<enrollment_id>/fee-quote", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def enrollment_fee_quote(enrollment_id):
    e = get_enrollment(enrollment_id)
    child = db.children.get(e["child_id"])
    if child is None:
        raise APIError("ERR_RESOURCE_NOT_FOUND", "Parent child not found.")
    assert_family_scope(child["family_id"])
    quote = fee_quote(enrollment_id)
    return success_response(quote)
