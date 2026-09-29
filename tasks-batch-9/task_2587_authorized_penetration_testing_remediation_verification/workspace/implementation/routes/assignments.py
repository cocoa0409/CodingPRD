"""Tester assignments, least-privilege access and the hour ledger (PRD 3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import core
import serialize
from auth import authorize
from core import new_record, recompute_hours, revoke_assignment, touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_asset, get_assignment, get_engagement, get_tester, paginate
from store import store
from util import dec, q2
from validate import (
    body,
    get_datetime,
    get_enum,
    get_int,
    get_number,
    get_str,
    get_str_array,
)

bp = Blueprint("assignments", __name__)

ASSIGNMENT_ROLES = ("LEAD", "MEMBER")
ACCESS_ACTIONS = ("PROVISION", "REVOKE")
READ_ROLES = ("ProgramManager", "ComplianceOfficer", "PlatformAdmin", "Tester")
LIVE_ACCESS_STATES = ("REQUESTED", "PROVISIONED")


@bp.post("/tester-assignments")
def request_assignment():
    authorize("ProgramManager")
    data = body()
    engagement_id = get_str(data, "engagement_id")
    tester_id = get_str(data, "tester_id")
    assignment_role = get_enum(data, "assignment_role", ASSIGNMENT_ROLES)
    start_raw, interval_start = get_datetime(data, "interval_start")
    end_raw, interval_end = get_datetime(data, "interval_end")
    hours = get_number(data, "requested_hours", minimum=0, exclusive_min=True, maximum=400)
    granted = get_str_array(data, "granted_asset_ids", required=True, min_len=0, max_len=20)
    expected_version = get_int(data, "expected_engagement_version")
    if not interval_end > interval_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "interval_end must fall strictly after interval_start."
        )
    engagement = get_engagement(engagement_id)
    tester = get_tester(tester_id)
    for asset_id in granted:
        get_asset(asset_id)
    if expected_version != engagement["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")
    if interval_start < engagement["window_start"] or interval_end > engagement["window_end"]:
        raise ApiError("ERR_INTERVAL_OUTSIDE_WINDOW")
    overlapping = 0
    for other in store.assignments.values():
        if other["tester_id"] != tester["id"]:
            continue
        if other["access_state"] not in LIVE_ACCESS_STATES:
            continue
        if other["interval_start"] < interval_end and other["interval_end"] > interval_start:
            overlapping += 1
    if overlapping >= tester["max_concurrent_engagements"]:
        raise ApiError("ERR_TESTER_CAPACITY_EXCEEDED")
    if assignment_role == "LEAD" and tester["qualification_score"] < calc.LEAD_MIN_SCORE:
        raise ApiError("ERR_LEAD_QUALIFICATION_NOT_MET")
    if hours > dec(engagement["hours_available"]):
        raise ApiError("ERR_ENGAGEMENT_HOURS_EXCEEDED")
    record = new_record(
        engagement_id=engagement["id"],
        tester_id=tester["id"],
        assignment_role=assignment_role,
        interval_start=interval_start,
        interval_start_raw=start_raw,
        interval_end=interval_end,
        interval_end_raw=end_raw,
        requested_hours=hours,
        granted_asset_ids=granted,
        access_state="REQUESTED",
        provisioned_at=None,
        revoked_at=None,
        settled_hours=Decimal("0"),
    )
    store.assignments[record["id"]] = record
    engagement["hours_reserved"] = q2(dec(engagement["hours_reserved"]) + hours)
    recompute_hours(engagement)
    touch(engagement)
    return object_response(serialize.assignment(record), 201)


@bp.get("/tester-assignments/<assignment_id>")
def read_assignment(assignment_id):
    authorize(*READ_ROLES)
    return object_response(serialize.assignment(get_assignment(assignment_id)))


@bp.get("/tester-assignments")
def list_assignments():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.assignments.values()),
        engagement_id=request.args.get("engagement_id"),
        tester_id=request.args.get("tester_id"),
        access_state=request.args.get("access_state"),
    )
    return paginate(rows, serialize.assignment)


@bp.post("/tester-assignments/<assignment_id>/access")
def move_access(assignment_id):
    authorize("ProgramManager")
    assignment = get_assignment(assignment_id)
    data = body()
    action = get_enum(data, "action", ACCESS_ACTIONS)
    engagement = store.engagements[assignment["engagement_id"]]
    if engagement["authorization_state"] == "SUSPENDED":
        raise ApiError("ERR_ENGAGEMENT_SUSPENDED")
    if action == "PROVISION" and engagement["authorization_state"] != "AUTHORIZED":
        raise ApiError("ERR_ENGAGEMENT_NOT_AUTHORIZED")
    if action == "PROVISION":
        if assignment["access_state"] != "REQUESTED":
            raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")
    else:
        if assignment["access_state"] not in LIVE_ACCESS_STATES:
            raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")
    tester = store.testers[assignment["tester_id"]]
    now = store.now()
    if action == "PROVISION":
        if tester["background_check_status"] != "CLEARED":
            raise ApiError("ERR_TESTER_NOT_CLEARED")
        if not tester["clearance_expires_at"] > now:
            raise ApiError("ERR_CLEARANCE_EXPIRED")
        roe = core.live_roe(engagement["id"])
        authorized_assets = set()
        if roe is not None:
            for target in core.roe_targets(roe["id"]):
                if target["state"] == "ACTIVE":
                    authorized_assets.add(target["asset_id"])
        if not set(assignment["granted_asset_ids"]).issubset(authorized_assets):
            raise ApiError("ERR_GRANT_EXCEEDS_AUTHORIZED_SCOPE")
        assignment["access_state"] = "PROVISIONED"
        assignment["provisioned_at"] = now
        touch(assignment)
        tester["active_assignment_count"] = tester["active_assignment_count"] + 1
        if tester["availability_state"] == "AVAILABLE":
            tester["availability_state"] = "ASSIGNED"
        touch(tester)
        touch(engagement)
    else:
        revoke_assignment(assignment)
    return object_response(serialize.assignment(assignment))
