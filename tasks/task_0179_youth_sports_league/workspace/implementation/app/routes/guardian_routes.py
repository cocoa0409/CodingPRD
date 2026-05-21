"""Guardian endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_roles
from ..errors import raise_error
from ..response import success_response
from ..services.lookup import get_guardian
from ..services.serializers import serialize_guardian
from ..store import get_store, new_id, stamp_create
from ..validation import as_string, get_json_body, require_fields

guardian_bp = Blueprint("guardians", __name__)


@guardian_bp.route("/league/guardians", methods=["POST"])
@require_roles(["LeagueAdmin", "Guardian"])
def create_guardian():
    body = get_json_body()
    require_fields(body, ["full_name", "email", "phone"])
    full_name = as_string(body["full_name"], "full_name", min_len=1, max_len=160)
    email = as_string(body["email"], "email", min_len=3, max_len=200)
    phone = as_string(body["phone"], "phone", min_len=1, max_len=32)

    store = get_store()
    for gn in store.guardians.values():
        if gn["email"] == email:
            raise_error("ERR_VALIDATION", "Guardian email already exists.")

    guardian = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "volunteer_hours_logged": Decimal("0.00"),
        "volunteer_status": "DEFICIENT",
    }
    stamp_create(guardian)
    store.guardians[guardian["id"]] = guardian
    store.record_audit("Guardian", guardian["id"], g.role, g.user_id, "GUARDIAN_CREATED", {})
    return success_response(serialize_guardian(guardian), status_code=201)


@guardian_bp.route("/league/guardians/<guardian_id>", methods=["GET"])
@require_roles(["LeagueAdmin", "Guardian"])
def read_guardian(guardian_id: str):
    store = get_store()
    # Existence first.
    guardian = store.guardians.get(guardian_id)
    if guardian is None:
        # PRD uses ERR_REFERENCE_NOT_FOUND for guardians (no dedicated existence error in scaffold).
        raise_error("ERR_REFERENCE_NOT_FOUND", "Guardian not found.")
    # Guardians may only read their own record.
    if g.role == "Guardian" and g.user_id != guardian_id:
        raise_error("ERR_NOT_OWNER")
    return success_response(serialize_guardian(guardian), status_code=200)
