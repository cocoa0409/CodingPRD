"""Volunteer endpoints (PRD §3.1). Email uniqueness within org over status IN
{ACTIVE, SUSPENDED}; GET applies lazy bg-tier expiry."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_role
from response import object_response, array_response
from services.common import (base_record, touch, get_or_404, find_fk_or_404,
                             require_org_active, get_json, require_field,
                             require_int, list_collection)
from services.serialize import serialize, serialize_list
from services.domain import apply_bg_expiry

bp = Blueprint("volunteers", __name__)
COLL = "volunteers"


@bp.post("/vm/volunteers")
@require_role("ComplianceOfficer", "ShiftCoordinator")
def create_volunteer():
    body = get_json()
    org_id = require_field(body, "organization_id", str)
    full_name = require_field(body, "full_name", str)
    email = require_field(body, "email", str)
    with store.lock:
        org = find_fk_or_404("organizations", org_id)
        require_org_active(org)
        # email unique within org over ACTIVE/SUSPENDED volunteers
        for v in store.volunteers.values():
            if (v["organization_id"] == org_id and v["email"] == email
                    and v["status"] in ("ACTIVE", "SUSPENDED")):
                raise ApiError("ERR_INVALID_REQUEST",
                               "email already in use within organization")
        rec = base_record(COLL)
        rec.update({
            "organization_id": org_id,
            "full_name": full_name,
            "email": email,
            "status": "ACTIVE",
            "bg_check_tier": "NONE",
            "lifetime_no_show_count": 0,
            "total_verified_hours": 0,
            "reliability_score": 100,
            "milestone_tier": "NONE",
        })
        store.volunteers[rec["id"]] = rec
    return object_response(serialize(COLL, rec), status=201)


@bp.get("/vm/volunteers")
@require_role("ComplianceOfficer", "ShiftCoordinator")
def list_volunteers():
    org_id = request.args.get("organization_id")
    status = request.args.get("status")

    def pred(r):
        if org_id is not None and r["organization_id"] != org_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    page, limit, offset, total = list_collection(COLL, pred)
    return array_response(serialize_list(COLL, page), limit, offset, total)


@bp.get("/vm/volunteers/<volunteer_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def get_volunteer(volunteer_id):
    with store.lock:
        rec = get_or_404(COLL, volunteer_id)
        apply_bg_expiry(rec)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/volunteers/<volunteer_id>/withdraw")
@require_role("ComplianceOfficer")
def withdraw_volunteer(volunteer_id):
    body = get_json()
    expected = require_int(body, "expected_volunteer_version")
    with store.lock:
        rec = get_or_404(COLL, volunteer_id)
        if rec["version"] != expected:
            raise ApiError("ERR_STALE_VOLUNTEER_VERSION",
                           "expected_volunteer_version does not match")
        rec["status"] = "WITHDRAWN"
        touch(rec)
    return object_response(serialize(COLL, rec))
