"""Member endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import success_object
from ..errors import APIError
from ..serializers import serialize_member
from ..services.common import compute_eligible_to_vote, require
from ..store import store
from ..util import new_uuid
from ._helpers import get_json_body, require_field

bp = Blueprint("members", __name__)


@bp.route("/hoa/members", methods=["POST"])
@require_roles(["PresidentRole"])
def create_member():
    body = get_json_body()
    full_name = require_field(body, "full_name")
    email = require_field(body, "email")
    if not isinstance(full_name, str) or not full_name:
        raise APIError("ERR_INVALID_STATE", "full_name must be a non-empty string", 409)
    if not isinstance(email, str) or not email:
        raise APIError("ERR_INVALID_STATE", "email must be a non-empty string", 409)

    s = store()
    # Email uniqueness per HOA
    for m in s.members.values():
        if m["email"].lower() == email.lower():
            raise APIError("ERR_INVALID_STATE", "Email already registered", 409)

    now = s.now()
    member = {
        "id": new_uuid(),
        "full_name": full_name,
        "email": email,
        "eligible_to_vote": False,
        "board_role": "NONE",
        "total_overdue_amount_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("members", member)
    return jsonify(success_object(serialize_member(member))), 201


@bp.route("/hoa/members/<member_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_member(member_id: str):
    member = require("members", member_id)
    # Recompute eligible_to_vote on every read (computed field)
    member["eligible_to_vote"] = compute_eligible_to_vote(member)
    return jsonify(success_object(serialize_member(member))), 200
