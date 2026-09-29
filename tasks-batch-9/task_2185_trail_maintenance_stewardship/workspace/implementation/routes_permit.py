"""Work permits: request, decision (issue / deny) and revocation."""

from flask import Blueprint, request

import calc
import domain
import store
import validation as v
from auth import ALL_ROLES, actor, require
from envelope import created, ok, paginate
from errors import fail
from store import new_entity, touch

bp = Blueprint("permit", __name__)

PERMIT_STATUSES = ("REQUESTED", "ISSUED", "DENIED", "CONSUMED", "EXPIRED", "REVOKED")


@bp.post("/work-permits")
@require("CrewLeader")
def create_permit():
    data = v.body()
    work_plan_id = v.req_id(data, "work_plan_id")
    trail_segment_id = v.req_id(data, "trail_segment_id")
    window_start_date = v.req_date(data, "window_start_date")
    window_end_date = v.req_date(data, "window_end_date")
    requested_work_types = v.req_enum_array(data, "requested_work_types", calc.WORK_TYPES)
    if window_end_date < window_start_date:
        fail("ERR_INVALID_REQUEST", "window_end_date must be on or after window_start_date.")

    plan = domain.get_plan(work_plan_id)
    segment = domain.get_segment(trail_segment_id)

    agreement = domain.plan_agreement(plan)
    if agreement is None or agreement["status"] != "ACTIVE":
        fail("ERR_ADOPTION_NOT_ACTIVE", "The governing adoption is not ACTIVE.")
    if plan["status"] != "APPROVED":
        fail("ERR_WORK_PLAN_NOT_APPROVED", "The governing work plan is not APPROVED.")

    manager = domain.segment_manager(segment)
    lead_days = (window_start_date - store.clock_date()).days
    if lead_days < int(manager["permit_lead_days"]):
        fail("ERR_PERMIT_LEAD_TIME_INSUFFICIENT",
             "The permit request does not meet the agency lead-time rule.")

    permit = new_entity({
        "work_plan_id": work_plan_id,
        "trail_segment_id": trail_segment_id,
        "land_manager_id": segment["land_manager_id"],
        "window_start_date": store.fmt_date(window_start_date),
        "window_end_date": store.fmt_date(window_end_date),
        "requested_work_types": list(requested_work_types),
        "allowed_work_types": None,
        "max_party_size": None,
        "status": "REQUESTED",
        "issued_by_user_id": None,
        "issued_at": None,
        "denial_reason": None,
        "revocation_reason": None,
        "consumed_party_count": 0,
    })
    store.permits[permit["id"]] = permit
    return created(domain.s_permit(permit))


@bp.get("/work-permits/<entity_id>")
@require(*ALL_ROLES)
def read_permit(entity_id):
    return ok(domain.s_permit(domain.get_permit(entity_id)))


@bp.get("/work-permits")
@require(*ALL_ROLES)
def list_permits():
    work_plan_id = request.args.get("work_plan_id")
    trail_segment_id = request.args.get("trail_segment_id")
    land_manager_id = request.args.get("land_manager_id")
    status = request.args.get("status")
    if status is not None and status not in PERMIT_STATUSES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a declared member.")
    rows = store.ordered(list(store.permits.values()))
    if work_plan_id is not None:
        rows = [r for r in rows if r["work_plan_id"] == work_plan_id]
    if trail_segment_id is not None:
        rows = [r for r in rows if r["trail_segment_id"] == trail_segment_id]
    if land_manager_id is not None:
        rows = [r for r in rows if r["land_manager_id"] == land_manager_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, domain.s_permit)


@bp.post("/work-permits/<entity_id>/decision")
@require("LandManagerOfficer")
def decide_permit(entity_id):
    permit = domain.get_permit(entity_id)
    if actor() != permit["land_manager_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the governing land manager may decide this permit.")

    data = v.body()
    decision = v.req_enum(data, "decision", ("ISSUE", "DENY"))
    allowed_work_types = None
    max_party_size = None
    denial_reason = None
    if decision == "ISSUE":
        allowed_work_types = v.req_enum_array(data, "allowed_work_types", calc.WORK_TYPES)
        max_party_size = v.req_int(data, "max_party_size", minimum=1)
    else:
        denial_reason = v.req_str(data, "denial_reason")

    if permit["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED permit may be decided.")

    segment = domain.get_segment(permit["trail_segment_id"])
    manager = domain.segment_manager(segment)

    if decision == "ISSUE":
        if segment["posture"] == "INCIDENT_CLOSED":
            fail("ERR_SEGMENT_CLOSED", "The segment is closed by an incident.")
        requested = set(permit["requested_work_types"])
        if not set(allowed_work_types).issubset(requested):
            fail("ERR_INVALID_REQUEST",
                 "allowed_work_types must be a subset of requested_work_types.")
        if max_party_size > int(manager["max_party_size"]):
            fail("ERR_INVALID_REQUEST",
                 "max_party_size exceeds the agency ceiling.")
        permit["status"] = "ISSUED"
        permit["allowed_work_types"] = list(allowed_work_types)
        permit["max_party_size"] = max_party_size
        permit["issued_by_user_id"] = actor()
        permit["issued_at"] = store.now_iso()
        touch(permit)
        for party in domain.parties_of_permit(permit):
            domain.try_clear(party)
    else:
        permit["status"] = "DENIED"
        permit["denial_reason"] = denial_reason
        permit["issued_by_user_id"] = actor()
        touch(permit)
        domain.block_parties_for_permit(permit, "PERMIT_REVOKED", suspend_confirmed=False)

    return ok(domain.s_permit(permit))


@bp.post("/work-permits/<entity_id>/revoke")
@require("LandManagerOfficer")
def revoke_permit(entity_id):
    permit = domain.get_permit(entity_id)
    if actor() != permit["land_manager_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the governing land manager may revoke this permit.")

    data = v.body()
    revocation_reason = v.req_str(data, "revocation_reason")

    if permit["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Only an ISSUED permit may be revoked.")

    permit["status"] = "REVOKED"
    permit["revocation_reason"] = revocation_reason
    touch(permit)
    domain.block_parties_for_permit(permit, "PERMIT_REVOKED", suspend_confirmed=True)
    return ok(domain.s_permit(permit))
