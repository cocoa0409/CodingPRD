"""Referee endpoints — registration only."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_roles
from ..errors import raise_error
from ..response import success_response
from ..services.serializers import serialize_referee
from ..store import get_store, new_id, stamp_create
from ..validation import as_enum, as_int, as_string, get_json_body, require_fields

referee_bp = Blueprint("referees", __name__)

CERT_LEVELS = {"LEVEL_1", "LEVEL_2", "LEVEL_3"}


@referee_bp.route("/league/referees", methods=["POST"])
@require_roles(["LeagueAdmin"])
def create_referee():
    body = get_json_body()
    require_fields(body, ["full_name", "email", "certification_level"])
    full_name = as_string(body["full_name"], "full_name", min_len=1, max_len=200)
    email = as_string(body["email"], "email", min_len=3, max_len=200)
    cert = as_enum(body["certification_level"], "certification_level", CERT_LEVELS)
    cap = 5
    if "weekly_assignment_cap" in body and body["weekly_assignment_cap"] is not None:
        cap = as_int(body["weekly_assignment_cap"], "weekly_assignment_cap", minimum=1, maximum=20)

    store = get_store()
    for r in store.referees.values():
        if r["email"] == email:
            raise_error("ERR_VALIDATION", "Referee email already exists.")

    ref = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "certification_level": cert,
        "weekly_assignment_cap": cap,
        "active": True,
    }
    stamp_create(ref)
    store.referees[ref["id"]] = ref
    store.record_audit("Referee", ref["id"], g.role, g.user_id, "REFEREE_CREATED", {})
    return success_response(serialize_referee(ref), status_code=201)
