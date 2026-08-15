"""Candidate routes."""

from flask import Blueprint, request, g

from db import db
from errors import (
    err_validation,
    err_duplicate_email,
    err_forbidden,
)
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_candidate,
    candidate_view,
    application_view,
)
from utils import (
    parse_pagination,
    require_string,
    require_timestamp,
    stamp_new,
)

bp = Blueprint("candidates", __name__)


@bp.route("/candidates", methods=["POST"])
@require_auth(["Anonymous"])
def register_candidate():
    payload = request.get_json(silent=True) or {}
    email = require_string(payload, "email")
    full_name = require_string(payload, "full_name")
    expected_graduation_date = require_timestamp(payload, "expected_graduation_date")
    email_norm = email.lower()
    for c in db.candidates.values():
        if c["email"].lower() == email_norm:
            raise err_duplicate_email()
    c = {
        "email": email,
        "full_name": full_name,
        "_expected_graduation_date": expected_graduation_date,
        "is_alumnus": False,
    }
    stamp_new(c)
    db.candidates[c["id"]] = c
    return success_object(candidate_view(c), 201)


@bp.route("/candidates/<cid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Candidate"])
def get_one_candidate(cid):
    c = get_candidate(cid)
    # Ownership: Candidate reads only own
    if g.role == "Candidate" and g.user_id != c["id"]:
        raise err_forbidden("Candidate may read only its own record")
    return success_object(candidate_view(c))


@bp.route("/candidates/<cid>/applications", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Candidate"])
def list_candidate_applications(cid):
    c = get_candidate(cid)
    if g.role == "Candidate" and g.user_id != c["id"]:
        raise err_forbidden("Candidate may read only its own applications")
    limit, offset = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    items = [
        a for a in db.applications.values()
        if a["candidate_id"] == cid
        and (season_id is None or a["season_id"] == season_id)
        and (status is None or a["status"] == status)
    ]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([application_view(a) for a in page], total, limit, offset)
