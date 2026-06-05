"""Candidate routes + candidate sub-resource (clep-claims)."""
from flask import Blueprint, request

from db import store, stamp_create
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import object_response, array_response
from services import lookups, serializers
from services.common import (get_json_body, require_fields, parse_pagination,
                             paginate, sort_by_created_at)

bp = Blueprint("candidates", __name__)


@bp.route("/candidates", methods=["POST"])
@require_roles("Candidate")
def create_candidate():
    body = get_json_body()
    require_fields(body, ["legal_first_name", "legal_last_name", "date_of_birth",
                          "home_state_code", "id_document_state_code"])

    for f in ["legal_first_name", "legal_last_name", "date_of_birth",
              "home_state_code", "id_document_state_code"]:
        if not isinstance(body[f], str):
            raise err(ERR_INVALID_REQUEST, f"{f} must be a string")

    has_504 = body.get("has_active_504_iep", False)
    if has_504 is None:
        has_504 = False
    if not isinstance(has_504, bool):
        raise err(ERR_INVALID_REQUEST, "has_active_504_iep must be a boolean")

    candidate = {
        "legal_first_name": body["legal_first_name"],
        "legal_last_name": body["legal_last_name"],
        "date_of_birth": body["date_of_birth"],
        "home_state_code": body["home_state_code"],
        "id_document_state_code": body["id_document_state_code"],
        "has_active_504_iep": has_504,
    }
    stamp_create(candidate)
    store.candidates[candidate["id"]] = candidate
    return object_response(serializers.candidate(candidate), 201)


@bp.route("/candidates/<cid>", methods=["GET"])
@require_roles("Candidate", "TestCenterAdmin", "ScoreOps", "AccommodationReviewer")
def get_candidate(cid):
    candidate = lookups.candidate(cid)
    return object_response(serializers.candidate(candidate), 200)


@bp.route("/candidates/<cid>/clep-claims", methods=["GET"])
@require_roles("Candidate", "ScoreOps")
def list_candidate_clep_claims(cid):
    lookups.candidate(cid)  # existence check on path id
    limit, offset = parse_pagination()
    status = request.args.get("status")

    items = [c for c in store.clep_claims.values() if c["candidate_id"] == cid]
    if status is not None:
        items = [c for c in items if c["status"] == status]

    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serializers.clep_claim(c) for c in page],
                          limit, offset, total, 200)
