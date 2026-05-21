"""Claim routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_CLAIMANT,
    ROLE_SYSTEM_ADMIN,
    current_role,
    current_user_id,
    require_auth,
)
from ..envelope import success_object
from ..errors import APIError
from ..serializers import serialize_claim
from ..services.entities import adjudicate_claim, apply_extension, submit_claim
from ..validators import get_json_body, optional_int, require_enum, require_string
from ._helpers import lookup_claim, require_claim_owner

bp = Blueprint("claims", __name__)


@bp.get("/claims/<claim_id>")
@require_auth([ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_APPEAL_OFFICER, ROLE_SYSTEM_ADMIN])
def claims_read(claim_id: str):
    cl = lookup_claim(claim_id)
    require_claim_owner(cl)
    return jsonify(success_object(serialize_claim(cl))), 200


@bp.post("/claims/<claim_id>/submit")
@require_auth([ROLE_CLAIMANT])
def claims_submit(claim_id: str):
    lookup_claim(claim_id)
    cl = submit_claim(claim_id, current_user_id())
    return jsonify(success_object(serialize_claim(cl))), 200


@bp.post("/claims/<claim_id>/adjudicate")
@require_auth([ROLE_ADJUDICATOR])
def claims_adjudicate(claim_id: str):
    lookup_claim(claim_id)
    body = get_json_body()
    decision = require_enum(body, "decision", {"ELIGIBLE", "DENIED"})
    version = optional_int(body, "version", min_val=0)
    cl = adjudicate_claim(claim_id, decision, current_user_id(), version)
    return jsonify(success_object(serialize_claim(cl))), 200


@bp.post("/claims/<claim_id>/apply-extension")
@require_auth([ROLE_CLAIMANT])
def claims_apply_extension(claim_id: str):
    lookup_claim(claim_id)
    body = get_json_body()
    extension_id = require_string(body, "extension_id")
    version = optional_int(body, "version", min_val=0)
    cl = apply_extension(claim_id, extension_id, current_user_id(), version)
    return jsonify(success_object(serialize_claim(cl))), 200
