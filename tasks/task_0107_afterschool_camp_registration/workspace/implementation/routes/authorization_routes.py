"""Authorization routes (create, revoke)."""

from flask import Blueprint

from clock import parse_iso
from config import (
    AUTH_KINDS,
    ROLE_GUARDIAN,
    ROLE_PROGRAM_ADMIN,
    SCOPE_TEXT_MAX,
    SCOPE_TEXT_MIN,
)
from db import db, init_lean_fields
from errors import APIError
from middleware import get_json_body, require_auth
from response import success_response
from services.authorizations import revoke_authorization
from services.lookups import (
    assert_family_scope,
    get_authorization,
    get_child,
    get_guardian,
)
from services.projection import project_child_auth_statuses
from services.serializers import serialize_authorization
from services.validators import require_enum, require_string


authorization_bp = Blueprint("authorization", __name__)


@authorization_bp.route("/children/<child_id>/authorizations", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def create_authorization(child_id):
    child = get_child(child_id)
    assert_family_scope(child["family_id"])
    body = get_json_body()
    guardian_id = require_string(body, "guardian_id", min_len=1)
    guardian = get_guardian(guardian_id)
    # Guardian must belong to the same family as the child — ERR_FAMILY_MISMATCH
    if guardian["family_id"] != child["family_id"]:
        raise APIError("ERR_FAMILY_MISMATCH")
    kind = require_enum(body, "kind", AUTH_KINDS)
    scope_text = require_string(body, "scope_text", min_len=SCOPE_TEXT_MIN, max_len=SCOPE_TEXT_MAX)
    effective_at_raw = require_string(body, "effective_at", min_len=1)
    expires_at_raw = require_string(body, "expires_at", min_len=1)
    eff_dt = parse_iso(effective_at_raw)
    exp_dt = parse_iso(expires_at_raw)
    if exp_dt <= eff_dt:
        raise APIError("ERR_INVALID_TIME_RANGE")
    row = init_lean_fields({
        "child_id": child_id,
        "guardian_id": guardian_id,
        "kind": kind,
        "scope_text": scope_text,
        "effective_at": effective_at_raw,
        "expires_at": expires_at_raw,
        "status": "ACTIVE",
        "revoked_at": None,
    })
    db.authorizations[row["id"]] = row
    project_child_auth_statuses(child, persist=True)
    return success_response(serialize_authorization(row), status=201)


@authorization_bp.route("/authorizations/<authorization_id>/revoke", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def revoke_authorization_route(authorization_id):
    from flask import g
    from db import detect_race_and_mark_losers
    auth = get_authorization(authorization_id)
    child = db.children.get(auth["child_id"])
    if child is None:
        raise APIError("ERR_RESOURCE_NOT_FOUND", "Parent child not found.")
    assert_family_scope(child["family_id"])
    # PRD §3.2 confirm-vs-revoke-medical race detection — intent already
    # registered in before_request when kind==MEDICAL.
    my_seq = getattr(g, "request_entry_seq", None)
    if (
        auth.get("kind") == "MEDICAL"
        and my_seq is not None
        and detect_race_and_mark_losers(child["id"], "med_revoke", my_seq)
    ):
        raise APIError("ERR_AUTHORIZATION_NOT_ACTIVE")
    revoke_authorization(auth)
    return success_response(serialize_authorization(auth))
