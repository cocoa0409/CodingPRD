"""PeerToPeerConference endpoints."""
from datetime import timedelta
from flask import Blueprint

import db
from db import now_iso
from errors import (
    ApiError, ERR_CASE_CLOSED, ERR_INVALID_STATE, ERR_P2P_NOT_ELIGIBLE,
    ERR_NOT_PHYSICIAN_ADVISOR, ERR_P2P_WINDOW_EXPIRED, ERR_SCHEDULING_OVERLAP,
    ERR_P2P_RESCHEDULE_LIMIT, ERR_VALIDATION_FAILED, ERR_BED_DAY_BUDGET_EXCEEDED,
)
from middleware import require_roles, check_attending_ownership
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.case_service import (
    maybe_expire_conference, recompute_certified_counts, case_frontier_end,
)
from services.clock import logical_now, parse_iso
from services.common import init_common, touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_int,
    validate_string, validate_datetime,
)

bp = Blueprint("p2p", __name__)

CREATE_FIELDS = ["advisor_physician_id", "scheduled_start_at", "scheduled_end_at"]
RESCHEDULE_FIELDS = ["scheduled_start_at", "scheduled_end_at"]
COMPLETE_FIELDS = ["outcome", "certified_day_count"]

MIN_DURATION = timedelta(minutes=15)
BUFFER = timedelta(minutes=15)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _denial_for_auth(auth_id):
    for d in db.denial_cases.values():
        if d["authorization_request_id"] == auth_id:
            return d
    return None


def _check_calendar_clearance(advisor_id, start, end, exclude_conf_id=None):
    """New conference must leave >= 15 min clearance from every SCHEDULED
    conference of the same advisor (exactly 15 minutes allowed)."""
    for other in db.peer_to_peer_conferences.values():
        if other["advisor_physician_id"] != advisor_id:
            continue
        if exclude_conf_id is not None and other["id"] == exclude_conf_id:
            continue
        maybe_expire_conference(other)
        if other["status"] != "SCHEDULED":
            continue
        o_start = parse_iso(other["scheduled_start_at"])
        o_end = parse_iso(other["scheduled_end_at"])
        # Buffered overlap: clearance on both sides
        if start < o_end + BUFFER and end > o_start - BUFFER:
            raise ApiError(ERR_SCHEDULING_OVERLAP,
                           "Advisor calendar conflict: less than 15 minutes clearance", 409)


def _check_shape(body):
    start = validate_datetime(body, "scheduled_start_at")
    end = validate_datetime(body, "scheduled_end_at")
    if end <= start:
        raise ApiError(ERR_VALIDATION_FAILED, "scheduled_end_at must be strictly after scheduled_start_at", 400)
    if end - start < MIN_DURATION:
        raise ApiError(ERR_VALIDATION_FAILED, "Conference duration must be at least 15 minutes", 400)
    return start, end


