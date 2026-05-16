"""Scholarship routes."""

from flask import Blueprint

from config import ROLE_PROGRAM_ADMIN, SCHOLARSHIP_KINDS
from db import db, init_common_fields
from errors import APIError
from middleware import get_json_body, require_auth
from response import success_response
from services.authorizations import revoke_scholarship
from services.lookups import get_family, get_scholarship
from services.serializers import serialize_scholarship
from services.validators import require_enum, require_int


scholarship_bp = Blueprint("scholarship", __name__)


@scholarship_bp.route("/families/<family_id>/scholarships", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def create_scholarship(family_id):
    fam = get_family(family_id)
    body = get_json_body()
    total = require_int(body, "total_credit_cents", minimum=1)
    granted_for = require_enum(body, "granted_for_kind", SCHOLARSHIP_KINDS)
    row = init_common_fields({
        "family_id": family_id,
        "total_credit_cents": total,
        "consumed_credit_cents": 0,
        "granted_for_kind": granted_for,
        "status": "ACTIVE",
        "revoked_at": None,
    })
    db.scholarships[row["id"]] = row
    return success_response(serialize_scholarship(row), status=201)


@scholarship_bp.route("/scholarships/<scholarship_id>/revoke", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def revoke_scholarship_route(scholarship_id):
    s = get_scholarship(scholarship_id)
    revoke_scholarship(s)
    return success_response(serialize_scholarship(s))
