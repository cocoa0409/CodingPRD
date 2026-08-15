"""IncidentReport endpoints: file, list, read, advance with strike cascade."""
from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_MEMBER_NOT_FOUND, ERR_DOG_NOT_FOUND,
    ERR_AREA_NOT_FOUND, ERR_INCIDENT_NOT_FOUND, ERR_INSUFFICIENT_PERMISSIONS,
    ERR_SELF_REPORT_NOT_ALLOWED, ERR_INCIDENT_NOT_ADVANCABLE,
)
from helpers import (
    get_body, req_string, req_enum, parse_datetime, parse_pagination, slice_page,
)
from middleware import require_auth
from response import ok
from services import domain
from services.domain import SEVERITY_POINTS, SUSPENSION_THRESHOLD

bp = Blueprint("incidents", __name__)

REPORT_STATUSES = ("FILED", "UNDER_REVIEW", "CONFIRMED", "DISMISSED")
ADVANCE_TARGETS = ("UNDER_REVIEW", "CONFIRMED", "DISMISSED")


@bp.route("/dog-park/incident-reports", methods=["POST"])
def file_report():
    uid, role = require_auth(["Member", "Steward", "ParkAdmin"])
    body = get_body()
    subject_member_id = req_string(body, "subject_member_id")
    severity = req_enum(body, "severity", ("MINOR", "MAJOR", "SEVERE"))
    occurred_raw = req_string(body, "occurred_at")
    if parse_datetime(occurred_raw) is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "occurred_at must be an ISO 8601 UTC instant")
    description = req_string(body, "description")
    subject_dog_id = body.get("subject_dog_id")
    area_id = body.get("area_id")
    if subject_dog_id is not None and not isinstance(subject_dog_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "subject_dog_id must be a string or null")
    if area_id is not None and not isinstance(area_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "area_id must be a string or null")
    # Stage 6 existence of body-referenced entities.
    subject = store.members.get(subject_member_id)
    if subject is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, 404, "Subject member not found")
    if subject_dog_id is not None and subject_dog_id not in store.dogs:
        raise ApiError(ERR_DOG_NOT_FOUND, 404, "Subject dog not found")
    if area_id is not None and area_id not in store.areas:
        raise ApiError(ERR_AREA_NOT_FOUND, 404, "Area not found")
    # Stage 10 business constraint: no self-reporting (ParkAdmin's identity is
    # opaque and never compared to entity ids).
    if role in ("Member", "Steward") and subject_member_id == uid:
        raise ApiError(ERR_SELF_REPORT_NOT_ALLOWED, 422,
                       "A member may not file an incident report against themselves")
    report = domain.new_entity(store.incidents, {
        "reporter_member_id": None if role == "ParkAdmin" else uid,
        "subject_member_id": subject_member_id,
        "subject_dog_id": subject_dog_id,
        "area_id": area_id,
        "severity": severity,
        "description": description,
        "occurred_at": occurred_raw,
        "status": "FILED",
        "resolution_note": None,
    })
    # Filing recomputes the subject's provisional_strike_score; a new FILED
    # report always raises it, so the member record mutates.
    domain.touch(subject)
    return ok(domain.public(report), 201)


@bp.route("/dog-park/incident-reports", methods=["GET"])
def list_reports():
    require_auth(["Steward", "ParkAdmin"])
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in REPORT_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid status filter")
    limit, offset = parse_pagination()
    filters = {
        "reporter_member_id": request.args.get("reporter_member_id"),
        "subject_member_id": request.args.get("subject_member_id"),
        "subject_dog_id": request.args.get("subject_dog_id"),
        "area_id": request.args.get("area_id"),
    }
    items = []
    for r in store.incidents.values():
        if status_filter is not None and r["status"] != status_filter:
            continue
        if any(fval is not None and r[fkey] != fval
               for fkey, fval in filters.items()):
            continue
        items.append(r)
    page, meta = slice_page(items, limit, offset)
    return ok([domain.public(r) for r in page], 200, meta)


@bp.route("/dog-park/incident-reports/<reportId>", methods=["GET"])
def get_report(reportId):
    require_auth(["Steward", "ParkAdmin"])
    report = store.incidents.get(reportId)
    if report is None:
        raise ApiError(ERR_INCIDENT_NOT_FOUND, 404, "Incident report not found")
    return ok(domain.public(report))


@bp.route("/dog-park/incident-reports/<reportId>/advance", methods=["POST"])
def advance_report(reportId):
    uid, role = require_auth(["Steward", "ParkAdmin"])
    body = get_body()
    target = req_enum(body, "to", ADVANCE_TARGETS)
    resolution_note = body.get("resolution_note")
    if resolution_note is not None and not isinstance(resolution_note, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "resolution_note must be a string or null")
    # Outcome-level role split: CONFIRMED/DISMISSED are ParkAdmin-only. This is
    # a stage-2 authorization failure and precedes existence/state checks.
    if target in ("CONFIRMED", "DISMISSED") and role == "Steward":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403,
                       "Only ParkAdmin may advance a report to {}".format(target))
    report = store.incidents.get(reportId)
    if report is None:
        raise ApiError(ERR_INCIDENT_NOT_FOUND, 404, "Incident report not found")
    # Stage 8 state preconditions per the state machine.
    if target == "UNDER_REVIEW":
        if report["status"] != "FILED":
            raise ApiError(ERR_INCIDENT_NOT_ADVANCABLE, 409,
                           "UNDER_REVIEW is only reachable from FILED")
        report["status"] = "UNDER_REVIEW"
        domain.touch(report)
        # Provisional score is unchanged: FILED and UNDER_REVIEW both count
        # at half weight, so the subject record does not mutate.
    else:
        if report["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INCIDENT_NOT_ADVANCABLE, 409,
                           "{} is only reachable from UNDER_REVIEW".format(target))
        report["status"] = target
        if resolution_note is not None:
            report["resolution_note"] = resolution_note
        domain.touch(report)
        subject = store.members.get(report["subject_member_id"])
        if subject is not None:
            if target == "CONFIRMED":
                subject["strike_points"] += SEVERITY_POINTS[report["severity"]]
                if (subject["strike_points"] >= SUSPENSION_THRESHOLD
                        and subject["status"] == "ACTIVE"):
                    domain.suspend_member(subject)
            # Both outcomes change the subject's strike view (CONFIRMED raises
            # strike_points; DISMISSED drops the report from pending), so the
            # member record mutates exactly once.
            domain.touch(subject)
    return ok(domain.public(report))
