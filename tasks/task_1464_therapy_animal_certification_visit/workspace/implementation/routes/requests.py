"""Visit request endpoints (posting, offers, accept/decline, matching)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request, err_stale_version
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services import gates, scoring
from services.records import new_record, touch, public
from constants import SPECIES, VISIT_PROGRAMS, PRIORITIES
from util import now_dt, parse_datetime, fmt_dt
from validate import get_body, validate_body

bp = Blueprint("requests", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_request(request_id):
    r = store.visit_requests.get(request_id)
    if r is None:
        raise err_not_found("request")
    return r


@bp.post("/v1/visit-requests")
def create_request():
    auth = get_auth()
    require_roles(auth, ["FacilityCoordinator"])
    body = validate_body(get_body(), {
        "requested_start": ("datetime", True, None),
        "requested_end": ("datetime", True, None),
        "species_preference": ("string", False, SPECIES),
        "visit_program": ("string", True, VISIT_PROGRAMS),
        "priority": ("string", True, PRIORITIES),
    })
    start = parse_datetime(body["requested_start"])
    end = parse_datetime(body["requested_end"])
    if end <= start:
        raise err_invalid_request("requested_start must be strictly before requested_end")
    # Temporal: requested start must lie in the future.
    if start < now_dt():
        raise err("ERR_VISIT_IN_PAST", 409, "requested_start lies in the past")
    # Generic duration check only: 30..120 (flat program ceiling).
    duration = int((end - start).total_seconds() // 60)
    if duration < 30:
        raise err("ERR_VISIT_DURATION_INVALID", 422,
                  "Visit duration must be at least 30 minutes")
    if duration > 120:
        raise err("ERR_VISIT_DURATION_EXCEEDS_CAP", 422,
                  "Visit duration exceeds the 120-minute program ceiling")
    rec = new_record(store.visit_requests, {
        "facility_id": auth.user_id,
        "requested_start": fmt_dt(start),
        "requested_end": fmt_dt(end),
        "species_preference": body.get("species_preference"),
        "visit_program": body["visit_program"],
        "priority": body["priority"],
        "status": "OPEN",
        "offered_team_id": None,
        "offered_at": None,
        "offer_expires_at": None,
        "decline_count": 0,
        "expired_on": None,
        "fulfilled_on": None,
    })
    return success_object(public(rec), 201)


@bp.get("/v1/visit-requests/<request_id>")
def get_request(request_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_request(request_id)), 200)


@bp.get("/v1/visit-requests")
def list_requests():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.visit_requests.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    priority = request.args.get("priority")
    offered_team_id = request.args.get("offered_team_id")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if priority is not None:
        records = [r for r in records if r["priority"] == priority]
    if offered_team_id is not None:
        records = [r for r in records if r.get("offered_team_id") == offered_team_id]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/visit-requests/<request_id>/offers")
def create_offer(request_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    req = _get_request(request_id)
    body = validate_body(get_body(), {
        "team_id": ("string", True, None),
        "expected_visit_request_version": ("integer", True, None),
    })
    team = store.teams.get(body["team_id"])
    if team is None:
        raise err_not_found("team")
    # OCC (category 6) — before state preconditions.
    if body["expected_visit_request_version"] != req["version"]:
        raise err_stale_version()
    if req["status"] != "OPEN":
        raise err("ERR_REQUEST_NOT_OPEN", 409, "Visit request is not OPEN")
    if not scoring.team_eligible_for_request(team, req):
        raise err("ERR_TEAM_NOT_ELIGIBLE", 422,
                  "Team fails the eligibility filter for this request")
    now = now_dt()
    req["status"] = "OFFERED"
    req["offered_team_id"] = team["id"]
    req["offered_at"] = fmt_dt(now)
    req["offer_expires_at"] = fmt_dt(now + timedelta(hours=72))
    touch(req)  # increments VisitRequest.version by 1
    return success_object(public(req), 200)


@bp.post("/v1/visit-requests/<request_id>/accept")
def accept_request(request_id):
    auth = get_auth()
    require_roles(auth, ["Handler"])
    req = _get_request(request_id)
    if req["status"] != "OFFERED":
        raise err("ERR_REQUEST_NOT_OFFERED", 409, "Visit request is not OFFERED")
    team = store.teams.get(req.get("offered_team_id"))
    if team is None or team["handler_id"] != auth.user_id:
        raise err_ownership()
    if now_dt() > parse_datetime(req["offer_expires_at"]):
        raise err("ERR_OFFER_EXPIRED", 409, "The offer has expired")
    # Re-run the entire visit-creation gate chain against the requested window.
    facility = store.facilities.get(req["facility_id"])
    start = parse_datetime(req["requested_start"])
    end = parse_datetime(req["requested_end"])
    gates.run_visit_gates(team, facility, start, end)
    visit = gates.create_visit(team, facility, start, end, request_id=req["id"])
    req["status"] = "ACCEPTED"
    touch(req)
    return success_object(public(visit), 200)


@bp.post("/v1/visit-requests/<request_id>/decline")
def decline_request(request_id):
    auth = get_auth()
    require_roles(auth, ["Handler"])
    req = _get_request(request_id)
    if req["status"] != "OFFERED":
        raise err("ERR_REQUEST_NOT_OFFERED", 409, "Visit request is not OFFERED")
    team = store.teams.get(req.get("offered_team_id"))
    if team is None or team["handler_id"] != auth.user_id:
        raise err_ownership()
    req["status"] = "OPEN"
    req["offered_team_id"] = None
    req["offered_at"] = None
    req["offer_expires_at"] = None
    req["decline_count"] = req.get("decline_count", 0) + 1
    touch(req)
    return success_object(public(req), 200)


@bp.post("/v1/visit-requests/<request_id>/withdraw")
def withdraw_request(request_id):
    auth = get_auth()
    require_roles(auth, ["FacilityCoordinator"])
    req = _get_request(request_id)
    if auth.user_id != req["facility_id"]:
        raise err_ownership()
    if req["status"] not in ("OPEN", "OFFERED"):
        raise err("ERR_REQUEST_NOT_WITHDRAWABLE", 409,
                  "Visit request is not OPEN or OFFERED")
    req["status"] = "WITHDRAWN"
    touch(req)
    return success_object(public(req), 200)


@bp.get("/v1/visit-requests/<request_id>/candidate-teams")
def get_candidate_teams(request_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    req = _get_request(request_id)
    ranked = scoring.candidate_teams(req)
    data = []
    for team, score in ranked:
        rec = public(team)
        rec["score"] = score
        data.append(rec)
    return success_list(data, len(data) if data else 10, 0, len(data))
