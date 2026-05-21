"""Employer routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..common import bump, check_occ, get_json_body, positive_int, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import employer_view
from ..store import store


bp = Blueprint("employers", __name__, url_prefix="/transit/employers")


@bp.post("")
@require_auth("AgencyOfficer")
def create_employer():
    body = get_json_body()
    require_fields(body, "legal_name", "monthly_contribution_cap_cents")
    legal_name = body["legal_name"]
    if not isinstance(legal_name, str) or not legal_name.strip():
        raise ApiError("ERR_VALIDATION", "legal_name is required")
    cap = positive_int(body["monthly_contribution_cap_cents"], "monthly_contribution_cap_cents", allow_zero=True)

    with store.lock:
        emp = {
            "legal_name": legal_name,
            "enrollment_status": "ACTIVE",
            "monthly_contribution_cap_cents": cap,
        }
        stamp_new(emp)
        store.employers[emp["id"]] = emp
    return respond(employer_view(emp), 201)


@bp.post("/<employer_id>/suspend")
@require_auth("AgencyOfficer")
def suspend_employer(employer_id: str):
    body = get_json_body()
    with store.lock:
        emp = store.employers.get(employer_id)
        if emp is None:
            raise ApiError("ERR_NOT_FOUND", "Employer not found")
        if emp["enrollment_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Employer is not ACTIVE")
        check_occ(emp, body.get("version"))
        emp["enrollment_status"] = "SUSPENDED"
        bump(emp)
        # Cascade: every FSA account for this employer ACTIVE -> FROZEN
        for acc in store.fsa_accounts.values():
            if acc.get("employer_id") == employer_id and acc.get("status") == "ACTIVE":
                acc["status"] = "FROZEN"
                bump(acc)
    return respond(employer_view(emp), 200)
