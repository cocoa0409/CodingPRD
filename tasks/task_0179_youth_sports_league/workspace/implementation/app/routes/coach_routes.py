"""Coach endpoints — registration only."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_roles
from ..errors import raise_error
from ..response import success_response
from ..services.serializers import serialize_coach
from ..store import get_store, new_id, stamp_create
from ..validation import as_bool, as_string, get_json_body, require_fields

coach_bp = Blueprint("coaches", __name__)


@coach_bp.route("/league/coaches", methods=["POST"])
@require_roles(["LeagueAdmin"])
def create_coach():
    body = get_json_body()
    require_fields(body, ["full_name", "email"])
    full_name = as_string(body["full_name"], "full_name", min_len=1, max_len=160)
    email = as_string(body["email"], "email", min_len=3, max_len=200)
    bg = False
    if "background_check_passed" in body and body["background_check_passed"] is not None:
        bg = as_bool(body["background_check_passed"], "background_check_passed")

    store = get_store()
    for c in store.coaches.values():
        if c["email"] == email:
            raise_error("ERR_VALIDATION", "Coach email already exists.")

    coach = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "background_check_passed": bg,
    }
    stamp_create(coach)
    store.coaches[coach["id"]] = coach
    store.record_audit("Coach", coach["id"], g.role, g.user_id, "COACH_CREATED", {})
    return success_response(serialize_coach(coach), status_code=201)