@bp.post("/api/authorization-requests/<aid>/peer-to-peer-conferences")
def create_conference(aid):
    user_id, role = require_roles(["AttendingPhysician"])
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    validate_string(body, "advisor_physician_id")
    start, end = _check_shape(body)

    ar = lookup(db.authorization_requests, aid, "AuthorizationRequest")
    case = db.utilization_cases[ar["case_id"]]
    payer = db.payers[case["payer_id"]]

    # Priority 5: attending ownership
    check_attending_ownership(case, user_id)
    # Priority 6: case-open gate
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    # Priority 10: P2P eligibility — parent auth must be DENIED
    if ar["status"] != "DENIED":
        raise ApiError(ERR_P2P_NOT_ELIGIBLE,
                       "Peer-to-peer requires the authorization request to be DENIED", 409)

    window_deadline = parse_iso(ar["decided_at"]) + timedelta(hours=payer["p2p_window_hours"])

    # Priority 15: window check
    if logical_now() > window_deadline or start > window_deadline:
        raise ApiError(ERR_P2P_WINDOW_EXPIRED,
                       "Logical now or scheduled_start_at is past the P2P window deadline", 422)
    # Priority 20: advisor calendar clearance
    _check_calendar_clearance(body["advisor_physician_id"], start, end)
    # Priority 26: advisor reference
    advisor = lookup(db.physicians, body["advisor_physician_id"], "Physician")
    if not advisor["is_advisor"]:
        raise ApiError(ERR_NOT_PHYSICIAN_ADVISOR,
                       "advisor_physician_id does not resolve to a Physician with is_advisor true", 422)

    conf = {
        **init_common(),
        "authorization_request_id": aid,
        "attending_physician_id": user_id,
        "advisor_physician_id": body["advisor_physician_id"],
        "scheduled_start_at": body["scheduled_start_at"],
        "scheduled_end_at": body["scheduled_end_at"],
        "window_deadline_at": _iso(window_deadline),
        "reschedule_count": 0,
        "status": "SCHEDULED",
        "outcome": "NONE",
    }
    db.peer_to_peer_conferences[conf["id"]] = conf

    denial = _denial_for_auth(aid)
    if denial is not None and denial["status"] == "OPEN":
        denial["status"] = "P2P_SCHEDULED"
        touch(denial)

    append_audit(case["id"], "P2P_SCHEDULED", role, user_id,
                 f"P2P conference {conf['id']} scheduled for auth {aid}")
    return success_object(conf, 201)


@bp.get("/api/authorization-requests/<aid>/peer-to-peer-conferences")
def list_conferences(aid):
    any_authenticated()
    lookup(db.authorization_requests, aid, "AuthorizationRequest")
    items = sorted(
        (c for c in db.peer_to_peer_conferences.values() if c["authorization_request_id"] == aid),
        key=lambda c: c["created_at"],
    )
    for c in items:
        maybe_expire_conference(c)
    return paginate(items)


@bp.get("/api/peer-to-peer-conferences/<cid>")
def get_conference(cid):
    any_authenticated()
    conf = lookup(db.peer_to_peer_conferences, cid, "PeerToPeerConference")
    maybe_expire_conference(conf)
    return success_object(conf)


