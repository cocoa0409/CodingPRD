"""CorporateGroup endpoints (PRD §3.7)."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_role
from response import object_response, array_response
from services.common import (base_record, touch, get_or_404, find_fk_or_404,
                             require_org_active, get_json, require_field,
                             require_int, list_collection)
from services.serialize import serialize, serialize_list
from services.domain import occupy_seat

bp = Blueprint("corporate_groups", __name__)
COLL = "corporate_groups"


@bp.post("/vm/corporate-groups")
@require_role("CorporateSponsor", "ShiftCoordinator")
def create_corporate_group():
    body = get_json()
    opportunity_id = require_field(body, "opportunity_id", str)
    sponsor_name = require_field(body, "sponsor_name", str)
    requested_seats = require_field(body, "requested_seats")
    target_shift_id = require_field(body, "target_shift_id", str)
    if isinstance(requested_seats, bool) or not isinstance(requested_seats, int):
        raise ApiError("ERR_INVALID_REQUEST", "requested_seats must be an integer")
    with store.lock:
        opp = find_fk_or_404("opportunities", opportunity_id)
        shift = find_fk_or_404("shifts", target_shift_id)
        org = store.organizations.get(opp["organization_id"])
        if org is not None:
            require_org_active(org)
        if requested_seats < 1:
            raise ApiError("ERR_INVALID_SEATS", "requested_seats must be >= 1")
        rec = base_record(COLL)
        rec.update({
            "opportunity_id": opportunity_id,
            "sponsor_name": sponsor_name,
            "requested_seats": requested_seats,
            "target_shift_id": target_shift_id,
            "status": "PROPOSED",
            "allocated_seat_count": 0,
        })
        store.corporate_groups[rec["id"]] = rec
    return object_response(serialize(COLL, rec), status=201)


@bp.get("/vm/corporate-groups")
@require_role("CorporateSponsor", "ComplianceOfficer", "ShiftCoordinator")
def list_corporate_groups():
    opportunity_id = request.args.get("opportunity_id")
    target_shift_id = request.args.get("target_shift_id")
    status = request.args.get("status")

    def pred(r):
        if opportunity_id is not None and r["opportunity_id"] != opportunity_id:
            return False
        if target_shift_id is not None and r["target_shift_id"] != target_shift_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    page, limit, offset, total = list_collection(COLL, pred)
    return array_response(serialize_list(COLL, page), limit, offset, total)


@bp.get("/vm/corporate-groups/<group_id>")
@require_role("CorporateSponsor", "ComplianceOfficer", "ShiftCoordinator")
def get_corporate_group(group_id):
    rec = get_or_404(COLL, group_id)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/corporate-groups/<group_id>/approve")
@require_role("ShiftCoordinator")
def approve_corporate_group(group_id):
    with store.lock:
        rec = get_or_404(COLL, group_id)
        if rec["status"] != "PROPOSED":
            raise ApiError("ERR_GROUP_NOT_PROPOSED", "approve requires PROPOSED")
        opp = store.opportunities.get(rec["opportunity_id"])
        if opp is None or not opp["is_group_event"]:
            raise ApiError("ERR_OPPORTUNITY_NOT_GROUP_EVENT",
                           "parent opportunity is not a group event")
        if opp["publication_status"] != "PUBLISHED":
            raise ApiError("ERR_OPPORTUNITY_NOT_PUBLISHED",
                           "parent opportunity is not PUBLISHED")
        rec["status"] = "APPROVED"
        touch(rec)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/corporate-groups/<group_id>/reject")
@require_role("ShiftCoordinator")
def reject_corporate_group(group_id):
    with store.lock:
        rec = get_or_404(COLL, group_id)
        if rec["status"] != "PROPOSED":
            raise ApiError("ERR_GROUP_NOT_PROPOSED", "reject requires PROPOSED")
        rec["status"] = "REJECTED"
        touch(rec)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/corporate-groups/<group_id>/allocate")
@require_role("ShiftCoordinator")
def allocate_corporate_group(group_id):
    body = get_json()
    expected_shift_version = require_int(body, "expected_shift_version")
    with store.lock:
        rec = get_or_404(COLL, group_id)
        shift = store.shifts.get(rec["target_shift_id"])
        if shift is None:
            raise ApiError("ERR_SHIFT_NOT_FOUND", "target shift not found")
        # OCC on the target shift precedes the state/capacity checks (PRD §3.7).
        if shift["version"] != expected_shift_version:
            raise ApiError("ERR_STALE_SHIFT_VERSION",
                           "expected_shift_version does not match")
        if rec["status"] != "APPROVED":
            raise ApiError("ERR_GROUP_NOT_APPROVED", "allocate requires APPROVED")
        if shift["status"] != "OPEN":
            raise ApiError("ERR_SHIFT_NOT_OPEN", "target shift is not OPEN")
        seats = rec["requested_seats"]
        if (shift["capacity"] - shift["reserved_count"]) < seats:
            raise ApiError("ERR_INSUFFICIENT_SHIFT_CAPACITY",
                           "insufficient remaining capacity")
        # create requested_seats group-placeholder signups, each occupying a seat
        for _ in range(seats):
            sgn = base_record("signups")
            sgn.update({
                "shift_id": shift["id"],
                "volunteer_id": None,
                "corporate_group_id": rec["id"],
                "status": "RESERVED",
                "logged_hours": None,
                "verified_hours": None,
                "provisional_hours": 0,
            })
            store.signups[sgn["id"]] = sgn
            shift["reserved_count"] += 1
            shift["group_reserved_seats"] += 1
            touch(shift)  # increments shift.version by one per created signup
        sync_state(shift)
        rec["status"] = "ALLOCATED"
        rec["allocated_seat_count"] = seats
        touch(rec)
    return object_response(serialize(COLL, rec))


def sync_state(shift):
    from services.domain import sync_shift_full_state
    sync_shift_full_state(shift)


@bp.post("/vm/corporate-groups/<group_id>/cancel")
@require_role("CorporateSponsor")
def cancel_corporate_group(group_id):
    with store.lock:
        rec = get_or_404(COLL, group_id)
        if rec["status"] not in ("PROPOSED", "APPROVED"):
            raise ApiError("ERR_GROUP_NOT_CANCELLABLE", "cancel requires PROPOSED/APPROVED")
        rec["status"] = "CANCELLED"
        touch(rec)
    return object_response(serialize(COLL, rec))
