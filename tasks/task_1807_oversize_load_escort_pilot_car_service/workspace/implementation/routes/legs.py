"""RouteLeg endpoints + permit and route-survey creation nested under legs."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_JOB_NOT_FOUND,
    ERR_LEG_NOT_FOUND,
    ERR_LEG_INVALID_STATE,
    ERR_OPEN_SURVEY_EXISTS,
    raise_err,
)
from middleware import require_roles, ALL_ROLES
from mutate import mark
from response import success_object, paginate
from serializers import ser_leg, ser_permit, ser_survey
from services import cascade
from util import body_json, req_string, req_dt, new_id, parse_date

bp = Blueprint("legs", __name__)


def _new_resource():
    n = db.now()
    return {"id": new_id(), "created_at": n, "updated_at": n, "version": 1,
            "_seq": db.next_seq()}


def get_leg_or_404(leg_id):
    leg = db.legs.get(leg_id)
    if leg is None:
        raise_err(ERR_LEG_NOT_FOUND, f"Leg {leg_id} not found")
    return leg


@bp.get("/jobs/<id>/legs")
def list_job_legs(id):
    require_roles(*ALL_ROLES)
    if id not in db.jobs:
        raise_err(ERR_JOB_NOT_FOUND, f"Job {id} not found")
    rows = [l for l in db.legs.values() if l["job_id"] == id]
    rows.sort(key=lambda l: (l["sequence_index"], l["_seq"]))
    return paginate(request, [ser_leg(l) for l in rows])


@bp.get("/legs/<id>")
def get_leg(id):
    require_roles(*ALL_ROLES)
    return success_object(ser_leg(get_leg_or_404(id)))


@bp.post("/legs/<id>/confirm-police")
def confirm_police(id):
    require_roles("Dispatcher")
    body_json(request)
    leg = get_leg_or_404(id)
    if not leg["requires_police_escort"]:
        raise_err(ERR_INVALID_REQUEST, "This leg does not require a police escort")
    leg["police_confirmed"] = True
    mark(leg)
    cascade.reevaluate_leg_and_job_gates(leg, promote_from=("DETERMINED",))
    return success_object(ser_leg(leg))


@bp.post("/legs/<id>/permits")
def create_permit(id):
    require_roles("Dispatcher")
    data = body_json(request)
    permit_number = req_string(data, "permit_number")
    valid_from = req_dt(data, "valid_from")
    valid_until = req_dt(data, "valid_until")
    if not valid_until > valid_from:
        raise_err(ERR_INVALID_REQUEST, "valid_until must be later than valid_from")
    closures = data.get("holiday_closure_dates")
    if closures is None:
        closures = []
    if not isinstance(closures, list):
        raise_err(ERR_INVALID_REQUEST, "holiday_closure_dates must be an array")
    for c in closures:
        if parse_date(c) is None:
            raise_err(ERR_INVALID_REQUEST, "holiday_closure_dates entries must be YYYY-MM-DD dates")
    leg = get_leg_or_404(id)
    permit = _new_resource()
    permit.update({
        "leg_id": leg["id"],
        "permit_number": permit_number,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "holiday_closure_dates": list(closures),
        "permit_status": "APPLIED",
        "issued_at": None,
    })
    db.permits[permit["id"]] = permit
    return success_object(ser_permit(permit), status=201)


@bp.get("/legs/<id>/permits")
def list_leg_permits(id):
    require_roles(*ALL_ROLES)
    leg = get_leg_or_404(id)
    rows = cascade.permits_of_leg(leg["id"])
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return paginate(request, [ser_permit(p) for p in rows])


@bp.post("/legs/<id>/route-surveys")
def create_route_survey(id):
    require_roles("RouteSurveyor")
    body_json(request)
    leg = get_leg_or_404(id)
    if leg["leg_status"] not in ("DETERMINED", "BLOCKED"):
        raise_err(ERR_LEG_INVALID_STATE,
                  "A route survey may be requested only on a DETERMINED or BLOCKED leg")
    for s in cascade.surveys_of_leg(leg["id"]):
        if s["survey_status"] in ("REQUESTED", "SUBMITTED"):
            raise_err(ERR_OPEN_SURVEY_EXISTS, "The leg already has a non-terminal survey")
    survey = _new_resource()
    survey.update({
        "leg_id": leg["id"],
        "survey_status": "REQUESTED",
        "surveyed_min_clearance_inches": None,
        "submitted_at": None,
        "decided_at": None,
        "decided_by_user_id": None,
        "rejection_reason": None,
    })
    db.surveys[survey["id"]] = survey
    if leg["leg_status"] == "BLOCKED":
        leg["leg_status"] = "DETERMINED"
        leg["clearance_verdict"] = "UNKNOWN"
        leg["survey_min_clearance_inches"] = None
        mark(leg)
    return success_object(ser_survey(survey), status=201)


@bp.get("/legs/<id>/route-surveys")
def list_leg_surveys(id):
    require_roles(*ALL_ROLES)
    leg = get_leg_or_404(id)
    rows = cascade.surveys_of_leg(leg["id"])
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return paginate(request, [ser_survey(s) for s in rows])
