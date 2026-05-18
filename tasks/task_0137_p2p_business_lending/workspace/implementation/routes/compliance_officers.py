"""ComplianceOfficer endpoints: register, get."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_invalid_request
from middleware import require_auth
from response import success
from routes._helpers import get_compliance_officer, get_json, get_platform
from services.engine import stamp_create
from services.serializers import serialize_compliance_officer

bp = Blueprint("compliance_officers", __name__)


@bp.post("/platforms/<platform_id>/compliance_officers")
@require_auth(["PlatformOperator"])
def create_compliance_officer(platform_id):
    get_platform(platform_id)
    body = get_json()
    display_name = body.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise err_invalid_request("display_name is required.")
    with store.lock:
        officer = {
            "platform_id": platform_id,
            "display_name": display_name,
            "status": "ACTIVE",
        }
        stamp_create(officer)
        store.compliance_officers[officer["id"]] = officer
    return success(serialize_compliance_officer(officer), 201)


@bp.get("/platforms/<platform_id>/compliance_officers/<officer_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer"])
def get_officer(platform_id, officer_id):
    o = get_compliance_officer(platform_id, officer_id)
    return success(serialize_compliance_officer(o))
