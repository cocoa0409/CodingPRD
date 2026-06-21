"""Organization endpoints (PRD §3.1, §2.9)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_role
from response import object_response, array_response
from services.common import (base_record, touch, get_or_404, get_json,
                             require_field, optional_field, require_int,
                             list_collection)
from services.serialize import serialize, serialize_list

bp = Blueprint("organizations", __name__)
COLL = "organizations"


@bp.post("/vm/organizations")
@require_role("ComplianceOfficer", "ShiftCoordinator")
def create_organization():
    body = get_json()
    name = require_field(body, "name", str)
    threshold = optional_field(body, "reliability_suspension_threshold", 40, int)
    strike_limit = optional_field(body, "no_show_strike_limit", 3, int)
    if isinstance(threshold, bool) or isinstance(strike_limit, bool):
        raise ApiError("ERR_INVALID_REQUEST", "threshold fields must be integers")
    with store.lock:
        rec = base_record(COLL)
        rec.update({
            "name": name,
            "reliability_suspension_threshold": threshold,
            "no_show_strike_limit": strike_limit,
            "status": "ACTIVE",
        })
        store.organizations[rec["id"]] = rec
    return object_response(serialize(COLL, rec), status=201)


@bp.get("/vm/organizations")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator", "CorporateSponsor")
def list_organizations():
    from flask import request
    status = request.args.get("status")

    def pred(r):
        return status is None or r["status"] == status

    page, limit, offset, total = list_collection(COLL, pred)
    return array_response(serialize_list(COLL, page), limit, offset, total)


@bp.get("/vm/organizations/<org_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator", "CorporateSponsor")
def get_organization(org_id):
    rec = get_or_404(COLL, org_id)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/organizations/<org_id>/archive")
@require_role("ComplianceOfficer")
def archive_organization(org_id):
    body = get_json()
    expected = require_int(body, "expected_organization_version")
    with store.lock:
        rec = get_or_404(COLL, org_id)
        if rec["version"] != expected:
            raise ApiError("ERR_STALE_ORGANIZATION_VERSION",
                           "expected_organization_version does not match")
        rec["status"] = "ARCHIVED"
        touch(rec)
    return object_response(serialize(COLL, rec))