@bp.post("/api/peer-to-peer-conferences/<cid>/reschedule")
def reschedule_conference(cid):
    user_id, role = require_roles(["AttendingPhysician"])
    body = get_json_body()
    reject_unknown_fields(body, RESCHEDULE_FIELDS)
    start, end = _check_shape(body)

    conf = lookup(db.peer_to_peer_conferences, cid, "PeerToPeerConference")
    maybe_expire_conference(conf)
    ar = db.authorization_requests[conf["authorization_request_id"]]
    case = db.utilization_cases[ar["case_id"]]

    # Priority 5: attending ownership
    check_attending_ownership(case, user_id)
    # Priority 6
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    # Priority 7: state legality
    if conf["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, f"Conference is {conf['status']}, not SCHEDULED", 409)
    # Priority 22: reschedule hard cap
    if conf["reschedule_count"] >= 2:
        raise ApiError(ERR_P2P_RESCHEDULE_LIMIT, "reschedule_count already equals 2", 409)
    # Priority 15: window re-applies
    window_deadline = parse_iso(conf["window_deadline_at"])
    if logical_now() > window_deadline or start > window_deadline:
        raise ApiError(ERR_P2P_WINDOW_EXPIRED,
                       "Logical now or new scheduled_start_at is past the P2P window deadline", 422)
    # Priority 20: calendar clearance re-applies
    _check_calendar_clearance(conf["advisor_physician_id"], start, end, exclude_conf_id=cid)

    conf["scheduled_start_at"] = body["scheduled_start_at"]
    conf["scheduled_end_at"] = body["scheduled_end_at"]
    conf["reschedule_count"] += 1
    touch(conf)
    append_audit(case["id"], "P2P_RESCHEDULED", role, user_id,
                 f"Conference {cid} rescheduled (count {conf['reschedule_count']})")
    return success_object(conf, 200)


@bp.post("/api/peer-to-peer-conferences/<cid>/complete")
def complete_conference(cid):
    user_id, role = require_roles(["PhysicianAdvisor"])
    body = get_json_body()
    reject_unknown_fields(body, COMPLETE_FIELDS)
    validate_enum(body, "outcome", {"UPHELD", "OVERTURNED"})
    outcome = body["outcome"]
    if outcome == "OVERTURNED":
        validate_int(body, "certified_day_count", min_val=1)
    elif "certified_day_count" in body and body["certified_day_count"] is not None:
        validate_int(body, "certified_day_count", min_val=1)

    conf = lookup(db.peer_to_peer_conferences, cid, "PeerToPeerConference")
    maybe_expire_conference(conf)
    ar = db.authorization_requests[conf["authorization_request_id"]]
    case = db.utilization_cases[ar["case_id"]]
    payer = db.payers[case["payer_id"]]

    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if conf["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, f"Conference is {conf['status']}, not SCHEDULED", 409)
    # Completion must occur while now <= scheduled_end_at
    if logical_now() > parse_iso(conf["scheduled_end_at"]):
        raise ApiError(ERR_P2P_WINDOW_EXPIRED,
                       "Completion attempted after scheduled_end_at", 422)

    denial = _denial_for_auth(conf["authorization_request_id"])

    conf["status"] = "COMPLETED"
    conf["outcome"] = outcome
    touch(conf)

    if outcome == "OVERTURNED":
        granted = body["certified_day_count"]
        # Restore auth at case frontier
        frontier = case_frontier_end(case["id"])
        # budget check against the restored grant
        if case["certified_day_count"] + granted > payer["bed_day_budget_per_case"]:
            raise ApiError(ERR_BED_DAY_BUDGET_EXCEEDED,
                           "Restored certified days would exceed payer bed_day_budget_per_case", 422)
        ar["status"] = "APPROVED"
        ar["certified_day_start"] = frontier
        ar["certified_day_end"] = frontier + granted
        touch(ar)
        if denial is not None and denial["status"] in ("OPEN", "P2P_SCHEDULED"):
            denial["status"] = "RESOLVED_OVERTURNED"
            touch(denial)
            append_audit(case["id"], "DENIAL_OVERTURNED", role, user_id,
                         f"Denial {denial['id']} resolved OVERTURNED via P2P")
        case["auth_status"] = "AUTHORIZED"
        recompute_certified_counts(case)
        touch(case)
    else:  # UPHELD
        if denial is not None and denial["status"] == "P2P_SCHEDULED":
            denial["status"] = "OPEN"
            touch(denial)

    append_audit(case["id"], "P2P_COMPLETED", role, user_id,
                 f"Conference {cid} completed with outcome {outcome}")
    return success_object(conf, 200)


@bp.post("/api/peer-to-peer-conferences/<cid>/cancel")
def cancel_conference(cid):
    user_id, role = require_roles(["AttendingPhysician"])
    get_json_body()

    conf = lookup(db.peer_to_peer_conferences, cid, "PeerToPeerConference")
    maybe_expire_conference(conf)
    ar = db.authorization_requests[conf["authorization_request_id"]]
    case = db.utilization_cases[ar["case_id"]]

    check_attending_ownership(case, user_id)
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if conf["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, f"Conference is {conf['status']}, not SCHEDULED", 409)

    conf["status"] = "CANCELLED"
    touch(conf)
    denial = _denial_for_auth(conf["authorization_request_id"])
    if denial is not None and denial["status"] == "P2P_SCHEDULED":
        denial["status"] = "OPEN"  # appeal_deadline_at conserved
        touch(denial)
    append_audit(case["id"], "P2P_CANCELLED", role, user_id,
                 f"Conference {cid} cancelled")
    return success_object(conf, 200)
