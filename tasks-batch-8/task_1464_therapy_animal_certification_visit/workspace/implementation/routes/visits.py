"""Visit endpoints (scheduling, check-in/out, cancel, verification)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request, err_stale_version
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services import cascades, credits, gates
from services.records import new_record, touch, public
from util import now_dt, now_iso, parse_datetime, fmt_dt, floor_div_seconds_to_minutes
from validate import get_body, validate_body

bp = Blueprint("visits", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_visit(visit_id):
    v = store.visits.get(visit_id)
    if v is None:
        raise err_not_found("visit")
    return v


def _team_of(visit):
    return store.teams.get(visit["team_id"])


@bp.post("/v1/visits")
def create_visit():
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    body = validate_body(get_body(), {
        "team_id": ("string", True, None),
        "facility_id": ("string", True, None),
        "scheduled_start": ("datetime", True, None),
        "scheduled_end": ("datetime", True, None),
        "expected_team_version": ("integer", True, None),
    })
    team = store.teams.get(body["team_id"])
    if team is None:
        raise err_not_found("team")
    facility = store.facilities.get(body["facility_id"])
    if facility is None:
        raise err_not_found("facility")
    start = parse_datetime(body["scheduled_start"])
    end = parse_datetime(body["scheduled_end"])
    if end <= start:
        raise err_invalid_request("scheduled_start must be strictly before scheduled_end")
    # OCC (category 6) fires before state preconditions.
    if body["expected_team_version"] != team["version"]:
        raise err_stale_version()
    gates.run_visit_gates(team, facility, start, end)
    visit = gates.create_visit(team, facility, start, end)
    return success_object(public(visit), 201)


@bp.get("/v1/visits/<visit_id>")
def get_visit(visit_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_visit(visit_id)), 200)


@bp.get("/v1/visits")
def list_visits():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.visits.values())
    team_id = request.args.get("team_id")
    facility_id = request.args.get("facility_id")
    request_id = request.args.get("request_id")
    lifecycle_status = request.args.get("lifecycle_status")
    verification_status = request.args.get("verification_status")
    if team_id is not None:
        records = [r for r in records if r["team_id"] == team_id]
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    if request_id is not None:
        records = [r for r in records if r.get("request_id") == request_id]
    if lifecycle_status is not None:
        records = [r for r in records if r["lifecycle_status"] == lifecycle_status]
    if verification_status is not None:
        records = [r for r in records if r["verification_status"] == verification_status]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/visits/<visit_id>/check-in")
def check_in(visit_id):
    auth = get_auth()
    require_roles(auth, ["Handler"])
    visit = _get_visit(visit_id)
    team = _team_of(visit)
    if team is None or team["handler_id"] != auth.user_id:
        raise err_ownership()
    if visit["lifecycle_status"] != "SCHEDULED":
        raise err("ERR_VISIT_NOT_SCHEDULED", 409, "Visit is not SCHEDULED")
    # Safety: animal not in WELFARE_HOLD
    animal = store.animals.get(team["animal_id"])
    if animal is not None and animal["status"] == "WELFARE_HOLD":
        raise err("ERR_ANIMAL_WELFARE_HOLD", 403, "Animal is in WELFARE_HOLD")
    # Referential: certification ACTIVE | RENEWAL_DUE
    cert = gates.team_active_certification(team["id"])
    if cert is None:
        raise err("ERR_CERT_NOT_ACTIVE", 409,
                  "Team certification is not ACTIVE or RENEWAL_DUE")
    # Temporal window: [scheduled_start - 15min, scheduled_end]
    now = now_dt()
    start = parse_datetime(visit["scheduled_start"])
    end = parse_datetime(visit["scheduled_end"])
    if now < start - timedelta(minutes=15):
        raise err("ERR_CHECKIN_TOO_EARLY", 409, "Check-in window has not opened")
    if now > end:
        raise err("ERR_CHECKIN_WINDOW_PASSED", 409, "The visit window has passed")
    visit["lifecycle_status"] = "IN_PROGRESS"
    visit["actual_start"] = now_iso()
    touch(visit)
    return success_object(public(visit), 200)


@bp.post("/v1/visits/<visit_id>/check-out")
def check_out(visit_id):
    auth = get_auth()
    require_roles(auth, ["Handler"])
    visit = _get_visit(visit_id)
    team = _team_of(visit)
    if team is None or team["handler_id"] != auth.user_id:
        raise err_ownership()
    if visit["lifecycle_status"] != "IN_PROGRESS":
        raise err("ERR_VISIT_NOT_IN_PROGRESS", 409, "Visit is not IN_PROGRESS")
    now = now_dt()
    actual_start = parse_datetime(visit["actual_start"])
    actual_minutes = floor_div_seconds_to_minutes((now - actual_start).total_seconds())
    visit["lifecycle_status"] = "COMPLETED"
    visit["actual_end"] = now_iso()
    visit["actual_minutes"] = actual_minutes
    touch(visit)

    # PROVISIONAL credit = scheduled minutes (unrounded).
    scheduled_minutes = credits.scheduled_minutes_of(visit)
    credits.post_credit(team["handler_id"], visit["id"], "PROVISIONAL",
                        scheduled_minutes, note="check-out provisional")

    # Rest block: actual_end + rest_requirement(actual_minutes)
    animal = store.animals.get(team["animal_id"])
    if animal is not None:
        rest = credits.rest_requirement_minutes(actual_minutes)
        animal["welfare_blocked_until"] = fmt_dt(now + timedelta(minutes=rest))
        touch(animal)
        credits.recompute_animal_workloads(animal)

    # Request-backed: ACCEPTED -> FULFILLED
    req_id = visit.get("request_id")
    if req_id:
        req = store.visit_requests.get(req_id)
        if req is not None and req["status"] == "ACCEPTED":
            req["status"] = "FULFILLED"
            req["fulfilled_on"] = now.date().isoformat()
            touch(req)
    return success_object(public(visit), 200)


@bp.post("/v1/visits/<visit_id>/cancel")
def cancel_visit(visit_id):
    auth = get_auth()
    require_roles(auth, ["Handler", "ProgramAdmin", "FacilityCoordinator"])
    visit = _get_visit(visit_id)
    validate_body(get_body(), {"reason": ("string", False, None)}, partial=True)
    team = _team_of(visit)
    # Ownership per actor class.
    if auth.role == "Handler":
        if team is None or team["handler_id"] != auth.user_id:
            raise err_ownership()
    elif auth.role == "FacilityCoordinator":
        if visit["facility_id"] != auth.user_id:
            raise err_ownership()
    if visit["lifecycle_status"] != "SCHEDULED":
        raise err("ERR_VISIT_NOT_CANCELLABLE", 409, "Visit is not SCHEDULED")

    reason_map = {
        "Handler": "HANDLER_CANCEL",
        "ProgramAdmin": "ADMIN_CANCEL",
        "FacilityCoordinator": "FACILITY_CANCEL",
    }
    cancel_reason = reason_map[auth.role]
    scheduled_start = parse_datetime(visit["scheduled_start"])
    scheduled_minutes = credits.scheduled_minutes_of(visit)
    cascades.cancel_visit_record(visit, cancel_reason)

    # Handler-initiated only: late-cancel penalty tiers.
    if auth.role == "Handler" and team is not None:
        notice_seconds = (scheduled_start - now_dt()).total_seconds()
        hours_notice = int(notice_seconds // 3600)
        if hours_notice >= 48:
            points = 0
        elif hours_notice >= 24:
            points = 1
        else:
            points = 2
        if points:
            team["late_cancel_count"] = team.get("late_cancel_count", 0) + points
            touch(team)
            if team["late_cancel_count"] >= 3:
                cert = None
                for c in store.certifications.values():
                    if c["team_id"] == team["id"] and c["status"] in ("ACTIVE", "RENEWAL_DUE"):
                        cert = c
                        break
                if cert is not None:
                    cascades.suspend_certification(cert, "LATE_CANCELLATIONS", None)
                team["late_cancel_count"] = 0
                touch(team)
    return success_object(public(visit), 200)


@bp.post("/v1/visits/<visit_id>/verify")
def verify_visit(visit_id):
    auth = get_auth()
    require_roles(auth, ["FacilityCoordinator"])
    visit = _get_visit(visit_id)
    if visit["facility_id"] != auth.user_id:
        raise err_ownership()
    if visit["lifecycle_status"] != "COMPLETED":
        raise err("ERR_VISIT_NOT_COMPLETED", 409, "Visit is not COMPLETED")
    if visit["verification_status"] != "UNVERIFIED":
        raise err("ERR_VISIT_ALREADY_RESOLVED", 409,
                  "Visit verification is not UNVERIFIED")
    visit["verification_status"] = "VERIFIED"
    visit["verified_at"] = now_iso()
    touch(visit)
    credits.reconcile_final_credit(visit, visit.get("actual_minutes") or 0)
    return success_object(public(visit), 200)


@bp.post("/v1/visits/<visit_id>/dispute")
def dispute_visit(visit_id):
    auth = get_auth()
    require_roles(auth, ["FacilityCoordinator"])
    visit = _get_visit(visit_id)
    validate_body(get_body(), {"dispute_reason": ("string", True, None)})
    if visit["facility_id"] != auth.user_id:
        raise err_ownership()
    if visit["lifecycle_status"] != "COMPLETED":
        raise err("ERR_VISIT_NOT_COMPLETED", 409, "Visit is not COMPLETED")
    if visit["verification_status"] != "UNVERIFIED":
        raise err("ERR_VISIT_ALREADY_RESOLVED", 409,
                  "Visit verification is not UNVERIFIED")
    visit["verification_status"] = "DISPUTED"
    touch(visit)
    return success_object(public(visit), 200)


@bp.post("/v1/visits/<visit_id>/resolve-dispute")
def resolve_dispute(visit_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    visit = _get_visit(visit_id)
    body = validate_body(get_body(), {"approved_minutes": ("integer", True, None)})
    scheduled_minutes = credits.scheduled_minutes_of(visit)
    if not (0 <= body["approved_minutes"] <= scheduled_minutes):
        raise err_invalid_request("approved_minutes must be within 0..scheduled_minutes")
    if visit["verification_status"] != "DISPUTED":
        raise err("ERR_VISIT_NOT_DISPUTED", 409, "Visit verification is not DISPUTED")
    visit["verification_status"] = "VERIFIED"
    visit["approved_minutes"] = body["approved_minutes"]
    visit["verified_at"] = now_iso()
    touch(visit)
    credits.reconcile_final_credit(visit, body["approved_minutes"])
    return success_object(public(visit), 200)
