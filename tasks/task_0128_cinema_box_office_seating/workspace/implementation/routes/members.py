"""Member endpoints (PRD §3.3). Registration is the only Anonymous-reachable op."""
from __future__ import annotations

from flask import Blueprint

import db
import errors as E
from middleware import (
    authenticate, authorize,
    CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER, ANONYMOUS,
)
import response
from services import common as C
from routes._helpers import get_or_404, require_member_owns_member

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    # POST /members is reachable by Anonymous, CinemaManager, BoxOfficeAgent.
    # Per PRD §2.1 this is the only endpoint reachable without authentication;
    # we therefore do NOT require auth headers here. If headers are supplied they
    # must still name a recognized, permitted role.
    from flask import request
    role = request.headers.get("X-User-Role")
    if role is not None:
        actor = authenticate()
        authorize(actor, {ANONYMOUS, CINEMA_MANAGER, BOX_OFFICE_AGENT})

    body = C.get_body()
    C.require_fields(body, ["email", "full_name"])
    email = C.require_str(body, "email")
    full_name = C.require_str(body, "full_name")

    member = C.new_common_fields()
    member.update({
        "email": email,
        "full_name": full_name,
        "loyalty_points": 0,
        "tier": "BRONZE",
        "wallet_credit_cents": 0,
    })
    db.members[member["id"]] = member
    return response.ok_object(C.serialize(member), 201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    role = authenticate()
    authorize(role, {MEMBER, CINEMA_MANAGER, BOX_OFFICE_AGENT})
    member = get_or_404(db.members, member_id, "Member")
    require_member_owns_member(member_id)
    return response.ok_object(C.serialize(member), 200)
