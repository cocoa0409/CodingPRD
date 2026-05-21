"""Resident routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..errors import ApiError
from ..responses import success_response
from ..services.calculations import recompute_violation_count_12mo
from ..services.entities import get_resident_or_404, init_common_fields
from ..services.serialization import serialize_resident
from ..store import store
from ..validation import get_json_body, require_email, require_string


bp = Blueprint("residents", __name__)


@bp.route("/residents", methods=["POST"])
@require_auth("ParkManager", "PlatformAdmin")
def create_resident():
    body = get_json_body()
    full_name = require_string(body, "full_name", min_len=1, max_len=120)
    email = require_email(body, "email")

    with store.lock:
        for r in store.residents.values():
            if r["email"] == email:
                raise ApiError("ERR_VALIDATION", f"Email {email} is already in use.")
        resident = init_common_fields({
            "full_name": full_name,
            "email": email,
            "violation_count_12mo": 0,
        })
        store.residents[resident["id"]] = resident

    return success_response(serialize_resident(resident), status=201)


@bp.route("/residents/<resident_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_resident(resident_id: str):
    resident = get_resident_or_404(resident_id)
    recompute_violation_count_12mo(resident)
    return success_response(serialize_resident(resident), status=200)


__all__ = ["bp"]
